"""Local demo check-in, support cases and authenticated member administration."""
import sqlite3,json,uuid
from contextlib import closing
from datetime import datetime,timezone,timedelta
from flask import request,jsonify,g
from membership import status

def configure_services(app):
    def connect():
        c=sqlite3.connect(app.config['DATABASE'],timeout=15);c.row_factory=sqlite3.Row;return c
    with closing(connect()) as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS demo_checkins(booking_id TEXT NOT NULL,user_id INTEGER NOT NULL,checked_at TEXT NOT NULL,PRIMARY KEY(booking_id,user_id));
        CREATE TABLE IF NOT EXISTS support_cases(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,booking_id TEXT,category TEXT NOT NULL,message TEXT NOT NULL,created_at TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'open');''')
    @app.post('/api/checkin')
    def checkin():
        if g.user is None:return jsonify(error='กรุณาเข้าสู่ระบบ'),401
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict):return jsonify(error='ข้อมูลไม่ถูกต้อง'),400
        ref=str(data.get('ref','')).strip().upper();name=str(data.get('name','')).strip().casefold()
        with closing(connect()) as c:
            row=c.execute('SELECT * FROM bookings WHERE id=? AND user_id=?',(ref,g.user['id'])).fetchone()
            if not row:return jsonify(error='ไม่พบการจองในบัญชีนี้'),404
            b=app.booking_details(row,c)
            if not name or not any(name in {p['first'].strip().casefold(),p['last'].strip().casefold()} for p in b.get('passengers',[])):return jsonify(error='ชื่อหรือนามสกุลไม่ตรงกับผู้โดยสาร'),400
            if b['booking_state'] in ('refund_requested','demo_refunded','demo_completed'):return jsonify(error='สถานะการจองไม่สามารถเช็คอินได้'),409
            now=datetime.now(timezone(timedelta(hours=7)))
            departure=datetime.fromisoformat(b['depart']+'T'+b['flights'][0]['start']).replace(tzinfo=now.tzinfo)
            if not timedelta(hours=1)<=departure-now<=timedelta(hours=2):return jsonify(error='เช็คอินสาธิตเปิด 2 ถึง 1 ชั่วโมงก่อนขาไป กติกานี้เป็นของเว็บสาธิต ไม่ใช่กติกาสายการบิน'),409
            c.execute('INSERT OR IGNORE INTO demo_checkins VALUES(?,?,?)',(ref,g.user['id'],now.isoformat()));app.audit(g.user['id'],'demo_checkin',ref,c);c.commit()
        return jsonify(message='เช็คอินสาธิตสำเร็จ ไม่ใช่การเช็คอินกับสายการบินและใช้ขึ้นเครื่องจริงไม่ได้',ref=ref,passengers=[dict(first=p['first'],last=p['last']) for p in b['passengers']])
    @app.post('/api/support')
    def support():
        if g.user is None:return jsonify(error='กรุณาเข้าสู่ระบบก่อนส่งเรื่อง'),401
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict):return jsonify(error='ข้อมูลไม่ถูกต้อง'),400
        message=data.get('message','');category=data.get('category','general');ref=str(data.get('ref','')).strip().upper()
        if not isinstance(message,str) or not 10<=len(message.strip())<=3000 or category not in ('general','payment','refund','change'):return jsonify(error='กรอกข้อความ 10–3000 ตัวอักษรและเลือกหัวข้อให้ถูกต้อง'),400
        with closing(connect()) as c:
            if ref and not c.execute('SELECT 1 FROM bookings WHERE id=? AND user_id=?',(ref,g.user['id'])).fetchone():return jsonify(error='หมายเลขจองไม่อยู่ในบัญชีนี้'),400
            key='SUP-'+uuid.uuid4().hex[:12].upper();c.execute('INSERT INTO support_cases(id,user_id,booking_id,category,message,created_at) VALUES(?,?,?,?,?,?)',(key,g.user['id'],ref or None,category,message.strip(),datetime.now(timezone.utc).isoformat()));app.audit(g.user['id'],'support_created',key,c);c.commit()
        return jsonify(message='บันทึกเรื่องให้แอดมินแล้ว',ref=key),201
    @app.get('/api/admin/support')
    def admin_support():
        with closing(connect()) as c:rows=c.execute('SELECT s.*,u.username,u.email FROM support_cases s JOIN users u ON s.user_id=u.id ORDER BY s.created_at DESC LIMIT 200').fetchall()
        return jsonify(cases=[dict(r) for r in rows])
    @app.get('/api/admin/members')
    def admin_members():
        with closing(connect()) as c:
            members=[dict(id=u['id'],username=u['username'],email=u['email'],**status(c,u['id'])) for u in c.execute("SELECT id,username,email FROM users WHERE role='user' ORDER BY id DESC").fetchall()]
        return jsonify(members=members,updated_at=datetime.now(timezone.utc).isoformat())
