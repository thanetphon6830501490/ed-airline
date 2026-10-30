# ED Airline

เว็บไซต์สาธิตจองเที่ยวบินด้วย Python Flask และ SQLite สำหรับนำเสนอผลงาน
**ไม่ใช่เว็บไซต์ขายตั๋วจริง ไม่รับชำระ ไม่ตรวจเงินเข้า และไม่ออกตั๋วจริง**

## ฟังก์ชัน
- สมัครและเข้าสู่ระบบ ค้นหาเที่ยวเดียวและไปกลับ พร้อมตัวกรอง
- กรอกผู้โดยสาร เลือกบริการ ตรวจราคาและส่วนลด และบันทึกการจองจำลอง
- ดูตั๋ว ประวัติ ขอยกเลิกพร้อมเหตุผล สมาชิก เช็คอิน และติดต่อ
- หน้าผู้ดูแลสำหรับรายการจองและเรื่องติดต่อ

## รันในเครื่อง
```sh
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```
เปิด http://127.0.0.1:5000 ฐานข้อมูลใหม่สร้างใน instance/ อัตโนมัติ
บน macOS/Linux ใช้ .venv/bin/python แทน .venv\Scripts\python.exe

## นำขึ้น GitHub Public
1. สมัคร https://github.com/signup และยืนยันอีเมลด้วยตัวเอง
2. แตก ZIP ให้เป็นโฟลเดอร์ ed-airline ยังไม่ต้องสร้าง repository บนเว็บไซต์
3. ใช้ GitHub Desktop (https://desktop.github.com/) เลือก File > Add local repository
   เลือกโฟลเดอร์นี้ หากยังไม่มี Git ให้เลือก create a repository ที่ตำแหน่งนี้
4. ตรวจรายการไฟล์ แล้ว commit จากนั้น Publish repository ไปยังบัญชีของตน
   หากต้องการ Public ให้เอา Keep this code private ออก
5. เปิด repository ที่เผยแพร่แล้วบนเว็บไซต์ GitHub และตรวจว่าเห็น app.py กับ render.yaml ที่หน้าแรก

คลิปพื้นหลังมีไฟล์ใหญ่กว่า 25 MB จึงควรใช้ GitHub Desktop หรือ git push
การอัปโหลด ZIP เข้า repository โดยไม่แตกไฟล์จะไม่ทำให้ Render รันโครงการได้
ห้ามอัปโหลด instance/, ฐานข้อมูลเดิม, .env, กุญแจ, ไฟล์ .enc หรือ log
GitHub Pages รองรับเว็บ static จึงรัน Flask/SQLite ของโครงการนี้ไม่ได้

## เปิดเว็บไซต์ฟรีด้วย Render
1. สมัคร https://dashboard.render.com/register และเชื่อม GitHub ด้วยตัวเอง
2. เลือก New > Blueprint แล้วเลือก repository ed-airline
3. ใช้ render.yaml ในโครงการนี้ ตรวจว่า plan เป็น Free และไม่มี disk หรือบริการที่คิดเงิน
4. กดสร้าง/Deploy แล้วรอ build และ health check ผ่าน
5. เปิด URL https://<ชื่อบริการที่ระบบกำหนด>.onrender.com ที่ Render แสดง
   อย่าเดา URL ก่อนสร้างสำเร็จ และส่ง URL นี้ให้ผู้ตรวจผลงาน
6. ตรวจหน้าแรก ค้นหา สมัครบัญชีสมมติ เข้าสู่ระบบ บันทึกจำลอง และเปิดประวัติ

หากสร้าง Web Service แบบกรอกเอง:
- Runtime: Python; Build: pip install -r requirements.txt
- Start: python serve.py; Health Check: /healthz; Instance: Free
- ตั้ง Environment Variables ให้ตรง render.yaml
- ARI_SESSION_SECRET ต้องเป็นค่าสุ่มยาวอย่างน้อย 32 ตัว สร้างในแดชบอร์ดและอย่าส่งในแชต
- ไม่กำหนด PORT เองหาก Render กำหนดให้อยู่แล้ว

## ขอบเขตของโหมดสาธารณะสำหรับทดลอง
ED_PUBLIC_PREVIEW=1 ทำงานร่วมกับ ED_SALES_MODE=demo เท่านั้น
- ใช้ HTTPS/secure cookies, CSRF, สิทธิ์บัญชี และ 2FA ของผู้ดูแลตามเดิม
- อนุญาตบัญชีที่ยังไม่ยืนยันอีเมลให้บันทึก **การจองจำลอง** เพื่อสาธิตโดยไม่ต้องตั้ง SMTP
- ปิดผู้รับ PromptPay และ QR โอนเงินจริงในโหมดนี้ แม้มีการตั้งค่าผู้รับใน environment
- แสดงข้อความให้ใช้ข้อมูลสมมติและแจ้งว่าข้อมูลอาจหาย
- การกู้รหัสด้วยอีเมลและเบอร์ในเครื่องยังไม่เปิดบนเว็บสาธารณะ
- ไม่ตั้งบัญชีหรือรหัสผ่าน Admin เริ่มต้นให้ผู้เข้าชม

หากปิด ED_PUBLIC_PREVIEW การยืนยันอีเมลก่อนบันทึกใน production จะกลับมาบังคับตามเดิม
ต้องตั้งบริการอีเมลให้พร้อมก่อนใช้ขั้นตอนยืนยัน/กู้รหัสผ่านจริง

## ข้อจำกัดของโฮสต์ฟรีและ SQLite
Render Free ไม่มี persistent disk ข้อมูลบัญชี การจอง กุญแจเข้ารหัส และการตั้งค่าในเครื่อง
อาจหายหลังพักบริการ restart หรือ deploy ใหม่ ให้ใช้เฉพาะข้อมูลสมมติสำหรับตรวจผลงาน
ห้ามย้ายข้อมูลลูกค้าจริงขึ้นแพ็กเกจนี้ หน้าแรกอาจเปิดช้าเมื่อบริการพัก
หากต้องเก็บข้อมูลถาวร ให้ย้าย ED_DATA_DIR ไปยัง persistent disk ที่โฮสต์รองรับ
และเก็บฐานข้อมูลพร้อม account.key/session.key ที่คู่กัน ห้ามเผยแพร่ลง GitHub

## ตั้งผู้ดูแล (เจ้าของระบบเท่านั้น)
สมัครบัญชีของตนก่อน แล้วรันบนเครื่องโฮสต์ที่เข้าถึงฐานข้อมูลเดียวกัน:
```sh
python -m flask --app app make-admin YOUR_USERNAME
```
เข้าสู่ระบบแบบ Admin และเปิด Authenticator ตามข้อกำหนดของระบบ
Render Free อาจไม่มี shell สำหรับคำสั่งนี้ จึงไม่รวมการสร้าง Admin อัตโนมัติ
ผู้เข้าชมทั่วไปไม่จำเป็นต้องมี Admin เพื่อทดลองจอง

## ทดสอบก่อนเผยแพร่
```sh
python -m unittest discover -s tests -v
```
ทดสอบใช้ฐานข้อมูลชั่วคราว ไม่แตะข้อมูลผู้ใช้เดิม

เอกสารอ้างอิง:
- https://render.com/docs/deploy-flask
- https://render.com/docs/free
- https://render.com/docs/disks
- https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site

## คลิปวิดีโอไฟล์ใหญ่
คลิป thailand-memories.mp4 แบ่งเป็นส่วนใน media-parts เพื่อให้อัปโหลดผ่านเว็บได้
รัน python assemble_media.py เพื่อประกอบและตรวจ SHA-256 ก่อนเปิดเว็บ
Render จะประกอบคลิปนี้ให้อัตโนมัติระหว่าง Build
