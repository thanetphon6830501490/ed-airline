from password_policy import valid_password, PASSWORD_MESSAGE
from profile_rules import validate_profile_text
"""Local security controls and deployment settings; no payment verification."""
import os
import json
import secrets
import hashlib
import hmac
import base64
import struct
import time
import sqlite3
import smtplib
import ssl
import zipfile
from email.message import EmailMessage
from pathlib import Path
from contextlib import closing
from datetime import datetime, timezone
import click
from flask import request, session, g, jsonify
from werkzeug.security import generate_password_hash, check_password_hash


def configure_security(app):
    instance=Path(app.config['DATABASE']).parent
    keyfile=instance/'session.key'
    if not keyfile.exists():
        try:
            with keyfile.open('xb') as f:f.write(secrets.token_bytes(32))
        except FileExistsError:pass
    production=os.environ.get('ARI_ENV')=='production'
    configured_secret=os.environ.get('ARI_SESSION_SECRET')
    if configured_secret and (len(configured_secret)<32 or configured_secret.startswith('REPLACE')):
        raise RuntimeError('ARI_SESSION_SECRET ต้องเป็นค่าสุ่มจริงอย่างน้อย 32 ตัว ห้ามใช้ข้อความตัวอย่าง')
    app.secret_key=os.environ.get('ARI_SESSION_SECRET') or keyfile.read_bytes()
    app.config.update(SESSION_COOKIE_SECURE=production,PRODUCTION=production)

    def connect():
        c=sqlite3.connect(app.config['DATABASE'],timeout=15);c.row_factory=sqlite3.Row
        return c

    def initialize():
        with closing(connect()) as c:
            columns={r['name'] for r in c.execute('PRAGMA table_info(users)')}
            for name,decl in [('session_version','INTEGER NOT NULL DEFAULT 0'),('email_verified','INTEGER NOT NULL DEFAULT 0'),('must_change_password','INTEGER NOT NULL DEFAULT 0'),('mfa_secret','BLOB')]:
                if name not in columns:c.execute(f'ALTER TABLE users ADD COLUMN {name} {decl}')
            c.executescript('''
                CREATE TABLE IF NOT EXISTS rate_events (key TEXT NOT NULL, at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS rate_events_key ON rate_events(key,at);
                CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY, actor_id INTEGER, action TEXT NOT NULL, target TEXT, at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS account_tokens (digest TEXT PRIMARY KEY,user_id INTEGER NOT NULL,kind TEXT NOT NULL,expires REAL NOT NULL,used INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS mail_outbox (id INTEGER PRIMARY KEY, payload BLOB NOT NULL,at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS idempotency (user_id INTEGER NOT NULL,key TEXT NOT NULL,digest TEXT NOT NULL,response TEXT NOT NULL,PRIMARY KEY(user_id,key));
                CREATE TABLE IF NOT EXISTS pending_mfa (user_id INTEGER PRIMARY KEY,secret BLOB NOT NULL,expires REAL NOT NULL);
            ''')
            for u in c.execute("SELECT id,password_hash FROM users WHERE role='admin'").fetchall():
                if check_password_hash(u['password_hash'],'admin101'):
                    c.execute('UPDATE users SET must_change_password=1 WHERE id=?',(u['id'],))
            c.commit()
    app.initialize_security=initialize;initialize()

    def audit(actor,action,target,conn=None):
        if conn is not None:
            conn.execute('INSERT INTO audit_log(actor_id,action,target,at) VALUES (?,?,?,?)',(actor,action,str(target)[:100],datetime.now(timezone.utc).isoformat()))
        else:
            with closing(connect()) as c:
                audit(actor,action,target,c);c.commit()
    app.audit=audit

    def totp(secret,code):
        if not isinstance(code,str) or len(code)!=6 or not code.isdigit():return False
        key=base64.b32decode(secret)
        for delta in (-1,0,1):
            data=struct.pack('>Q',int(time.time()//30)+delta)
            digest=hmac.new(key,data,hashlib.sha1).digest();offset=digest[-1]&15
            candidate=f'{(struct.unpack(">I",digest[offset:offset+4])[0]&0x7fffffff)%1000000:06d}'
            if hmac.compare_digest(candidate,code):return True
        return False

    def check_login(user,data):
        if user['mfa_secret'] and not totp(app.profile_cipher.decrypt(user['mfa_secret']).decode(),data.get('otp','')):
            return jsonify(error='ต้องระบุรหัส 6 หลักจากแอป Authenticator',mfa_required=True),401
        return None
    app.check_login_security=check_login

    @app.before_request
    def guard():
        if request.path in {'/api/password/local-recovery','/api/login','/api/register','/api/password/request-reset','/api/password/reset','/api/email/verify','/api/email/request-verification'} and request.method=='POST':
            data=request.get_json(silent=True);identifier=str(data.get('identifier',data.get('email','')))[:150].lower() if isinstance(data,dict) else ''
            ip=request.remote_addr or 'unknown';window=3600 if request.path=='/api/register' else 600;limit=5 if request.path=='/api/register' else 10
            keys=[hashlib.sha256((request.path+':ip:'+ip).encode()).hexdigest()]
            if identifier:keys.append(hashlib.sha256((request.path+':account:'+identifier).encode()).hexdigest())
            with closing(connect()) as c:
                c.execute('BEGIN IMMEDIATE');c.execute('DELETE FROM rate_events WHERE at<?',(time.time()-86400,))
                blocked=any(c.execute('SELECT COUNT(*) FROM rate_events WHERE key=? AND at>?',(key,time.time()-window)).fetchone()[0]>=limit for key in keys)
                if not blocked:c.executemany('INSERT INTO rate_events VALUES (?,?)',[(key,time.time()) for key in keys])
                c.commit()
            if blocked:return jsonify(error='ลองหลายครั้งเกินไป กรุณารอแล้วลองใหม่'),429
        if g.user is not None:
            if session.get('version')!=g.user['session_version']:
                session.clear();g.user=None
                if request.path!='/api/session':return jsonify(error='Session หมดอายุ กรุณาเข้าสู่ระบบใหม่'),401
            elif g.user['must_change_password'] and request.path.startswith('/api/') and request.path not in {'/api/session','/api/profile','/api/password/change','/api/logout'}:
                return jsonify(error='กรุณาเปลี่ยนรหัสผ่าน Admin เริ่มต้นก่อนใช้งาน',password_change_required=True),403
        if request.path in {'/api/profile','/api/password/change','/api/email/request-verification','/api/security/mfa/setup','/api/security/mfa/enable','/api/security/revoke-sessions'} and g.user is None:
            return jsonify(error='กรุณาเข้าสู่ระบบ'),401
        if production and not app.config.get('PUBLIC_PREVIEW') and request.path=='/api/bookings' and request.method=='POST' and g.user is not None and not g.user['email_verified']:
            return jsonify(error='กรุณายืนยันอีเมลก่อนจอง'),403
        if production and request.path.startswith('/api/admin') and g.user is not None and not g.user['mfa_secret']:
            return jsonify(error='Admin ต้องเปิดใช้ 2FA ก่อนใช้งานบนโฮสติ้ง'),403
        if request.path=='/api/bookings' and request.method=='POST' and g.user is not None:
            key=request.headers.get('Idempotency-Key','')
            if not 16<=len(key)<=100 or not all(ch.isalnum() or ch in '-_' for ch in key):return jsonify(error='กรุณารีเฟรชเพื่อสร้างรหัสคำขอจอง'),400
            digest=hashlib.sha256(json.dumps(request.get_json(silent=True),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            with closing(connect()) as c:r=c.execute('SELECT * FROM idempotency WHERE user_id=? AND key=?',(g.user['id'],key)).fetchone()
            if r:
                if not hmac.compare_digest(r['digest'],digest):return jsonify(error='คำขอเดิมมีข้อมูลเปลี่ยน กรุณากลับไปตรวจสอบการจอง'),409
                return jsonify(json.loads(r['response'])),200
            g.booking_key=key;g.booking_digest=digest

    def record_response(conn,response):
        conn.execute('INSERT INTO idempotency VALUES (?,?,?,?)',(g.user['id'],g.booking_key,g.booking_digest,json.dumps(response)))
        audit(g.user['id'],'booking_created',response['ref'],conn)
    app.record_booking_response=record_response
    def existing_response(conn):
        row=conn.execute('SELECT digest,response FROM idempotency WHERE user_id=? AND key=?',(g.user['id'],g.booking_key)).fetchone()
        if row:
            if not hmac.compare_digest(row[0],g.booking_digest):
                from flask import abort
                abort(409)
            return json.loads(row[1])
        return None
    app.existing_booking_response=existing_response

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='strict-origin-when-cross-origin'
        response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
        if request.path.startswith('/api/'):response.headers['Cache-Control']='no-store'
        if production:
            response.headers['Strict-Transport-Security']='max-age=31536000'
            response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' https: data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'; form-action 'self'"
        return response

    @app.get('/api/profile')
    def profile():return jsonify(user=app.public_user(g.user))

    @app.post('/api/profile')
    def edit_profile():
        data=request.get_json(silent=True)
        if not isinstance(data,dict):return jsonify(error='ข้อมูลไม่ถูกต้อง'),400
        p=json.loads(app.profile_cipher.decrypt(g.user['profile']).decode())
        for key in ('first','last','nationality','phone','dial','ethnicity','religion','birth','gender'):
            if key in data:
                v=data[key]
                if not isinstance(v,str) or len(v)>150 or (key in {'first','last','nationality','phone','dial'} and not v.strip()):return jsonify(error='กรุณาตรวจสอบข้อมูลโปรไฟล์'),400
                p[key]=v.strip()
        try:validate_profile_text(p)
        except ValueError as error:return jsonify(error=str(error)),400
        import re
        if not re.fullmatch(r'[0-9 ()+\-]{6,20}',p['phone']) or not re.fullmatch(r'\d{1,4}',p['dial']):return jsonify(error='เบอร์โทรไม่ถูกต้อง'),400
        from datetime import date
        try:
            birth=date.fromisoformat(p['birth']);today=datetime.now(timezone.utc).date()
            age=today.year-birth.year-((today.month,today.day)<(birth.month,birth.day))
            if not 12<=age<=120 or p['gender'] not in {'ชาย','หญิง'}:raise ValueError()
        except (ValueError,TypeError):return jsonify(error='กรุณาตรวจสอบวันเกิดและเพศ'),400
        if data.get('document'):
            document=data['document'];kind=data.get('document_type')
            if not isinstance(document,str) or kind not in {'id','passport'} or not re.fullmatch(r'\d{13}' if kind=='id' else r'[A-Za-z0-9]{5,13}',document):return jsonify(error='เลขเอกสารไม่ถูกต้อง'),400
            p.update(document=document,document_type=kind)
        with closing(connect()) as c:
            c.execute('UPDATE users SET profile=? WHERE id=?',(app.profile_cipher.encrypt(json.dumps(p,ensure_ascii=False).encode()),g.user['id']));audit(g.user['id'],'profile_updated',g.user['id'],c);c.commit()
            user=c.execute('SELECT * FROM users WHERE id=?',(g.user['id'],)).fetchone()
        return jsonify(user=app.public_user(user))

    @app.post('/api/password/change')
    def change_password():
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict) or not isinstance(data.get('old_password'),str) or not check_password_hash(g.user['password_hash'],data['old_password']):return jsonify(error='รหัสผ่านเดิมไม่ถูกต้อง'),400
        new=data.get('new_password')
        if not valid_password(new) or new == data['old_password']:return jsonify(error=PASSWORD_MESSAGE+' และต้องต่างจากรหัสเดิม'),400
        version=g.user['session_version']+1
        with closing(connect()) as c:
            c.execute('UPDATE users SET password_hash=?,session_version=?,must_change_password=0 WHERE id=?',(generate_password_hash(new),version,g.user['id']));audit(g.user['id'],'password_changed',g.user['id'],c);c.commit()
        session['version']=version
        return jsonify(message='เปลี่ยนรหัสผ่านสำเร็จ Session อื่นถูกยกเลิกแล้ว')

    @app.post('/api/security/revoke-sessions')
    def revoke_sessions():
        with closing(connect()) as c:
            c.execute('UPDATE users SET session_version=session_version+1 WHERE id=?',(g.user['id'],));audit(g.user['id'],'sessions_revoked',g.user['id'],c);c.commit()
        session.clear();return jsonify(message='ออกจากระบบทุกอุปกรณ์แล้ว')

    @app.post('/api/security/mfa/setup')
    def mfa_setup():
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict) or not isinstance(data.get('password'),str) or not check_password_hash(g.user['password_hash'],data['password']):return jsonify(error='รหัสผ่านไม่ถูกต้อง'),400
        if g.user['mfa_secret']:return jsonify(error='เปิดใช้งาน 2FA แล้ว'),409
        secret=base64.b32encode(secrets.token_bytes(20)).decode()
        with closing(connect()) as c:
            c.execute('INSERT OR REPLACE INTO pending_mfa VALUES (?,?,?)',(g.user['id'],app.profile_cipher.encrypt(secret.encode()),time.time()+600));c.commit()
        return jsonify(secret=secret,message='เพิ่มกุญแจในแอป Authenticator แล้วกรอกรหัส 6 หลักเพื่อยืนยัน')

    @app.post('/api/security/mfa/enable')
    def mfa_enable():
        data=request.get_json(silent=True) or {}
        with closing(connect()) as c:
            pending=c.execute('SELECT secret FROM pending_mfa WHERE user_id=? AND expires>?',(g.user['id'],time.time())).fetchone()
        secret=app.profile_cipher.decrypt(pending[0]).decode() if pending else None
        if not isinstance(data,dict) or not secret or not totp(secret,data.get('otp')):return jsonify(error='รหัส Authenticator ไม่ถูกต้อง'),400
        version=g.user['session_version']+1
        with closing(connect()) as c:
            c.execute('UPDATE users SET mfa_secret=?,session_version=? WHERE id=?',(app.profile_cipher.encrypt(secret.encode()),version,g.user['id']));c.execute('DELETE FROM pending_mfa WHERE user_id=?',(g.user['id'],));audit(g.user['id'],'mfa_enabled',g.user['id'],c);c.commit()
        session['version']=version
        return jsonify(message='เปิดใช้ 2FA แล้ว ต้องใช้รหัสจากแอปเมื่อเข้าสู่ระบบครั้งถัดไป')

    def create_mail(user,kind):
        token=secrets.token_urlsafe(32);digest=hashlib.sha256(token.encode()).hexdigest()
        origin=os.environ.get('ARI_PUBLIC_URL','http://127.0.0.1:5000').rstrip('/')
        url=origin+('/?reset_token=' if kind=='reset' else '/?verify_token=')+token
        payload=dict(to=user['email'],subject='ED Airline '+('Reset password' if kind=='reset' else 'Verify email'),body=url)
        with closing(connect()) as c:
            c.execute('UPDATE account_tokens SET used=1 WHERE user_id=? AND kind=?',(user['id'],kind))
            c.execute('INSERT INTO account_tokens VALUES (?,?,?,?,0)',(digest,user['id'],kind,time.time()+1800))
            c.execute('INSERT INTO mail_outbox(payload,at) VALUES (?,?)',(app.profile_cipher.encrypt(json.dumps(payload).encode()),datetime.now(timezone.utc).isoformat()));c.commit()
        host=os.environ.get('ARI_SMTP_HOST')
        if host and all(os.environ.get(k) for k in ('ARI_SMTP_FROM','ARI_SMTP_USER','ARI_SMTP_PASSWORD')):
            msg=EmailMessage();msg['From']=os.environ['ARI_SMTP_FROM'];msg['To']=user['email'];msg['Subject']=payload['subject'];msg.set_content(url)
            try:
                with smtplib.SMTP(host,int(os.environ.get('ARI_SMTP_PORT','587')),timeout=10) as smtp:
                    smtp.starttls(context=ssl.create_default_context());smtp.login(os.environ['ARI_SMTP_USER'],os.environ['ARI_SMTP_PASSWORD']);smtp.send_message(msg)
            except Exception:app.logger.error('Email delivery failed; message retained in encrypted outbox')

    @app.post('/api/email/request-verification')
    def request_verification():
        create_mail(g.user,'verify');return jsonify(message='สร้างคำขอยืนยันแล้ว หากตั้งค่าอีเมลจะได้รับลิงก์ มิฉะนั้นตรวจกล่องทดสอบผ่าน Terminal')

    @app.post('/api/password/local-recovery')
    def local_recovery():
        if production:return jsonify(error='การกู้รหัสด้วยอีเมลและเบอร์ใช้ได้เฉพาะเว็บสาธิตในเครื่อง'),403
        if request.remote_addr not in ('127.0.0.1','::1'):return jsonify(error='ใช้การกู้รหัสนี้ได้จากเครื่องที่รันเว็บเท่านั้น'),403
        data=request.get_json(silent=True)
        if not isinstance(data,dict):return jsonify(error='ข้อมูลไม่ถูกต้อง'),400
        email=str(data.get('email','')).strip()[:150]
        phone=''.join(ch for ch in str(data.get('phone','')) if ch.isdigit())
        password=data.get('password')
        if not valid_password(password):return jsonify(error=PASSWORD_MESSAGE),400
        with closing(connect()) as c:
            user=c.execute('SELECT * FROM users WHERE email=? COLLATE NOCASE',(email,)).fetchone()
            profile=json.loads(app.profile_cipher.decrypt(user['profile'])) if user else {}
            stored=''.join(ch for ch in str(profile.get('phone','')) if ch.isdigit())
            if not user or not phone or not stored or not secrets.compare_digest(phone,stored):return jsonify(error='อีเมลหรือเบอร์โทรไม่ตรงกับบัญชี'),400
            if user['mfa_secret'] and not totp(app.profile_cipher.decrypt(user['mfa_secret']).decode(),data.get('otp','')):return jsonify(error='ต้องระบุรหัส 6 หลักจากแอป Authenticator',mfa_required=True),401
            c.execute('UPDATE users SET password_hash=?,session_version=session_version+1,must_change_password=0 WHERE id=?',(generate_password_hash(password),user['id']))
            c.execute('UPDATE account_tokens SET used=1 WHERE user_id=?',(user['id'],))
            audit(user['id'],'local_password_recovered',user['id'],c);c.commit()
        session.clear()
        return jsonify(message='ตั้งรหัสผ่านใหม่แล้ว กรุณาเข้าสู่ระบบอีกครั้ง')

    @app.post('/api/password/request-reset')
    def request_reset():
        data=request.get_json(silent=True) or {};email=data.get('email','') if isinstance(data,dict) else ''
        with closing(connect()) as c:user=c.execute('SELECT * FROM users WHERE email=? COLLATE NOCASE',(str(email).strip()[:150],)).fetchone()
        if not all(os.environ.get(k) for k in ('ARI_SMTP_HOST','ARI_SMTP_FROM','ARI_SMTP_USER','ARI_SMTP_PASSWORD')):
            return jsonify(error='ยังไม่ได้ตั้งค่าระบบส่งอีเมล กรุณาติดต่อผู้ดูแลเว็บไซต์'),503
        if user:create_mail(user,'reset')
        return jsonify(message='หากอีเมลมีอยู่ในระบบ จะส่งลิงก์รีเซ็ตรหัสผ่านให้ กรุณาตรวจกล่องจดหมายและสแปม')

    def consume(kind,token,password=None):
        if not isinstance(token,str):return False
        with closing(connect()) as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM account_tokens WHERE digest=? AND kind=? AND used=0 AND expires>?',(hashlib.sha256(token.encode()).hexdigest(),kind,time.time())).fetchone()
            if not row:return False
            if kind=='reset':
                user=c.execute('SELECT mfa_secret FROM users WHERE id=?',(row['user_id'],)).fetchone()
                data=request.get_json(silent=True) or {}
                if user['mfa_secret'] and not totp(app.profile_cipher.decrypt(user['mfa_secret']).decode(),data.get('otp','')):return False
                c.execute('UPDATE users SET password_hash=?,session_version=session_version+1,must_change_password=0 WHERE id=?',(generate_password_hash(password),row['user_id']))
            else:c.execute('UPDATE users SET email_verified=1 WHERE id=?',(row['user_id'],))
            c.execute('UPDATE account_tokens SET used=1 WHERE digest=?',(row['digest'],));audit(row['user_id'],kind+'_completed',row['user_id'],c);c.commit()
        return True

    @app.post('/api/email/verify')
    def verify_email():
        d=request.get_json(silent=True) or {}
        if not isinstance(d,dict) or not consume('verify',d.get('token')):return jsonify(error='ลิงก์ใช้ไม่ได้ หมดอายุ หรือถูกใช้แล้ว'),400
        return jsonify(message='ยืนยันอีเมลสำเร็จ')

    @app.post('/api/password/reset')
    def reset_password():
        d=request.get_json(silent=True) or {};password=d.get('password') if isinstance(d,dict) else None
        if not valid_password(password):return jsonify(error=PASSWORD_MESSAGE),400
        if not consume('reset',d.get('token'),password):return jsonify(error='ลิงก์หรือรหัส 2FA ไม่ถูกต้อง หมดอายุ หรือใช้แล้ว'),400
        return jsonify(message='ตั้งรหัสผ่านใหม่สำเร็จ กรุณาเข้าสู่ระบบ')

    @app.get('/api/admin/audit')
    def audit_log():
        with closing(connect()) as c:rows=c.execute('SELECT a.*,u.username FROM audit_log a LEFT JOIN users u ON a.actor_id=u.id ORDER BY a.id DESC LIMIT 200').fetchall()
        return jsonify(events=[dict(r) for r in rows])

    @app.cli.command('mail-outbox')
    def mail_outbox():
        """Local development mail viewer. Never expose it as a public endpoint."""
        with closing(connect()) as c:rows=c.execute('SELECT payload FROM mail_outbox ORDER BY id DESC LIMIT 10').fetchall()
        for r in rows:click.echo(app.profile_cipher.decrypt(r['payload']).decode())

    @app.cli.command('reset-mfa')
    @click.argument('username')
    def reset_mfa(username):
        """Offline recovery by the server owner; revokes all account sessions."""
        if not click.confirm('ปิด 2FA ของบัญชีนี้และยกเลิกทุก Session?',default=False):return
        with closing(connect()) as c:
            user=c.execute('SELECT id FROM users WHERE username=? COLLATE NOCASE',(username,)).fetchone()
            if not user:raise click.ClickException('ไม่พบบัญชี')
            c.execute('UPDATE users SET mfa_secret=NULL,session_version=session_version+1 WHERE id=?',(user['id'],));audit(user['id'],'mfa_offline_recovery',user['id'],c);c.commit()
        click.echo('ปิด 2FA แล้ว ให้ตั้งค่าใหม่ก่อนใช้งานหลังบ้านบนโฮสติ้ง')

    @app.cli.command('backup')
    def backup():
        folder=Path(app.config['DATABASE']).parent/'backups';folder.mkdir(exist_ok=True)
        stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S');db=folder/(stamp+'.db');archive=folder/(stamp+'.zip')
        with closing(connect()) as source,closing(sqlite3.connect(db)) as target:source.backup(target)
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            z.write(db,'potter.db')
            for name in ('account.key','session.key','promptpay.enc'):
                if (instance/name).exists():z.write(instance/name,name)
        db.unlink();click.echo(str(archive));click.echo('เก็บไฟล์นี้ในที่ปลอดภัย มีข้อมูลส่วนตัวและกุญแจเข้ารหัส')
