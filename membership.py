"""Rolling 30-day flown spend and atomic single-use tier benefits."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone, date
from flask import g, jsonify, request
from travel import fare_total, party

TIERS=[('platinum',100000,20,30,1),('exclusive',150000,30,30,2),('premium_exclusive',200000,50,60,2)]


def now():
    return datetime.now(timezone(timedelta(hours=7)))


def status(conn,uid):
    cutoff=now()-timedelta(days=30)
    spend=0
    for r in conn.execute("SELECT b.created_at,b.total,b.details,c.completed_at FROM bookings b JOIN completed_journeys c ON b.id=c.booking_id WHERE b.user_id=? AND NOT EXISTS (SELECT 1 FROM booking_lifecycle l WHERE l.booking_id=b.id AND l.state IN ('refund_requested','demo_refunded'))",(uid,)):
        created=datetime.fromisoformat(r[0]);completed=datetime.fromisoformat(r[3]);d=json.loads(r[2])
        travel=date.fromisoformat(d.get('return') if d.get('trip')=='round' else d['depart'])
        if cutoff<=created<=now() and cutoff<=completed<=now() and cutoff.date()<=travel<=now().date():
            spend+=r[1]
    payments=[]
    for r in conn.execute("SELECT b.id,b.created_at,b.total,b.details,COALESCE(l.state,'demo_paid') FROM bookings b LEFT JOIN booking_lifecycle l ON l.booking_id=b.id WHERE b.user_id=? ORDER BY b.created_at DESC",(uid,)):
        if cutoff<=datetime.fromisoformat(r[1])<=now():
            d=json.loads(r[3])
            payments.append(dict(ref=r[0],paid_at=r[1],total=r[2],state=r[4],from_airport=d.get('from'),to_airport=d.get('to'),payment_method=d.get('pay')))
    paid_spend=sum(p['total'] for p in payments if p['state'] not in ('refund_requested','demo_refunded'))
    flown_spend=spend
    spend=paid_spend
    tier=next((t for t in reversed(TIERS) if spend>=t[1]),None)
    used=bool(tier and conn.execute('SELECT 1 FROM benefit_redemptions WHERE user_id=? AND tier=?',(uid,tier[0])).fetchone())
    return dict(flown_spend=flown_spend,paid_spend=paid_spend,payments=payments,spend=spend,tier=tier[0] if tier else 'standard',discount=tier[2] if tier else 0,bag_kg=tier[3] if tier else 0,bag_people=tier[4] if tier else 0,used=used,available=bool(tier and not used),next_threshold=next((t[1] for t in TIERS if spend<t[1]),None))


def quote(conn,uid,data,total):
    member=status(conn,uid);fare=fare_total(data)
    discount=0;free_ticket=0;bag_saving=0;free_people=0
    if data.get('use_member_benefit') is True and member['available']:
        if data.get('promotion',{}).get('discount',0):
            raise ValueError('เลือกใช้ส่วนลดสมาชิกหรือโปรโมชันอย่างใดอย่างหนึ่ง')
        if member['tier']=='premium_exclusive' and data['trip']!='round':
            raise ValueError('สิทธิ์ Premium Exclusive พร้อมตั๋วฟรีต้องใช้กับการจองไปกลับ')
        if member['tier']=='premium_exclusive' and data['trip']=='round':
            free_ticket=sum(f['price'] for f in data['flights'])
        discount=round((fare-free_ticket)*member['discount']/100)
        free_people=min(member['bag_people'],party(data)[0])
        bag_saving=data['bag']*free_people*len(data['flights'])
    return dict(total=total-discount-free_ticket-bag_saving,fare_discount=discount,free_ticket=free_ticket,bag_saving=bag_saving,free_bag_people=free_people,free_bag_kg=member['bag_kg'] if free_people else 0,tier=member['tier'],applied=bool(free_people),membership=member)


def configure_membership(app,validate):
    def initialize():
        with closing(sqlite3.connect(app.config['DATABASE'])) as conn:
            conn.executescript('''CREATE TABLE IF NOT EXISTS completed_journeys (
                booking_id TEXT PRIMARY KEY REFERENCES bookings(id), completed_at TEXT NOT NULL, admin_id INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS benefit_redemptions (
                user_id INTEGER NOT NULL, tier TEXT NOT NULL, booking_id TEXT NOT NULL, redeemed_at TEXT NOT NULL,
                PRIMARY KEY(user_id,tier));''')
    app.initialize_membership=initialize
    app.membership_quote=quote
    initialize()

    @app.get('/api/membership')
    def my_membership():
        if g.user is None:return jsonify(error='กรุณาเข้าสู่ระบบ'),401
        with closing(sqlite3.connect(app.config['DATABASE'])) as conn:
            return jsonify(status(conn,g.user['id']))

    @app.post('/api/membership/quote')
    def membership_quote():
        if g.user is None:return jsonify(error='กรุณาเข้าสู่ระบบ'),401
        try:
            data,total=validate(request.get_json(silent=True))
            with closing(sqlite3.connect(app.config['DATABASE'])) as conn:
                return jsonify(quote(conn,g.user['id'],data,total))
        except (ValueError,TypeError,KeyError) as error:
            return jsonify(error=str(error) or 'กรุณาตรวจสอบข้อมูลการจองก่อนคำนวณสิทธิ์'),400

    @app.post('/api/admin/complete-journey')
    def complete_journey():
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict):return jsonify(error='ข้อมูลไม่ถูกต้อง'),400
        with closing(sqlite3.connect(app.config['DATABASE'])) as conn:
            row=conn.execute('SELECT details FROM bookings WHERE id=?',(data.get('ref'),)).fetchone()
            if not row:return jsonify(error='ไม่พบการจอง'),404
            invalid=conn.execute("SELECT 1 FROM booking_lifecycle WHERE booking_id=? AND state IN ('refund_requested','demo_refunded')",(data['ref'],)).fetchone()
            if invalid:return jsonify(error='รายการยกเลิกไม่สามารถยืนยันเดินทางได้'),409
            booking=json.loads(row[0]);end=booking['return'] if booking['trip']=='round' else booking['depart']
            if date.fromisoformat(end)>now().date():return jsonify(error='ยังไม่ถึงวันเดินทางครบ ไม่สามารถนับยอดสมาชิกได้'),400
            conn.execute('INSERT OR IGNORE INTO completed_journeys VALUES (?,?,?)',(data['ref'],now().isoformat(),g.user['id']))
            app.audit(g.user['id'],'journey_completed',data['ref'],conn)
            conn.commit()
        return jsonify(message='ยืนยันเดินทางครบแล้ว ยอดสมาชิกคำนวณย้อนหลัง 30 วัน')