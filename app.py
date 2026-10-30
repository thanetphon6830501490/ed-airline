"""Potter: local flight-booking demo with Flask and SQLite."""
import json
import os
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

from flask import Flask, jsonify, render_template, request, g

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, root_path=str(BASE_DIR))
app.config['PUBLIC_PREVIEW'] = os.environ.get('ED_PUBLIC_PREVIEW') == '1' and os.environ.get('ED_SALES_MODE') == 'demo'
app.config.update(DATABASE=str(Path(os.environ.get('ED_DATA_DIR', str(BASE_DIR / 'instance'))) / 'potter.db'), MAX_CONTENT_LENGTH=64 * 1024)
from travel import AIRPORTS, catalogue, party, fare_total, promotion
AIRLINES = [('Thai AirAsia', 'FD', 0, '07:15', '08:30'),
            ('Thai Vietjet', 'VZ', 260, '10:40', '11:55'),
            ('Thai Lion Air', 'SL', 520, '14:20', '15:35'),
            ('Nok Air', 'DD', 1390, '16:45', '18:00'),
            ('Thai Airways', 'TG', 2100, '19:10', '20:25')]


def init_db():
    """Create the database and tables without deleting previous bookings."""
    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(app.config['DATABASE'])) as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS bookings (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status = 'demo_paid'),
                total INTEGER NOT NULL,
                details TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS passengers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id TEXT NOT NULL REFERENCES bookings(id),
                gender TEXT NOT NULL,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                birth_date TEXT NOT NULL
            );
        ''')
        conn.commit()


def fares(destination):
    base = 1190 if destination == 'HKT' else 890
    return [dict(air=air, code=f'{code}{310+i}', price=base+extra, start=start, end=end)
            for i, (air, code, extra, start, end) in enumerate(AIRLINES)]


def clean_text(value, label, limit=100):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'กรุณาตรวจสอบ{label}')
    return value.strip()


def validate_booking(data):
    if not isinstance(data, dict):
        raise ValueError('ข้อมูลการจองไม่ถูกต้อง')
    today = datetime.now(timezone(timedelta(hours=7))).date()
    origin, destination = data.get('from'), data.get('to')
    if origin not in AIRPORTS or destination not in AIRPORTS or origin == destination:
        raise ValueError('กรุณาตรวจสอบสนามบินต้นทางและปลายทาง')
    trip = data.get('trip')
    if trip not in {'one', 'round'}:
        raise ValueError('ประเภทการเดินทางไม่ถูกต้อง')
    depart = date.fromisoformat(data.get('depart', ''))
    if depart < today:
        raise ValueError('วันที่เดินทางต้องไม่อยู่ในอดีต')
    if trip == 'round' and date.fromisoformat(data.get('return', '')) < depart:
        raise ValueError('วันกลับต้องไม่ก่อนวันเดินทาง')
    count = data.get('count')
    adults, children, infants = party(data)
    contact = data.get('contact')
    if not isinstance(contact, dict):
        raise ValueError('กรุณากรอกข้อมูลติดต่อ')
    for key, label in [('first', 'ชื่อ'), ('last', 'นามสกุล'), ('email', 'อีเมล'), ('country', 'ประเทศ'), ('dial', 'รหัสประเทศ'), ('phone', 'เบอร์โทร')]:
        contact[key] = clean_text(contact.get(key), label)
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', contact['email']):
        raise ValueError('อีเมลไม่ถูกต้อง')
    if not re.fullmatch(r'[0-9 ()+\-]{6,20}', contact['phone']) or not re.fullmatch(r'\d{1,4}', contact['dial']):
        raise ValueError('เบอร์โทรหรือรหัสประเทศไม่ถูกต้อง')
    passengers = data.get('passengers')
    if not isinstance(passengers, list) or len(passengers) != count:
        raise ValueError('จำนวนข้อมูลผู้โดยสารไม่ตรงกับการจอง')
    for index, p in enumerate(passengers):
        if not isinstance(p, dict) or p.get('gender') not in {'ชาย', 'หญิง'}:
            raise ValueError('กรุณาระบุเพศผู้โดยสาร')
        p['first'] = clean_text(p.get('first'), 'ชื่อผู้โดยสาร')
        p['last'] = clean_text(p.get('last'), 'นามสกุลผู้โดยสาร')
        birth = date.fromisoformat(p.get('birth', ''))
        age = depart.year - birth.year - ((depart.month, depart.day) < (birth.month, birth.day))
        category = 'adult' if index < adults else 'child' if index < adults+children else 'infant'
        if birth > today or age > 120 or (category == 'adult' and age < 12) or (category == 'child' and not 2 <= age <= 11) or (category == 'infant' and not 0 <= age < 2):
            raise ValueError('อายุผู้โดยสารไม่ตรงกับประเภทในวันเดินทาง')
        if trip == 'round' and category != 'adult':
            back = date.fromisoformat(data['return'])
            back_age = back.year-birth.year-((back.month, back.day)<(birth.month,birth.day))
            if (category == 'infant' and back_age >= 2) or (category == 'child' and back_age >= 12):
                raise ValueError('ประเภทผู้โดยสารต้องตรงกับอายุทั้งขาไปและขากลับ')
        p['category'] = category
    selected = data.get('flights')
    if not isinstance(selected, list) or len(selected) != (2 if trip == 'round' else 1):
        raise ValueError('กรุณาเลือกเที่ยวบินให้ครบ')
    # Recalculate fares on the server. Never trust prices from the browser.
    canonical = []
    modern = data.get('catalogue_version') == 2
    if not modern and (children or infants or data.get('cabin','economy') != 'economy' or data.get('promo_code')):
        raise ValueError('กรุณาค้นหาเที่ยวบินใหม่')
    for index, f in enumerate(selected):
        source, target = (origin,destination) if index == 0 else (destination,origin)
        travel_date = data['depart'] if index == 0 else data['return']
        choices = catalogue(source,target,travel_date,data.get('cabin','economy')) if modern else fares(target)
        allowed = {choice['code']: choice for choice in choices}
        if not isinstance(f,dict) or f.get('code') not in allowed:
            raise ValueError('เที่ยวบินไม่ตรงกับเส้นทาง วันที่ หรือชั้นโดยสาร')
        if modern and any(f.get(k)!=allowed[f['code']][k] for k in ('from','to','date','cabin')):
            raise ValueError('กรุณาเลือกเที่ยวบินใหม่ให้ตรงกับเส้นทางและวันที่')
        canonical.append(allowed[f['code']].copy())
    if modern and trip == 'round' and data['depart'] == data['return']:
        arrival = canonical[0]['arrival_day']*1440 + sum(int(v)*m for v,m in zip(canonical[0]['end'].split(':'),(60,1)))
        departure = sum(int(v)*m for v,m in zip(canonical[1]['start'].split(':'),(60,1)))
        if departure < arrival+60:
            raise ValueError('ขากลับต้องออกหลังขาไปถึงอย่างน้อย 1 ชั่วโมง')
    bag = data.get('bag', 0)
    if type(bag) is not int or bag not in {0, 450, 700}:
        raise ValueError('สัมภาระไม่ถูกต้อง')
    for key in ('premium', 'insurance'):
        if type(data.get(key)) is not bool:
            raise ValueError('บริการเสริมไม่ถูกต้อง')
    if data.get('pay') not in {'bank', 'promptpay', 'seven', 'card'} or data.get('demo_ack') is not True:
        raise ValueError('กรุณายืนยันการชำระเงินจำลอง')
    if data.get('pay') == 'bank' and data.get('bank') not in {'kbank','ktb','bbl','scb','gsb'}:
        raise ValueError('กรุณาเลือกธนาคาร')
    data['flights'] = canonical
    data['adults'], data['children'], data['infants'] = adults, children, infants
    total = fare_total(data) + bag * (adults+children) * len(canonical)
    total += (670 if data['premium'] else 0) + (184 * count if data['insurance'] else 0)
    promo = promotion(data, today)
    data['promotion'] = promo
    cutoff=datetime.now(timezone(timedelta(hours=7)))+timedelta(hours=2)
    for i,f in enumerate(data['flights']):
        day=data['depart'] if i==0 else data['return']
        if datetime.fromisoformat(day+'T'+f['start']).replace(tzinfo=cutoff.tzinfo)<cutoff:
            raise ValueError('ต้องจองอย่างน้อย 2 ชั่วโมงก่อนออกบิน กรุณาเลือกเที่ยวบินใหม่')
    return data, total - promo['discount']


@app.get('/admin')
def admin_entry():
    return render_template('index.html')


@app.get('/healthz')
def healthz():
    try:
        with closing(sqlite3.connect(app.config['DATABASE'])) as connection:
            connection.execute('SELECT id FROM users LIMIT 1').fetchone()
        return jsonify(status='ok'), 200
    except sqlite3.Error:
        return jsonify(status='unavailable'), 503


@app.get('/')
def index():
    return render_template('index.html')


@app.post('/api/bookings')
def create_booking():
    try:
        data, total = validate_booking(request.get_json(silent=True))
    except (ValueError, TypeError, KeyError):
        return jsonify(error='ข้อมูลไม่ถูกต้อง โปรดตรวจสอบวันเดินทาง ข้อมูลติดต่อ ผู้โดยสาร และตัวเลือกการจอง'), 400
    reference = 'ED-' + uuid.uuid4().hex[:12].upper()
    paid_at = datetime.now(timezone(timedelta(hours=7))).isoformat(timespec='seconds')
    data.update(ref=reference, paidAt=paid_at, total=total, status='demo_paid')
    data.pop('demo_ack', None)
    with closing(sqlite3.connect(app.config['DATABASE'])) as conn:
        conn.execute('PRAGMA foreign_keys = ON')
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            previous=app.existing_booking_response(conn)
            if previous is not None:return jsonify(previous),200
            try:
                benefit=app.membership_quote(conn,g.user['id'],data,total)
            except ValueError as error:
                return jsonify(error=str(error)),400
            total=benefit['total']
            data.update(total=total,member_benefit=benefit)
            if benefit['applied']:
                conn.execute('INSERT INTO benefit_redemptions VALUES (?,?,?,?)',(g.user['id'],benefit['tier'],reference,paid_at))
            conn.execute('INSERT INTO bookings (id,created_at,status,total,details,user_id) VALUES (?, ?, ?, ?, ?, ?)',
                         (reference, paid_at, 'demo_paid', total, json.dumps(data, ensure_ascii=False), g.user['id']))
            conn.executemany('INSERT INTO passengers (booking_id, gender, first_name, last_name, birth_date) VALUES (?, ?, ?, ?, ?)',
                             [(reference, p['gender'], p['first'], p['last'], p['birth']) for p in data['passengers']])
            if data.get('checkout_key'):
                draft=conn.execute('SELECT user_id FROM booking_drafts WHERE id=?',(data['checkout_key'],)).fetchone()
                if draft and draft[0]!=g.user['id']:
                    conn.rollback()
                    return jsonify(error='ร่างการจองไม่ใช่ของบัญชีนี้'),403
                conn.execute('DELETE FROM booking_drafts WHERE id=? AND user_id=?',(data['checkout_key'],g.user['id']))
            app.record_booking_response(conn,dict(ref=reference,paidAt=paid_at,total=total,member_benefit=benefit,promotion=data['promotion'],status='demo_paid'))
    return jsonify(ref=reference, paidAt=paid_at, total=total, member_benefit=benefit, promotion=data['promotion'], status='demo_paid'), 201


from accounts import configure_accounts
init_db()
configure_accounts(app)
app.initialize_accounts()
from membership import configure_membership
configure_membership(app,validate_booking)
from security import configure_security
from mailsettings import configure_mailsettings
configure_mailsettings(app)
configure_security(app)
from lifecycle import configure_lifecycle
app.validate_booking=validate_booking
configure_lifecycle(app)

from travel import configure_travel
configure_travel(app)

from promptpay import configure_promptpay
configure_promptpay(app)

from services import configure_services
configure_services(app)

from checkin14 import configure_checkin14
configure_checkin14(app)

from commerce import configure_commerce
configure_commerce(app)

from customer_details import configure_customer_details
configure_customer_details(app)

from assistant_service import configure_assistant
configure_assistant(app)

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
