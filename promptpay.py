"""Amount-specific PromptPay QR. Does not verify transfers or issue real tickets."""
import base64,json,os,re,sqlite3,uuid
from io import BytesIO
from pathlib import Path
from contextlib import closing
from datetime import datetime,timezone,timedelta
import click
from flask import g,jsonify,request
import qrcode
import qrcode.image.svg

def mobile(value):
    value=re.sub(r'[ +()-]','',value)
    if value.startswith('66'):value='0'+value[2:]
    if not re.fullmatch(r'0[689]\d{8}',value):raise ValueError('ต้องเป็นเบอร์มือถือไทย 10 หลักที่ผูกพร้อมเพย์ ชื่อโดเมนหรืออีเมลใช้แทนไม่ได้')
    return value

def tlv(tag,value):
    return f'{tag}{len(value):02d}{value}'

def crc16(value):
    crc=0xffff
    for byte in value.encode('ascii'):
        crc^=byte<<8
        for _ in range(8):crc=((crc<<1)^0x1021 if crc&0x8000 else crc<<1)&0xffff
    return f'{crc:04X}'

def payload(number,total):
    if type(total) is not int or total<=0 or total>99999999:raise ValueError('ยอด QR ไม่ถูกต้อง')
    receiver=tlv('00','A000000677010111')+tlv('01','0066'+mobile(number)[1:])
    data=tlv('00','01')+tlv('01','12')+tlv('29',receiver)+tlv('53','764')+tlv('54',f'{total}.00')+tlv('58','TH')+'6304'
    return data+crc16(data)

def qr_svg(data):
    qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=8,border=4)
    qr.add_data(data);qr.make(fit=True)
    image=qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    out=BytesIO();image.save(out)
    return 'data:image/svg+xml;base64,'+base64.b64encode(out.getvalue()).decode('ascii')

def configure_promptpay(app):
    def read_receiver():
        if app.config.get('PUBLIC_PREVIEW'):return None
        number=os.environ.get('ED_PROMPTPAY_MOBILE');name=os.environ.get('ED_PROMPTPAY_NAME')
        if number and name:return dict(mobile=mobile(number),name=name.strip())
        file=Path(app.config['DATABASE']).parent/'promptpay.enc'
        if not file.exists():return None
        data=json.loads(app.profile_cipher.decrypt(file.read_bytes()))
        return dict(mobile=mobile(data['mobile']),name=data['name'])
    app.promptpay_receiver=read_receiver

    @app.cli.command('configure-promptpay')
    def configure():
        """Set the receiving mobile/name locally. No credentials or OTP required."""
        number=click.prompt('PromptPay mobile (10 digits)',hide_input=True)
        try:number=mobile(number)
        except ValueError as e:raise click.ClickException(str(e))
        confirm=click.prompt('Repeat receiving mobile',hide_input=True)
        if number!=mobile(confirm):raise click.ClickException('เบอร์ทั้งสองครั้งไม่ตรงกัน')
        name=click.prompt('Bank account holder name').strip()
        if not name or len(name)>100:raise click.ClickException('กรุณาระบุชื่อผู้รับตามบัญชีธนาคาร')
        file=Path(app.config['DATABASE']).parent/'promptpay.enc'
        encrypted=app.profile_cipher.encrypt(json.dumps(dict(mobile=number,name=name),ensure_ascii=False).encode())
        temporary=file.with_suffix('.tmp');temporary.write_bytes(encrypted);temporary.replace(file)
        click.echo('Saved receiving details locally (encrypted). Verify bank-app recipient name before any transfer.')

    @app.post('/api/promptpay/quote')
    def quote():
        if g.user is None:return jsonify(error='กรุณาเข้าสู่ระบบ'),401
        try:
            receiver=read_receiver()
            if not receiver:return jsonify(error='ยังไม่ได้ตั้งค่าผู้รับพร้อมเพย์ใหม่ จึงไม่แสดง QR ของบัญชีเดิม',configured=False),503
            data,total=app.validate_booking(request.get_json(silent=True))
            if data['pay']!='promptpay':raise ValueError('กรุณาเลือกพร้อมเพย์')
            with closing(sqlite3.connect(app.config['DATABASE'])) as c:
                benefit=app.membership_quote(c,g.user['id'],data,total)
            total=benefit['total'];image=qr_svg(payload(receiver['mobile'],total)) if total else None
            return jsonify(image=image,total=total,currency='THB',receiver_name=receiver['name'],receiver_masked='******'+receiver['mobile'][-4:],quoted_at=datetime.now(timezone(timedelta(hours=7))).isoformat(),verified=False,demo_booking=True)
        except (ValueError,TypeError,KeyError):return jsonify(error='กรุณาตรวจสอบการจองหรือการตั้งค่าผู้รับพร้อมเพย์'),400
