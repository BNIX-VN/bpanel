#!/usr/bin/env bash
# Update BPanel from GitHub.
#
# This script is meant to live in a checkout of the BPanel repo (e.g.
# /opt/bpanel-source). It pulls the latest commit from origin/main, syncs the
# source into /opt/bpanel, rebuilds the frontend, refreshes the direct panel
# service, restarts the API, and reloads nginx for customer vhosts.
#
# Usage:
#   sudo bash installer/update.sh
#   sudo bash installer/update.sh --branch dev
#   APP_DIR=/srv/bpanel sudo -E bash installer/update.sh

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root"
  exit 1
fi

# --- Config ----------------------------------------------------------------
APP_DIR="${APP_DIR:-/opt/bpanel}"                 # Production deployment dir
DEFAULT_SOURCE_DIR="/opt/bpanel-source"           # Where the git checkout lives

# Resolve where THIS script lives. If it's inside a real git checkout we use
# that. Otherwise we fall back to /opt/bpanel-source so users running the
# script from the deploy dir still get a usable workflow.
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -d "$_SCRIPT_DIR/.git" ]]; then
  SOURCE_DIR="${SOURCE_DIR:-$_SCRIPT_DIR}"
else
  SOURCE_DIR="${SOURCE_DIR:-$DEFAULT_SOURCE_DIR}"
fi

REPO_URL="${REPO_URL:-https://github.com/BNIX-VN/bpanel.git}"
BRANCH="${BRANCH:-main}"
SKIP_PULL="${SKIP_PULL:-false}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch) BRANCH="$2"; shift 2 ;;
    --skip-pull) SKIP_PULL="true"; shift ;;
    --app-dir) APP_DIR="$2"; shift 2 ;;
    -h|--help)
      sed -n '1,30p' "${BASH_SOURCE[0]}"
      exit 0 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

log()  { echo ""; echo "==> $1"; }
fail() { echo "ERROR: $1" >&2; exit 1; }

env_get() {
  local file="$APP_DIR/backend/.env" key="$1"
  [[ -f "$file" ]] || return 0
  awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); print; exit }' "$file"
}

env_set_default() {
  local file="$APP_DIR/backend/.env" key="$1" value="$2"
  if ! grep -q "^${key}=" "$file"; then
    printf '%s=%s\n' "$key" "$value" >>"$file"
  fi
}

detect_server_ip() {
  hostname -I 2>/dev/null | awk '{print $1}' || true
}

write_tools_nginx_config() {
  local panel_port panel_domain panel_cert panel_key filebrowser_port php_version server_ip host api_scheme tools_scheme pma_secure ssl_block
  panel_port="$(env_get PANEL_PORT)"; panel_port="${panel_port:-2222}"
  panel_domain="$(env_get PANEL_DOMAIN)"
  panel_cert="$(env_get PANEL_SSL_CERT)"
  panel_key="$(env_get PANEL_SSL_KEY)"
  filebrowser_port="$(env_get FILEBROWSER_PORT)"; filebrowser_port="${filebrowser_port:-8088}"
  php_version="${PHP_DEFAULT:-8.3}"
  server_ip="$(detect_server_ip)"
  host="${panel_domain:-$server_ip}"
  api_scheme="http"; tools_scheme="http"; pma_secure="false"; ssl_block=""
  if [[ -n "$panel_cert" && -n "$panel_key" && -f "$panel_cert" && -f "$panel_key" ]]; then
    api_scheme="https"; tools_scheme="https"; pma_secure="true"
    printf -v ssl_block '\n    listen 443 ssl default_server;\n    ssl_certificate %s;\n    ssl_certificate_key %s;' "$panel_cert" "$panel_key"
  fi
  cat >/etc/nginx/conf.d/00-bpanel-tools.conf <<NGINX
server {
    listen 80 default_server;${ssl_block}
    server_name _;
    client_max_body_size 1100M;

    location = /_bpanel/filebrowser-auth {
        internal;
        proxy_pass ${api_scheme}://127.0.0.1:${panel_port}/api/maintenance/filebrowser-auth;
        proxy_ssl_verify off;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header Cookie \$http_cookie;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
    }

    location /filebrowser/ {
        auth_request /_bpanel/filebrowser-auth;
        auth_request_set \$filebrowser_user \$upstream_http_x_bpanel_user;
        proxy_pass http://127.0.0.1:${filebrowser_port};
        proxy_http_version 1.1;
        proxy_request_buffering off;
        proxy_buffering off;
        proxy_set_header Host \$host;
        proxy_set_header X-Bpanel-User \$filebrowser_user;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Prefix /filebrowser;
        proxy_set_header X-Original-URI \$request_uri;
    }

    location = /phpmyadmin { return 301 /phpmyadmin/; }
    location /phpmyadmin/ { alias /usr/share/phpmyadmin/; index index.php; try_files \$uri \$uri/ =404; }
    location ~ ^/phpmyadmin/(.+\.php)$ {
        alias /usr/share/phpmyadmin/\$1;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME /usr/share/phpmyadmin/\$1;
        fastcgi_param SCRIPT_NAME /phpmyadmin/\$1;
        fastcgi_pass unix:/run/php/php${php_version}-fpm.sock;
        fastcgi_read_timeout 300;
    }
}
NGINX
  sed -i -E "s#(\$apiUrl = ')[^']+(/api/databases/phpmyadmin-sso/)'#\1${api_scheme}://127.0.0.1:${panel_port}\2'#" /usr/share/phpmyadmin/bpanel-signon.php 2>/dev/null || true
  sed -i -E "s#('secure' => )(true|false)#\1${pma_secure}#" /etc/phpmyadmin/conf.d/bpanel-signon.php /usr/share/phpmyadmin/bpanel-signon.php 2>/dev/null || true
  [[ -n "$host" ]] && sed -i -E "s#(\$cfg\['PmaAbsoluteUri'\] = ')[^']+('#\1${tools_scheme}://${host}/phpmyadmin/\2#" /etc/phpmyadmin/conf.d/bpanel-signon.php 2>/dev/null || true
}

install_panel_runtime() {
  local env_file="$APP_DIR/backend/.env"
  [[ -f "$env_file" ]] || return 0
  local panel_port panel_url server_ip filebrowser_port
  panel_port="$(env_get PANEL_PORT)"
  panel_port="${panel_port:-2222}"
  filebrowser_port="$(env_get FILEBROWSER_PORT)"
  filebrowser_port="${filebrowser_port:-8088}"
  server_ip="$(detect_server_ip)"
  panel_url="$(env_get PANEL_URL)"
  panel_url="${panel_url:-http://${server_ip:-127.0.0.1}:${panel_port}}"

  env_set_default PANEL_PORT "$panel_port"
  env_set_default PANEL_URL "$panel_url"
  env_set_default PANEL_DOMAIN ""
  env_set_default PANEL_SSL_CERT ""
  env_set_default PANEL_SSL_KEY ""
  env_set_default FRONTEND_DIST "$APP_DIR/frontend/dist"
  if [[ -z "$(env_get ALLOWED_ORIGINS)" ]]; then
    env_set_default ALLOWED_ORIGINS "$panel_url"
  fi

  getent group bpanel-sites >/dev/null || groupadd --system bpanel-sites
  if ! command -v setfacl >/dev/null 2>&1 && command -v apt-get >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y acl
  fi
  usermod -aG bpanel-sites bpanel 2>/dev/null || true
  usermod -aG bpanel-sites www-data 2>/dev/null || true
  install -d -o bpanel -g bpanel-sites -m 2775 "${SITES_ROOT:-/home/bpanel-sites}"

  cat >/usr/local/sbin/bpanel-api-start <<STARTER
#!/usr/bin/env bash
set -euo pipefail
cd ${APP_DIR}/backend
args=(app.main:app --host 0.0.0.0 --port "\${PANEL_PORT:-2222}" --proxy-headers --forwarded-allow-ips "*")
if [[ -n "\${PANEL_SSL_CERT:-}" && -n "\${PANEL_SSL_KEY:-}" && -f "\${PANEL_SSL_CERT}" && -f "\${PANEL_SSL_KEY}" ]]; then
  args+=(--ssl-certfile "\${PANEL_SSL_CERT}" --ssl-keyfile "\${PANEL_SSL_KEY}")
fi
exec ${APP_DIR}/backend/.venv/bin/uvicorn "\${args[@]}"
STARTER
  chmod 0755 /usr/local/sbin/bpanel-api-start
  mkdir -p /etc/systemd/system/bpanel-api.service.d
  cat >/etc/systemd/system/bpanel-api.service.d/20-panel-port.conf <<'SERVICE'
[Service]
ExecStart=
ExecStart=/usr/local/sbin/bpanel-api-start
SupplementaryGroups=www-data bpanel-sites
ProtectHome=false
ReadWritePaths=/home /home/bpanel-sites /var/backups/bpanel /etc/nginx/conf.d /tmp /var/lib/bpanel
SERVICE
  mkdir -p /etc/systemd/system/filebrowser.service.d
  cat >/etc/systemd/system/filebrowser.service.d/10-bpanel-sites.conf <<'SERVICE'
[Service]
SupplementaryGroups=bpanel-sites
ReadWritePaths=/home /home/bpanel-sites /etc/filebrowser /var/lib/filebrowser /tmp
SERVICE
  if command -v filebrowser >/dev/null 2>&1 && [[ -f /etc/filebrowser/database.db ]]; then
    systemctl stop filebrowser 2>/dev/null || true
    runuser -u www-data -- filebrowser -d /etc/filebrowser/database.db config set \
      --root /home \
      --address 127.0.0.1 \
      --port "$filebrowser_port" \
      --auth.method=proxy \
      --auth.header X-Bpanel-User \
      --baseURL /filebrowser >/dev/null 2>&1 || true
    if ! runuser -u www-data -- filebrowser -d /etc/filebrowser/database.db users ls 2>/dev/null | grep -q '^admin'; then
      runuser -u www-data -- filebrowser -d /etc/filebrowser/database.db users add admin "$(openssl rand -base64 24)" --perm.admin >/dev/null 2>&1 || true
    fi
  fi
  if command -v ufw >/dev/null 2>&1; then
    ufw allow "${panel_port}/tcp" >/dev/null || true
  fi
  rm -f /etc/nginx/sites-enabled/default /etc/nginx/conf.d/default.conf 2>/dev/null || true
  rm -f /etc/nginx/sites-enabled/bpanel.conf /etc/nginx/sites-available/bpanel.conf 2>/dev/null || true
  write_tools_nginx_config
  if [[ -f /usr/share/phpmyadmin/bpanel-signon.php ]]; then
    local scheme="http"
    if [[ -n "$(env_get PANEL_SSL_CERT)" && -n "$(env_get PANEL_SSL_KEY)" ]]; then
      scheme="https"
    fi
    sed -i -E "s#(\$apiUrl = ')[^']+(/api/databases/phpmyadmin-sso/)'#\1${scheme}://127.0.0.1:${panel_port}\2'#" /usr/share/phpmyadmin/bpanel-signon.php || true
  fi
}

panel_healthcheck() {
  local port
  port="$(env_get PANEL_PORT)"
  port="${port:-2222}"
  curl -kfsS "https://127.0.0.1:${port}/api/health" >/dev/null 2>&1 \
    || curl -fsS "http://127.0.0.1:${port}/api/health" >/dev/null 2>&1
}

refresh_bpanel_mariadb_grants() {
  local defaults_file="$APP_DIR/.my.cnf"
  [[ -f "$defaults_file" ]] || return 0
  local mysql_bin
  mysql_bin="$(command -v mariadb || command -v mysql || true)"
  [[ -n "$mysql_bin" ]] || return 0
  local password
  password="$(awk -F= '
    /^\[client\]/ { in_client=1; next }
    /^\[/ { in_client=0 }
    in_client && $1 == "password" {
      value=$0; sub(/^[^=]*=/, "", value); gsub(/^"|"$/, "", value); print value; exit
    }
  ' "$defaults_file")"
  [[ -n "$password" ]] || return 0
  "$mysql_bin" <<SQL
CREATE USER IF NOT EXISTS 'bpanel'@'localhost' IDENTIFIED BY '${password}';
ALTER USER 'bpanel'@'localhost' IDENTIFIED BY '${password}';
GRANT ALL PRIVILEGES ON *.* TO 'bpanel'@'localhost' WITH GRANT OPTION;
FLUSH PRIVILEGES;
SQL
}

# --- Snapshot the SQLite DB before doing anything ---------------------------
backup_db() {
  local db_path="$APP_DIR/backend/bpanel.db"
  if [[ ! -f "$db_path" ]]; then
    return 0
  fi
  local snap_dir="${BACKUP_ROOT:-/var/backups/bpanel}/db-snapshots"
  install -d -m 0750 "$snap_dir"
  if id -u bpanel >/dev/null 2>&1; then
    chown bpanel:bpanel "$snap_dir" 2>/dev/null || true
  fi
  local stamp
  stamp=$(date -u +%Y%m%d-%H%M%S)
  local snap="$snap_dir/bpanel-$stamp.db"
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$db_path" ".backup '$snap'"
  else
    cp -a "$db_path" "$snap"
  fi
  echo "DB snapshot saved: $snap"
  # Keep the 10 most recent snapshots.
  ls -1t "$snap_dir"/bpanel-*.db 2>/dev/null | tail -n +11 | xargs -r rm -f
}

log "Backing up SQLite DB before update"
backup_db

# --- Pull latest source ----------------------------------------------------
if [[ "$(readlink -f "$SOURCE_DIR")" == "$(readlink -f "$APP_DIR")" ]]; then
  fail "SOURCE_DIR ($SOURCE_DIR) and APP_DIR ($APP_DIR) must be different. Clone the repo to /opt/bpanel-source first."
fi

if [[ "$SKIP_PULL" != "true" ]]; then
  if [[ ! -d "$SOURCE_DIR/.git" ]]; then
    if [[ -e "$SOURCE_DIR" && -n "$(ls -A "$SOURCE_DIR" 2>/dev/null)" ]]; then
      fail "$SOURCE_DIR exists but is not a git checkout and is not empty. Move it aside or set SOURCE_DIR=/some/empty/dir."
    fi
    log "Cloning $REPO_URL to $SOURCE_DIR"
    git clone "$REPO_URL" "$SOURCE_DIR"
  fi
  log "Pulling latest from origin/$BRANCH"
  cd "$SOURCE_DIR"
  git fetch --all --prune
  git checkout "$BRANCH"
  git reset --hard "origin/$BRANCH"
  echo "HEAD: $(git rev-parse --short HEAD) â€” $(git log -1 --pretty=%s)"
fi

# --- Validate ---------------------------------------------------------------
[[ -d "$SOURCE_DIR/backend"  ]] || fail "Missing $SOURCE_DIR/backend"
[[ -d "$SOURCE_DIR/frontend" ]] || fail "Missing $SOURCE_DIR/frontend"

# --- Sync code into APP_DIR -------------------------------------------------
log "Syncing source to $APP_DIR"
mkdir -p "$APP_DIR"

if command -v rsync >/dev/null 2>&1; then
  # --filter='P ...' (protect) keeps the destination file even when --delete
  # would otherwise remove it because the source side doesn't have it. We use
  # this for runtime artefacts that the installer creates: .env, .venv,
  # bpanel.db, .my.cnf.
  rsync -a --delete \
    --filter='P /.env' \
    --filter='P /.venv/***' \
    --filter='P /bpanel.db' \
    --filter='P /.my.cnf' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    "$SOURCE_DIR/backend/" "$APP_DIR/backend/"
  rsync -a --delete \
    --filter='P /node_modules/***' \
    --filter='P /dist/***' \
    --filter='P /.vite/***' \
    "$SOURCE_DIR/frontend/" "$APP_DIR/frontend/"
else
  cp -r "$SOURCE_DIR/backend/."  "$APP_DIR/backend/"
  cp -r "$SOURCE_DIR/frontend/." "$APP_DIR/frontend/"
fi

# Defensive: if .env still doesn't exist (e.g. fresh deploy syncing on top of
# nothing), leave a clear error message.
if [[ ! -f "$APP_DIR/backend/.env" ]]; then
  fail "$APP_DIR/backend/.env is missing. Run installer/install.sh first or restore .env from backup."
fi
log "Installing direct panel runtime on port 2222"
install_panel_runtime
if [[ ! -x "$APP_DIR/backend/.venv/bin/uvicorn" ]]; then
  log "Recreating Python virtualenv (was missing)"
  rm -rf "$APP_DIR/backend/.venv"
  python3 -m venv "$APP_DIR/backend/.venv"
fi

# --- Refresh helper + sudoers (idempotent) ---------------------------------
if [[ -f "$SOURCE_DIR/installer/files/bpanel-helper.sh" ]]; then
  log "Refreshing /usr/local/sbin/bpanel-helper and /etc/sudoers.d/bpanel"
  if id -u bpanel >/dev/null 2>&1; then
    install -m 0750 -o root -g bpanel "$SOURCE_DIR/installer/files/bpanel-helper.sh" /usr/local/sbin/bpanel-helper
    install -m 0440 -o root -g root  "$SOURCE_DIR/installer/files/bpanel-sudoers"   /etc/sudoers.d/bpanel
    visudo -c -f /etc/sudoers.d/bpanel >/dev/null
    sudo -u bpanel env HOME="$APP_DIR" sudo -n /usr/local/sbin/bpanel-helper wp --info >/dev/null
  else
    echo "  (bpanel user not found; skipping helper refresh â€” run install.sh first)"
  fi
fi

if [[ -f "$SOURCE_DIR/installer/files/bpanelctl" ]]; then
  log "Refreshing SSH menu command: bpanel"
  install -m 0755 -o root -g root "$SOURCE_DIR/installer/files/bpanelctl" /usr/local/sbin/bpanel
  ln -sfn /usr/local/sbin/bpanel /usr/local/sbin/bpanelctl
fi

# --- Restore ownership so bpanel user can read/write the deploy ------------
if id -u bpanel >/dev/null 2>&1; then
  chown -R bpanel:bpanel "$APP_DIR/backend" "$APP_DIR/frontend" 2>/dev/null || true
  [[ -f "$APP_DIR/backend/.env" ]] && chmod 0640 "$APP_DIR/backend/.env"
fi

# --- Backend ---------------------------------------------------------------
log "Updating backend dependencies"
cd "$APP_DIR/backend"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

log "Refreshing MariaDB grants"
refresh_bpanel_mariadb_grants

log "Running database migrations"
if id -u bpanel >/dev/null 2>&1; then
  # Run migrations as the bpanel user so the SQLite file ownership stays correct.
  sudo -u bpanel "$APP_DIR/backend/.venv/bin/python" -c \
    "from app.core.database import run_migrations; run_migrations()"
else
  python -c "from app.core.database import run_migrations; run_migrations()"
fi

log "Refreshing managed site permissions"
if id -u bpanel >/dev/null 2>&1; then
  sudo -u bpanel env HOME="$APP_DIR" BPANEL_USE_HELPER=true "$APP_DIR/backend/.venv/bin/python" - <<'PY'
from app.core.database import SessionLocal
from app.models.entities import Website
from app.services import site_users

with SessionLocal() as db:
    for website in db.query(Website).all():
        try:
            if website.linux_user:
                runtime_php_version = website.php_version if (website.app_type or "wordpress") == "wordpress" else None
                site_users.ensure_site_runtime(website.domain, website.root_path, runtime_php_version)
            site_users.fix_site_permissions(website.root_path, website.linux_user)
        except Exception as exc:
            print(f"WARNING: could not refresh permissions for {website.domain}: {exc}")
PY
fi

log "Compiling backend modules"
python -m py_compile \
  app/main.py \
  app/api/auth.py \
  app/api/users.py \
  app/api/websites.py \
  app/api/databases.py \
  app/api/maintenance.py \
  app/api/firewall.py \
  app/api/services.py \
  app/services/firewall.py \
  app/services/nginx.py \
  app/services/panel_urls.py \
  app/services/mariadb.py \
  app/services/wordpress.py \
  app/services/file_manager.py \
  app/services/backup.py \
  app/services/site_users.py \
  app/services/cron.py \
  app/services/php.py \
  app/schemas/schemas.py \
  app/seed.py
deactivate

log "Restarting bpanel-api"
mkdir -p /etc/systemd/system/bpanel-api.service.d
cat >/etc/systemd/system/bpanel-api.service.d/10-bpanel-helper.conf <<'SERVICE'
[Service]
NoNewPrivileges=false
ProtectSystem=false
RestrictSUIDSGID=false
CapabilityBoundingSet=~
SystemCallFilter=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
SERVICE
systemctl daemon-reload
systemctl restart bpanel-api
systemctl restart filebrowser 2>/dev/null || true

# --- Frontend --------------------------------------------------------------
log "Building frontend (clean rebuild)"
cd "$APP_DIR/frontend"
rm -rf dist .vite node_modules/.vite

if [[ ! -d node_modules ]] || [[ package.json -nt node_modules ]]; then
  rm -rf node_modules package-lock.json
  npm install
fi
VITE_API_URL=/api npm run build

[[ -f dist/index.html ]] || fail "Frontend build failed: dist/index.html missing"
HASHED=$(grep -oE 'index-[a-zA-Z0-9_-]+\.js' dist/index.html | head -n1 || true)
echo "Built bundle: ${HASHED:-unknown}"

# Make sure nginx (www-data) can read the freshly built bundle.
chmod o+rX "$APP_DIR" "$APP_DIR/frontend" 2>/dev/null || true
chmod -R o+rX "$APP_DIR/frontend/dist"

# --- Reload Nginx ----------------------------------------------------------
log "Reloading nginx"
nginx -t
systemctl reload nginx

# --- Health check ----------------------------------------------------------
log "Health check"
for _ in {1..20}; do
  if panel_healthcheck; then
    echo "API is healthy."
    echo ""
    echo "Update completed."
    echo "If the browser still shows the old UI, hard refresh (Ctrl + Shift + R)."
    exit 0
  fi
  sleep 1
done

echo "API did not respond. Check logs:"
echo "  journalctl -u bpanel-api -n 100 --no-pager"
exit 1
