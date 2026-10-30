"""Demo cancellation/refund lifecycle. Does not initiate bank transfers."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime,timezone,timedelta,date
from flask import g,request,jsonify


def configure_lifecycle(app):
    def connect():
        c=sqlite3.connect(app.config['DATABASE']);c.row_factory=sqlite3.Row;return c
    def initialize():
        with closing(connect()) as c:
            c.execute('CREATE TABLE IF NOT EXISTS booking_lifecycle (booking_id TEXT PRIMARY KEY,state TEXT NOT NULL,updated_at TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS cancellation_requests (booking_id TEXT PRIMARY KEY REFERENCES bookings(id),user_id INTEGER NOT NULL,reason TEXT NOT NULL,requested_at TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS booking_drafts (id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,details TEXT NOT NULL,total INTEGER NOT NULL,created_at TEXT NOT NULL)');c.commit()
    app.initialize_lifecycle=initialize;initialize()
    def details(row,conn):
        d=json.loads(row['details']);state=conn.execute('SELECT state FROM booking_lifecycle WHERE booking_id=?',(row['id'],)).fetchone()
        complete=conn.execute('SELECT 1 FROM completed_journeys WHERE booking_id=?',(row['id'],)).fetchone()
        d['booking_state']=state[0] if state else 'demo_completed' if complete else 'demo_paid'
        cancellation=conn.execute('SELECT reason,requested_at FROM cancellation_requests WHERE booking_id=?',(row['id'],)).fetchone()
        d['cancellation']=dict(cancellation) if cancellation else None
        d['total']=row['total']
        return d
    app.booking_details=details
    def drafts(conn,uid=None):
        rows=conn.execute('SELECT * FROM booking_drafts'+(' WHERE user_id=?' if uid is not None else ''),((uid,) if uid is not None else ())).fetchall()
        return [dict(json.loads(r['details']),ref='DR-'+r['id'][:12].upper(),checkout_key=r['id'],total=r['total'],booking_state='awaiting_demo_payment',created_at=r['created_at']) for r in rows]
    app.booking_drafts=drafts

    @app.post('/api/bookings/draft')
    def draft():
        data=request.get_json(silent=True)
        try:
            validated,total=app.validate_booking(data)
            key=validated.get('checkout_key','')
            import uuid
            uuid.UUID(key)
        except (ValueError,TypeError,KeyError,AttributeError):return jsonify(error='ข้อมูลร่างการจองไม่ถูกต้อง'),400
        with closing(connect()) as c:
            existing=c.execute('SELECT user_id FROM booking_drafts WHERE id=?',(key,)).fetchone()
            if existing and existing[0]!=g.user['id']:return jsonify(error='ไม่พบร่างการจอง'),404
            validated.pop('demo_ack',None)
            c.execute('INSERT INTO booking_drafts VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET details=excluded.details,total=excluded.total',(key,g.user['id'],json.dumps(validated,ensure_ascii=False),total,datetime.now(timezone.utc).isoformat()));c.commit()
        return jsonify(message='บันทึกร่างที่รอชำระเงินจำลองแล้ว')

    @app.post('/api/bookings/discard-draft')
    def discard_draft():
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict):return jsonify(error='ข้อมูลไม่ถูกต้อง'),400
        with closing(connect()) as c:
            c.execute('DELETE FROM booking_drafts WHERE id=? AND user_id=?',(data.get('key'),g.user['id']));c.commit()
        return jsonify(message='ลบร่างการจองแล้ว')

    @app.post('/api/bookings/cancel')
    def cancel():
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict):return jsonify(error='ข้อมูลไม่ถูกต้อง'),400
        reason=data.get('reason')
        if not isinstance(reason,str) or not 5<=len(reason.strip())<=1000:return jsonify(error='กรุณาระบุเหตุผลขอยกเลิก 5–1000 ตัวอักษร'),400
        reason=reason.strip()
        with closing(connect()) as c:
            c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM bookings WHERE id=? AND user_id=?',(data.get('ref'),g.user['id'])).fetchone()
            if not row:return jsonify(error='ไม่พบการจอง'),404
            d=details(row,c);today=datetime.now(timezone(timedelta(hours=7))).date()
            if date.fromisoformat(d['depart'])<=today or d['booking_state']!='demo_paid':return jsonify(error='ยกเลิกได้เฉพาะรายการที่ยังไม่ถึงวันเดินทางและไม่เคยยกเลิก'),409
            c.execute('INSERT INTO booking_lifecycle VALUES (?,?,?)',(row['id'],'refund_requested',datetime.now(timezone.utc).isoformat()))
            c.execute('INSERT INTO cancellation_requests VALUES (?,?,?,?)',(row['id'],g.user['id'],reason,datetime.now(timezone.utc).isoformat()))
            app.audit(g.user['id'],'cancellation_requested',row['id'],c);c.commit()
        return jsonify(message='ยกเลิกการจองสาธิตแล้ว ส่งคำขอคืนเงินจำลองให้ Admin ตรวจสอบ ไม่มีการคืนเงินจริง')

    @app.post('/api/admin/refund')
    def refund():
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict):return jsonify(error='ข้อมูลไม่ถูกต้อง'),400
        with closing(connect()) as c:
            c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM bookings WHERE id=?',(data.get('ref'),)).fetchone()
            if not row:return jsonify(error='ไม่พบการจอง'),404
            if details(row,c)['booking_state']!='refund_requested':return jsonify(error='รายการนี้ไม่มีคำขอคืนเงินที่รออนุมัติ'),409
            c.execute("UPDATE booking_lifecycle SET state='demo_refunded',updated_at=? WHERE booking_id=?",(datetime.now(timezone.utc).isoformat(),row['id']))
            c.execute('DELETE FROM completed_journeys WHERE booking_id=?',(row['id'],))
            c.execute('DELETE FROM benefit_redemptions WHERE booking_id=?',(row['id'],))
            app.audit(g.user['id'],'demo_refund_approved',row['id'],c);c.commit()
        return jsonify(message='อนุมัติคืนเงินจำลองและคืนสิทธิ์ที่ใช้กับรายการนี้แล้ว ไม่มีการโอนเงินจริง')
