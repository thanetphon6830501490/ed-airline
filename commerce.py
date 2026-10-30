"""Fail-closed boundary for future live integrations; never fabricate supplier data."""
import os,sqlite3
from contextlib import closing
from flask import request,jsonify

def configure_commerce(app):
    live=os.environ.get('ED_SALES_MODE','live' if app.config.get('PRODUCTION') else 'demo')=='live'
    app.config['LIVE_SALES']=live
    # Separate real-sale records from legacy demo_paid bookings and memberships.
    with closing(sqlite3.connect(app.config['DATABASE'])) as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS commerce_orders(
          id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),
          supplier TEXT NOT NULL,offer_id TEXT NOT NULL,currency TEXT NOT NULL,
          amount_minor INTEGER NOT NULL CHECK(amount_minor>=0),
          state TEXT NOT NULL CHECK(state IN ('quoted','awaiting_payment','payment_verified','issuing','ticketed','issue_failed','refund_pending','refunded','expired')),
          supplier_order_id TEXT UNIQUE,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS commerce_payments(
          id TEXT PRIMARY KEY,order_id TEXT NOT NULL REFERENCES commerce_orders(id),
          gateway TEXT NOT NULL,gateway_charge_id TEXT UNIQUE NOT NULL,
          amount_minor INTEGER NOT NULL,currency TEXT NOT NULL,
          state TEXT NOT NULL CHECK(state IN ('pending','verified','failed','refunded')),
          verified_at TEXT);
          CREATE TABLE IF NOT EXISTS commerce_events(
          gateway TEXT NOT NULL,event_id TEXT NOT NULL,processed_at TEXT NOT NULL,
          PRIMARY KEY(gateway,event_id));''')
    @app.before_request
    def live_boundary():
        if not live:return
        blocked={'/api/flights','/api/bookings','/api/bookings/draft','/api/promptpay/quote','/api/checkin','/api/checkin/lookup','/api/membership/quote'}
        if request.path in blocked and (request.path=='/api/flights' or request.method=='POST'):
            return jsonify(error='โหมดขายจริงยังไม่พร้อม: ต้องเชื่อมผู้ให้บริการเที่ยวบิน การชำระเงิน และออกตั๋วก่อน',live_ready=False),503
    guards=app.before_request_funcs[None]
    guards.remove(live_boundary)
    guards.insert(0,live_boundary)
    @app.get('/api/commerce/status')
    def commerce_status():
        return jsonify(mode='live' if live else 'demo',live_ready=False,flight_connected=False,payment_connected=False,ticketing_connected=False,message='ยังไม่มีการเชื่อมผู้ให้บริการจริง')
