from password_policy import valid_password, PASSWORD_MESSAGE
from profile_rules import validate_profile_text
"""Account/session API. Public registration never grants admin privileges."""
import json
import secrets
import sqlite3
import re
from pathlib import Path
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import click
from flask import request, jsonify, session, g
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet


def configure_accounts(app):
    instance = Path(app.config['DATABASE']).parent
    instance.mkdir(parents=True, exist_ok=True)
    keyfile = instance / 'account.key'
    if not keyfile.exists():
        try:
            with keyfile.open('xb') as f:
                f.write(Fernet.generate_key())
        except FileExistsError:
            pass
    cipher = Fernet(keyfile.read_bytes())
    app.profile_cipher = cipher
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', PERMANENT_SESSION_LIFETIME=timedelta(hours=8))

    def connect():
        conn = sqlite3.connect(app.config['DATABASE'])
        conn.row_factory = sqlite3.Row
        return conn

    def initialize():
        with closing(connect()) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE COLLATE NOCASE NOT NULL,
                email TEXT UNIQUE COLLATE NOCASE NOT NULL, password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','admin')),
                profile BLOB NOT NULL, created_at TEXT NOT NULL)''')
            columns = {r['name'] for r in conn.execute('PRAGMA table_info(bookings)')}
            if 'user_id' not in columns:
                conn.execute('ALTER TABLE bookings ADD COLUMN user_id INTEGER REFERENCES users(id)')
            conn.commit()

    app.initialize_accounts = initialize

    def public_user(row):
        p = json.loads(cipher.decrypt(row['profile']).decode())
        p['document_masked'] = '••••' + p.pop('document', '')[-4:]
        birthday = date.fromisoformat(p['birth'])
        t = datetime.now(timezone(timedelta(hours=7))).date()
        p['age'] = t.year - birthday.year - ((t.month,t.day)<(birthday.month,birthday.day))
        return dict(id=row['id'], username=row['username'], email=row['email'], role=row['role'],email_verified=bool(row['email_verified']),mfa_enabled=bool(row['mfa_secret']),must_change_password=bool(row['must_change_password']), **p)

    app.public_user = public_user

    @app.before_request
    def account_context():
        g.user = None
        uid = session.get('user_id')
        if uid:
            with closing(connect()) as conn:
                g.user = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
        if request.method in {'POST','PUT','PATCH','DELETE'} and request.path.startswith('/api/'):
            if not secrets.compare_digest(request.headers.get('X-CSRF-Token','').encode(), session.get('csrf','missing').encode()):
                return jsonify(error='กรุณารีเฟรชหน้าเว็บแล้วลองใหม่'), 403
        if request.path.startswith('/api/admin') and (g.user is None or g.user['role'] != 'admin'):
            return jsonify(error='เฉพาะผู้ดูแลระบบเท่านั้น'), 403
        if request.path.startswith('/api/bookings') and g.user is None:
            return jsonify(error='กรุณาเข้าสู่ระบบก่อนจอง'), 401

    @app.get('/api/session')
    def account_session():
        session.setdefault('csrf', secrets.token_urlsafe(32))
        return jsonify(user=public_user(g.user) if g.user else None, csrf=session['csrf'])

    @app.post('/api/register')
    def register():
        data = request.get_json(silent=True)
        try:
            if not isinstance(data, dict):
                raise ValueError()
            username = data['username'].strip()
            email = data['email'].strip().lower()
            password = data['password']
            if not re.fullmatch(r'[A-Za-z0-9_.-]{3,30}', username) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):
                raise ValueError('Username ใช้ภาษาอังกฤษ/ตัวเลข 3–30 ตัว และต้องระบุอีเมลที่ถูกต้อง')
            if not valid_password(password):
                raise ValueError(PASSWORD_MESSAGE)
            profile = {}
            for key in ('first','last','birth','nationality','ethnicity','religion','phone','dial','gender','document_type','document'):
                value = data.get(key, '')
                if key in {'ethnicity','religion','document'} and not value:
                    profile[key] = ''
                    continue
                if not isinstance(value,str) or not value.strip() or len(value)>150:
                    raise ValueError('กรุณากรอกข้อมูลส่วนตัวให้ครบ')
                profile[key] = value.strip()
            validate_profile_text(profile)
            if len(profile['document'])>13:raise ValueError('เลขบัตรประชาชน / พาสปอร์ตต้องไม่เกิน 13 ตัว')
            birthday = date.fromisoformat(profile['birth'])
            t = datetime.now(timezone(timedelta(hours=7))).date()
            age = t.year-birthday.year-((t.month,t.day)<(birthday.month,birthday.day))
            if not 12 <= age <= 120:
                raise ValueError('รองรับสมาชิกอายุ 12–120 ปี')
            if profile['gender'] not in {'ชาย','หญิง'} or profile['document_type'] not in {'id','passport'}:
                raise ValueError('กรุณาตรวจข้อมูลเพศและประเภทเอกสาร')
            if profile['document'] and profile['document_type']=='id' and not re.fullmatch(r'\d{13}',profile['document']):
                raise ValueError('เลขบัตรประชาชนต้องมี 13 หลัก')
            if profile['document'] and profile['document_type']=='passport' and not re.fullmatch(r'[A-Za-z0-9]{5,13}',profile['document']):
                raise ValueError('หมายเลขพาสปอร์ตไม่ถูกต้อง')
            if not re.fullmatch(r'[0-9 ()+\-]{6,20}',profile['phone']) or not re.fullmatch(r'\d{1,4}',profile['dial']):
                raise ValueError('เบอร์โทรไม่ถูกต้อง')
            with closing(connect()) as conn:
                conn.execute('INSERT INTO users (username,email,password_hash,profile,created_at) VALUES (?,?,?,?,?)',
                             (username,email,generate_password_hash(password),cipher.encrypt(json.dumps(profile,ensure_ascii=False).encode()),datetime.now(timezone.utc).isoformat()))
                conn.commit()
        except sqlite3.IntegrityError:
            return jsonify(error='Username หรืออีเมลนี้มีผู้ใช้แล้ว'),409
        except (ValueError,KeyError,TypeError,AttributeError) as exc:
            return jsonify(error=str(exc) or 'กรุณาตรวจสอบข้อมูลลงทะเบียน'),400
        return jsonify(message='ลงทะเบียนสำเร็จ กรุณาเข้าสู่ระบบอีกครั้ง'),201

    @app.post('/api/login')
    def login():
        data = request.get_json(silent=True) or {}
        if not isinstance(data,dict):
            return jsonify(error='ข้อมูลไม่ถูกต้อง'),400
        identifier = str(data.get('identifier',''))[:150].strip()
        with closing(connect()) as conn:
            user = conn.execute('SELECT * FROM users WHERE username=? COLLATE NOCASE OR email=? COLLATE NOCASE',(identifier,identifier)).fetchone()
        password = data.get('password','')
        if not isinstance(password,str) or len(password)>128 or not user or not check_password_hash(user['password_hash'],password):
            return jsonify(error='Username/อีเมล หรือรหัสผ่านไม่ถูกต้อง'),401
        if data.get('role','user') != user['role']:
            return jsonify(error='บัญชีนี้ไม่มีสิทธิ์ในประเภทที่เลือก'),403
        failure=app.check_login_security(user,data)
        if failure:return failure
        session.clear()
        session.update(version=user['session_version'],user_id=user['id'],csrf=secrets.token_urlsafe(32))
        session.permanent=True
        return jsonify(user=public_user(user),csrf=session['csrf'])

    @app.post('/api/logout')
    def logout():
        session.clear()
        return jsonify(message='ออกจากระบบแล้ว')

    @app.get('/api/bookings')
    def my_bookings():
        with closing(connect()) as conn:
            rows=conn.execute("SELECT * FROM bookings WHERE user_id=? ORDER BY created_at DESC",(g.user['id'],)).fetchall()
            bookings=[app.booking_details(r,conn) for r in rows]+app.booking_drafts(conn,g.user['id'])
        return jsonify(bookings=bookings)

    @app.get('/api/admin/bookings')
    def admin_bookings():
        with closing(connect()) as conn:
            rows=conn.execute('SELECT b.*, u.username FROM bookings b LEFT JOIN users u ON b.user_id=u.id ORDER BY b.created_at DESC').fetchall()
            bookings=[dict(app.booking_details(r,conn),username=r['username'] or 'การจองก่อนมีระบบสมาชิก',status=r['status']) for r in rows]+app.booking_drafts(conn)
        return jsonify(bookings=bookings)

    @app.get('/api/admin/bookings/<reference>')
    def admin_booking_detail(reference):
        with closing(connect()) as conn:
            row=conn.execute('SELECT b.*,u.username FROM bookings b LEFT JOIN users u ON u.id=b.user_id WHERE b.id=?',(reference,)).fetchone()
            if row:
                booking=app.booking_details(row,conn)
                stored=conn.execute('SELECT gender,first_name,last_name,birth_date FROM passengers WHERE booking_id=? ORDER BY id',(reference,)).fetchall()
                original=booking.get('passengers',[])
                booking['passengers']=[dict(first=p['first_name'],last=p['last_name'],gender=p['gender'],birth=p['birth_date'],category=original[i].get('category','adult') if i<len(original) else 'adult') for i,p in enumerate(stored)] or original
                booking.update(username=row['username'] or 'การจองก่อนมีบัญชี',created_at=row['created_at'])
            else:
                row=conn.execute('SELECT d.*,u.username FROM booking_drafts d LEFT JOIN users u ON u.id=d.user_id WHERE d.id=?',(reference,)).fetchone()
                if not row:return jsonify(error='ไม่พบการจอง'),404
                booking=dict(json.loads(row['details']),ref='DR-'+row['id'][:12].upper(),checkout_key=row['id'],total=row['total'],booking_state='awaiting_demo_payment',created_at=row['created_at'],username=row['username'])
        return jsonify(booking=booking)

    @app.cli.command('make-admin')
    @click.argument('username')
    def make_admin(username):
        """Promote an existing account from the local terminal only."""
        with closing(connect()) as conn:
            result=conn.execute("UPDATE users SET role='admin' WHERE username=? COLLATE NOCASE",(username,))
            conn.commit()
        if not result.rowcount:
            raise click.ClickException('ไม่พบ username กรุณาลงทะเบียนก่อน')
        click.echo('กำหนดสิทธิ์ Admin สำเร็จ')

