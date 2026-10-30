import re

PASSWORD_MESSAGE='รหัสผ่านต้องมี 8 ตัวพอดี ใช้เฉพาะ A–Z, a–z และ 0–9 มีตัวพิมพ์เล็กและตัวพิมพ์ใหญ่อย่างน้อยอย่างละ 1 ตัว ห้ามสัญลักษณ์พิเศษ'

def valid_password(value):
    return isinstance(value,str) and re.fullmatch(r'(?=.*[a-z])(?=.*[A-Z])[A-Za-z0-9]{8}',value) is not None
