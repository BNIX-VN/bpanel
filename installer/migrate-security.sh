#!/usr/bin/env bash
# One-time migration: move BPanel from root-mode to non-root + helper mode.
#
# Run on a server that already has BPanel installed (the API is currently
# running as root). After this script the API will run as user `bpanel`,
# all privileged operations go through /usr/local/sbin/bpanel-helper, and
# the systemd unit is hardened.
#
# Safe to re-run.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root."
  exit 1
fi

APP_DIR="${APP_DIR:-/opt/bpanel}"
SITES_ROOT="${SITES_ROOT:-/home/bpanel-sites}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/bpanel}"
SOURCE_DIR="${SOURCE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

log() { echo ""; echo "==> $1"; }
fail() { echo "ERROR: $1" >&2; exit 1; }

[[ -d "$APP_DIR/backend" ]] || fail "Missing $APP_DIR/backend"
[[ -f "$SOURCE_DIR/installer/files/bpanel-helper.sh" ]] || fail "Missing helper file in $SOURCE_DIR/installer/files/. Pull latest source first."

log "Stopping bpanel-api"
systemctl stop bpanel-api 2>/dev/null || true

log "Creating system user 'bpanel'"
if ! id -u bpanel >/dev/null 2>&1; then
  useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin --user-group bpanel
fi
usermod -aG www-data bpanel || true

log "Installing privileged helper and sudoers rule"
install -m 0750 -o root -g bpanel "$SOURCE_DIR/installer/files/bpanel-helper.sh" /usr/local/sbin/bpanel-helper
install -m 0440 -o root -g root  "$SOURCE_DIR/installer/files/bpanel-sudoers"   /etc/sudoers.d/bpanel
visudo -c -f /etc/sudoers.d/bpanel >/dev/null
sudo -u bpanel env HOME="$APP_DIR" sudo -n /usr/local/sbin/bpanel-helper wp --info >/dev/null

log "Fixing filesystem ownership and permissions"
# /etc/nginx/conf.d: writable by group bpanel (so bpanel can write vhost files)
install -d -o root -g bpanel -m 2775 /etc/nginx/conf.d
chgrp -R bpanel /etc/nginx/conf.d
chmod g+rw /etc/nginx/conf.d/*.conf 2>/dev/null || true

# Site root: owned by bpanel, group www-data, setgid so new files inherit group
mkdir -p "$SITES_ROOT"
chown -R bpanel:www-data "$SITES_ROOT"
chmod 2775 "$SITES_ROOT"
# Existing site files keep www-data ownership but group writable for bpanel via setgid
find "$SITES_ROOT" -type d -exec chmod g+s {} + 2>/dev/null || true

# Backup root
mkdir -p "$BACKUP_ROOT"
chown -R bpanel:bpanel "$BACKUP_ROOT"
chmod 0750 "$BACKUP_ROOT"

# Application files (Python venv, frontend, .env, sqlite db)
chown -R bpanel:bpanel "$APP_DIR/backend"
[[ -d "$APP_DIR/frontend" ]] && chown -R bpanel:bpanel "$APP_DIR/frontend"
# Make sure the env file is readable by the service user.
[[ -f "$APP_DIR/backend/.env" ]] && chmod 0640 "$APP_DIR/backend/.env"

log "Setting up MariaDB credentials for the bpanel user"
if [[ -f "$APP_DIR/.my.cnf" ]]; then
  echo "  $APP_DIR/.my.cnf already exists, leaving it as-is"
else
  MARIADB_PASSWORD="$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-32)"
  # mariadb client when present, otherwise mysql; both still use socket auth as root
  MYSQL_BIN="$(command -v mariadb || command -v mysql)"
  [[ -n "$MYSQL_BIN" ]] || fail "Neither mariadb nor mysql client found"
  "$MYSQL_BIN" <<SQL
CREATE USER IF NOT EXISTS 'bpanel'@'localhost' IDENTIFIED BY '${MARIADB_PASSWORD}';
GRANT ALL PRIVILEGES ON *.* TO 'bpanel'@'localhost' WITH GRANT OPTION;
FLUSH PRIVILEGES;
SQL
  cat >"$APP_DIR/.my.cnf" <<MYCNF
[client]
user=bpanel
password="${MARIADB_PASSWORD}"
host=localhost

[mysqldump]
user=bpanel
password="${MARIADB_PASSWORD}"
host=localhost
MYCNF
  chown bpanel:bpanel "$APP_DIR/.my.cnf"
  chmod 0600 "$APP_DIR/.my.cnf"
  echo "  MariaDB user 'bpanel' created and ~/.my.cnf written"
fi

log "Writing hardened systemd unit"
install -d -o bpanel -g bpanel -m 0750 /var/lib/bpanel
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

# Hardening. These settings must not block the sudo helper; privileged work is
# restricted by /usr/local/sbin/bpanel-helper and /etc/sudoers.d/bpanel.
NoNewPrivileges=false
ProtectSystem=false
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
RestrictSUIDSGID=false
LockPersonality=true
MemoryDenyWriteExecute=true
SystemCallArchitectures=native
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
CapabilityBoundingSet=~

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload

log "Updating Python deps and re-compiling"
cd "$APP_DIR/backend"
sudo -u bpanel bash -c "
  if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
  source .venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt
"

log "Starting bpanel-api"
systemctl enable --now bpanel-api

log "Health check"
for _ in {1..20}; do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    echo "API is healthy."
    echo ""
    echo "Migration complete. The API now runs as user 'bpanel' and is restricted by:"
    echo "  - hardened systemd unit"
    echo "  - sudoers limited to /usr/local/sbin/bpanel-helper"
    echo ""
    echo "Verify with:  systemctl status bpanel-api  |  ps -o user,cmd -C uvicorn"
    exit 0
  fi
  sleep 1
done

echo "API did not respond. Check logs:"
echo "  journalctl -u bpanel-api -n 100 --no-pager"
exit 1
