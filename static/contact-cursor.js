// Visible service entrances, including administrator support cases.
const contactAdminNav=accountNav;
accountNav=function(){contactAdminNav();const nav=document.querySelector('header nav');nav?.querySelector('.admin-support-shortcut')?.remove();if(account?.role==='admin')nav?.insertAdjacentHTML('beforeend','<button class="admin-support-shortcut" onclick="adminSupportPage()">ข้อความลูกค้า / Admin</button>')};
accountNav();
const contactBookingList=listBookings;
listBookings=async function(admin=false){await contactBookingList(admin);if(admin&&account?.role==='admin'){const flow=app.querySelector('.flow');if(flow)flow.insertAdjacentHTML('afterbegin','<div class="admin-service-links"><button onclick="adminSupportPage()">กล่องข้อความลูกค้า</button><button class="secondary" onclick="contactPage()">ข้อมูลติดต่อเรา</button><button class="secondary" onclick="adminMembersPage()">ยอดสมาชิก</button></div>')}};
document.querySelector('footer')?.insertAdjacentHTML('beforeend','<div class="footer-contact"><b>ติดต่อ ED Airline</b><a href="tel:+66928947577">0928947577</a><a href="mailto:Thanetphon.sa@kkumail.com">Thanetphon.sa@kkumail.com</a><span>คณะศึกษาศาสตร์ มหาวิทยาลัยขอนแก่น</span><button class="secondary" onclick="contactPage()">ติดต่อเรา / ส่งเรื่อง →</button></div>');
