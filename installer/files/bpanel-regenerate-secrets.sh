#!/usr/bin/env bash
# Give a server cloned from an image secrets of its own (`bpanel
# regenerate-secrets`; security, 2026-11-10).
#
# Every VPS made from one image starts with the image's secrets, so each one
# accepts the others' sessions and tokens and shares their database password.
# This replaces, on this server only:
#
#   - the panel's SECRET_KEY (sessions, and the passwords it stores encrypted:
#     those are encrypted again under the new key) and the API and MCP tokens
#     (deleted) -- app.regenerate_secrets;
#   - phpMyAdmin's cookie secret (blowfish);
#   - the password of MariaDB's `bpanel` user and /opt/bpanel/.my.cnf;
#   - the panel's self-signed certificate, when it uses one;
#   - the DNS Manager's API key and the Email addon's webmail secrets, when
#     those addons are installed;
#   - the shared blocklist's reporter key: the server registers as itself.
#
# Everyone signed in to the panel is signed out. The admin's password is not
# changed here; `bpanel sync-admin-root-password` or `bpanel
# change-admin-password` does that.
#
#   bpanel regenerate-secrets           replace them now
#   bpanel regenerate-secrets --once    only on a server other than the one it
#                                       last ran on (for an image's boot script)
#
# What it changes is copied under /root/bpanel-secrets.XXXXXX first.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/bpanel}"
DATA_DIR="${BPANEL_DATA_DIR:-/var/lib/bpanel}"
ENV_FILE="$APP_DIR/backend/.env"
MYCNF="$APP_DIR/.my.cnf"
MARKER="$DATA_DIR/secrets-host"
HELPER=/usr/local/sbin/bpanel-helper
PMA_SIGNON_CONF=/etc/phpmyadmin/conf.d/bpanel-signon.php
PDNS_KEY=/etc/bpanel/pdns-api.key
PDNS_CONF=/etc/powerdns/pdns.d/zz-bpanel.conf
WEBMAIL_ENV=/etc/bnix-webmail.env
WEBMAIL_SSO_KEY=/etc/bpanel/webmail-sso.key
DOVECOT_MASTERS=/etc/dovecot/bpanel/masters
WEBMAIL_MASTER_USER=bpanel-webmail

die() { echo "ERROR: $*" >&2; exit 1; }
warn() { echo "WARN: $*" >&2; }
env_value() { awk -F= -v key="$1" '$1 == key { sub(/^[^=]*=/, ""); print; exit }' "$ENV_FILE" 2>/dev/null || true; }

# This server, as far as an image's clones differ: the machine id, the SSH
# host key (both remade per instance by cloud-init) and the address.
host_identity() {
  {
    cat /etc/machine-id 2>/dev/null || true
    cat /etc/ssh/ssh_host_ed25519_key.pub 2>/dev/null | awk '{print $2}' || true
    hostname -I 2>/dev/null | awk '{print $1}' || true
  } | sha256sum | cut -d' ' -f1
}

once=0
case "${1:-}" in
  "") ;;
  --once) once=1 ;;
  -h|--help) sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) die "usage: bpanel regenerate-secrets [--once]" ;;
esac
[[ $EUID -eq 0 ]] || die "Run as root"
[[ -f "$ENV_FILE" ]] || die "$ENV_FILE not found"

identity="$(host_identity)"
if [[ $once -eq 1 && -f "$MARKER" && "$(cat "$MARKER" 2>/dev/null)" == "$identity" ]]; then
  echo "This server's secrets were already made here; nothing to change."
  exit 0
fi

backup_root="$(mktemp -d /root/bpanel-secrets.XXXXXX)"
chmod 0700 "$backup_root"
keep() {
  local path
  for path in "$@"; do
    [[ -e "$path" ]] || continue
    mkdir -p "$backup_root$(dirname "$path")"
    cp -a -- "$path" "$backup_root$path"
  done
}

db_path="$(env_value DATABASE_URL)"
db_path="${db_path:-sqlite:///./bpanel.db}"
db_path="${db_path#sqlite:///}"
[[ "$db_path" == /* ]] || db_path="$APP_DIR/backend/${db_path#./}"

systemctl stop bpanel-backup-scheduler.timer >/dev/null 2>&1 || true
systemctl stop bpanel-api >/dev/null 2>&1 || true
restart_panel() {
  systemctl start bpanel-api >/dev/null 2>&1 || warn "bpanel-api did not start: journalctl -u bpanel-api"
  systemctl start bpanel-backup-scheduler.timer >/dev/null 2>&1 || true
}
trap restart_panel EXIT

keep "$ENV_FILE" "$db_path" "$MYCNF" "$PMA_SIGNON_CONF" "$PDNS_KEY" "$PDNS_CONF" \
  "$WEBMAIL_ENV" "$WEBMAIL_SSO_KEY" "$DOVECOT_MASTERS" \
  /etc/bpanel/panel-selfsigned-fullchain.pem /etc/bpanel/panel-selfsigned-privkey.pem "$MARKER"
while IFS= read -r -d '' json; do
  keep "$json"
done < <(find "$DATA_DIR" -xdev -type f -name '*.json' -print0 2>/dev/null)

# 1. The panel's own: SECRET_KEY and what it encrypts, the API and MCP tokens.
( cd "$APP_DIR/backend" && sudo -u bpanel env HOME="$APP_DIR" BPANEL_DATA_DIR="$DATA_DIR" \
    "$APP_DIR/backend/.venv/bin/python" -W ignore -m app.regenerate_secrets ) \
  || die "the panel's secrets could not be replaced; nothing of them changed (backup: $backup_root)"
changed=("panel SECRET_KEY, stored passwords re-encrypted, API/MCP tokens deleted")

# 2. phpMyAdmin's cookie secret.
if [[ -f "$PMA_SIGNON_CONF" ]]; then
  sed -i -E "s/^(\\\$cfg\['blowfish_secret'\] = ')[^']*(';)/\1$(openssl rand -hex 32)\2/" "$PMA_SIGNON_CONF"
  changed+=("phpMyAdmin cookie secret")
fi

# 3. MariaDB's `bpanel` user.
if [[ -f "$MYCNF" ]] && command -v mariadb >/dev/null 2>&1; then
  password="$(openssl rand -base64 32 | tr -d '/+=\n' | cut -c1-32)"
  if mariadb <<SQL
ALTER USER 'bpanel'@'localhost' IDENTIFIED BY '${password}';
FLUSH PRIVILEGES;
SQL
  then
    python3 - "$MYCNF" "$password" <<'PY'
import re, sys
path, password = sys.argv[1:3]
text = open(path, encoding="utf-8").read()
text = re.sub(r'(?m)^(\s*password\s*=\s*).*$', lambda m: m.group(1) + '"' + password + '"', text)
open(path, "w", encoding="utf-8").write(text)
PY
    changed+=("MariaDB password of the bpanel user")
  else
    warn "MariaDB's bpanel user kept its password"
  fi
fi

# 4. The panel's self-signed certificate, made again for its current address.
if [[ "$(env_value PANEL_SSL_MODE)" == "selfsigned" && -x "$HELPER" ]]; then
  panel_url="$(env_value PANEL_URL)"
  host="${panel_url#*://}"; host="${host%%/*}"; port="${host##*:}"; host="${host%:*}"
  [[ "$port" =~ ^[0-9]+$ ]] || port=2222
  sudo -u bpanel env HOME="$APP_DIR" sudo -n "$HELPER" panel-ssl-selfsigned "$host" "$port" >/dev/null 2>&1 \
    && changed+=("the panel's self-signed certificate") \
    || warn "the self-signed certificate was not remade"
fi

# 5. DNS Manager: its API key (PowerDNS's api-key and the file the panel reads).
if [[ -f "$PDNS_KEY" && -f "$PDNS_CONF" ]]; then
  key="$(openssl rand -hex 32)"
  printf '%s\n' "$key" >"$PDNS_KEY.new"
  chown --reference="$PDNS_KEY" "$PDNS_KEY.new"
  chmod --reference="$PDNS_KEY" "$PDNS_KEY.new"
  mv -f "$PDNS_KEY.new" "$PDNS_KEY"
  sed -i -E "s/^api-key=.*/api-key=${key}/" "$PDNS_CONF"
  systemctl restart pdns >/dev/null 2>&1 || warn "pdns did not restart: journalctl -u pdns"
  changed+=("DNS Manager API key")
fi

# 6. Email addon: the webmail's session and sign-on secrets and the password
#    of its sign-on master user in Dovecot.
if [[ -f "$WEBMAIL_ENV" ]]; then
  auth_secret="$(openssl rand -hex 32)"
  sso_secret="$(openssl rand -hex 32)"
  master_password="$(openssl rand -hex 24)"
  sed -i -E -e "s/^AUTH_SECRET=.*/AUTH_SECRET=${auth_secret}/" -e "s/^SSO_SECRET=.*/SSO_SECRET=${sso_secret}/" \
    -e "s/^SSO_MASTER_PASSWORD=.*/SSO_MASTER_PASSWORD=${master_password}/" "$WEBMAIL_ENV"
  install -m 0640 -o root -g bpanel /dev/null "$WEBMAIL_SSO_KEY.new"
  printf '%s\n' "$sso_secret" >"$WEBMAIL_SSO_KEY.new"
  mv -f "$WEBMAIL_SSO_KEY.new" "$WEBMAIL_SSO_KEY"
  if [[ -d "$(dirname "$DOVECOT_MASTERS")" ]]; then
    install -m 0640 -o root -g dovecot /dev/null "$DOVECOT_MASTERS.new"
    printf '%s:{SHA512-CRYPT}%s\n' "$WEBMAIL_MASTER_USER" \
      "$(printf '%s\n' "$master_password" | openssl passwd -6 -stdin)" >"$DOVECOT_MASTERS.new"
    mv -f "$DOVECOT_MASTERS.new" "$DOVECOT_MASTERS"
    systemctl reload dovecot >/dev/null 2>&1 || systemctl restart dovecot >/dev/null 2>&1 || warn "dovecot did not reload"
  fi
  systemctl restart bpanel-webmail >/dev/null 2>&1 || warn "the webmail did not restart"
  changed+=("webmail secrets and its Dovecot sign-on password")
fi

# 7. Shared blocklist: forget the image's reporter key; the next run registers
#    this server as a reporter of its own (approved again on the collector).
state="$DATA_DIR/shared-blocklist.json"
if [[ -f "$state" ]] && grep -q '"key"' "$state"; then
  python3 - "$state" <<'PY'
import json, os, sys
path = sys.argv[1]
data = json.load(open(path, encoding="utf-8"))
if isinstance(data, dict) and data.get("key"):
    data.update(key="", reporter_id=None, status="", last_error="")
    tmp = path + ".regen-tmp"
    open(tmp, "w", encoding="utf-8").write(json.dumps(data, indent=2) + "\n")
    st = os.stat(path)
    os.chown(tmp, st.st_uid, st.st_gid)
    os.chmod(tmp, st.st_mode & 0o777)
    os.replace(tmp, path)
PY
  changed+=("shared blocklist reporter key (registers again)")
fi

install -m 0644 -o root -g root /dev/null "$MARKER"
printf '%s\n' "$identity" >"$MARKER"

echo "Replaced on this server:"
printf '  %s\n' "${changed[@]}"
echo "Everyone signed in to the panel has to sign in again."
echo "Backup: $backup_root"
