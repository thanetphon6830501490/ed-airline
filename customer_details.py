import sqlite3
from contextlib import closing
from datetime import datetime,timezone
from flask import g,request,jsonify

def configure_customer_details(app):
    def connect():
        c=sqlite3.connect(app.config['DATABASE']);c.row_factory=sqlite3.Row;return c
    with closing(connect()) as c:c.execute('CREATE TABLE IF NOT EXISTS support_replies(id INTEGER PRIMARY KEY,case_id TEXT NOT NULL REFERENCES support_cases(id),actor_id INTEGER NOT NULL,body TEXT NOT NULL,created_at TEXT NOT NULL)');c.commit()
    @app.get('/api/support/cases')
    def my_cases():
        if g.user is None:return jsonify(error='กรุณาเข้าสู่ระบบ'),401
        with closing(connect()) as c:
            cases=[]
            for row in c.execute('SELECT * FROM support_cases WHERE user_id=? ORDER BY created_at DESC',(g.user['id'],)).fetchall():
                item=dict(row);item['replies']=[dict(r) for r in c.execute('SELECT body,created_at FROM support_replies WHERE case_id=? ORDER BY id',(row['id'],))];cases.append(item)
        return jsonify(cases=cases)
    @app.post('/api/admin/support/reply')
    def reply():
        d=request.get_json(silent=True)
        if not isinstance(d,dict) or not isinstance(d.get('body'),str) or not 1<=len(d['body'].strip())<=3000 or d.get('state') not in ('open','in_progress','resolved'):return jsonify(error='ข้อความหรือสถานะไม่ถูกต้อง'),400
        with closing(connect()) as c:
            if not c.execute('SELECT 1 FROM support_cases WHERE id=?',(d.get('ref'),)).fetchone():return jsonify(error='ไม่พบเรื่องติดต่อ'),404
            c.execute('INSERT INTO support_replies(case_id,actor_id,body,created_at) VALUES(?,?,?,?)',(d['ref'],g.user['id'],d['body'].strip(),datetime.now(timezone.utc).isoformat()));c.execute('UPDATE support_cases SET state=? WHERE id=?',(d['state'],d['ref']));app.audit(g.user['id'],'support_reply',d['ref'],c);c.commit()
        return jsonify(message='บันทึกคำตอบแล้ว ลูกค้าอ่านได้ในเรื่องติดต่อของฉัน')
    @app.get('/api/admin/support/<ref>/replies')
    def replies(ref):
        with closing(connect()) as c:rows=[dict(r) for r in c.execute('SELECT body,created_at FROM support_replies WHERE case_id=? ORDER BY id',(ref,))]
        return jsonify(replies=rows)
