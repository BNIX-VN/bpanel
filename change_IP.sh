#!/usr/bin/env bash
set -euo pipefail

# Replace an old server IP with a new one in BPanel runtime/config files.
# It only edits text/config files and creates a backup under /root first.

APP_DIR="${APP_DIR:-/opt/bpanel}"
BPANEL_DATA_DIR="${BPANEL_DATA_DIR:-/var/lib/bpanel}"
LOGIN_FILE="${LOGIN_FILE:-/root/login.txt}"

usage() {
  cat <<'EOF'
Usage:
  sudo ./change_IP.sh <old-ip> <new-ip>
  sudo ./change_IP.sh <old-ip>

If <new-ip> is omitted, the script prompts for it and suggests the current detected address.
EOF
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

warn() {
  echo "WARN: $*" >&2
}

is_ipv4() {
  local value="$1" part
  local -a parts

  [[ "$value" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
  IFS=. read -r -a parts <<<"$value"
  for part in "${parts[@]}"; do
    [[ "$part" =~ ^[0-9]+$ ]] || return 1
    (( 10#$part >= 0 && 10#$part <= 255 )) || return 1
  done
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $EUID -ne 0 ]]; then
  die "Run as root: sudo $0 <old-ip> <new-ip>"
fi

old_ip="${1:-}"
new_ip="${2:-}"

if [[ -z "$old_ip" ]]; then
  read -rp "Old IP: " old_ip
fi

if [[ -z "$new_ip" ]]; then
  current_ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  if [[ -n "$current_ip" ]]; then
    read -rp "New IP [${current_ip}]: " new_ip
    new_ip="${new_ip:-$current_ip}"
  else
    read -rp "New IP: " new_ip
  fi
fi

is_ipv4 "$old_ip" || die "Invalid old IP: $old_ip"
is_ipv4 "$new_ip" || die "Invalid new IP: $new_ip"
[[ "$old_ip" != "$new_ip" ]] || die "Old IP and new IP are the same"

backup_root="$(mktemp -d /root/bpanel-ip-change.XXXXXX)"
declare -A seen=()
declare -a files=()
old_ip_ere="${old_ip//./\\.}"

add_candidate() {
  local path="$1" resolved
  [[ -e "$path" ]] || return 0
  resolved="$(readlink -f -- "$path" 2>/dev/null || true)"
  [[ -n "$resolved" ]] || return 0
  [[ -f "$resolved" ]] || return 0
  if [[ -z "${seen[$resolved]+x}" ]]; then
    seen["$resolved"]=1
    files+=("$resolved")
  fi
}

collect_glob() {
  local path
  for path in "$@"; do
    case "$path" in
      *.db|*.sqlite*|*.sqlite3|*.pem|*.key|*.crt|*.csr|*.p12|*.pfx|*.png|*.jpg|*.jpeg|*.webp|*.ico|*.gif|*.zip|*.tar|*.gz|*.tgz)
        continue
        ;;
    esac
    case "$path" in
      *.env|*.env.*|*.conf|*.json|*.php|*.txt|*.yml|*.yaml|*.ini|*.service|*.timer|*.socket|*.sh|*.js|*.css|*.html|*/hosts|*/login.txt|*/panel-settings.json|*/bpanel-signon.php)
        add_candidate "$path"
        ;;
    esac
  done
}

collect_tree() {
  local root="$1"
  [[ -d "$root" ]] || return 0
  while IFS= read -r -d '' path; do
    collect_glob "$path"
  done < <(
    find "$root" -xdev \
      \( -path '*/.git/*' -o -path '*/.venv/*' -o -path '*/node_modules/*' -o -path '*/__pycache__/*' -o -path '*/assets/*' \) -prune -o \
      -type f \
      \( -name '.env' -o -name '.env.*' -o -name '*.conf' -o -name '*.json' -o -name '*.php' -o -name '*.txt' -o -name '*.yml' -o -name '*.yaml' -o -name '*.ini' -o -name '*.service' -o -name '*.timer' -o -name '*.socket' -o -name '*.sh' -o -name '*.js' -o -name '*.css' -o -name '*.html' \) \
      -print0 2>/dev/null
  )
}

shopt -s nullglob
collect_glob \
  "$APP_DIR/backend/.env" \
  "$APP_DIR"/backend/.env.* \
  "$BPANEL_DATA_DIR/panel-settings.json" \
  "$LOGIN_FILE" \
  /etc/hosts \
  /usr/share/phpmyadmin/bpanel-signon.php \
  /etc/phpmyadmin/conf.d/*.php \
  /etc/nginx/conf.d/*.conf \
  /etc/nginx/sites-available/*.conf \
  /etc/nginx/sites-enabled/*.conf
shopt -u nullglob

collect_tree "$APP_DIR"
collect_tree "$BPANEL_DATA_DIR"
collect_tree /etc/nginx
collect_tree /etc/phpmyadmin
collect_tree /etc/systemd/system

env_value() {
  local key="$1"
  awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); print; exit }' "$APP_DIR/backend/.env" 2>/dev/null || true
}

changed=0
declare -a changed_files=()

backup_file() {
  local src="$1" dest
  dest="$backup_root$src"
  mkdir -p "$(dirname "$dest")"
  cp -a -- "$src" "$dest"
}

for file in "${files[@]}"; do
  if grep -IqE "(^|[^0-9.])${old_ip_ere}([^0-9.]|$)" "$file"; then
    backup_file "$file"
    perl -0pi -e "s/(?<![0-9.])\\Q$old_ip\\E(?![0-9.])/$new_ip/g" "$file"
    changed_files+=("$file")
    ((++changed))
  fi
done

sync_panel_settings_json() {
  local settings_file="$BPANEL_DATA_DIR/panel-settings.json" panel_url current_panel_url
  [[ -f "$settings_file" ]] || return 0
  panel_url="$(env_value PANEL_URL)"
  [[ -n "$panel_url" ]] || return 0

  current_panel_url="$(
    python3 - "$settings_file" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        print(data.get("panel_url", ""))
except Exception:
    pass
PY
  )"
  if [[ "$current_panel_url" == "$panel_url" ]]; then
    return 0
  fi

  backup_file "$settings_file"
  python3 - "$settings_file" "$panel_url" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
panel_url = sys.argv[2]
try:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        data = {}
except Exception:
    data = {}
data["panel_url"] = panel_url
path.write_text(json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  changed_files+=("$settings_file")
  ((++changed))
}

sync_login_info_url() {
  local login_file="$LOGIN_FILE" panel_url current_login_url
  [[ -f "$login_file" ]] || return 0
  panel_url="$(env_value PANEL_URL)"
  [[ -n "$panel_url" ]] || return 0

  current_login_url="$(awk -F': ' '/^Panel URL: / {print $2; exit}' "$login_file" 2>/dev/null || true)"
  if [[ "$current_login_url" == "$panel_url" ]]; then
    return 0
  fi

  backup_file "$login_file"
  python3 - "$login_file" "$panel_url" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
panel_url = sys.argv[2]
try:
    lines = path.read_text(encoding="utf-8").splitlines()
except Exception:
    lines = []

updated = False
for idx, line in enumerate(lines):
    if line.startswith("Panel URL: "):
        lines[idx] = f"Panel URL: {panel_url}"
        updated = True
        break

if not updated:
    lines.insert(0, f"Panel URL: {panel_url}")

path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
  changed_files+=("$login_file")
  ((++changed))
}

sync_panel_settings_json
sync_login_info_url

restart_if_loaded() {
  local unit="$1"
  if command -v systemctl >/dev/null 2>&1 && systemctl show -p LoadState --value "$unit" 2>/dev/null | grep -qx loaded; then
    if ! systemctl restart "$unit" >/dev/null 2>&1; then
      warn "Could not restart $unit"
    fi
  fi
}

reload_systemd() {
  if command -v systemctl >/dev/null 2>&1; then
    if ! systemctl daemon-reload >/dev/null 2>&1; then
      warn "Could not reload systemd units"
    fi
  fi
}

reload_nginx() {
  if command -v nginx >/dev/null 2>&1 && command -v systemctl >/dev/null 2>&1 && systemctl show -p LoadState --value nginx 2>/dev/null | grep -qx loaded; then
    if nginx -t >/dev/null 2>&1; then
      if ! systemctl reload nginx >/dev/null 2>&1; then
        warn "Could not reload nginx"
      fi
    else
      warn "nginx -t failed; please review the edited config files manually"
    fi
  fi
}

if (( changed > 0 )); then
  reload_systemd
  restart_if_loaded bpanel-api
  reload_nginx
fi

echo "Updated $changed file(s)."
if (( changed > 0 )); then
  echo "Backup: $backup_root"
  printf 'Changed files:\n'
  printf '  %s\n' "${changed_files[@]}"
else
  echo "No matching BPanel files contained $old_ip."
  echo "Backup: $backup_root (no files were changed)"
fi
