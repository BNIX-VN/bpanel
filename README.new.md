# BPanel

BPanel là panel quản trị VPS đơn giản cho **Ubuntu 24.04**, tập trung vào quản lý website **WordPress** chạy native bằng `systemd` và Nginx. Project **không dùng Docker**.

## Mục tiêu

- Cài và quản lý website WordPress trên VPS.
- Quản lý Nginx, PHP-FPM, MariaDB, Redis, SSL, backup và file website.
- Có phân quyền user để chia website cho từng tài khoản.
- Dễ cài trên VPS Ubuntu 24.04 mới.

## Công nghệ

| Thành phần | Công nghệ |
|---|---|
| Backend | Python FastAPI |
| Python | `3.9+` |
| Frontend | React + Vite |
| Node.js | Node.js `22.x` từ NodeSource |
| Database panel | SQLite mặc định |
| Web server | Nginx |
| PHP | PHP-FPM `8.3`, `8.4` mặc định |
| Database website | MariaDB |
| Cache/service | Redis |
| SSL | Certbot Let's Encrypt |
| WordPress automation | WP-CLI |
| Process manager | systemd |

## Tính năng chính

### Website WordPress

- Tạo website WordPress 1 click.
- Tạo database/user database tự động.
- Sinh Nginx vhost cho từng domain.
- Chọn PHP `8.3` hoặc `8.4`.
- Cấp SSL Let's Encrypt.
- Fix phân quyền WordPress.
- Fix security Nginx cho website hiện tại.
- Xóa website kèm source/vhost/database.

### Bảo mật Nginx website

Nút **Fix security** trong danh sách website sẽ cập nhật Nginx config theo domain và root path của website.

Template bảo mật mặc định gồm:

- `server_tokens off`
- `autoindex off`
- Security headers cơ bản:
  - `X-Frame-Options`
  - `X-Content-Type-Options`
  - `Referrer-Policy`
  - `X-XSS-Protection`
  - `Strict-Transport-Security`
  - `Permissions-Policy`
  - `Content-Security-Policy` mức tương thích WordPress
- Chặn `xmlrpc.php`
- Chặn `wp-config.php`
- Chặn `readme.html`, `license.txt`
- Chặn file nhạy cảm như `.env`, `.sql`, `.bak`, `.old`, `.log`, `.ini`, `.conf`, `.sh`, `.inc`
- Chặn dotfile, nhưng vẫn cho `.well-known` để SSL hoạt động
- Chặn chạy PHP trong `uploads`
- Chặn PHP trực tiếp trong `wp-includes` và `wp-admin/includes`
- Thêm `try_files $uri =404` cho PHP

Với website đã có SSL, chức năng này sẽ cập nhật header vào file Nginx hiện tại, không ghi đè mất cấu hình SSL của Certbot.

### Quản trị

- Đăng nhập JWT.
- User và role.
- Giới hạn số website/dung lượng.
- Gán domain cho user.
- Dashboard tổng quan.
- System status.
- Service status/control cơ bản.

### Backup / file / maintenance

- Backup website.
- Restore backup.
- Download/upload/delete backup.
- File manager cơ bản.
- Cron manager.
- WordPress update core/plugin/theme.
- PHP config manager.

## Role

| Role | Quyền |
|---|---|
| `readonly` | Xem thông tin được cấp quyền |
| `user` | Quản lý website thuộc tài khoản đó |
| `admin` | Quản lý website, user, service cơ bản |
| `super_admin` | Quyền cao nhất |

## Cấu trúc thư mục

```text
bpanel/
├── backend/              # FastAPI API
├── frontend/             # React UI
├── installer/            # Script cài Ubuntu 24.04
└── README.md
```

## Chạy dev trên Windows

Backend mặc định dùng `COMMAND_DRY_RUN=true`, các lệnh hệ thống chỉ giả lập.

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m app.seed
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Tài khoản mặc định:

```text
admin / <generated-password>
```

## Cài mới trên VPS

### 1. Yêu cầu

- VPS mới cài **Ubuntu 24.04**.
- Đăng nhập bằng `root`.
- RAM tối thiểu 1GB, khuyến nghị 2GB+.
- Dung lượng trống tối thiểu 10GB.
- Domain/subdomain trỏ về IP VPS, ví dụ `panel.example.com`.

Đăng nhập VPS:

```bash
ssh root@IP_VPS
```

### 2. Upload source lên VPS

Ví dụ upload vào `/root/bpanel`:

```bash
scp -r ./bpanel root@IP_VPS:/root/bpanel
```

Hoặc clone từ GitHub:

```bash
apt-get update
apt-get install -y git
git clone https://github.com/your-user/bpanel.git /root/bpanel
```

### 3. Chạy installer

```bash
cd /root/bpanel/installer
bash install.sh
```

Installer sẽ hỏi:

```text
Enter panel URL/domain, for example https://panel.example.com or panel.example.com:
Enable Let's Encrypt SSL for panel.example.com? [Y/n]:
Enter email for Let's Encrypt registration:
```

Cài không cần hỏi:

```bash
cd /root/bpanel/installer
PANEL_URL="https://panel.example.com" SSL_EMAIL="admin@example.com" bash install.sh
```

Cài không bật SSL cho panel:

```bash
cd /root/bpanel/installer
PANEL_URL="http://panel.example.com" ENABLE_SSL=no bash install.sh
```

### 4. PHP mặc định

Installer mặc định cài:

```text
PHP 8.3
PHP 8.4
```

PHP mặc định:

```text
8.3
```

Có thể đổi bằng biến môi trường:

```bash
PHP_VERSIONS="8.3 8.4" PHP_DEFAULT="8.4" bash install.sh
```

Không cài PHP `8.5` mặc định. Nếu thật sự cần PHP khác, tự thêm vào `PHP_VERSIONS` khi repo hỗ trợ.

### 5. Node.js

Installer mặc định cài Node.js `22.x` từ NodeSource.

Đổi major version:

```bash
NODE_MAJOR=20 bash install.sh
```

## Installer sẽ làm gì

Installer thực hiện các bước:

1. Kiểm tra Ubuntu 24.04.
2. Cài package nền: Nginx, MariaDB, Redis, Python, Certbot, phpMyAdmin, Git, UFW.
3. Cài Node.js từ NodeSource.
4. Cài PHP-FPM `8.3`, `8.4` từ Ondrej PPA.
5. Cài WP-CLI.
6. Copy source vào `/opt/bpanel`.
7. Build frontend ra `/opt/bpanel/frontend/dist`.
8. Tạo Python virtualenv cho backend.
9. Cài package Python.
10. Tạo file `/opt/bpanel/backend/.env`.
11. Seed tài khoản admin mặc định.
12. Tạo systemd service `bpanel-api`.
13. Kiểm tra backend health tại `127.0.0.1:8000/api/health`.
14. Tạo Nginx config cho panel.
15. Cấu hình phpMyAdmin tại `/phpmyadmin/`.
16. Cấp SSL Let's Encrypt cho panel nếu bật.
17. Mở firewall profile `Nginx Full` và `OpenSSH`.

Sau khi cài xong:

```text
https://panel.example.com/
```

API health:

```text
https://panel.example.com/api/health
```

Tài khoản mặc định:

```text
Username: admin
Password: xem dong "Admin: admin / ..." o cuoi installer
```

Nên đổi mật khẩu ngay sau khi đăng nhập.

## Cập nhật BPanel sau khi upload code mới

### Backend

```bash
cd /opt/bpanel/backend
source .venv/bin/activate
pip install -r requirements.txt
systemctl restart bpanel-api
```

Kiểm tra:

```bash
systemctl status bpanel-api
curl http://127.0.0.1:8000/api/health
```

### Frontend

```bash
cd /opt/bpanel/frontend
npm install
rm -rf dist
VITE_API_URL=/api npm run build
nginx -t
systemctl reload nginx
```

Sau đó hard refresh trình duyệt.

## Lệnh quản lý thường dùng

Restart API:

```bash
systemctl restart bpanel-api
```

Xem log API:

```bash
journalctl -u bpanel-api -f
```

Kiểm tra API:

```bash
curl http://127.0.0.1:8000/api/health
```

Kiểm tra Nginx:

```bash
nginx -t
systemctl status nginx
```

Reload Nginx:

```bash
systemctl reload nginx
```

Không nên stop Nginx từ panel vì panel đang chạy qua Nginx.

Kiểm tra PHP-FPM:

```bash
systemctl status php8.3-fpm
systemctl status php8.4-fpm
```

Kiểm tra MariaDB:

```bash
systemctl status mariadb
```

Kiểm tra Redis:

```bash
systemctl status redis-server
```

## Vị trí file sau khi cài

| Nội dung | Đường dẫn |
|---|---|
| Backend | `/opt/bpanel/backend` |
| Frontend source | `/opt/bpanel/frontend` |
| Frontend build | `/opt/bpanel/frontend/dist` |
| Database SQLite panel | `/opt/bpanel/backend/bpanel.db` |
| Source website WordPress | `/home/bpanel-sites` |
| Backup website | `/var/backups/bpanel` |
| Systemd service | `/etc/systemd/system/bpanel-api.service` |
| Env backend | `/opt/bpanel/backend/.env` |
| Nginx panel config | `/etc/nginx/sites-available/bpanel.conf` |
| Nginx website config | `/etc/nginx/conf.d/{domain}.conf` |

## File `.env`

Ví dụ:

```text
APP_ENV=production
SECRET_KEY=your-secret-key
COMMAND_DRY_RUN=false
DATABASE_URL=sqlite:////opt/bpanel/backend/bpanel.db
ALLOWED_ORIGINS=https://panel.example.com
SITES_ROOT=/home/bpanel-sites
BACKUP_ROOT=/var/backups/bpanel
PHP_FPM_SERVICE=php8.3-fpm
SSL_EMAIL=admin@example.com
```

Sau khi sửa `.env`:

```bash
systemctl restart bpanel-api
```

## Khôi phục SSL website nếu bị lỗi

Nếu file Nginx website bị sửa sai hoặc mất SSL:

```bash
certbot --nginx -d example.com -d www.example.com --redirect
nginx -t
systemctl reload nginx
```

Sau đó vào BPanel → `Websites` → bấm `Fix security`.

## Kiểm tra security header

```bash
curl -I https://example.com
```

Nên thấy các header như:

```text
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Frame-Options: SAMEORIGIN
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=(), bluetooth=(), magnetometer=(), gyroscope=(), accelerometer=()
Content-Security-Policy: default-src 'self' https: data: blob:; ...
```

## Gỡ PHP 8.5 nếu lỡ cài

BPanel hiện không cài PHP `8.5` mặc định. Nếu VPS đã từng cài nhầm:

```bash
systemctl stop php8.5-fpm 2>/dev/null || true
systemctl disable php8.5-fpm 2>/dev/null || true
apt-get purge -y 'php8.5*'
apt-get autoremove -y
apt-get autoclean
```

## Lưu ý bảo mật

- Đổi mật khẩu admin ngay sau khi cài.
- Đổi `SECRET_KEY` nếu nghi ngờ bị lộ.
- Chi khai bao origin panel trong `ALLOWED_ORIGINS`, khong mo CORS tu do tren VPS that.
- Không để `COMMAND_DRY_RUN=false` trên máy dev Windows.
- Chỉ mở port cần thiết.
- Dùng HTTPS cho panel.
- Không stop Nginx nếu đang truy cập panel qua Nginx.
- Sao lưu trước khi restore hoặc xóa website.
- CSP đang ở mức cơ bản để tương thích WordPress/plugin. Nếu muốn nghiêm ngặt hơn, cần test theme/plugin kỹ.

## Troubleshooting

### Frontend báo không kết nối được API

Kiểm tra:

```bash
systemctl status bpanel-api
curl http://127.0.0.1:8000/api/health
nginx -t
systemctl status nginx
```

Restart:

```bash
systemctl restart bpanel-api
systemctl reload nginx
```

### Nút mới chưa hiện sau khi upload frontend

Cần build lại frontend:

```bash
cd /opt/bpanel/frontend
rm -rf dist
VITE_API_URL=/api npm run build
systemctl reload nginx
```

Sau đó hard refresh trình duyệt.

### Website WordPress lỗi phân quyền

Trong BPanel → `Websites` → bấm `Fix phân quyền`.

Hoặc chạy tay:

```bash
chown -R www-data:www-data /home/bpanel-sites/example.com
find /home/bpanel-sites/example.com -type d -exec chmod 755 {} \;
find /home/bpanel-sites/example.com -type f -exec chmod 644 {} \;
chmod -R 775 /home/bpanel-sites/example.com/public/wp-content/uploads
```

### Nginx config lỗi

```bash
nginx -t
journalctl -u nginx -n 80 --no-pager
```

Nếu lỗi ở website config, kiểm tra:

```bash
nano /etc/nginx/conf.d/example.com.conf
```
Lệnh cài đặt:
apt -y install unzip
mkdir bpanel
cd bpanel
unzip *.zip
cd /root/bpanel/installer
sed -i 's/\r$//' install.sh
chmod +x install.sh
./install.sh

Lệnh update:
cd /opt/bpanel/backend
. .venv/bin/activate
python -m py_compile app/main.py app/api/firewall.py app/services/firewall.py app/schemas/schemas.py
systemctl restart bpanel-api

cd /opt/bpanel/frontend
VITE_API_URL=/api npm run build
nginx -t && systemctl reload nginx
