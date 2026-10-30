import sqlite3,json
from contextlib import closing
from datetime import datetime,timezone,timedelta
from flask import request,jsonify,g

def configure_checkin14(app):
    def connect():
        c=sqlite3.connect(app.config['DATABASE']);c.row_factory=sqlite3.Row;return c
    with closing(connect()) as c:c.execute('CREATE TABLE IF NOT EXISTS leg_checkins(booking_id TEXT,leg INTEGER,checked_at TEXT,PRIMARY KEY(booking_id,leg))');c.commit()
    def info(b,c):
        now=datetime.now(timezone(timedelta(hours=7)));legs=[]
        for i,f in enumerate(b['flights']):
            day=b['depart'] if i==0 else b['return'];depart=datetime.fromisoformat(day+'T'+f['start']).replace(tzinfo=now.tzinfo);opened=max(depart-timedelta(hours=2),depart.replace(hour=0,minute=0,second=0,microsecond=0));closed=depart-timedelta(hours=1)
            checked=c.execute('SELECT checked_at FROM leg_checkins WHERE booking_id=? AND leg=?',(b['ref'],i)).fetchone()
            if i==0 and not checked:checked=c.execute('SELECT checked_at FROM demo_checkins WHERE booking_id=?',(b['ref'],)).fetchone()
            legs.append(dict(index=i,flight=f,opens=opened.isoformat(),closes=closed.isoformat(),departure=depart.isoformat(),checked_at=checked[0] if checked else None,available=opened<=now<=closed and b['booking_state'] not in ('refund_requested','demo_refunded','demo_completed'),gate='รอยืนยันจากสายการบิน'))
        return dict(ref=b['ref'],legs=legs,state=b['booking_state'])
    def find(c,ref):
        row=c.execute('SELECT * FROM bookings WHERE id=? AND user_id=?',(ref,g.user['id'])).fetchone()
        return app.booking_details(row,c) if row else None
    @app.post('/api/checkin/lookup')
    def checkin_lookup():
        if g.user is None:return jsonify(error='กรุณาเข้าสู่ระบบ'),401
        d=request.get_json(silent=True)
        if not isinstance(d,dict):return jsonify(error='ข้อมูลไม่ถูกต้อง'),400
        with closing(connect()) as c:
            b=find(c,str(d.get('ref','')).strip().upper())
            if not b:return jsonify(error='ไม่พบการจองในบัญชีนี้'),404
            profile=app.public_user(g.user);names={profile['first'].strip().casefold(),profile['last'].strip().casefold()}
            names.update(v.strip().casefold() for p in b['passengers'] for v in (p['first'],p['last']))
            if str(d.get('name','')).strip().casefold() not in names:return jsonify(error='ชื่อไม่ตรงกับบัญชีหรือผู้โดยสาร'),400
            return jsonify(info(b,c))
    @app.get('/api/bookings/<ref>/checkin-status')
    def checkin_status(ref):
        if g.user is None:return jsonify(error='กรุณาเข้าสู่ระบบ'),401
        with closing(connect()) as c:
            row=c.execute('SELECT * FROM bookings WHERE id=?'+('' if g.user['role']=='admin' else ' AND user_id=?'),(ref,) if g.user['role']=='admin' else (ref,g.user['id'])).fetchone()
            if not row:return jsonify(error='ไม่พบการจอง'),404
            return jsonify(info(app.booking_details(row,c),c))
    def confirm():
        if g.user is None:return jsonify(error='กรุณาเข้าสู่ระบบ'),401
        d=request.get_json(silent=True)
        if not isinstance(d,dict) or type(d.get('leg',0)) is not int:return jsonify(error='ข้อมูลไม่ถูกต้อง'),400
        with closing(connect()) as c:
            b=find(c,str(d.get('ref','')).strip().upper())
            if not b:return jsonify(error='ไม่พบการจอง'),404
            leg=d.get('leg',0);details=info(b,c)
            if not 0<=leg<len(details['legs']):return jsonify(error='ขาเที่ยวบินไม่ถูกต้อง'),400
            selected=details['legs'][leg]
            if not selected['available']:return jsonify(error='นอกช่วงเช็คอิน หรือการจองถูกยกเลิก'),409
            if not selected['checked_at']:
                at=datetime.now(timezone.utc).isoformat();c.execute('INSERT OR IGNORE INTO leg_checkins VALUES(?,?,?)',(b['ref'],leg,at));app.audit(g.user['id'],'demo_checkin_leg',b['ref']+':'+str(leg),c);c.commit()
            return jsonify(info(b,c))
    app.view_functions['checkin']=confirm
    @app.get('/api/admin/checkins')
    def admin_checkins():
        with closing(connect()) as c:
            rows=c.execute('SELECT l.*,u.username FROM leg_checkins l JOIN bookings b ON b.id=l.booking_id JOIN users u ON u.id=b.user_id ORDER BY l.checked_at DESC LIMIT 200').fetchall()
            return jsonify(checkins=[dict(row) for row in rows])
