#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Please run this installer as root"
  exit 1
fi

if [[ ! -f /etc/os-release ]]; then
  echo "Cannot find /etc/os-release"
  exit 1
fi

source /etc/os-release
if [[ "${ID}" != "ubuntu" || "${VERSION_ID}" != "24.04" ]]; then
  echo "This installer only supports Ubuntu 24.04"
  echo "Current OS: ${PRETTY_NAME:-unknown}"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_SRC="${PROJECT_ROOT}/backend"
FRONTEND_SRC="${PROJECT_ROOT}/frontend"

PANEL_URL="${PANEL_URL:-}"
PANEL_DOMAIN=""
ENABLE_SSL="${ENABLE_SSL:-auto}"
SSL_EMAIL="${SSL_EMAIL:-}"
NODE_MAJOR="${NODE_MAJOR:-22}"
PHP_DEFAULT="${PHP_DEFAULT:-8.3}"
PHP_VERSIONS="${PHP_VERSIONS:-8.3 8.4}"
APP_DIR="${APP_DIR:-/opt/bpanel}"
SITES_ROOT="${SITES_ROOT:-/home/bpanel-sites}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/bpanel}"
ADMIN_PASSWORD=""

log() {
  echo ""
  echo "==> $1"
}

fail() {
  echo "ERROR: $1" >&2
  exit 1
}

need_dir() {
  [[ -d "$1" ]] || fail "Missing directory $1. Upload backend, frontend, and installer."
}

validate_sources() {
  need_dir "$BACKEND_SRC"
  need_dir "$FRONTEND_SRC"
  [[ -f "${BACKEND_SRC}/requirements.txt" ]] || fail "Missing backend/requirements.txt"
  [[ -f "${FRONTEND_SRC}/package.json" ]] || fail "Missing frontend/package.json"
}

ask_panel_url() {
  if [[ -z "$PANEL_URL" ]]; then
    read -rp "Enter panel URL/domain, for example https://panel.example.com or panel.example.com: " PANEL_URL
  fi

  PANEL_URL="${PANEL_URL%/}"
  [[ -n "$PANEL_URL" ]] || fail "Panel URL cannot be empty"

  if [[ "$PANEL_URL" =~ ^https?:// ]]; then
    PANEL_DOMAIN="$(echo "$PANEL_URL" | sed -E 's#^https?://([^/:]+).*#\1#')"
  else
    PANEL_DOMAIN="$(echo "$PANEL_URL" | sed -E 's#^([^/:]+).*#\1#')"
  fi

  if [[ "$PANEL_DOMAIN" == "localhost" || "$PANEL_DOMAIN" == "127.0.0.1" ]]; then
    ENABLE_SSL="no"
    PANEL_URL="http://${PANEL_DOMAIN}"
  elif [[ "$ENABLE_SSL" == "auto" ]]; then
    read -rp "Enable Let's Encrypt SSL for ${PANEL_DOMAIN}? [Y/n]: " ssl_answer
    ssl_answer="${ssl_answer:-Y}"
    if [[ "$ssl_answer" =~ ^[Nn]$ ]]; then
      ENABLE_SSL="no"
      PANEL_URL="http://${PANEL_DOMAIN}"
    else
      ENABLE_SSL="yes"
      PANEL_URL="https://${PANEL_DOMAIN}"
    fi
  elif [[ "$ENABLE_SSL" == "yes" ]]; then
    PANEL_URL="https://${PANEL_DOMAIN}"
  else
    ENABLE_SSL="no"
    PANEL_URL="http://${PANEL_DOMAIN}"
  fi

  if [[ "$ENABLE_SSL" == "yes" && -z "$SSL_EMAIL" ]]; then
    read -rp "Enter email for Let's Encrypt registration: " SSL_EMAIL
    [[ -n "$SSL_EMAIL" ]] || fail "Email is required to issue SSL"
  fi
}

install_base_packages() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y software-properties-common ca-certificates curl gnupg git nginx mariadb-server redis-server python3 python3-pip python3-venv certbot python3-certbot-nginx tar openssl unzip ufw phpmyadmin
  systemctl enable --now nginx mariadb redis-server
}

install_nodejs() {
  curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
  apt-get install -y nodejs
  node - <<'NODE'
const major = Number(process.versions.node.split('.')[0]);
if (major < 20) {
  throw new Error(`Node.js 20+ is required, current: ${process.version}`);
}
console.log(`Using Node.js ${process.version}`);
NODE
  npm --version
}

install_php() {
  add-apt-repository -y ppa:ondrej/php
  apt-get update

  if [[ ! " ${PHP_VERSIONS} " =~ " ${PHP_DEFAULT} " ]]; then
    fail "PHP_DEFAULT=${PHP_DEFAULT} must be included in PHP_VERSIONS='${PHP_VERSIONS}'"
  fi

  for version in $PHP_VERSIONS; do
    packages=(
      "php${version}"
      "php${version}-fpm"
      "php${version}-cli"
      "php${version}-mysql"
      "php${version}-gd"
      "php${version}-xml"
      "php${version}-mbstring"
      "php${version}-curl"
      "php${version}-zip"
      "php${version}-opcache"
      "php${version}-intl"
      "php${version}-bcmath"
      "php${version}-redis"
      "php${version}-imagick"
    )

    available_packages=()
    missing_packages=()
    for package in "${packages[@]}"; do
      if apt-cache show "$package" >/dev/null 2>&1; then
        available_packages+=("$package")
      else
        missing_packages+=("$package")
      fi
    done

    if [[ ${#missing_packages[@]} -gt 0 ]]; then
      echo "Skipping PHP packages not available in repo: ${missing_packages[*]}"
    fi

    if [[ ${#available_packages[@]} -eq 0 ]]; then
      fail "No package found for PHP ${version}. Remove ${version} from PHP_VERSIONS."
    fi

    apt-get install -y "${available_packages[@]}"

    ini_file="/etc/php/${version}/fpm/php.ini"
    if [[ -f "$ini_file" ]]; then
      sed -i \
        -e 's/^\s*;\?\s*upload_max_filesize\s*=.*/upload_max_filesize = 1024M/' \
        -e 's/^\s*;\?\s*post_max_size\s*=.*/post_max_size = 1024M/' \
        -e 's/^\s*;\?\s*memory_limit\s*=.*/memory_limit = 512M/' \
        -e 's/^\s*;\?\s*max_execution_time\s*=.*/max_execution_time = 300/' \
        -e 's/^\s*;\?\s*max_input_time\s*=.*/max_input_time = 600/' \
        -e 's/^\s*;\?\s*max_input_vars\s*=.*/max_input_vars = 10000/' \
        -e 's/^\s*;\?\s*max_file_uploads\s*=.*/max_file_uploads = 100/' \
        "$ini_file"
    fi

    systemctl enable --now "php${version}-fpm"
  done

  update-alternatives --set php "/usr/bin/php${PHP_DEFAULT}" || true
}

install_wp_cli() {
  if ! command -v wp >/dev/null 2>&1; then
    curl -fsSL -o /usr/local/bin/wp https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar
    chmod +x /usr/local/bin/wp
  fi
}

install_filebrowser() {
  if ! command -v filebrowser >/dev/null 2>&1; then
    local tmpdir arch fb_arch url
    tmpdir="$(mktemp -d)"
    arch="$(uname -m)"
    case "$arch" in
      x86_64|amd64) fb_arch="linux-amd64" ;;
      aarch64|arm64) fb_arch="linux-arm64" ;;
      *) fail "File Browser does not support this architecture yet: $arch" ;;
    esac
    url="$(curl -fsSL https://api.github.com/repos/filebrowser/filebrowser/releases/latest | python3 -c 'import json,sys; data=json.load(sys.stdin); arch=sys.argv[1]; matches=[a["browser_download_url"] for a in data.get("assets", []) if arch in a.get("name", "") and a.get("name", "").endswith(".tar.gz")]; print(matches[0] if matches else "")' "$fb_arch")"
    [[ -n "$url" ]] || fail "Cannot find File Browser release for $fb_arch"
    curl -fsSL "$url" -o "${tmpdir}/filebrowser.tar.gz"
    tar -xzf "${tmpdir}/filebrowser.tar.gz" -C "$tmpdir"
    install -m 0755 "${tmpdir}/filebrowser" /usr/local/bin/filebrowser
    rm -rf "$tmpdir"
  fi
}


copy_sources() {
  mkdir -p "$APP_DIR" "$SITES_ROOT" "$BACKUP_ROOT"
  rm -rf "${APP_DIR}/backend" "${APP_DIR}/frontend"
  cp -r "$BACKEND_SRC" "${APP_DIR}/backend"
  cp -r "$FRONTEND_SRC" "${APP_DIR}/frontend"
}

build_frontend() {
  cd "${APP_DIR}/frontend"
  rm -rf node_modules package-lock.json dist .vite
  npm install
  VITE_API_URL=/api npm run build
  if [[ ! -f dist/index.html ]]; then
    fail "Frontend build failed: ${APP_DIR}/frontend/dist/index.html is missing"
  fi
  # Nginx (www-data) needs to read the bundle. The frontend is public anyway.
  chmod o+rX "${APP_DIR}" "${APP_DIR}/frontend" 2>/dev/null || true
  chmod -R o+rX "${APP_DIR}/frontend/dist"
  echo "Frontend built: $(grep -oE 'index-[a-zA-Z0-9_-]+\.js' dist/index.html | head -n1 || echo 'unknown')"
}

setup_panel_user() {
  if ! id -u bpanel >/dev/null 2>&1; then
    useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin --user-group bpanel
  fi
  # bpanel needs to be in www-data group to write site files.
  usermod -aG www-data bpanel || true

  # Allow bpanel to write into /etc/nginx/conf.d (vhost files).
  install -d -o root -g bpanel -m 2775 /etc/nginx/conf.d
  # setgid so new files inherit the bpanel group; allows future writes.
  chmod g+s /etc/nginx/conf.d || true

  # Make the panel data dirs writable by bpanel.
  install -d -o bpanel -g bpanel -m 0750 "$APP_DIR"
  install -d -o bpanel -g www-data -m 2775 "$SITES_ROOT"
  install -d -o bpanel -g bpanel -m 0750 "$BACKUP_ROOT"

  # MariaDB: create an admin user that bpanel can use without password
  # (auth via a defaults-file in ~bpanel/.my.cnf, mode 0600).
  local mariadb_password
  mariadb_password="$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-32)"
  mariadb -e "
    CREATE USER IF NOT EXISTS 'bpanel'@'localhost' IDENTIFIED BY '${mariadb_password}';
    GRANT CREATE, DROP, ALTER, REFERENCES, INDEX, CREATE USER, RELOAD, PROCESS, SHOW DATABASES, LOCK TABLES, SELECT, INSERT, UPDATE, DELETE, GRANT OPTION ON *.* TO 'bpanel'@'localhost';
    FLUSH PRIVILEGES;
  " 2>/dev/null || mysql -e "
    CREATE USER IF NOT EXISTS 'bpanel'@'localhost' IDENTIFIED BY '${mariadb_password}';
    GRANT CREATE, DROP, ALTER, REFERENCES, INDEX, CREATE USER, RELOAD, PROCESS, SHOW DATABASES, LOCK TABLES, SELECT, INSERT, UPDATE, DELETE, GRANT OPTION ON *.* TO 'bpanel'@'localhost';
    FLUSH PRIVILEGES;
  "

  install -d -o bpanel -g bpanel -m 0700 /home/bpanel || true
  cat >"${APP_DIR}/.my.cnf" <<MYCNF
[client]
user=bpanel
password="${mariadb_password}"
host=localhost

[mysqldump]
user=bpanel
password="${mariadb_password}"
host=localhost
MYCNF
  chown bpanel:bpanel "${APP_DIR}/.my.cnf"
  chmod 0600 "${APP_DIR}/.my.cnf"
}

install_privileged_helper() {
  install -m 0750 -o root -g bpanel "${SCRIPT_DIR}/files/bpanel-helper.sh" /usr/local/sbin/bpanel-helper
  install -m 0440 -o root -g root "${SCRIPT_DIR}/files/bpanel-sudoers" /etc/sudoers.d/bpanel
  visudo -c -f /etc/sudoers.d/bpanel >/dev/null
}

setup_backend() {
  cd "${APP_DIR}/backend"
  python3 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt

  ADMIN_PASSWORD="${BPANEL_ADMIN_PASSWORD:-$(openssl rand -base64 24 | tr -d '\n')}"

  cat > .env <<ENV
APP_ENV=production
SECRET_KEY=$(openssl rand -hex 32)
COMMAND_DRY_RUN=false
DATABASE_URL=sqlite:///${APP_DIR}/backend/bpanel.db
ALLOWED_ORIGINS=${PANEL_URL}
SITES_ROOT=${SITES_ROOT}
BACKUP_ROOT=${BACKUP_ROOT}
SSL_EMAIL=${SSL_EMAIL}
FILEBROWSER_PORT=8088
ENV

  BPANEL_ADMIN_PASSWORD="$ADMIN_PASSWORD" python -m app.seed
  # Create / migrate the schema explicitly so subsequent service start is fast.
  python -c "from app.core.database import run_migrations; run_migrations()"
  deactivate || true

  # Lock down the env file: contains SECRET_KEY and ALLOWED_ORIGINS.
  chmod 0640 "${APP_DIR}/backend/.env"

  # Make all panel files owned by bpanel so the daemon can read/write them.
  chown -R bpanel:bpanel "${APP_DIR}/backend"
  chown -R bpanel:bpanel "${APP_DIR}/frontend" 2>/dev/null || true
}

wait_for_backend() {
  for _ in {1..30}; do
    if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  journalctl -u bpanel-api -n 80 --no-pager || true
  fail "bpanel-api did not respond at http://127.0.0.1:8000/api/health"
}

setup_systemd() {
  cat >/etc/systemd/system/bpanel-api.service <<SERVICE
[Unit]
Description=BPanel API
After=network.target mariadb.service

[Service]
Type=exec
User=bpanel
Group=bpanel
SupplementaryGroups=www-data
WorkingDirectory=${APP_DIR}/backend
EnvironmentFile=${APP_DIR}/backend/.env
Environment=HOME=${APP_DIR}
Environment=BPANEL_USE_HELPER=true
ExecStart=${APP_DIR}/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=always
RestartSec=3

# Hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=${APP_DIR} ${SITES_ROOT} ${BACKUP_ROOT} /etc/nginx/conf.d /tmp /var/lib/bpanel
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
ProtectClock=true
ProtectHostname=true
ProtectProc=invisible
RestrictNamespaces=true
RestrictRealtime=true
RestrictSUIDSGID=true
LockPersonality=true
MemoryDenyWriteExecute=true
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallFilter=~@privileged @resources @mount @debug @cpu-emulation @obsolete @reboot @swap
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
CapabilityBoundingSet=

[Install]
WantedBy=multi-user.target
SERVICE

  install -d -o bpanel -g bpanel -m 0750 /var/lib/bpanel
  systemctl daemon-reload
  systemctl enable --now bpanel-api
  wait_for_backend
}

setup_filebrowser_service() {
  install -d -o www-data -g www-data -m 0750 /etc/filebrowser /var/lib/filebrowser
  if [[ ! -f /etc/filebrowser/database.db ]]; then
    runuser -u www-data -- filebrowser -d /etc/filebrowser/database.db config init >/dev/null
  fi
  runuser -u www-data -- filebrowser -d /etc/filebrowser/database.db config set \
    --address 127.0.0.1 \
    --port 8088 \
    --baseURL /filebrowser \
    --root "$SITES_ROOT" \
    --auth.method=noauth \
    --branding.name BPanelFiles >/dev/null
  if ! runuser -u www-data -- filebrowser -d /etc/filebrowser/database.db users ls 2>/dev/null | grep -q '^admin'; then
    runuser -u www-data -- filebrowser -d /etc/filebrowser/database.db users add admin "$(openssl rand -base64 24)" --perm.admin >/dev/null
  fi
  chown -R www-data:www-data /etc/filebrowser

  cat >/etc/systemd/system/filebrowser.service <<SERVICE
[Unit]
Description=File Browser for BPanel
After=network.target

[Service]
User=www-data
Group=www-data
ExecStart=/usr/local/bin/filebrowser -d /etc/filebrowser/database.db
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=${SITES_ROOT} /etc/filebrowser /var/lib/filebrowser /tmp

[Install]
WantedBy=multi-user.target
SERVICE

  systemctl daemon-reload
  systemctl enable --now filebrowser
}


setup_phpmyadmin_sso() {
  local blowfish_secret
  blowfish_secret="$(openssl rand -hex 32)"

  cat >/etc/phpmyadmin/conf.d/bpanel-signon.php <<PHP
<?php
\$cfg['blowfish_secret'] = '${blowfish_secret}';
\$i = 1;
\$cfg['Servers'][\$i]['auth_type'] = 'signon';
\$cfg['Servers'][\$i]['SignonSession'] = 'BPanelPmaSignon';
\$cfg['Servers'][\$i]['SignonCookieParams'] = [
    'lifetime' => 0,
    'path' => '/',
    'domain' => '',
    'secure' => true,
    'httponly' => true,
    'samesite' => 'Lax',
];
\$cfg['Servers'][\$i]['SignonURL'] = '/phpmyadmin/bpanel-signon.php';
\$cfg['Servers'][\$i]['host'] = 'localhost';
\$cfg['Servers'][\$i]['AllowNoPassword'] = false;
\$cfg['Servers'][\$i]['only_db'] = '';
\$cfg['SessionSavePath'] = '/var/lib/php/sessions';
\$cfg['PmaAbsoluteUri'] = '${PANEL_URL}/phpmyadmin/';
PHP

  cat >/usr/share/phpmyadmin/bpanel-signon.php <<'PHP'
<?php
declare(strict_types=1);

session_save_path('/var/lib/php/sessions');
ini_set('session.use_cookies', 'true');
session_set_cookie_params([
    'lifetime' => 0,
    'path' => '/',
    'domain' => '',
    'secure' => true,
    'httponly' => true,
    'samesite' => 'Lax',
]);
session_name('BPanelPmaSignon');
if (!session_start()) {
    http_response_code(500);
    exit('Cannot start signon session');
}

$token = $_GET['bpanel_sso'] ?? '';
if (!preg_match('/^[A-Za-z0-9_-]{20,}$/', $token)) {
    http_response_code(403);
    exit('Invalid token');
}

$apiUrl = 'http://127.0.0.1:8000/api/databases/phpmyadmin-sso/' . rawurlencode($token);
$ch = curl_init($apiUrl);
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT => 5,
    CURLOPT_HTTPHEADER => ['Accept: application/json'],
]);
$response = curl_exec($ch);
$status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);

if ($status !== 200 || !$response) {
    http_response_code(403);
    exit('Expired token');
}

$data = json_decode($response, true);
if (!is_array($data) || empty($data['db_user']) || empty($data['db_password'])) {
    http_response_code(403);
    exit('Invalid signon data');
}

session_regenerate_id(true);
$_SESSION = [];
$_SESSION['PMA_single_signon_user'] = $data['db_user'];
$_SESSION['PMA_single_signon_password'] = $data['db_password'];
$_SESSION['PMA_single_signon_host'] = 'localhost';
$_SESSION['PMA_single_signon_port'] = '';
$_SESSION['PMA_single_signon_cfgupdate'] = [
    'only_db' => $data['db_name'] ?? '',
];
$_SESSION['PMA_single_signon_HMAC_secret'] = bin2hex(random_bytes(16));
session_write_close();

header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header('Pragma: no-cache');
header('Location: /phpmyadmin/index.php?server=1');
exit;
PHP

  chown root:www-data /etc/phpmyadmin/conf.d/bpanel-signon.php
  chmod 640 /etc/phpmyadmin/conf.d/bpanel-signon.php
  chmod 644 /usr/share/phpmyadmin/bpanel-signon.php
}

setup_nginx() {
  rm -f /etc/nginx/sites-enabled/default /etc/nginx/conf.d/default.conf 2>/dev/null || true

  cat >/etc/nginx/sites-available/bpanel.conf <<NGINX
server {
  listen 80;
  server_name ${PANEL_DOMAIN};

  server_tokens off;
  client_max_body_size 1100M;

  root ${APP_DIR}/frontend/dist;
  index index.html;

  add_header X-Frame-Options "SAMEORIGIN" always;
  add_header X-Content-Type-Options "nosniff" always;
  add_header Referrer-Policy "strict-origin-when-cross-origin" always;
  add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=(), bluetooth=(), magnetometer=(), gyroscope=(), accelerometer=()" always;

  # Hashed asset bundles can be cached for a long time.
  location ^~ /assets/ {
    expires 365d;
    add_header Cache-Control "public, immutable";
    try_files \$uri =404;
  }

  # index.html and any unhashed entry point must always be revalidated so users
  # see the latest deployed frontend.
  location = / {
    add_header Cache-Control "no-store" always;
    try_files /index.html =404;
  }

  location = /index.html {
    add_header Cache-Control "no-store" always;
  }

  location / {
    try_files \$uri \$uri/ /index.html;
  }

  location /api/ {
    client_max_body_size 1100M;
    proxy_request_buffering off;
    proxy_pass http://127.0.0.1:8000/api/;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header X-Forwarded-Host \$host;
    proxy_set_header X-Forwarded-Port \$server_port;
  }

  location = /filebrowser {
    return 301 /filebrowser/;
  }

  location = /filebrowser/api/health {
    proxy_pass http://127.0.0.1:8088/api/health;
    proxy_set_header Host \$host;
    proxy_set_header X-Forwarded-Proto \$scheme;
  }

  location /filebrowser/ {
    auth_request /api/maintenance/filebrowser-auth;
    proxy_pass http://127.0.0.1:8088/filebrowser/;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header X-Forwarded-Host \$host;
    proxy_set_header X-Forwarded-Prefix /filebrowser;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
    client_max_body_size 1100M;
    proxy_request_buffering off;
  }

  location = /phpmyadmin {
    return 301 /phpmyadmin/;
  }

  location /phpmyadmin/ {
    alias /usr/share/phpmyadmin/;
    index index.php;
    try_files \$uri \$uri/ /phpmyadmin/index.php;
  }

  location ~ ^/phpmyadmin/(.+\.php)$ {
    alias /usr/share/phpmyadmin/\$1;
    include fastcgi_params;
    fastcgi_param SCRIPT_FILENAME /usr/share/phpmyadmin/\$1;
    fastcgi_param HTTPS on;
    fastcgi_param REQUEST_SCHEME https;
    fastcgi_param SERVER_PORT 443;
    fastcgi_param HTTP_X_FORWARDED_PROTO https;
    fastcgi_param HTTP_X_FORWARDED_SSL on;
    fastcgi_param HTTP_HOST \$host;
    fastcgi_pass unix:/run/php/php${PHP_DEFAULT}-fpm.sock;
  }

  location ~* ^/phpmyadmin/(.+\.(?:css|js|jpg|jpeg|gif|png|ico|svg|woff|woff2|ttf|eot))$ {
    alias /usr/share/phpmyadmin/\$1;
    access_log off;
    expires 7d;
  }
}
NGINX

  ln -sfn /etc/nginx/sites-available/bpanel.conf /etc/nginx/sites-enabled/bpanel.conf
  nginx -t
  systemctl reload nginx
}

setup_firewall() {
  ufw default deny incoming || true
  ufw default allow outgoing || true
  ufw allow OpenSSH || true
  ufw allow 'Nginx Full' || true
}

setup_ssl() {
  if [[ "$ENABLE_SSL" != "yes" ]]; then
    return 0
  fi

  certbot --nginx -d "$PANEL_DOMAIN" --email "$SSL_EMAIL" --agree-tos --non-interactive --redirect
  systemctl reload nginx
}

print_summary() {
  echo ""
  echo "=================================================="
  echo "BPanel installation completed on Ubuntu 24.04"
  echo "Panel: ${PANEL_URL}"
  echo "API health: ${PANEL_URL}/api/health"
  echo "Admin: admin / ${ADMIN_PASSWORD}"
  echo "Node.js: $(node -v)"
  echo "Default PHP: ${PHP_DEFAULT}"
  echo "Installed PHP versions: ${PHP_VERSIONS}"
  echo "PHP-FPM service: php${PHP_DEFAULT}-fpm"
  echo "MariaDB: $(mariadb --version 2>/dev/null || mysql --version 2>/dev/null || echo installed)"
  echo "Backend: ${APP_DIR}/backend"
  echo "Frontend: ${APP_DIR}/frontend"
  echo "Nginx config: /etc/nginx/sites-available/bpanel.conf"
  echo "Firewall: UFW installed, OpenSSH and Nginx Full allowed. Enable it from the Firewall page."
  echo "=================================================="
}

main() {
  validate_sources
  ask_panel_url

  log "Installing base packages"
  install_base_packages

  log "Installing Node.js ${NODE_MAJOR} from NodeSource"
  install_nodejs

  log "Installing PHP ${PHP_VERSIONS} from Ondrej PPA"
  install_php

  log "Installing WP-CLI"
  install_wp_cli

  log "Installing File Browser"
  install_filebrowser

  log "Copying source to ${APP_DIR}"
  copy_sources

  log "Building frontend"
  build_frontend

  log "Creating bpanel system user, MariaDB credentials and filesystem ACLs"
  setup_panel_user

  log "Installing privileged helper and sudoers rule"
  install_privileged_helper

  log "Configuring backend"
  setup_backend

  log "Creating systemd service (hardened, runs as bpanel user)"
  setup_systemd

  log "Configuring File Browser"
  setup_filebrowser_service

  log "Configuring phpMyAdmin SSO"
  setup_phpmyadmin_sso

  log "Configuring Nginx for ${PANEL_DOMAIN}"
  setup_nginx

  log "Configuring firewall"
  setup_firewall

  log "Configuring SSL"
  setup_ssl

  print_summary
}

main "$@"
