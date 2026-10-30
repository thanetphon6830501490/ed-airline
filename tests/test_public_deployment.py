import os
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DATA = tempfile.TemporaryDirectory(prefix='ed-public-test-')
os.environ.update(ARI_ENV='production', ED_SALES_MODE='demo', ED_PUBLIC_PREVIEW='1', ED_DATA_DIR=DATA.name)
from app import app
from assemble_media import assemble


class MediaAssemblyTests(unittest.TestCase):
    def make_fixture(self, folder, target='static/videos/example.mp4', digest=None):
        import hashlib
        root=Path(folder);parts=root/'media-parts';parts.mkdir()
        (parts/'one.part').write_bytes(b'video-');(parts/'two.part').write_bytes(b'content')
        (parts/'manifest.json').write_text(json.dumps([dict(target=target,parts=['one.part','two.part'],sha256=digest or hashlib.sha256(b'video-content').hexdigest())]),encoding='utf8')

    def test_assembly_preserves_original_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            self.make_fixture(folder);assemble(folder)
            self.assertEqual((Path(folder)/'static/videos/example.mp4').read_bytes(),b'video-content')

    def test_corrupt_parts_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            self.make_fixture(folder,digest='0'*64)
            with self.assertRaises(ValueError):assemble(folder)
            self.assertFalse((Path(folder)/'static/videos/example.mp4').exists())

    def test_output_cannot_escape_project_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            self.make_fixture(folder,target='../outside.mp4')
            with self.assertRaises(ValueError):assemble(folder)


class PublicDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.base = 'https://example.test'
        self.headers = {'X-CSRF-Token': self.client.get('/api/session', base_url=self.base).json['csrf']}

    def signup(self):
        username = 'test_' + uuid.uuid4().hex[:12]
        profile = dict(username=username, email=username+'@example.com', password='Demo2026', first='Example', last='Passenger', birth='2000-01-15', nationality='ไทย', ethnicity='', religion='', phone='0800000000', dial='66', gender='ชาย', document_type='passport', document='')
        response = self.client.post('/api/register', json=profile, headers=self.headers, base_url=self.base)
        self.assertEqual(response.status_code, 201, response.json)
        response = self.client.post('/api/login', json=dict(identifier=username, password='Demo2026', role='user'), headers=self.headers, base_url=self.base)
        self.assertEqual(response.status_code, 200, response.json)
        self.headers['X-CSRF-Token'] = self.client.get('/api/session', base_url=self.base).json['csrf']
        return username

    def test_health_assets_and_secure_session(self):
        self.assertEqual(self.client.get('/healthz', base_url=self.base).status_code, 200)
        self.assertIn('เว็บไซต์ทดลอง ED Airline', self.client.get('/', base_url=self.base).get_data(as_text=True))
        with self.client.get('/static/airports.json', base_url=self.base) as asset:
            self.assertEqual(asset.status_code, 200)
        response = app.test_client().get('/api/session', base_url=self.base)
        self.assertIn('Secure', response.headers['Set-Cookie'])
        self.assertIn('HttpOnly', response.headers['Set-Cookie'])
        self.assertIn('max-age=', response.headers['Strict-Transport-Security'])
        self.assertEqual(Path(app.config['DATABASE']).parent, Path(DATA.name))

    def test_csrf_and_admin_access_are_preserved(self):
        self.assertEqual(self.client.post('/api/register', json={}, base_url=self.base).status_code, 403)
        self.signup()
        self.assertEqual(self.client.get('/api/admin/bookings', base_url=self.base).status_code, 403)

    def test_demo_booking_roundtrip_and_duplicate_request(self):
        username = self.signup()
        date = (datetime.now(timezone(timedelta(hours=7)))+timedelta(days=8)).date().isoformat()
        response = self.client.get('/api/flights', query_string={'from':'BKK','to':'CNX','date':date,'cabin':'economy'}, base_url=self.base)
        self.assertEqual(response.status_code, 200)
        flight = response.json['flights'][0]
        payload = dict(trip='one', **{'from':'BKK','to':'CNX'}, depart=date, count=1, adults=1, children=0, infants=0, cabin='economy', catalogue_version=2, flights=[flight], contact=dict(first='Example', last='Passenger', email=username+'@example.com', country='ไทย', dial='66', phone='0800000000'), passengers=[dict(first='Example', last='Passenger', gender='ชาย', birth='2000-01-15')], bag=0, premium=False, insurance=False, pay='card', demo_ack=True)
        headers={**self.headers,'Idempotency-Key':uuid.uuid4().hex}
        first=self.client.post('/api/bookings',json=payload,headers=headers,base_url=self.base)
        self.assertEqual(first.status_code,201,first.json)
        second=self.client.post('/api/bookings',json=payload,headers=headers,base_url=self.base)
        self.assertEqual(second.status_code,200,second.json)
        self.assertEqual(first.json['ref'],second.json['ref'])
        self.assertEqual(first.json['status'],'demo_paid')
        with sqlite3.connect(app.config['DATABASE']) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM bookings WHERE id=?',(first.json['ref'],)).fetchone()[0],1)

    def test_preview_never_exposes_real_promptpay(self):
        self.signup()
        os.environ['ED_PROMPTPAY_MOBILE']='0812345678'
        os.environ['ED_PROMPTPAY_NAME']='TEST ONLY'
        try:
            self.assertIsNone(app.promptpay_receiver())
            response=self.client.post('/api/promptpay/quote',json={},headers=self.headers,base_url=self.base)
            self.assertEqual(response.status_code,503)
            self.assertFalse(response.json['configured'])
        finally:
            os.environ.pop('ED_PROMPTPAY_MOBILE',None);os.environ.pop('ED_PROMPTPAY_NAME',None)

    def test_production_policy_returns_when_preview_is_off(self):
        username=self.signup()
        env={**os.environ,'ED_PUBLIC_PREVIEW':'0','TEST_USER':username}
        code="""import json
from app import app
import sqlite3,os
c=app.test_client()
with sqlite3.connect(app.config['DATABASE']) as db:
    user=db.execute('SELECT id,session_version FROM users WHERE username=?',(os.environ['TEST_USER'],)).fetchone()
with c.session_transaction() as s:s.update(csrf='sample',user_id=user[0],version=user[1])
response=c.post('/api/password/local-recovery',json={},headers={'X-CSRF-Token':'sample'},base_url='https://example.test')
booking=c.post('/api/bookings',json={},headers={'X-CSRF-Token':'sample'},base_url='https://example.test')
print(json.dumps({'preview':app.config['PUBLIC_PREVIEW'],'recovery':response.status_code,'booking':booking.status_code}))
"""
        response=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=env,capture_output=True,text=True,check=True)
        result=json.loads(response.stdout)
        self.assertFalse(result['preview'])
        self.assertEqual(result['recovery'],403)
        self.assertEqual(result['booking'],403)

    def test_keys_and_database_survive_restart_when_data_directory_survives(self):
        username=self.signup()
        key=(Path(DATA.name)/'account.key').read_bytes()
        code="""import sqlite3,json
from app import app
with sqlite3.connect(app.config['DATABASE']) as c:n=c.execute('SELECT COUNT(*) FROM users WHERE username=?',(__import__('os').environ['TEST_USER'],)).fetchone()[0]
print(json.dumps({'found':n}))
"""
        response=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env={**os.environ,'TEST_USER':username},capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(response.stdout)['found'],1)
        self.assertEqual((Path(DATA.name)/'account.key').read_bytes(),key)


if __name__=='__main__':
    unittest.main()
