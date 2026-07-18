#!/usr/bin/env bash
# /usr/local/sbin/bpanel-helper
#
# Root-privileged trampoline for the BPanel API daemon.
# This is the ONLY code that runs as root for the daemon.
# Installed by install.sh as root:root mode 0750, callable only by user
# 'bpanel' through sudo (see /etc/sudoers.d/bpanel).
#
# Every operation here is the trust boundary. Validate aggressively.

set -euo pipefail

if [[ "${SUDO_USER:-}" != "bpanel" ]]; then
  echo "bpanel-helper must be invoked by user 'bpanel' via sudo" >&2
  exit 2
fi

# Reset PATH so an attacker cannot ship a shadow binary in bpanel's PATH.
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

ALLOWED_SERVICES=(nginx mariadb redis-server php8.3-fpm php8.4-fpm bpanel-api)
ALLOWED_ACTIONS=(start stop restart reload status is-active is-enabled)
HOME_ROOT="/home"
NGINX_CONF_DIR="/etc/nginx/conf.d"
PHP_CONF_DIRS=(/etc/php/{5.6,7.4,8.0,8.1,8.2,8.3,8.4,8.5}/fpm/conf.d)
BPANEL_SITES_GROUP="bpanel-sites"
BPANEL_SFTP_GROUP="bpanel-sftp"
APP_DIR="/opt/bpanel"
ENV_FILE="${APP_DIR}/backend/.env"
DEFAULT_PANEL_PORT="2222"
SOURCE_DIR="/opt/bpanel-source"
UPDATE_SCRIPT="/usr/local/sbin/bpanel-update"
BPANEL_DATA_DIR="/var/lib/bpanel"
FIREWALL_BLOCKLIST_URLS="${BPANEL_DATA_DIR}/firewall-blocklists.urls"
FIREWALL_BLOCKLIST_WORK="${BPANEL_DATA_DIR}/firewall-blocklists.current"
NGINX_BLOCKLIST_DIR="/etc/nginx/bpanel"
NGINX_BLOCKLIST_CONF="/etc/nginx/conf.d/bpanel-ip-blocklist.conf"
NGINX_BLOCKLIST_RULES="${NGINX_BLOCKLIST_DIR}/ip-blocklist-geo.conf"
NGINX_BLOCKLIST_SERVER_CONF="${NGINX_BLOCKLIST_DIR}/ip-blocklist-server.conf"
NGINX_CUSTOM_DIR="${NGINX_BLOCKLIST_DIR}/custom"
NGINX_HTTP_FLOOD_CONF="/etc/nginx/conf.d/00-bpanel-http-flood.conf"
NGINX_HTTP_FLOOD_LEGACY_CONF="/etc/nginx/conf.d/bpanel-http-flood.conf"
NGINX_HTTP_FLOOD_ZONES="${NGINX_BLOCKLIST_DIR}/http-flood-zones.conf"
NGINX_HTTP_FLOOD_SERVER_CONF="${NGINX_BLOCKLIST_DIR}/http-flood-server.conf"
PHP_FPM_DEFAULT_WORKER_MB=128
PHP_FPM_DEFAULT_REQUEST_TERMINATE_TIMEOUT=300
MARIADB_TUNING_CONF="/etc/mysql/mariadb.conf.d/90-bpanel-tuning.cnf"

deny() { echo "bpanel-helper: $*" >&2; exit 1; }

ensure_bpanel_data_dir() {
  install -d -o bpanel -g bpanel -m 0750 "$BPANEL_DATA_DIR"
}

ensure_nginx_conf_dir_writable() {
  install -d -o root -g root -m 0755 "$NGINX_BLOCKLIST_DIR"
  if getent group bpanel >/dev/null 2>&1; then
    install -d -o root -g bpanel -m 2775 "$NGINX_CONF_DIR"
    install -d -o root -g bpanel -m 2775 "$NGINX_CUSTOM_DIR"
    chmod g+s "$NGINX_CONF_DIR" 2>/dev/null || true
    chmod g+s "$NGINX_CUSTOM_DIR" 2>/dev/null || true
  else
    install -d -o root -g root -m 0755 "$NGINX_CONF_DIR"
    install -d -o root -g root -m 0755 "$NGINX_CUSTOM_DIR"
  fi
}

file_has_nul() {
  local path="$1"
  python3 - "$path" <<'PY'
import sys

with open(sys.argv[1], "rb") as handle:
    data = handle.read()
sys.exit(0 if b"\0" in data else 1)
PY
}

env_get() {
  local key="$1"
  [[ -f "$ENV_FILE" ]] || return 0
  awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); print; exit }' "$ENV_FILE"
}

env_set() {
  local key="$1" value="$2" escaped
  [[ -f "$ENV_FILE" ]] || deny "$ENV_FILE not found"
  escaped="$(printf '%s' "$value" | sed -e 's/[&|]/\\&/g')"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${escaped}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >>"$ENV_FILE"
  fi
}

detect_ip() {
  hostname -I 2>/dev/null | awk '{print $1}' || true
}

is_ipv4() {
  local value="$1" part
  local -a parts
  [[ "$value" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
  IFS=. read -r -a parts <<<"$value"
  for part in "${parts[@]}"; do
    (( 10#$part >= 0 && 10#$part <= 255 )) || return 1
  done
}

is_domain() {
  [[ "$1" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]]
}

require_panel_scheme() {
  [[ "$1" == "http" || "$1" == "https" ]] || deny "invalid panel scheme: $1"
}

require_panel_host() {
  local host="$1"
  if is_domain "$host" || is_ipv4 "$host" || [[ "$host" == "localhost" ]]; then
    return 0
  fi
  deny "invalid panel host: $host"
}

allow_panel_port() {
  local port="$1"
  if command -v ufw >/dev/null 2>&1; then
    ufw_panel_allow_port "$port"
  fi
}

ufw_commented_rule_numbers() {
  local comment="$1" target="${2:-}"
  ufw status numbered 2>/dev/null \
    | awk -v comment="$comment" -v target="$target" '
        index($0, comment) {
          line = $0
          if (!match(line, /^\[[[:space:]]*[0-9]+\]/)) {
            next
          }
          number = substr(line, RSTART, RLENGTH)
          gsub(/[^0-9]/, "", number)
          if (target == "") {
            print number
            next
          }
          sub(/^\[[[:space:]]*[0-9]+\][[:space:]]*/, "", line)
          split(line, parts, /[[:space:]]+ALLOW[[:space:]]+/)
          rule_target = parts[1]
          if (rule_target == target || rule_target == target " (v6)") {
            print number
          }
        }
      '
}

ufw_delete_commented_rules() {
  local comment="$1" target="${2:-}" number
  while read -r number; do
    [[ -n "$number" ]] || continue
    ufw --force delete "$number" >/dev/null 2>&1 || true
  done < <(ufw_commented_rule_numbers "$comment" "$target" | sort -rn)
}

ufw_panel_allow_port() {
  local port="$1"
  require_port "$port"
  ufw_delete_commented_rules "bpanel:PanelZone" "${port}/tcp"
  ufw insert 1 allow "${port}/tcp" comment "bpanel:PanelZone" >/dev/null 2>&1 \
    || ufw insert 1 allow "${port}/tcp" >/dev/null 2>&1 \
    || ufw allow "${port}/tcp" >/dev/null 2>&1 \
    || true
}

ufw_panel_allow_app() {
  local app="$1"
  [[ "$app" == "OpenSSH" || "$app" == "Nginx Full" ]] || deny "invalid panel firewall app: $app"
  ufw_delete_commented_rules "bpanel:PanelZone" "$app"
  ufw insert 1 allow "$app" comment "bpanel:PanelZone" >/dev/null 2>&1 \
    || ufw insert 1 allow "$app" >/dev/null 2>&1 \
    || ufw allow "$app" >/dev/null 2>&1 \
    || true
}

require_time_hhmm() {
  local value="$1" hour minute
  [[ "$value" =~ ^[0-9]{2}:[0-9]{2}$ ]] || deny "invalid time: $value"
  hour="${value%%:*}"; minute="${value##*:}"
  (( 10#$hour >= 0 && 10#$hour <= 23 )) || deny "invalid hour: $hour"
  (( 10#$minute >= 0 && 10#$minute <= 59 )) || deny "invalid minute: $minute"
}

schedule_panel_restart() {
  local unit
  systemctl daemon-reload || true
  if command -v systemd-run >/dev/null 2>&1; then
    unit="bpanel-api-delayed-restart-$(date +%s)"
    systemd-run --unit="$unit" --on-active=2s /bin/systemctl restart bpanel-api >/dev/null 2>&1 || true
  else
    (sleep 2; systemctl restart bpanel-api >/dev/null 2>&1 || true) >/dev/null 2>&1 &
  fi
}

refresh_tools_nginx() {
  local port cert key domain host api_scheme tools_scheme pma_secure ssl_block php_version
  port="$(env_get PANEL_PORT)"; port="${port:-$DEFAULT_PANEL_PORT}"
  cert="$(env_get PANEL_SSL_CERT)"; key="$(env_get PANEL_SSL_KEY)"
  domain="$(env_get PANEL_DOMAIN)"; host="${domain:-$(detect_ip)}"
  php_version="${PHP_DEFAULT:-8.4}"
  api_scheme="http"; tools_scheme="http"; pma_secure="false"; ssl_block=""
  if [[ -n "$cert" && -n "$key" && -f "$cert" && -f "$key" ]]; then
    api_scheme="https"; tools_scheme="https"; pma_secure="true"
    printf -v ssl_block '\n    listen 443 ssl default_server;\n    ssl_certificate %s;\n    ssl_certificate_key %s;' "$cert" "$key"
  fi
  rm -f /etc/nginx/sites-enabled/default /etc/nginx/conf.d/default.conf 2>/dev/null || true
  ensure_nginx_conf_dir_writable
  firewall_blocklist_write_nginx_conf 2>/dev/null || true
  write_http_flood_nginx_conf 2>/dev/null || true
  cat >/etc/nginx/conf.d/00-bpanel-tools.conf <<NGINX
server {
    listen 80 default_server;${ssl_block}
    server_name _;
    include /etc/nginx/bpanel/ip-blocklist-server.conf;
    client_max_body_size 1100M;
    location = /phpmyadmin { return 301 /phpmyadmin/; }
    location /phpmyadmin/ { alias /usr/share/phpmyadmin/; index index.php; try_files \$uri \$uri/ =404; }
    location ~ ^/phpmyadmin/(.+\.php)$ { alias /usr/share/phpmyadmin/\$1; include fastcgi_params; fastcgi_param SCRIPT_FILENAME /usr/share/phpmyadmin/\$1; fastcgi_param SCRIPT_NAME /phpmyadmin/\$1; fastcgi_pass unix:/run/php/php${php_version}-fpm.sock; fastcgi_read_timeout 300; }
}
NGINX
  sed -i -E "/api\/databases\/phpmyadmin-sso/s#'[^']+/api/databases/phpmyadmin-sso/'#'${api_scheme}://127.0.0.1:${port}/api/databases/phpmyadmin-sso/'#" /usr/share/phpmyadmin/bpanel-signon.php 2>/dev/null || true
  sed -i -E "s#('secure' => )(true|false)#\1${pma_secure}#" /etc/phpmyadmin/conf.d/bpanel-signon.php /usr/share/phpmyadmin/bpanel-signon.php 2>/dev/null || true
  [[ -n "$host" ]] && sed -i -E "/PmaAbsoluteUri/s#'https?://[^']+/phpmyadmin/'#'${tools_scheme}://${host}/phpmyadmin/'#" /etc/phpmyadmin/conf.d/bpanel-signon.php 2>/dev/null || true
  nginx -t
  systemctl reload nginx || true
}

configure_unattended_upgrades() {
  local enabled="$1" mode="$2" reboot="$3" origins
  [[ "$enabled" == "on" || "$enabled" == "off" ]] || deny "enabled must be on/off"
  [[ "$mode" == "security" || "$mode" == "all" ]] || deny "mode must be security/all"
  [[ "$reboot" == "on" || "$reboot" == "off" ]] || deny "auto reboot must be on/off"

  DEBIAN_FRONTEND=noninteractive apt-get update --allow-releaseinfo-change
  DEBIAN_FRONTEND=noninteractive apt-get install -y unattended-upgrades apt-listchanges

  if [[ "$enabled" == "off" ]]; then
    cat >/etc/apt/apt.conf.d/20auto-upgrades <<'APT'
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Unattended-Upgrade "0";
APT
    systemctl disable --now unattended-upgrades.service 2>/dev/null || true
    echo "OS auto updates disabled"
    return 0
  fi

  origins='        "${distro_id}:${distro_codename}-security";'
  if [[ "$mode" == "all" ]]; then
    origins='        "${distro_id}:${distro_codename}";
        "${distro_id}:${distro_codename}-updates";
        "${distro_id}:${distro_codename}-security";'
  fi

  cat >/etc/apt/apt.conf.d/20auto-upgrades <<'APT'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
APT
  cat >/etc/apt/apt.conf.d/51bpanel-unattended-upgrades <<APT
Unattended-Upgrade::Allowed-Origins {
${origins}
};
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "$([[ "$reboot" == "on" ]] && echo true || echo false)";
Unattended-Upgrade::Automatic-Reboot-Time "03:00";
APT
  systemctl enable --now unattended-upgrades.service 2>/dev/null || true
  echo "OS auto updates enabled (${mode}, reboot=${reboot})"
}

run_os_update_now() {
  export DEBIAN_FRONTEND=noninteractive APT_LISTCHANGES_FRONTEND=none
  apt-get update --allow-releaseinfo-change
  apt-get \
    -o Dpkg::Options::=--force-confdef \
    -o Dpkg::Options::=--force-confold \
    upgrade -y
}

run_os_update() {
  local unit="bpanel-os-update"
  if systemctl is-active --quiet "${unit}.service"; then
    echo "OS update is already running: ${unit}.service"
    return 0
  fi
  if command -v systemd-run >/dev/null 2>&1; then
    systemd-run \
      --unit="$unit" \
      --collect \
      --description="Update OS packages for BPanel" \
      /bin/bash -lc 'export DEBIAN_FRONTEND=noninteractive APT_LISTCHANGES_FRONTEND=none; apt-get update --allow-releaseinfo-change; apt-get -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold upgrade -y'
    echo "OS update started: ${unit}.service"
    echo "Check progress: journalctl -u ${unit}.service -f"
    return 0
  fi
  nohup /bin/bash -lc 'export DEBIAN_FRONTEND=noninteractive APT_LISTCHANGES_FRONTEND=none; apt-get update --allow-releaseinfo-change; apt-get -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold upgrade -y' \
    >/var/log/bpanel-os-update.log 2>&1 &
  echo "OS update started in background. Log: /var/log/bpanel-os-update.log"
}

write_panel_auto_update_timer() {
  local enabled="$1" time_value="$2"
  [[ "$enabled" == "on" || "$enabled" == "off" ]] || deny "enabled must be on/off"
  require_time_hhmm "$time_value"
  if [[ "$enabled" == "off" ]]; then
    systemctl disable --now bpanel-auto-update.timer 2>/dev/null || true
    rm -f /etc/systemd/system/bpanel-auto-update.service /etc/systemd/system/bpanel-auto-update.timer
    systemctl daemon-reload
    echo "Panel auto update disabled"
    return 0
  fi
  [[ -f "$UPDATE_SCRIPT" ]] || deny "missing $UPDATE_SCRIPT"
  cat >/etc/systemd/system/bpanel-auto-update.service <<SERVICE
[Unit]
Description=Update BPanel from GitHub
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Environment=SOURCE_DIR=${SOURCE_DIR}
Environment=APP_DIR=${APP_DIR}
Environment=REPO_URL=${REPO_URL:-https://github.com/BNIX-VN/bpanel.git}
Environment=GIT_REMOTE=${GIT_REMOTE:-origin}
Environment=UPDATE_CHANNEL=${UPDATE_CHANNEL:-release}
Environment=BRANCH=${BRANCH:-main}
Environment=RELEASE_TAG=${RELEASE_TAG:-}
Environment=RELEASE_PATTERN=${RELEASE_PATTERN:-v[0-9]*.[0-9]*.[0-9]*}
Environment=SKIP_PULL=${SKIP_PULL:-false}
ExecStart=/bin/bash ${UPDATE_SCRIPT}
SERVICE
  cat >/etc/systemd/system/bpanel-auto-update.timer <<TIMER
[Unit]
Description=Run BPanel auto update daily

[Timer]
OnCalendar=*-*-* ${time_value}:00
Persistent=true
RandomizedDelaySec=15m

[Install]
WantedBy=timers.target
TIMER
  systemctl daemon-reload
  systemctl enable --now bpanel-auto-update.timer
  echo "Panel auto update enabled at ${time_value}"
}

run_panel_update() {
  [[ -f "$UPDATE_SCRIPT" ]] || deny "missing $UPDATE_SCRIPT"
  local unit="bpanel-panel-update"
  if systemctl is-active --quiet "${unit}.service"; then
    echo "Panel update is already running: ${unit}.service"
    return 0
  fi
  if command -v systemd-run >/dev/null 2>&1; then
    systemd-run \
      --unit="$unit" \
      --collect \
      --description="Update BPanel from GitHub" \
      --property="Environment=SOURCE_DIR=${SOURCE_DIR}" \
      --property="Environment=APP_DIR=${APP_DIR}" \
      --property="Environment=REPO_URL=${REPO_URL:-https://github.com/BNIX-VN/bpanel.git}" \
      --property="Environment=GIT_REMOTE=${GIT_REMOTE:-origin}" \
      --property="Environment=UPDATE_CHANNEL=${UPDATE_CHANNEL:-release}" \
      --property="Environment=BRANCH=${BRANCH:-main}" \
      --property="Environment=RELEASE_TAG=${RELEASE_TAG:-}" \
      --property="Environment=RELEASE_PATTERN=${RELEASE_PATTERN:-v[0-9]*.[0-9]*.[0-9]*}" \
      --property="Environment=SKIP_PULL=${SKIP_PULL:-false}" \
      /bin/bash "$UPDATE_SCRIPT"
    echo "Panel update started: ${unit}.service"
    echo "Check progress: journalctl -u ${unit}.service -f"
    return 0
  fi
  nohup env \
    SOURCE_DIR="$SOURCE_DIR" \
    APP_DIR="$APP_DIR" \
    REPO_URL="${REPO_URL:-https://github.com/BNIX-VN/bpanel.git}" \
    GIT_REMOTE="${GIT_REMOTE:-origin}" \
    UPDATE_CHANNEL="${UPDATE_CHANNEL:-release}" \
    BRANCH="${BRANCH:-main}" \
    RELEASE_TAG="${RELEASE_TAG:-}" \
    RELEASE_PATTERN="${RELEASE_PATTERN:-v[0-9]*.[0-9]*.[0-9]*}" \
    SKIP_PULL="${SKIP_PULL:-false}" \
    /bin/bash "$UPDATE_SCRIPT" \
    >/var/log/bpanel-panel-update.log 2>&1 &
  echo "Panel update started in background. Log: /var/log/bpanel-panel-update.log"
}

write_modsec_base_conf() {
  install -d -o root -g root -m 0755 /etc/nginx/modsec /etc/nginx/modsec/sites
  {
    [[ -f /etc/modsecurity/modsecurity.conf ]] && echo "Include /etc/modsecurity/modsecurity.conf"
    echo "SecRuleEngine On"
    echo "SecRequestBodyAccess Off"
  } >/etc/nginx/modsec/bpanel-base.conf
}

write_modsec_main_conf() {
  write_waf_default_rules
  write_modsec_base_conf
  touch /etc/nginx/modsec/bpanel-custom.conf
  {
    echo "Include /etc/nginx/modsec/bpanel-base.conf"
    echo "Include /etc/nginx/modsec/bpanel-default.conf"
    echo "Include /etc/nginx/modsec/bpanel-custom.conf"
  } >/etc/nginx/modsec/bpanel-main.conf
}

write_waf_default_rules() {
  install -d -o root -g root -m 0755 /etc/nginx/modsec
  cat >/etc/nginx/modsec/bpanel-default.conf <<'RULES'
# BPanel default WAF rules: lightweight WordPress, Laravel, and PHP probes only.
SecRule REQUEST_URI "@rx (?i)(?:/\.env(?:\.|$)|/\.user\.ini(?:\.|$)|/\.git/|/composer\.(?:json|lock)(?:$|[?])|/(?:phpinfo|info)\.php(?:$|[?])|/(?:config|database|db)\.php\.(?:bak|old|save|txt)(?:$|[?]))" "id:1001301,phase:1,deny,status:403,log,msg:'BPanel blocked PHP sensitive file probe'"
SecRule REQUEST_URI|ARGS "@rx (?i)(?:\.\./|\.\.\\|%2e%2e%2f|%252e%252e%252f)" "id:1001302,phase:2,deny,status:403,log,msg:'BPanel blocked PHP path traversal'"
SecRule REQUEST_URI "@rx (?i)(?:/(?:c99|r57|shell|cmd|wso)\.php(?:$|[?])|/vendor/phpunit/phpunit/src/Util/PHP/eval-stdin\.php(?:$|[?]))" "id:1001303,phase:1,deny,status:403,log,msg:'BPanel blocked PHP runtime probe'"
SecRule REQUEST_URI "@rx (?i)(?:/\.env(?:\.|$)|/artisan(?:$|[?])|/server\.php(?:$|[?])|/storage/logs/[^?]*\.log(?:$|[?])|/bootstrap/cache/[^?]*\.php(?:$|[?]))" "id:1001201,phase:1,deny,status:403,log,msg:'BPanel blocked Laravel sensitive path'"
SecRule REQUEST_URI "@rx (?i)(?:/_ignition/execute-solution(?:$|[?]))" "id:1001202,phase:1,deny,status:403,log,msg:'BPanel blocked Laravel Ignition RCE probe'"
SecRule REQUEST_URI "@rx (?i)(?:/wp-config\.php(?:\.|$|[?])|/wp-content/(?:uploads|cache|upgrade)/[^?]*\.php(?:$|[?])|/wp-admin/includes/[^?]*\.php(?:$|[?])|/wp-includes/[^?]*\.php(?:$|[?]))" "id:1001101,phase:1,deny,status:403,log,msg:'BPanel blocked WordPress sensitive path'"
SecRule ARGS:author "@rx ^[0-9]+$" "id:1001103,phase:2,deny,status:403,log,msg:'BPanel blocked WordPress author enumeration'"
SecRule REQUEST_URI "@rx (?i)(?:/wp-admin/install\.php(?:$|[?])|/wp-admin/setup-config\.php(?:$|[?]))" "id:1001104,phase:1,deny,status:403,log,msg:'BPanel blocked WordPress installer probe'"
RULES
}

save_waf_custom_rules() {
  install -d -o root -g root -m 0755 /etc/nginx/modsec
  write_waf_default_rules
  local tmp
  tmp="$(mktemp)"
  cat >"$tmp"
  if file_has_nul "$tmp"; then
    rm -f "$tmp"
    deny "WAF rules cannot contain NUL bytes"
  fi
  if [[ $(wc -c <"$tmp") -gt 65536 ]]; then
    rm -f "$tmp"
    deny "WAF custom rules must be 64 KB or smaller"
  fi
  install -m 0644 -o root -g root "$tmp" /etc/nginx/modsec/bpanel-custom.conf
  rm -f "$tmp"
  write_modsec_main_conf
  nginx -t
  systemctl reload nginx
  echo "WAF custom rules saved"
}

save_waf_site_rules() {
  local domain="$1" tmp target backup=""
  require_domain "$domain"
  install -d -o root -g root -m 0755 /etc/nginx/modsec /etc/nginx/modsec/sites
  write_modsec_base_conf
  tmp="$(mktemp)"
  cat >"$tmp"
  if file_has_nul "$tmp"; then
    rm -f "$tmp"
    deny "WAF rules cannot contain NUL bytes"
  fi
  if [[ $(wc -c <"$tmp") -gt 163840 ]]; then
    rm -f "$tmp"
    deny "WAF site rules must be 160 KB or smaller"
  fi
  target="/etc/nginx/modsec/sites/${domain}.conf"
  if [[ -f "$target" ]]; then
    backup="${target}.bak.$(date +%s)"
    cp "$target" "$backup"
  fi
  install -m 0644 -o root -g root "$tmp" "$target"
  rm -f "$tmp"
  if ! nginx -t; then
    if [[ -n "$backup" && -f "$backup" ]]; then
      mv -f "$backup" "$target"
    else
      rm -f "$target"
    fi
    deny "Nginx rejected WAF site rules"
  fi
  rm -f "$backup" 2>/dev/null || true
  systemctl reload nginx
  echo "WAF site rules saved: ${domain}"
}

install_waf_engine() {
  export DEBIAN_FRONTEND=noninteractive
  if ! dpkg -s libnginx-mod-http-modsecurity >/dev/null 2>&1; then
    apt-get update --allow-releaseinfo-change
    apt-get install -y libnginx-mod-http-modsecurity modsecurity-crs libmodsecurity3 || \
      apt-get install -y libnginx-mod-http-modsecurity libmodsecurity3
  fi
  install -d -o root -g root -m 0755 /etc/nginx/modsec /etc/nginx/modsec/sites
  write_waf_default_rules
  touch /etc/nginx/modsec/bpanel-custom.conf
  if [[ -f /etc/modsecurity/modsecurity.conf-recommended && ! -f /etc/modsecurity/modsecurity.conf ]]; then
    cp /etc/modsecurity/modsecurity.conf-recommended /etc/modsecurity/modsecurity.conf
  fi
  if [[ -f /etc/modsecurity/modsecurity.conf ]]; then
    sed -i -E 's/^SecRuleEngine .*/SecRuleEngine On/' /etc/modsecurity/modsecurity.conf
  fi
  if [[ -f /usr/share/nginx/modules-available/mod-http-modsecurity.conf ]]; then
    install -d /etc/nginx/modules-enabled
    ln -sfn /usr/share/nginx/modules-available/mod-http-modsecurity.conf /etc/nginx/modules-enabled/50-mod-http-modsecurity.conf
  fi
  write_modsec_main_conf
  write_http_flood_nginx_conf
  nginx -t
  systemctl reload nginx
  echo "WAF engine installed with BPanel lightweight WordPress/Laravel/PHP rules."
}

install_php_version() {
  local version="$1"
  export DEBIAN_FRONTEND=noninteractive
  require_php_version "$version"
  if [[ -f /etc/php/"$version"/fpm/php-fpm.conf ]]; then
    echo "PHP $version is already installed; ensuring BPanel extension set..."
  fi
  if ! apt-cache show "php${version}-fpm" >/dev/null 2>&1; then
    if ! grep -q "ondrej/php" /etc/apt/sources.list.d/*.list 2>/dev/null; then
      echo "Adding ondrej/php PPA for PHP $version..."
      apt-get update --allow-releaseinfo-change
      apt-get install -y software-properties-common || true
      add-apt-repository -y ppa:ondrej/php 2>/dev/null || true
    fi
    apt-get update --allow-releaseinfo-change
  fi
  echo "Installing PHP $version..."
  local packages=(
    "php${version}-fpm"
    "php${version}-cli"
    "php${version}-mysql"
    "php${version}-sqlite3"
    "php${version}-curl"
    "php${version}-gd"
    "php${version}-mbstring"
    "php${version}-xml"
    "php${version}-zip"
    "php${version}-opcache"
    "php${version}-intl"
    "php${version}-bcmath"
    "php${version}-redis"
    "php${version}-imagick"
  )
  local available_packages=() missing_packages=() package
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
  [[ ${#available_packages[@]} -gt 0 ]] || deny "No package found for PHP ${version}"
  apt-get install -y "${available_packages[@]}" || { echo "Failed to install PHP $version"; return 1; }
  install_ioncube_loader "$version"
  # Enable and start PHP-FPM
  systemctl enable "php${version}-fpm" 2>/dev/null || true
  systemctl start "php${version}-fpm" 2>/dev/null || true
  echo "PHP $version installed successfully"
}

install_ioncube_loader() {
  local version="$1" arch url tmp archive loader target_dir target loader_ini_dir
  require_php_version "$version"
  arch="$(dpkg --print-architecture 2>/dev/null || uname -m)"
  case "$arch" in
    amd64|x86_64)
      url="https://downloads.ioncube.com/loader_downloads/ioncube_loaders_lin_x86-64.tar.gz"
      ;;
    *)
      echo "Skipping ionCube Loader: unsupported architecture ${arch}"
      return 0
      ;;
  esac

  apt-get install -y ca-certificates curl tar >/dev/null
  tmp="$(mktemp -d)" || deny "cannot create ionCube temporary directory"
  archive="${tmp}/ioncube_loaders.tar.gz"
  if ! curl -fsSL --connect-timeout 10 --max-time 300 "$url" -o "$archive"; then
    rm -rf -- "$tmp"
    deny "failed to download ionCube Loader"
  fi
  if ! tar -xzf "$archive" -C "$tmp"; then
    rm -rf -- "$tmp"
    deny "failed to unpack ionCube Loader"
  fi
  loader="${tmp}/ioncube/ioncube_loader_lin_${version}.so"
  if [[ ! -f "$loader" ]]; then
    rm -rf -- "$tmp"
    echo "Skipping ionCube Loader: no loader found for PHP ${version}"
    return 0
  fi

  target_dir="/usr/local/ioncube"
  target="${target_dir}/ioncube_loader_lin_${version}.so"
  install -d -o root -g root -m 0755 "$target_dir"
  install -m 0644 -o root -g root "$loader" "$target"
  rm -rf -- "$tmp"

  for loader_ini_dir in /etc/php/"$version"/cli/conf.d /etc/php/"$version"/fpm/conf.d; do
    [[ -d "$loader_ini_dir" ]] || continue
    printf 'zend_extension=%s\n' "$target" >"${loader_ini_dir}/00-ioncube.ini"
    chown root:root "${loader_ini_dir}/00-ioncube.ini"
    chmod 0644 "${loader_ini_dir}/00-ioncube.ini"
  done

  if command -v "php${version}" >/dev/null 2>&1; then
    if ! "php${version}" -v 2>&1 | grep -qi 'ionCube'; then
      rm -f /etc/php/"$version"/cli/conf.d/00-ioncube.ini /etc/php/"$version"/fpm/conf.d/00-ioncube.ini
      deny "ionCube Loader failed to load for PHP ${version}"
    fi
  fi
  echo "ionCube Loader enabled for PHP ${version}"
}

validate_php_config_file() {
  local file="$1" line key value
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" ]] && continue
    case "$line" in *$'\r'*) deny "PHP config contains a carriage return" ;; esac
    [[ "$line" == *"="* ]] || deny "invalid PHP config line: $line"
    key="$(printf '%s' "${line%%=*}" | xargs)"
    value="$(printf '%s' "${line#*=}" | xargs)"
    case "$key" in
      display_errors)
        [[ "$value" == "On" || "$value" == "Off" ]] || deny "invalid display_errors value"
        ;;
      memory_limit|upload_max_filesize|post_max_size)
        [[ "$value" =~ ^[0-9]{1,6}[KMG]?$ ]] || deny "invalid PHP size value for $key"
        ;;
      max_execution_time|max_input_time)
        [[ "$value" =~ ^[0-9]{1,4}$ ]] || deny "invalid integer value for $key"
        (( 10#$value >= 1 && 10#$value <= 3600 )) || deny "$key out of range"
        ;;
      max_input_vars)
        [[ "$value" =~ ^[0-9]{1,7}$ ]] || deny "invalid integer value for $key"
        (( 10#$value >= 100 && 10#$value <= 1000000 )) || deny "max_input_vars out of range"
        ;;
      *)
        deny "unsupported PHP config directive: $key"
        ;;
    esac
  done <"$file"
}

write_php_config() {
  local version="$1" conf_dir target tmp size
  require_php_version "$version"
  conf_dir="/etc/php/${version}/fpm/conf.d"
  target="${conf_dir}/99-bpanel.ini"
  [[ -d "$conf_dir" ]] || deny "PHP FPM config directory not found: $conf_dir"
  tmp="$(mktemp "${conf_dir}/.99-bpanel.ini.XXXXXX")" || deny "cannot create temporary PHP config"
  if ! cat >"$tmp"; then
    rm -f -- "$tmp"
    deny "failed to read PHP config"
  fi
  size="$(wc -c <"$tmp" | tr -d '[:space:]')"
  if (( size <= 0 || size > 8192 )); then
    rm -f -- "$tmp"
    deny "PHP config size out of range"
  fi
  validate_php_config_file "$tmp"
  chown root:root "$tmp"
  chmod 0644 "$tmp"
  mv -f -- "$tmp" "$target"
  systemctl restart "php${version}-fpm"
  echo "PHP ${version} config updated: ${target}"
}

waf_status() {
  echo "ModSecurity module:"
  if nginx -V 2>&1 | grep -qi modsecurity || [[ -e /etc/nginx/modules-enabled/50-mod-http-modsecurity.conf ]]; then
    echo "  installed"
  else
    echo "  not installed"
  fi
  echo "Rules file:"
  [[ -f /etc/nginx/modsec/bpanel-main.conf ]] && echo "  /etc/nginx/modsec/bpanel-main.conf" || echo "  missing"
  echo "Default rules:"
  [[ -f /etc/nginx/modsec/bpanel-default.conf ]] && echo "  /etc/nginx/modsec/bpanel-default.conf" || echo "  missing"
  echo "Custom rules:"
  [[ -f /etc/nginx/modsec/bpanel-custom.conf ]] && echo "  /etc/nginx/modsec/bpanel-custom.conf" || echo "  missing"
  echo "Managed profile:"
  echo "  BPanel built-in lightweight WordPress/Laravel/PHP rules"
  echo "Timers:"
  systemctl list-timers bpanel-auto-update.timer apt-daily-upgrade.timer --no-pager 2>/dev/null || true
}

audit_log() {
  local quoted="" arg
  for arg in "$@"; do
    printf -v quoted '%s %q' "$quoted" "$arg"
  done
  if command -v logger >/dev/null 2>&1; then
    logger -t bpanel-helper -- "cmd=${cmd:-unknown}${quoted}"
  fi
}

run_ufw_ip_rule() {
  local action="$1" network="$2" port="${3:-}" protocol="${4:-tcp}"
  require_ip_or_cidr "$network"
  case "$action" in
    allow|deny) ;;
    *) deny "invalid ufw action: $action" ;;
  esac
  if [[ -z "$port" ]]; then
    ufw "$action" from "$network" comment "bpanel:UserZone" \
      || ufw "$action" from "$network"
    return 0
  fi
  require_port "$port"; require_proto "$protocol"
  ufw "$action" from "$network" to any port "$port" proto "$protocol" comment "bpanel:UserZone" \
    || ufw "$action" from "$network" to any port "$port" proto "$protocol"
}

require_url() {
  local value="$1"
  [[ "$value" =~ ^https?://[^[:space:]]+$ ]] || deny "invalid URL: $value"
}

firewall_blocklist_urls() {
  ensure_bpanel_data_dir
  touch "$FIREWALL_BLOCKLIST_URLS"
  sed '/^[[:space:]]*$/d' "$FIREWALL_BLOCKLIST_URLS" | sort -u
}

firewall_blocklist_write_timer() {
  cat >/etc/systemd/system/bpanel-firewall-blocklist.service <<SERVICE
[Unit]
Description=Refresh BPanel Nginx IP blocklists
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Environment=SUDO_USER=bpanel
ExecStart=/usr/local/sbin/bpanel-helper nginx-blocklist-run
SERVICE
  cat >/etc/systemd/system/bpanel-firewall-blocklist.timer <<TIMER
[Unit]
Description=Refresh BPanel Nginx IP blocklists daily

[Timer]
OnCalendar=*-*-* 01:00:00
Persistent=true

[Install]
WantedBy=timers.target
TIMER
  firewall_blocklist_write_nginx_conf
  systemctl daemon-reload
  systemctl enable --now bpanel-firewall-blocklist.timer >/dev/null 2>&1 || true
}

firewall_blocklist_write_nginx_conf() {
  ensure_nginx_conf_dir_writable
  touch "$NGINX_BLOCKLIST_RULES"
  chown root:root "$NGINX_BLOCKLIST_RULES"
  chmod 0644 "$NGINX_BLOCKLIST_RULES"
  cat >"$NGINX_BLOCKLIST_SERVER_CONF" <<'CONF'
# Managed by BPanel. Included inside server blocks.
if ($bpanel_blocklisted_ip) {
    return 444;
}
CONF
  chown root:root "$NGINX_BLOCKLIST_SERVER_CONF"
  chmod 0644 "$NGINX_BLOCKLIST_SERVER_CONF"
  cat >"$NGINX_BLOCKLIST_CONF" <<CONF
# Managed by BPanel. URL IP blocklists are enforced by Nginx instead of UFW.
geo \$bpanel_blocklisted_ip {
    default 0;
    include ${NGINX_BLOCKLIST_RULES};
}
CONF
  chown root:root "$NGINX_BLOCKLIST_CONF"
  chmod 0644 "$NGINX_BLOCKLIST_CONF"
}

write_http_flood_nginx_conf() {
  ensure_nginx_conf_dir_writable
  if [[ ! -f "$NGINX_HTTP_FLOOD_ZONES" ]]; then
    cat >"$NGINX_HTTP_FLOOD_ZONES" <<'CONF'
# Managed by BPanel. Shared zones for per-website HTTP flood protection.
map $cookie_bpanel_http_flood_ok $bpanel_http_flood_key {
    default $binary_remote_addr;
    1 "";
}
limit_conn_zone $bpanel_http_flood_key zone=bpanel_conn_flood:10m;
CONF
  fi
  cat >"$NGINX_HTTP_FLOOD_CONF" <<'CONF'
# Managed by BPanel. Shared zones for per-website HTTP flood protection.
include /etc/nginx/bpanel/http-flood-zones.conf;
CONF
  rm -f "$NGINX_HTTP_FLOOD_LEGACY_CONF" "$NGINX_HTTP_FLOOD_SERVER_CONF" 2>/dev/null || true
  chown root:root "$NGINX_HTTP_FLOOD_CONF" "$NGINX_HTTP_FLOOD_ZONES"
  chmod 0644 "$NGINX_HTTP_FLOOD_CONF" "$NGINX_HTTP_FLOOD_ZONES"
}

save_http_flood_zones() {
  local tmp backup=""
  ensure_nginx_conf_dir_writable
  tmp="$(mktemp)"
  cat >"$tmp"
  if [[ $(wc -c <"$tmp") -gt 131072 ]]; then
    rm -f "$tmp"
    deny "HTTP flood zones are too large"
  fi
  if file_has_nul "$tmp"; then
    rm -f "$tmp"
    deny "HTTP flood zones cannot contain NUL bytes"
  fi
  if [[ -f "$NGINX_HTTP_FLOOD_ZONES" ]]; then
    backup="${NGINX_HTTP_FLOOD_ZONES}.bak.$(date +%s)"
    cp "$NGINX_HTTP_FLOOD_ZONES" "$backup"
  fi
  install -m 0644 -o root -g root "$tmp" "$NGINX_HTTP_FLOOD_ZONES"
  rm -f "$tmp"
  write_http_flood_nginx_conf
  if ! nginx -t; then
    if [[ -n "$backup" && -f "$backup" ]]; then
      mv -f "$backup" "$NGINX_HTTP_FLOOD_ZONES"
    else
      cat >"$NGINX_HTTP_FLOOD_ZONES" <<'CONF'
# Managed by BPanel. Shared zones for per-website HTTP flood protection.
map $cookie_bpanel_http_flood_ok $bpanel_http_flood_key {
    default $binary_remote_addr;
    1 "";
}
limit_conn_zone $bpanel_http_flood_key zone=bpanel_conn_flood:10m;
CONF
    fi
    deny "Nginx rejected HTTP flood zones"
  fi
  rm -f "$backup" 2>/dev/null || true
  systemctl reload nginx
  echo "HTTP flood zones saved"
}

firewall_blocklist_status() {
  ensure_bpanel_data_dir
  touch "$FIREWALL_BLOCKLIST_URLS"
  echo "URLs:"
  if [[ -s "$FIREWALL_BLOCKLIST_URLS" ]]; then
    firewall_blocklist_urls | sed 's/^/  /'
  else
    echo "  (none)"
  fi
  echo ""
  echo "Engine:"
  echo "  nginx"
  echo "Rules file:"
  [[ -f "$NGINX_BLOCKLIST_RULES" ]] && echo "  ${NGINX_BLOCKLIST_RULES}" || echo "  missing"
  echo ""
  echo "Networks:"
  if [[ -s "$FIREWALL_BLOCKLIST_WORK" ]]; then
    local total shown
    total="$(sed '/^[[:space:]]*$/d' "$FIREWALL_BLOCKLIST_WORK" | wc -l | tr -d '[:space:]')"
    shown=50
    echo "  ${total} network(s), showing first ${shown}:"
    sed '/^[[:space:]]*$/d' "$FIREWALL_BLOCKLIST_WORK" | head -n "$shown" | sed 's/^/  /'
    if (( total > shown )); then
      echo "  ... $((total - shown)) more"
    fi
  else
    echo "  (none)"
  fi
  echo ""
  echo "Timer:"
  systemctl is-enabled bpanel-firewall-blocklist.timer 2>/dev/null || true
  systemctl list-timers bpanel-firewall-blocklist.timer --no-pager 2>/dev/null || true
}

firewall_blocklist_clear_rules() {
  local numbers number
  numbers="$(ufw_commented_rule_numbers "bpanel:UserZone:blocklist" | sort -rn)"
  for number in $numbers; do
    ufw --force delete "$number" >/dev/null 2>&1 || true
  done
}

firewall_blocklist_run() {
  ensure_bpanel_data_dir
  touch "$FIREWALL_BLOCKLIST_URLS"
  local tmp fetched rules_tmp count url old_work old_rules
  tmp="$(mktemp)"
  fetched="$(mktemp)"
  rules_tmp="$(mktemp)"
  old_work="$(mktemp)"
  old_rules="$(mktemp)"
  [[ -f "$FIREWALL_BLOCKLIST_WORK" ]] && cp "$FIREWALL_BLOCKLIST_WORK" "$old_work" || true
  [[ -f "$NGINX_BLOCKLIST_RULES" ]] && cp "$NGINX_BLOCKLIST_RULES" "$old_rules" || true
  while IFS= read -r url; do
    [[ -n "$url" ]] || continue
    require_url "$url"
    curl -fsSL --connect-timeout 10 --max-time 30 "$url" >>"$fetched" || echo "WARNING: could not fetch $url" >&2
    printf '\n' >>"$fetched"
  done < <(firewall_blocklist_urls)
  python3 - "$fetched" "$tmp" "$rules_tmp" <<'PY'
import ipaddress
import re
import sys

seen = set()
networks = []
for raw in open(sys.argv[1], encoding="utf-8", errors="ignore"):
    line = re.split(r"[\s#;,]+", raw.strip(), 1)[0]
    if not line:
        continue
    try:
        value = str(ipaddress.ip_network(line, strict=False))
    except ValueError:
        continue
    if value not in seen:
        seen.add(value)
        networks.append(value)

with open(sys.argv[2], "w", encoding="utf-8") as handle:
    for value in networks:
        handle.write(value + "\n")

with open(sys.argv[3], "w", encoding="utf-8") as handle:
    handle.write("# Managed by BPanel. Generated from URL IP blocklists.\n")
    handle.write("# Loaded into the bpanel_blocklisted_ip geo map.\n")
    for value in networks:
        handle.write(f"{value} 1;\n")
PY
  install -d -o root -g root -m 0755 "$NGINX_BLOCKLIST_DIR"
  install -m 0644 -o root -g root "$rules_tmp" "$NGINX_BLOCKLIST_RULES"
  install -m 0644 -o root -g root "$tmp" "$FIREWALL_BLOCKLIST_WORK"
  firewall_blocklist_write_nginx_conf
  if ! nginx -t; then
    if [[ -s "$old_rules" ]]; then
      install -m 0644 -o root -g root "$old_rules" "$NGINX_BLOCKLIST_RULES"
    else
      : >"$NGINX_BLOCKLIST_RULES"
    fi
    if [[ -s "$old_work" ]]; then
      install -m 0644 -o root -g root "$old_work" "$FIREWALL_BLOCKLIST_WORK"
    else
      : >"$FIREWALL_BLOCKLIST_WORK"
    fi
    rm -f "$tmp" "$fetched" "$rules_tmp" "$old_work" "$old_rules"
    deny "Nginx rejected URL blocklist"
  fi
  systemctl reload nginx
  firewall_blocklist_clear_rules
  count="$(sed '/^[[:space:]]*$/d' "$FIREWALL_BLOCKLIST_WORK" | wc -l | tr -d '[:space:]')"
  firewall_blocklist_write_timer
  rm -f "$tmp" "$fetched" "$rules_tmp" "$old_work" "$old_rules"
  echo "Nginx blocklist refreshed: ${count} network(s)"
}

firewall_blocklist_add_url() {
  local url="$1"
  require_url "$url"
  ensure_bpanel_data_dir
  touch "$FIREWALL_BLOCKLIST_URLS"
  if ! grep -Fxq -- "$url" "$FIREWALL_BLOCKLIST_URLS"; then
    printf '%s\n' "$url" >>"$FIREWALL_BLOCKLIST_URLS"
  fi
  sort -u -o "$FIREWALL_BLOCKLIST_URLS" "$FIREWALL_BLOCKLIST_URLS"
  firewall_blocklist_write_nginx_conf
  firewall_blocklist_write_timer
  echo "Nginx blocklist URL added"
}

firewall_blocklist_delete_url() {
  local url="$1"
  require_url "$url"
  ensure_bpanel_data_dir
  touch "$FIREWALL_BLOCKLIST_URLS"
  grep -Fxv -- "$url" "$FIREWALL_BLOCKLIST_URLS" >"${FIREWALL_BLOCKLIST_URLS}.tmp" || true
  mv -f "${FIREWALL_BLOCKLIST_URLS}.tmp" "$FIREWALL_BLOCKLIST_URLS"
  firewall_blocklist_write_nginx_conf
  firewall_blocklist_write_timer
  echo "Nginx blocklist URL removed"
}

write_ssl_auto_renew_timer() {
  cat >/etc/systemd/system/bpanel-ssl-auto-renew.service <<SERVICE
[Unit]
Description=Renew BPanel SSL certificates that expire within 10 days
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Environment=SUDO_USER=bpanel
ExecStart=/usr/local/sbin/bpanel-helper certbot-renew-soon 10
SERVICE
  cat >/etc/systemd/system/bpanel-ssl-auto-renew.timer <<TIMER
[Unit]
Description=Check BPanel SSL certificates daily

[Timer]
OnCalendar=*-*-* 01:30:00
Persistent=true

[Install]
WantedBy=timers.target
TIMER
  systemctl daemon-reload
  systemctl enable --now bpanel-ssl-auto-renew.timer >/dev/null 2>&1 || true
}

copy_panel_live_certificate() {
  local domain="$1"
  [[ -n "$domain" ]] || return 0
  [[ -f "/etc/letsencrypt/live/${domain}/fullchain.pem" && -f "/etc/letsencrypt/live/${domain}/privkey.pem" ]] || return 0
  install -d -o root -g bpanel -m 0750 /etc/bpanel
  install -m 0640 -o root -g bpanel "/etc/letsencrypt/live/${domain}/fullchain.pem" /etc/bpanel/panel-fullchain.pem
  install -m 0640 -o root -g bpanel "/etc/letsencrypt/live/${domain}/privkey.pem" /etc/bpanel/panel-privkey.pem
  if [[ -f "$ENV_FILE" ]]; then
    env_set PANEL_SSL_CERT "/etc/bpanel/panel-fullchain.pem"
    env_set PANEL_SSL_KEY "/etc/bpanel/panel-privkey.pem"
  fi
}

install_manual_ssl() {
  local domain="$1" base tmpdir
  require_domain "$domain"
  base="/etc/nginx/bpanel/ssl/sites/${domain}"
  tmpdir="$(mktemp -d /tmp/bpanel-manual-ssl.XXXXXX)"
  trap 'rm -rf "$tmpdir"' RETURN
  local payload_file="$tmpdir/payload.json"
  cat >"$payload_file"
  python3 - "$tmpdir" "$payload_file" <<'PY'
import json
import pathlib
import sys

tmpdir = pathlib.Path(sys.argv[1])
payload_file = pathlib.Path(sys.argv[2])
data = json.loads(payload_file.read_text(encoding="utf-8"))
parts = {
    "cert.crt": data.get("certificate", ""),
    "privkey.key": data.get("private_key", ""),
}
ca_bundle = data.get("ca_bundle", "")
if ca_bundle:
    parts["ca.crt"] = ca_bundle
for name, content in parts.items():
    if not content or "\x00" in content:
        raise SystemExit(f"invalid {name}")
    (tmpdir / name).write_text(content, encoding="utf-8")
PY
  install -d -o root -g bpanel -m 0750 "$base"
  install -m 0640 -o root -g bpanel "$tmpdir/cert.crt" "$base/cert.crt"
  install -m 0640 -o root -g bpanel "$tmpdir/privkey.key" "$base/privkey.key"
  if [[ -f "$tmpdir/ca.crt" ]]; then
    install -m 0640 -o root -g bpanel "$tmpdir/ca.crt" "$base/ca.crt"
    cat "$tmpdir/cert.crt" "$tmpdir/ca.crt" >"$tmpdir/fullchain.crt"
    install -m 0640 -o root -g bpanel "$tmpdir/fullchain.crt" "$base/fullchain.crt"
  else
    rm -f "$base/ca.crt"
    install -m 0640 -o root -g bpanel "$tmpdir/cert.crt" "$base/fullchain.crt"
  fi
  echo "Manual SSL installed for ${domain}"
}

remove_manual_ssl() {
  local domain="$1" base
  require_domain "$domain"
  base="/etc/nginx/bpanel/ssl/sites/${domain}"
  rm -f "$base/cert.crt" "$base/privkey.key" "$base/ca.crt" "$base/fullchain.crt"
  rmdir "$base" 2>/dev/null || true
  echo "Manual SSL removed for ${domain}"
}

renew_ssl_soon() {
  local days="${1:-10}" seconds cert cert_name checked=0 renewed=0 panel_domain
  [[ "$days" =~ ^[0-9]+$ && "$days" -ge 1 && "$days" -le 30 ]] || deny "usage: certbot-renew-soon [1-30 days]"
  write_ssl_auto_renew_timer
  if ! command -v certbot >/dev/null 2>&1; then
    echo "certbot is not installed"
    return 0
  fi
  seconds=$((days * 86400))
  shopt -s nullglob
  for cert in /etc/letsencrypt/live/*/cert.pem; do
    [[ -f "$cert" ]] || continue
    cert_name="$(basename "$(dirname "$cert")")"
    [[ "$cert_name" == "README" ]] && continue
    checked=$((checked + 1))
    if ! openssl x509 -checkend "$seconds" -noout -in "$cert" >/dev/null 2>&1; then
      echo "Renewing certificate: ${cert_name}"
      if certbot renew --cert-name "$cert_name" --quiet --force-renewal \
        --deploy-hook "systemctl reload nginx || true; systemctl restart bpanel-api || true"; then
        renewed=$((renewed + 1))
      else
        echo "WARNING: could not renew ${cert_name}" >&2
      fi
    fi
  done
  shopt -u nullglob
  panel_domain="$(env_get PANEL_DOMAIN)"
  copy_panel_live_certificate "$panel_domain"
  if [[ "$renewed" -gt 0 ]]; then
    systemctl reload nginx >/dev/null 2>&1 || true
    systemctl restart bpanel-api >/dev/null 2>&1 || true
  fi
  echo "SSL auto-renew checked ${checked} certificate(s); renewed ${renewed} certificate(s) within ${days} day(s)."
}

is_in() {
  local needle="$1"; shift
  local x
  for x in "$@"; do [[ "$x" == "$needle" ]] && return 0; done
  return 1
}

is_allowed_service() {
  local service="$1" php_version=""
  if is_in "$service" "${ALLOWED_SERVICES[@]}"; then
    return 0
  fi
  if [[ "$service" =~ ^php([0-9]+\.[0-9]+)-fpm$ ]]; then
    php_version="${BASH_REMATCH[1]}"
    [[ -f "/etc/php/${php_version}/fpm/php-fpm.conf" ]] && return 0
  fi
  return 1
}

require_safe_path() {
  local prefix="$1" path="$2"
  # Reject path traversal components, newlines, and empty input. Bash strings
  # cannot carry NUL bytes, so there is no separate NUL pattern here.
  # Note: we cannot use `*..*` as a glob because that would also reject
  # legitimate filenames that just happen to contain a dot adjacent to a dot
  # via Bash's pattern matching quirks; instead we match the `..` only when
  # it actually forms a path component.
  case "$path" in
    *$'\n'*) deny "unsafe path: $path" ;;
    "") deny "empty path" ;;
    "..") deny "path traversal not allowed" ;;
    "../"*|*"/.."|*"/../"*) deny "path traversal not allowed" ;;
  esac
  local resolved
  resolved=$(readlink -m "$path") || deny "cannot resolve $path"
  case "$resolved/" in
    "$prefix"/*) ;;
    *) deny "path outside $prefix: $resolved" ;;
  esac
  echo "$resolved"
}

require_domain() {
  local d="$1"
  [[ "$d" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]] \
    || deny "invalid domain: $d"
}

require_email() {
  local e="$1"
  [[ "$e" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] \
    || deny "invalid email: $e"
}

require_port() {
  [[ "$1" =~ ^[0-9]{1,5}$ ]] || deny "invalid port: $1"
  (( $1 >= 1 && $1 <= 65535 )) || deny "port out of range: $1"
}

require_tail_lines() {
  [[ "$1" =~ ^[0-9]{1,4}$ ]] || deny "invalid log line count: $1"
  (( $1 >= 1 && $1 <= 5000 )) || deny "log line count out of range: $1"
}

require_proto() {
  [[ "$1" == "tcp" || "$1" == "udp" ]] || deny "invalid protocol: $1"
}

require_php_version() {
  [[ "$1" =~ ^(5\.6|7\.4|8\.0|8\.1|8\.2|8\.3|8\.4|8\.5)$ ]] || deny "invalid PHP version: $1"
}

require_linux_user() {
  [[ "$1" =~ ^[a-z_][a-z0-9_-]{2,31}$ ]] || deny "invalid panel Linux user: $1"
  case "$1" in
    root|daemon|bin|sys|sync|games|man|lp|mail|news|uucp|proxy|www-data|backup|list|irc|_apt|nobody|bpanel|bpanel-sites|bpanel-sftp|mysql|redis|nginx)
      deny "reserved panel Linux user: $1" ;;
  esac
}

require_site_domain_segment() {
  [[ "$1" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]] \
    || deny "invalid site domain path segment: $1"
}

read_site_log() {
  local domain="$1" kind="$2" lines="$3" path resolved
  require_domain "$domain"
  [[ "$kind" == "access" || "$kind" == "error" ]] || deny "invalid log kind: $kind"
  require_tail_lines "$lines"
  path="/var/log/nginx/${domain}.${kind}.log"
  resolved=$(readlink -m "$path") || deny "cannot resolve log path"
  case "$resolved" in
    /var/log/nginx/*) ;;
    *) deny "log path outside /var/log/nginx: $resolved" ;;
  esac
  echo "BPANEL_LOG_PATH=$resolved" >&2
  if [[ ! -f "$resolved" ]]; then
    echo "BPANEL_LOG_MISSING=1" >&2
    return 0
  fi
  tail -n "$lines" -- "$resolved"
}

require_managed_path() {
  local path="$1" user="${2:-}"
  local resolved first_part relative domain_part
  resolved=$(require_safe_path "$HOME_ROOT" "$path")
  if [[ -n "$user" ]]; then
    require_linux_user "$user"
    case "$resolved/" in
      "$HOME_ROOT/$user/"*)
        relative="${resolved#${HOME_ROOT}/${user}/}"
        domain_part="${relative%%/*}"
        require_site_domain_segment "$domain_part"
        ;;
      *) deny "path is not owned by panel Linux user $user: $resolved" ;;
    esac
  else
    case "$resolved/" in
      "$HOME_ROOT"/*/*)
        first_part="${resolved#${HOME_ROOT}/}"
        first_part="${first_part%%/*}"
        require_linux_user "$first_part"
        relative="${resolved#${HOME_ROOT}/${first_part}/}"
        domain_part="${relative%%/*}"
        require_site_domain_segment "$domain_part"
        ;;
      *) deny "path outside managed site roots: $resolved" ;;
    esac
  fi
  echo "$resolved"
}

require_terminal_cwd() {
  local path="$1" user="$2" resolved
  require_linux_user "$user"
  resolved=$(require_safe_path "$HOME_ROOT" "$path")
  case "$resolved" in
    "$HOME_ROOT/$user"|"$HOME_ROOT/$user"/*) ;;
    *) deny "terminal cwd is not owned by panel Linux user $user: $resolved" ;;
  esac
  [[ -d "$resolved" ]] || deny "terminal cwd is not a directory: $resolved"
  echo "$resolved"
}

require_terminal_path_args() {
  local user="$1" cwd="$2" arg resolved
  shift 2
  require_linux_user "$user"
  for arg in "$@"; do
    case "$arg" in
      ""|"-"*|"--") continue ;;
      *$'\n'*|".."|"../"*|*"/.."|*"/../"*) deny "terminal path argument escapes user home: $arg" ;;
    esac
    if [[ "$arg" = /* ]]; then
      resolved=$(readlink -m -- "$arg") || deny "cannot resolve terminal path: $arg"
    else
      resolved=$(readlink -m -- "$cwd/$arg") || deny "cannot resolve terminal path: $arg"
    fi
    case "$resolved/" in
      "$HOME_ROOT/$user/"*) ;;
      *) deny "terminal path argument is outside panel user home: $arg" ;;
    esac
  done
}

require_terminal_download_args() {
  local user="$1" cwd="$2" arg value expect_output=0
  shift 2
  for arg in "$@"; do
    case "${arg,,}" in
      file://*) deny "terminal URL argument uses local file scheme: $arg" ;;
    esac
    if (( expect_output )); then
      require_terminal_path_args "$user" "$cwd" "$arg"
      expect_output=0
      continue
    fi
    case "$arg" in
      --output=*|--output-document=*|-O=*)
        value="${arg#*=}"
        require_terminal_path_args "$user" "$cwd" "$value"
        ;;
      -o|-O|--output|--output-document)
        expect_output=1
        ;;
      http://*|https://*|ftp://*|ftps://*|sftp://*)
        ;;
      -*|"")
        ;;
      *)
        require_terminal_path_args "$user" "$cwd" "$arg"
        ;;
    esac
  done
  (( expect_output == 0 )) || deny "terminal download output path is missing"
}

ensure_sites_group() {
  getent group "$BPANEL_SITES_GROUP" >/dev/null || groupadd --system "$BPANEL_SITES_GROUP"
  usermod -aG "$BPANEL_SITES_GROUP" bpanel 2>/dev/null || true
  usermod -aG "$BPANEL_SITES_GROUP" www-data 2>/dev/null || true
}

ensure_sftp_group() {
  getent group "$BPANEL_SFTP_GROUP" >/dev/null || groupadd --system "$BPANEL_SFTP_GROUP"
}

clear_path_acl() {
  local target="$1"
  if command -v setfacl >/dev/null 2>&1; then
    setfacl -b -k "$target" 2>/dev/null || true
  fi
}

harden_site_dir() {
  local target="$1" user="$2"
  chown "$user:$BPANEL_SITES_GROUP" "$target"
  clear_path_acl "$target"
  chmod 2750 "$target"
  chmod u-s "$target" 2>/dev/null || true
  chmod -t "$target" 2>/dev/null || true
}

harden_site_dir_path() {
  local root="$1" target="$2" user="$3" relative current part
  ensure_sites_group
  require_linux_user "$user"
  root=$(readlink -m "$root") || deny "cannot resolve $root"
  target=$(readlink -m "$target") || deny "cannot resolve $target"
  case "$target" in
    "$root"|"$root"/*) ;;
    *) deny "directory path outside site root: $target" ;;
  esac
  [[ -d "$target" ]] || deny "site directory does not exist: $target"
  harden_site_dir "$root" "$user"
  [[ "$target" == "$root" ]] && return 0
  relative="${target#${root}/}"
  current="$root"
  IFS='/' read -r -a root_parts <<< "$relative"
  for part in "${root_parts[@]}"; do
    current="$current/$part"
    [[ -d "$current" ]] || deny "site directory does not exist: $current"
    harden_site_dir "$current" "$user"
  done
}

ensure_panel_user_home() {
  local user="$1" home_dir="$HOME_ROOT/$1"
  ensure_sites_group
  ensure_sftp_group
  require_linux_user "$user"
  getent group "$user" >/dev/null || groupadd "$user"
  chown root:root "$HOME_ROOT"
  chmod 0711 "$HOME_ROOT"
  chmod a-s "$HOME_ROOT" 2>/dev/null || true
  chmod -t "$HOME_ROOT" 2>/dev/null || true
  if ! id -u "$user" >/dev/null 2>&1; then
    useradd --create-home --home-dir "$home_dir" --shell /usr/sbin/nologin --gid "$user" "$user"
  fi
  usermod --home "$home_dir" --shell /usr/sbin/nologin --gid "$user" "$user" 2>/dev/null || true
  usermod -aG "$BPANEL_SFTP_GROUP" "$user" 2>/dev/null || true
  mkdir -p "$home_dir"
  chown "root:$user" "$home_dir"
  chmod 0751 "$home_dir"
  chmod a-s "$home_dir" 2>/dev/null || true
  chmod -t "$home_dir" 2>/dev/null || true
  clear_path_acl "$home_dir"
}

set_panel_user_password() {
  local user="$1" password
  require_linux_user "$user"
  id -u "$user" >/dev/null 2>&1 || deny "panel Linux user does not exist: $user"
  password="$(cat)"
  password="${password%$'\n'}"
  [[ ${#password} -ge 12 && ${#password} -le 72 ]] || deny "password must be 12-72 characters"
  case "$password" in
    *:*|*$'\r'*|*$'\n'*) deny "password cannot contain ':', carriage returns or newlines" ;;
  esac
  printf '%s:%s\n' "$user" "$password" | chpasswd
  passwd -u "$user" >/dev/null 2>&1 || true
}

delete_panel_user_runtime() {
  local user="$1"
  require_linux_user "$user"
  for dir in /etc/php/*/fpm/pool.d; do
    [[ -d "$dir" ]] || continue
    for pool_file in "$dir"/bpanel-${user}.conf "$dir"/bpanel-${user}-*.conf; do
      [[ -f "$pool_file" ]] || continue
      rm -f "$pool_file"
      local php_version
      php_version="$(echo "$dir" | awk -F/ '{print $4}')"
      systemctl reload "php${php_version}-fpm" 2>/dev/null || true
    done
  done
  crontab -r -u "$user" 2>/dev/null || true
  pkill -u "$user" 2>/dev/null || true
  userdel "$user" 2>/dev/null || true
  groupdel "$user" 2>/dev/null || true
  rm -rf "$HOME_ROOT/$user" 2>/dev/null || true
  rm -rf "/var/lib/php/sessions/$user" 2>/dev/null || true
  rm -rf "/var/lib/php/uploads/$user" 2>/dev/null || true
}

site_php_pool_glob() {
  local user="$1" target="$2"
  require_linux_user "$user"
  target=$(readlink -m "$target") || deny "cannot resolve $target"
  local site_hash
  site_hash="$(printf '%s' "$target" | sha256sum | awk '{print substr($1, 1, 12)}')"
  printf 'bpanel-%s-%s-*' "$user" "$site_hash"
}

positive_int_or_default() {
  local value="${1:-}" default="$2" min="${3:-1}" max="${4:-}"
  if [[ ! "$value" =~ ^[0-9]+$ ]]; then
    value="$default"
  fi
  if (( value < min )); then
    value="$min"
  fi
  if [[ -n "$max" ]] && (( value > max )); then
    value="$max"
  fi
  printf '%s\n' "$value"
}

php_fpm_tuning_value() {
  local key="$1" default="$2" value=""
  if [[ -v "$key" ]]; then
    value="${!key}"
  fi
  if [[ -z "$value" ]]; then
    value="$(env_get "$key" 2>/dev/null || true)"
  fi
  printf '%s\n' "${value:-$default}"
}

php_fpm_total_memory_mb() {
  local total
  total="$(awk '/^MemTotal:/ { print int($2 / 1024); exit }' /proc/meminfo 2>/dev/null || true)"
  positive_int_or_default "$total" 1024 256 1048576
}

php_fpm_cpu_count() {
  local count
  count="$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)"
  positive_int_or_default "$count" 1 1 256
}

php_fpm_pool_count() {
  local current_pool="${1:-}" count=0 pool_file
  shopt -s nullglob
  for pool_file in /etc/php/*/fpm/pool.d/bpanel-*.conf; do
    [[ -f "$pool_file" ]] || continue
    count=$((count + 1))
  done
  shopt -u nullglob
  if [[ -n "$current_pool" && ! -f "$current_pool" ]]; then
    count=$((count + 1))
  fi
  if (( count < 1 )); then
    count=1
  fi
  printf '%s\n' "$count"
}

php_fpm_reserved_memory_mb() {
  local total="$1" reserve
  if (( total <= 1024 )); then
    reserve=$((total * 45 / 100))
    (( reserve >= 448 )) || reserve=448
  elif (( total <= 2048 )); then
    reserve=$((total * 35 / 100))
    (( reserve >= 640 )) || reserve=640
  elif (( total <= 4096 )); then
    reserve=$((total * 30 / 100))
    (( reserve >= 896 )) || reserve=896
  elif (( total <= 8192 )); then
    reserve=$((total * 25 / 100))
    (( reserve >= 1280 )) || reserve=1280
  else
    reserve=$((total * 20 / 100))
    (( reserve >= 2048 )) || reserve=2048
  fi
  if (( reserve > total - 128 )); then
    reserve=$((total - 128))
  fi
  if (( reserve < 128 )); then
    reserve=128
  fi
  printf '%s\n' "$reserve"
}

calculate_php_fpm_pool_tuning() {
  local current_pool="${1:-}" total_mb reserve_mb php_budget_mb cpu_count pool_count worker_mb
  local global_children pool_children cpu_cap profile_cap forced_children idle_default requests_default
  local active_pool_divisor pool_floor
  total_mb="$(php_fpm_total_memory_mb)"
  cpu_count="$(php_fpm_cpu_count)"
  pool_count="$(php_fpm_pool_count "$current_pool")"
  worker_mb="$(positive_int_or_default "$(php_fpm_tuning_value BPANEL_PHP_FPM_WORKER_MB "$PHP_FPM_DEFAULT_WORKER_MB")" "$PHP_FPM_DEFAULT_WORKER_MB" 32 1024)"
  reserve_mb="$(php_fpm_reserved_memory_mb "$total_mb")"
  php_budget_mb=$((total_mb - reserve_mb))
  if (( php_budget_mb < worker_mb )); then
    php_budget_mb="$worker_mb"
  fi

  global_children=$((php_budget_mb / worker_mb))
  (( global_children >= 1 )) || global_children=1

  active_pool_divisor=1
  while (( active_pool_divisor * active_pool_divisor < pool_count )); do
    active_pool_divisor=$((active_pool_divisor + 1))
  done
  pool_children=$((global_children / active_pool_divisor))
  (( pool_children >= 1 )) || pool_children=1

  cpu_cap=$((cpu_count * 4))
  if (( total_mb >= 3072 )); then
    cpu_cap=$((cpu_count * 6))
  fi
  if (( total_mb >= 8192 )); then
    cpu_cap=$((cpu_count * 8))
  fi
  (( cpu_cap >= 2 )) || cpu_cap=2
  (( cpu_cap <= 96 )) || cpu_cap=96

  if (( total_mb <= 1024 )); then
    pool_floor=1
    profile_cap=4
    idle_default=10
    requests_default=300
  elif (( total_mb <= 2048 )); then
    pool_floor=2
    profile_cap=8
    idle_default=15
    requests_default=400
  elif (( total_mb <= 4096 )); then
    pool_floor=3
    profile_cap=14
    idle_default=20
    requests_default=500
  elif (( total_mb <= 8192 )); then
    pool_floor=4
    profile_cap=24
    idle_default=30
    requests_default=750
  else
    pool_floor=6
    profile_cap=48
    idle_default=45
    requests_default=1000
  fi

  (( pool_children >= pool_floor )) || pool_children="$pool_floor"
  (( pool_children <= cpu_cap )) || pool_children="$cpu_cap"
  (( pool_children <= profile_cap )) || pool_children="$profile_cap"
  forced_children="$(php_fpm_tuning_value BPANEL_PHP_FPM_MAX_CHILDREN "")"
  if [[ -n "$forced_children" ]]; then
    pool_children="$(positive_int_or_default "$forced_children" "$pool_children" 1 512)"
  fi

  PHP_FPM_PM_MODE="ondemand"
  PHP_FPM_MAX_CHILDREN="$pool_children"
  PHP_FPM_PROCESS_IDLE_TIMEOUT="$(positive_int_or_default "$(php_fpm_tuning_value BPANEL_PHP_FPM_IDLE_TIMEOUT "$idle_default")" "$idle_default" 5 300)"
  PHP_FPM_MAX_REQUESTS="$(positive_int_or_default "$(php_fpm_tuning_value BPANEL_PHP_FPM_MAX_REQUESTS "$requests_default")" "$requests_default" 50 10000)"
  PHP_FPM_REQUEST_TERMINATE_TIMEOUT="$(positive_int_or_default "$(php_fpm_tuning_value BPANEL_PHP_FPM_REQUEST_TERMINATE_TIMEOUT "$PHP_FPM_DEFAULT_REQUEST_TERMINATE_TIMEOUT")" "$PHP_FPM_DEFAULT_REQUEST_TERMINATE_TIMEOUT" 30 3600)"
}

php_fpm_set_directive() {
  local file="$1" key="$2" value="$3" key_re
  key_re="${key//./\\.}"
  if grep -Eq "^[;[:space:]]*${key_re}[[:space:]]*=" "$file"; then
    sed -i -E "s|^[;[:space:]]*${key_re}[[:space:]]*=.*|${key} = ${value}|" "$file"
  else
    printf '%s = %s\n' "$key" "$value" >>"$file"
  fi
}

apply_php_fpm_tuning_to_pool_file() {
  local pool_file="$1"
  php_fpm_set_directive "$pool_file" "pm" "$PHP_FPM_PM_MODE"
  php_fpm_set_directive "$pool_file" "pm.max_children" "$PHP_FPM_MAX_CHILDREN"
  php_fpm_set_directive "$pool_file" "pm.process_idle_timeout" "${PHP_FPM_PROCESS_IDLE_TIMEOUT}s"
  php_fpm_set_directive "$pool_file" "pm.max_requests" "$PHP_FPM_MAX_REQUESTS"
  php_fpm_set_directive "$pool_file" "request_terminate_timeout" "${PHP_FPM_REQUEST_TERMINATE_TIMEOUT}s"
}

retune_php_fpm_pools() {
  local pool_file php_version count=0 versions=""
  shopt -s nullglob
  for pool_file in /etc/php/*/fpm/pool.d/bpanel-*.conf; do
    [[ -f "$pool_file" ]] || continue
    calculate_php_fpm_pool_tuning "$pool_file"
    apply_php_fpm_tuning_to_pool_file "$pool_file"
    count=$((count + 1))
    php_version="$(echo "$pool_file" | awk -F/ '{print $4}')"
    case " $versions " in
      *" $php_version "*) ;;
      *) versions="${versions} ${php_version}" ;;
    esac
  done
  shopt -u nullglob
  for php_version in $versions; do
    systemctl reload "php${php_version}-fpm" 2>/dev/null || true
  done
  echo "Retuned ${count} BPanel PHP-FPM pool(s)."
}

mariadb_tuning_value() {
  local key="$1" default="$2" value=""
  if [[ -v "$key" ]]; then
    value="${!key}"
  fi
  if [[ -z "$value" ]]; then
    value="$(env_get "$key" 2>/dev/null || true)"
  fi
  printf '%s\n' "${value:-$default}"
}

mariadb_megabytes() {
  local value="${1:-}" default="$2" number unit
  if [[ "$value" =~ ^([0-9]+)([KkMmGg]?)$ ]]; then
    number="${BASH_REMATCH[1]}"
    unit="${BASH_REMATCH[2]}"
    case "$unit" in
      [Kk]) printf '%s\n' $(((number + 1023) / 1024)) ;;
      [Gg]) printf '%s\n' $((number * 1024)) ;;
      *) printf '%s\n' "$number" ;;
    esac
    return 0
  fi
  printf '%s\n' "$default"
}

calculate_mariadb_tuning() {
  local total_mb cpu_count buffer_default buffer_mb log_file_mb tmp_mb max_connections thread_cache
  local table_open_cache open_files_limit packet_mb io_capacity
  total_mb="$(php_fpm_total_memory_mb)"
  cpu_count="$(php_fpm_cpu_count)"

  if (( total_mb <= 1024 )); then
    buffer_default=$((total_mb * 22 / 100))
    max_connections=35
    thread_cache=16
    table_open_cache=512
    tmp_mb=32
    packet_mb=64
  elif (( total_mb <= 2048 )); then
    buffer_default=$((total_mb * 25 / 100))
    max_connections=50
    thread_cache=24
    table_open_cache=512
    tmp_mb=48
    packet_mb=64
  elif (( total_mb <= 4096 )); then
    buffer_default=$((total_mb * 28 / 100))
    max_connections=80
    thread_cache=32
    table_open_cache=1024
    tmp_mb=64
    packet_mb=96
  elif (( total_mb <= 8192 )); then
    buffer_default=$((total_mb * 32 / 100))
    max_connections=120
    thread_cache=48
    table_open_cache=1024
    tmp_mb=96
    packet_mb=128
  else
    buffer_default=$((total_mb * 36 / 100))
    max_connections=180
    thread_cache=64
    table_open_cache=2048
    tmp_mb=128
    packet_mb=128
  fi

  (( buffer_default >= 128 )) || buffer_default=128
  (( buffer_default <= total_mb * 45 / 100 )) || buffer_default=$((total_mb * 45 / 100))
  buffer_mb="$(mariadb_megabytes "$(mariadb_tuning_value BPANEL_MARIADB_BUFFER_POOL_SIZE "${buffer_default}M")" "$buffer_default")"
  buffer_mb="$(positive_int_or_default "$buffer_mb" "$buffer_default" 128 "$((total_mb * 60 / 100))")"

  max_connections="$(positive_int_or_default "$(mariadb_tuning_value BPANEL_MARIADB_MAX_CONNECTIONS "$max_connections")" "$max_connections" 20 1000)"
  thread_cache="$(positive_int_or_default "$(mariadb_tuning_value BPANEL_MARIADB_THREAD_CACHE_SIZE "$thread_cache")" "$thread_cache" 8 256)"
  table_open_cache="$(positive_int_or_default "$(mariadb_tuning_value BPANEL_MARIADB_TABLE_OPEN_CACHE "$table_open_cache")" "$table_open_cache" 256 65535)"
  tmp_mb="$(mariadb_megabytes "$(mariadb_tuning_value BPANEL_MARIADB_TMP_TABLE_SIZE "${tmp_mb}M")" "$tmp_mb")"
  tmp_mb="$(positive_int_or_default "$tmp_mb" 64 16 512)"
  packet_mb="$(mariadb_megabytes "$(mariadb_tuning_value BPANEL_MARIADB_MAX_ALLOWED_PACKET "${packet_mb}M")" "$packet_mb")"
  packet_mb="$(positive_int_or_default "$packet_mb" 64 16 512)"
  log_file_mb=$((buffer_mb / 4))
  log_file_mb="$(positive_int_or_default "$(mariadb_megabytes "$(mariadb_tuning_value BPANEL_MARIADB_LOG_FILE_SIZE "${log_file_mb}M")" "$log_file_mb")" "$log_file_mb" 64 1024)"
  io_capacity=$((cpu_count * 200))
  io_capacity="$(positive_int_or_default "$(mariadb_tuning_value BPANEL_MARIADB_IO_CAPACITY "$io_capacity")" "$io_capacity" 200 4000)"
  open_files_limit=$((table_open_cache * 2 + max_connections + 512))
  open_files_limit="$(positive_int_or_default "$(mariadb_tuning_value BPANEL_MARIADB_OPEN_FILES_LIMIT "$open_files_limit")" "$open_files_limit" 2048 200000)"

  MARIADB_INNODB_BUFFER_POOL_SIZE="${buffer_mb}M"
  MARIADB_INNODB_LOG_FILE_SIZE="${log_file_mb}M"
  MARIADB_MAX_CONNECTIONS="$max_connections"
  MARIADB_THREAD_CACHE_SIZE="$thread_cache"
  MARIADB_TABLE_OPEN_CACHE="$table_open_cache"
  MARIADB_TMP_TABLE_SIZE="${tmp_mb}M"
  MARIADB_MAX_ALLOWED_PACKET="${packet_mb}M"
  MARIADB_INNODB_IO_CAPACITY="$io_capacity"
  MARIADB_OPEN_FILES_LIMIT="$open_files_limit"
}

write_mariadb_tuning() {
  calculate_mariadb_tuning
  install -d -o root -g root -m 0755 "$(dirname "$MARIADB_TUNING_CONF")"
  cat >"$MARIADB_TUNING_CONF" <<MYSQL
# BPanel auto-tunes MariaDB for small and medium VPS plans.
# Optional overrides in ${ENV_FILE}: BPANEL_MARIADB_BUFFER_POOL_SIZE,
# BPANEL_MARIADB_MAX_CONNECTIONS, BPANEL_MARIADB_THREAD_CACHE_SIZE,
# BPANEL_MARIADB_TABLE_OPEN_CACHE, BPANEL_MARIADB_TMP_TABLE_SIZE,
# BPANEL_MARIADB_MAX_ALLOWED_PACKET, BPANEL_MARIADB_LOG_FILE_SIZE,
# BPANEL_MARIADB_IO_CAPACITY, BPANEL_MARIADB_OPEN_FILES_LIMIT.
[mysqld]
innodb_buffer_pool_size = ${MARIADB_INNODB_BUFFER_POOL_SIZE}
innodb_log_file_size = ${MARIADB_INNODB_LOG_FILE_SIZE}
innodb_flush_log_at_trx_commit = 2
innodb_flush_method = O_DIRECT
innodb_io_capacity = ${MARIADB_INNODB_IO_CAPACITY}
max_connections = ${MARIADB_MAX_CONNECTIONS}
thread_cache_size = ${MARIADB_THREAD_CACHE_SIZE}
table_open_cache = ${MARIADB_TABLE_OPEN_CACHE}
tmp_table_size = ${MARIADB_TMP_TABLE_SIZE}
max_heap_table_size = ${MARIADB_TMP_TABLE_SIZE}
max_allowed_packet = ${MARIADB_MAX_ALLOWED_PACKET}
skip_name_resolve = 1
slow_query_log = 1
slow_query_log_file = /var/log/mysql/bpanel-slow.log
long_query_time = 2

[server]
open_files_limit = ${MARIADB_OPEN_FILES_LIMIT}
MYSQL
}

ensure_mariadb_slow_log() {
  local log_dir="/var/log/mysql" log_file="/var/log/mysql/bpanel-slow.log" log_group="mysql"
  getent group adm >/dev/null 2>&1 && log_group="adm"
  install -d -o mysql -g "$log_group" -m 0750 "$log_dir"
  touch "$log_file"
  chown mysql:"$log_group" "$log_file"
  chmod 0640 "$log_file"
}

retune_mariadb() {
  write_mariadb_tuning
  ensure_mariadb_slow_log
  mariadbd --help --verbose >/dev/null
  systemctl restart mariadb
  echo "Retuned MariaDB: innodb_buffer_pool_size=${MARIADB_INNODB_BUFFER_POOL_SIZE}, max_connections=${MARIADB_MAX_CONNECTIONS}, table_open_cache=${MARIADB_TABLE_OPEN_CACHE}."
}

delete_site_php_pools() {
  local user="$1" target="$2" glob
  glob="$(site_php_pool_glob "$user" "$target")"
  for dir in /etc/php/*/fpm/pool.d; do
    [[ -d "$dir" ]] || continue
    for pool_file in "$dir"/$glob.conf; do
      [[ -f "$pool_file" ]] || continue
      rm -f "$pool_file"
      local php_version
      php_version="$(echo "$dir" | awk -F/ '{print $4}')"
      systemctl reload "php${php_version}-fpm" 2>/dev/null || true
    done
  done
}

ensure_php_pool() {
  local user="$1" target="$2" php_version="$3"
  [[ "$php_version" != "none" ]] || return 0
  require_linux_user "$user"
  require_php_version "$php_version"
  target=$(readlink -m "$target") || deny "cannot resolve $target"
  local pool_suffix="${php_version//./_}"
  local site_hash
  site_hash="$(printf '%s' "$target" | sha256sum | awk '{print substr($1, 1, 12)}')"
  local pool_name="bpanel-${user}-${site_hash}-${pool_suffix}"
  local pool_file="/etc/php/${php_version}/fpm/pool.d/${pool_name}.conf"
  # Per-user dirs for sessions/uploads. Sharing /tmp across pools lets one
  # site read another's session files (mode 0600 helps but only inside the
  # same uid; uploads land world-writable on tmpfs). Using 0700 dirs owned
  # by the pool's Linux user contains the data inside the site's trust
  # boundary.
  local sess_dir="/var/lib/php/sessions/${user}"
  local upload_dir="/var/lib/php/uploads/${user}"
  install -d -o "$user" -g "$user" -m 0700 "$sess_dir"
  install -d -o "$user" -g "$user" -m 0700 "$upload_dir"
  calculate_php_fpm_pool_tuning "$pool_file"
  cat >"$pool_file" <<POOL
[${pool_name}]
user = ${user}
group = ${user}
listen = /run/php/${pool_name}.sock
listen.owner = www-data
listen.group = www-data
listen.mode = 0660
; BPanel auto-tunes these values from RAM, CPU and managed pool count.
; Optional overrides: BPANEL_PHP_FPM_WORKER_MB, BPANEL_PHP_FPM_MAX_CHILDREN,
; BPANEL_PHP_FPM_IDLE_TIMEOUT, BPANEL_PHP_FPM_MAX_REQUESTS,
; BPANEL_PHP_FPM_REQUEST_TERMINATE_TIMEOUT.
pm = ${PHP_FPM_PM_MODE}
pm.max_children = ${PHP_FPM_MAX_CHILDREN}
pm.process_idle_timeout = ${PHP_FPM_PROCESS_IDLE_TIMEOUT}s
pm.max_requests = ${PHP_FPM_MAX_REQUESTS}
request_terminate_timeout = ${PHP_FPM_REQUEST_TERMINATE_TIMEOUT}s
chdir = /
php_admin_value[open_basedir] = ${target}:${sess_dir}:${upload_dir}:/usr/share/php
php_admin_value[upload_tmp_dir] = ${upload_dir}
php_admin_value[session.save_path] = ${sess_dir}
POOL
  systemctl reload "php${php_version}-fpm"
}

fix_site_tree() {
  local target="$1" user="$2"
  ensure_sites_group
  require_linux_user "$user"
  chown -R "$user:$BPANEL_SITES_GROUP" "$target"
  if [[ -d "$target" ]]; then
    if command -v setfacl >/dev/null 2>&1; then
      setfacl -Rb "$target" 2>/dev/null || true
      find "$target" -type d -exec setfacl -k {} + 2>/dev/null || true
    fi
    find "$target" -type d -exec chmod 2750 {} +
    find "$target" -type d -exec chmod u-s {} + 2>/dev/null || true
    find "$target" -type d -exec chmod -t {} + 2>/dev/null || true
    find "$target" -type f -exec chmod 640 {} +
  else
    clear_path_acl "$target"
    chmod 640 "$target"
  fi
}

require_ip_or_cidr() {
  # Loose check; we trust ufw to do the final parsing.
  [[ "$1" =~ ^[0-9a-fA-F.:/]+$ ]] || deny "invalid IP/CIDR: $1"
}

cmd="${1:-}"
shift || true
audit_log "$@"

case "$cmd" in

  # ---- systemctl --------------------------------------------------------
  systemctl)
    [[ $# -ge 2 ]] || deny "usage: systemctl <service> <action>"
    service="$1"; action="$2"
    is_allowed_service "$service" || deny "service not allowed: $service"
    is_in "$action" "${ALLOWED_ACTIONS[@]}" || deny "action not allowed: $action"
    if [[ "$action" == "stop" && ( "$service" == "bpanel-api" || "$service" == "redis-server" ) ]]; then
      deny "refusing to stop panel-critical service: $service"
    fi
    exec systemctl "$action" "$service"
    ;;

  daemon-reload)
    exec systemctl daemon-reload
    ;;

  # ---- nginx ------------------------------------------------------------
  nginx-test)
    exec nginx -t
    ;;

  nginx-reload)
    nginx -t
    exec systemctl reload nginx
    ;;
  nginx-custom-write)
    [[ $# -eq 1 ]] || deny "usage: nginx-custom-write <domain>"
    domain="$1"
    require_domain "$domain"
    ensure_nginx_conf_dir_writable
    target="${NGINX_CUSTOM_DIR}/${domain}.conf"
    tmp="${target}.tmp.$$"
    cat >"$tmp"
    if file_has_nul "$tmp"; then
      rm -f "$tmp"
      deny "custom nginx include contains NUL byte"
    fi
    install -m 0664 -o root -g bpanel "$tmp" "$target"
    rm -f "$tmp"
    ;;
  nginx-custom-delete)
    [[ $# -eq 1 ]] || deny "usage: nginx-custom-delete <domain>"
    domain="$1"
    require_domain "$domain"
    rm -f "${NGINX_CUSTOM_DIR}/${domain}.conf"
    ;;

  fastcgi-cache-clear)
    [[ $# -eq 0 ]] || deny "usage: fastcgi-cache-clear"
    install -d -o www-data -g www-data -m 0755 /var/cache/nginx/bpanel-fastcgi
    find /var/cache/nginx/bpanel-fastcgi -mindepth 1 -delete
    ;;

  # ---- updates ----------------------------------------------------------
  updates-status)
    echo "BPanel release status:"
    if [[ -f "${BPANEL_DATA_DIR}/update-status.json" ]]; then
      cat "${BPANEL_DATA_DIR}/update-status.json"
    else
      echo "No update status file found."
    fi
    echo ""
    echo "APT upgradable packages:"
    apt list --upgradable 2>/dev/null | sed -n '1,60p' || true
    echo ""
    echo "Unattended upgrades:"
    systemctl is-enabled unattended-upgrades.service 2>/dev/null || true
    systemctl is-active unattended-upgrades.service 2>/dev/null || true
    echo ""
    echo "Panel auto update timer:"
    systemctl is-enabled bpanel-auto-update.timer 2>/dev/null || true
    systemctl list-timers bpanel-auto-update.timer apt-daily-upgrade.timer --no-pager 2>/dev/null || true
    echo ""
    echo "OS update service:"
    systemctl is-active bpanel-os-update.service 2>/dev/null | sed 's/^inactive$/idle/' || true
    journalctl -u bpanel-os-update.service -n 16 --no-pager 2>/dev/null | grep -v "Failed to open /run/systemd/transient" || true
    echo ""
    echo "Panel update service:"
    systemctl is-active bpanel-panel-update.service 2>/dev/null | sed 's/^inactive$/idle/' || true
    journalctl -u bpanel-panel-update.service -n 16 --no-pager 2>/dev/null | grep -v "Failed to open /run/systemd/transient" || true
    ;;

  updates-os-run)
    run_os_update
    ;;

  updates-os-auto)
    [[ $# -eq 3 ]] || deny "usage: updates-os-auto <on|off> <security|all> <on|off>"
    configure_unattended_upgrades "$1" "$2" "$3"
    ;;

  updates-panel-run)
    run_panel_update
    ;;

  updates-panel-auto)
    [[ $# -eq 2 ]] || deny "usage: updates-panel-auto <on|off> <HH:MM>"
    write_panel_auto_update_timer "$1" "$2"
    ;;

  # ---- WAF --------------------------------------------------------------
  waf-status)
    waf_status
    ;;

  waf-install)
    install_waf_engine
    ;;

  waf-update)
    write_modsec_main_conf
    nginx -t
    systemctl reload nginx
    echo "BPanel lightweight WAF rules refreshed"
    ;;

  waf-default-rules)
    write_waf_default_rules
    exec cat /etc/nginx/modsec/bpanel-default.conf
    ;;

  waf-custom-rules)
    touch /etc/nginx/modsec/bpanel-custom.conf
    exec cat /etc/nginx/modsec/bpanel-custom.conf
    ;;

  waf-custom-save)
    save_waf_custom_rules
    ;;
  waf-site-rules)
    [[ $# -eq 1 ]] || deny "usage: waf-site-rules <domain>"
    require_domain "$1"
    exec cat "/etc/nginx/modsec/sites/${1}.conf"
    ;;
  waf-site-save)
    [[ $# -eq 1 ]] || deny "usage: waf-site-save <domain>"
    save_waf_site_rules "$1"
    ;;
  http-flood-zones-save)
    [[ $# -eq 0 ]] || deny "usage: http-flood-zones-save"
    save_http_flood_zones
    ;;

  # ---- PHP installation --------------------------------------------------
  php-install)
    [[ $# -eq 1 ]] || deny "usage: php-install <version>"
    install_php_version "$1"
    ;;

  php-config-write)
    [[ $# -eq 1 ]] || deny "usage: php-config-write <version>"
    write_php_config "$1"
    ;;

  php-fpm-retune)
    [[ $# -eq 0 ]] || deny "usage: php-fpm-retune"
    retune_php_fpm_pools
    ;;

  mariadb-retune)
    [[ $# -eq 0 ]] || deny "usage: mariadb-retune"
    retune_mariadb
    ;;

  # ---- panel runtime ----------------------------------------------------
  panel-url-set)
    [[ $# -eq 3 ]] || deny "usage: panel-url-set <http|https> <host> <port>"
    scheme="$1"; host="$2"; port="$3"
    require_panel_scheme "$scheme"
    require_panel_host "$host"
    require_port "$port"
    env_set PANEL_PORT "$port"
    env_set PANEL_URL "${scheme}://${host}:${port}"
    env_set ALLOWED_ORIGINS "${scheme}://${host}:${port}"
    if is_domain "$host"; then
      env_set PANEL_DOMAIN "$host"
    else
      env_set PANEL_DOMAIN ""
    fi
    if [[ "$scheme" == "http" ]]; then
      env_set PANEL_SSL_CERT ""
      env_set PANEL_SSL_KEY ""
    fi
    allow_panel_port "$port"
    refresh_tools_nginx
    schedule_panel_restart
    echo "Panel URL: ${scheme}://${host}:${port}"
    ;;

  panel-ssl-install)
    [[ $# -ge 2 && $# -le 3 ]] || deny "usage: panel-ssl-install <domain> <port> [email]"
    domain="$1"; port="$2"; email="${3:-}"
    require_domain "$domain"
    require_port "$port"
    certbot_args=(certonly --standalone
      -d "$domain" \
      --agree-tos \
      --non-interactive \
      --pre-hook "systemctl stop nginx || true" \
      --post-hook "systemctl start nginx || true" \
      --deploy-hook "install -d -o root -g bpanel -m 0750 /etc/bpanel && install -m 0640 -o root -g bpanel /etc/letsencrypt/live/${domain}/fullchain.pem /etc/bpanel/panel-fullchain.pem && install -m 0640 -o root -g bpanel /etc/letsencrypt/live/${domain}/privkey.pem /etc/bpanel/panel-privkey.pem")
    if [[ -n "$email" ]]; then
      require_email "$email"
      certbot_args+=(--email "$email")
    else
      certbot_args+=(--register-unsafely-without-email)
    fi
    certbot "${certbot_args[@]}"
    install -d -o root -g bpanel -m 0750 /etc/bpanel
    install -m 0640 -o root -g bpanel "/etc/letsencrypt/live/${domain}/fullchain.pem" /etc/bpanel/panel-fullchain.pem
    install -m 0640 -o root -g bpanel "/etc/letsencrypt/live/${domain}/privkey.pem" /etc/bpanel/panel-privkey.pem
    env_set PANEL_DOMAIN "$domain"
    env_set PANEL_PORT "$port"
    env_set PANEL_SSL_CERT "/etc/bpanel/panel-fullchain.pem"
    env_set PANEL_SSL_KEY "/etc/bpanel/panel-privkey.pem"
    env_set PANEL_URL "https://${domain}:${port}"
    env_set ALLOWED_ORIGINS "https://${domain}:${port}"
    if [[ -n "$email" ]]; then
      env_set SSL_EMAIL "$email"
    fi
    allow_panel_port "$port"
    refresh_tools_nginx
    schedule_panel_restart
    echo "Panel SSL enabled: https://${domain}:${port}"
    ;;

  # ---- certbot ----------------------------------------------------------
  certbot-issue)
    [[ $# -ge 1 ]] || deny "usage: certbot-issue <domain> [email]"
    domain="$1"; email="${2:-}"
    require_domain "$domain"
    install -d -o root -g bpanel -m 0755 /var/www/bpanel-acme/.well-known/acme-challenge
    if [[ -f "/etc/nginx/conf.d/${domain}.conf" ]]; then
      if grep -q "/var/lib/bpanel/acme-challenges" "/etc/nginx/conf.d/${domain}.conf"; then
        cp -a "/etc/nginx/conf.d/${domain}.conf" "/etc/nginx/conf.d/${domain}.conf.bak"
        sed -i 's#/var/lib/bpanel/acme-challenges#/var/www/bpanel-acme#g' "/etc/nginx/conf.d/${domain}.conf"
        nginx -t && systemctl reload nginx
      elif ! grep -q "well-known/acme-challenge" "/etc/nginx/conf.d/${domain}.conf"; then
        cp -a "/etc/nginx/conf.d/${domain}.conf" "/etc/nginx/conf.d/${domain}.conf.bak"
        python3 - "$domain" <<'PY'
from pathlib import Path
import sys

domain = sys.argv[1]
path = Path(f"/etc/nginx/conf.d/{domain}.conf")
content = path.read_text(encoding="utf-8")
block = """\

    # BPANEL ACME CHALLENGE
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/bpanel-acme;
        default_type text/plain;
        try_files $uri =404;
        access_log off;
        auth_basic off;
    }
"""
marker = "    client_max_body_size"
if marker in content:
    line_end = content.find("\n", content.find(marker))
    content = content[: line_end + 1] + block + content[line_end + 1 :]
else:
    content = content.replace("\n    location / {", block + "\n    location / {", 1)
path.write_text(content, encoding="utf-8")
PY
        nginx -t && systemctl reload nginx
      fi
    fi
    args=(certonly --webroot -w /var/www/bpanel-acme -d "$domain" --non-interactive --agree-tos)
    if [[ -n "$email" ]]; then
      require_email "$email"
      args+=(--email "$email")
    else
      args+=(--register-unsafely-without-email)
    fi
    certbot "${args[@]}"
    exec certbot install --nginx --cert-name "$domain" -d "$domain" --non-interactive --redirect
    ;;

  certbot-renew)
    exec certbot renew --quiet
    ;;
  certbot-renew-soon)
    [[ $# -le 1 ]] || deny "usage: certbot-renew-soon [days]"
    renew_ssl_soon "${1:-10}"
    ;;
  certbot-auto-renew-install)
    write_ssl_auto_renew_timer
    echo "SSL auto-renew timer installed"
    ;;
  manual-ssl-install)
    [[ $# -eq 1 ]] || deny "usage: manual-ssl-install <domain>"
    install_manual_ssl "$1"
    ;;
  manual-ssl-remove)
    [[ $# -eq 1 ]] || deny "usage: manual-ssl-remove <domain>"
    remove_manual_ssl "$1"
    ;;

  # ---- ufw --------------------------------------------------------------
  ufw-status)
    exec ufw status numbered
    ;;
  ufw-enable)
    exec ufw --force enable
    ;;
  ufw-disable)
    exec ufw --force disable
    ;;
  ufw-reload)
    exec ufw reload
    ;;
  ufw-allow-port)
    [[ $# -eq 2 ]] || deny "usage: ufw-allow-port <port> <proto>"
    require_port "$1"; require_proto "$2"
    ufw allow "${1}/${2}" comment "bpanel:UserZone" \
      || ufw allow "${1}/${2}"
    ;;
  ufw-panel-allow-port)
    [[ $# -eq 1 ]] || deny "usage: ufw-panel-allow-port <port>"
    ufw_panel_allow_port "$1"
    ;;
  ufw-allow-ip)
    [[ $# -ge 1 && $# -le 3 ]] || deny "usage: ufw-allow-ip <ip> [port] [proto]"
    run_ufw_ip_rule allow "$1" "${2:-}" "${3:-tcp}"
    ;;
  ufw-deny-ip)
    [[ $# -ge 1 && $# -le 3 ]] || deny "usage: ufw-deny-ip <ip> [port] [proto]"
    run_ufw_ip_rule deny "$1" "${2:-}" "${3:-tcp}"
    ;;
  ufw-delete)
    [[ $# -eq 1 && "$1" =~ ^[0-9]+$ ]] || deny "usage: ufw-delete <number>"
    exec ufw --force delete "$1"
    ;;
  nginx-blocklist-status|ufw-blocklist-status)
    firewall_blocklist_status
    ;;
  nginx-blocklist-timer-install|ufw-blocklist-timer-install)
    firewall_blocklist_write_timer
    echo "Nginx blocklist timer installed"
    ;;
  nginx-blocklist-add|ufw-blocklist-add)
    [[ $# -eq 1 ]] || deny "usage: nginx-blocklist-add <url>"
    firewall_blocklist_add_url "$1"
    ;;
  nginx-blocklist-delete|ufw-blocklist-delete)
    [[ $# -eq 1 ]] || deny "usage: nginx-blocklist-delete <url>"
    firewall_blocklist_delete_url "$1"
    ;;
  nginx-blocklist-run|ufw-blocklist-run)
    [[ $# -eq 0 ]] || deny "usage: nginx-blocklist-run"
    firewall_blocklist_run
    ;;

  # ---- filesystem -------------------------------------------------------
  chown-www)
    [[ $# -eq 1 ]] || deny "usage: chown-www <path>"
    target=$(require_managed_path "$1")
    chown -R www-data:www-data "$target"
    find "$target" -type d -exec chmod 750 {} +
    find "$target" -type d -exec chmod a-s {} + 2>/dev/null || true
    find "$target" -type d -exec chmod -t {} + 2>/dev/null || true
    find "$target" -type f -exec chmod 640 {} +
    ;;

  fix-permissions)
    [[ $# -ge 1 && $# -le 2 ]] || deny "usage: fix-permissions <path> [site-user]"
    target=$(require_managed_path "$1" "${2:-}")
    if [[ $# -eq 2 ]]; then
      fix_site_tree "$target" "$2"
      exit 0
    fi
    chown -R www-data:www-data "$target"
    if command -v setfacl >/dev/null 2>&1; then
      setfacl -Rb "$target" 2>/dev/null || true
      find "$target" -type d -exec setfacl -k {} + 2>/dev/null || true
    fi
    find "$target" -type d -exec chmod 750 {} +
    find "$target" -type d -exec chmod a-s {} + 2>/dev/null || true
    find "$target" -type d -exec chmod -t {} + 2>/dev/null || true
    find "$target" -type f -exec chmod 640 {} +
    ;;

  site-path-fix)
    [[ $# -eq 2 ]] || deny "usage: site-path-fix <path> <site-user>"
    target=$(require_managed_path "$1" "$2")
    fix_site_tree "$target" "$2"
    ;;

  site-document-root-ensure)
    [[ $# -eq 3 ]] || deny "usage: site-document-root-ensure <site-user> <site-root> <relative-path>"
    user="$1"; root_arg="$2"; rel_arg="$3"
    ensure_sites_group
    require_linux_user "$user"
    root_target=$(require_managed_path "$root_arg" "$user")
    [[ "$rel_arg" =~ ^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$ ]] || deny "unsafe relative path: $rel_arg"
    case "$rel_arg" in
      ""|"/"|/*|*$'\n'*|"."|".."|"./"*|"../"*|*"/."|*"/.."|*"/./"*|*"/../"*) deny "unsafe relative path: $rel_arg" ;;
    esac
    target=$(require_safe_path "$root_target" "$root_target/$rel_arg")
    mkdir -p -- "$target"
    harden_site_dir_path "$root_target" "$target" "$user"
    ;;

  site-file-write)
    [[ $# -eq 3 || $# -eq 4 ]] || deny "usage: site-file-write <site-user> <site-root> <relative-path> [0644|0640]"
    user="$1"; root_arg="$2"; rel_arg="$3"; mode_arg="${4:-0644}"
    require_linux_user "$user"
    [[ "$mode_arg" == "0644" || "$mode_arg" == "0640" ]] || deny "invalid file mode: $mode_arg"
    [[ "$mode_arg" == "0644" ]] && mode_arg="0640"
    root_target=$(require_managed_path "$root_arg" "$user")
    case "$rel_arg" in
      ""|"/"|/*|*$'\n'*|".."|"../"*|*"/.."|*"/../"*) deny "unsafe relative path: $rel_arg" ;;
    esac
    target=$(require_safe_path "$root_target" "$root_target/$rel_arg")
    [[ -d "$target" ]] && deny "cannot write a directory: $target"
    [[ -L "$target" ]] && deny "refusing to write through a symlink: $target"
    parent=$(dirname -- "$target")
    runuser -u "$user" -- mkdir -p -- "$parent"
    harden_site_dir_path "$root_target" "$parent" "$user"
    existing_mode=""
    if [[ -e "$target" ]]; then
      existing_mode=$(stat -c '%a' -- "$target")
    fi
    base=$(basename -- "$target")
    tmp="$parent/.${base}.bpanel-write-$$"
    rm -f -- "$tmp"
    cat >"$tmp"
    chown "$user:$BPANEL_SITES_GROUP" "$tmp"
    chmod "$mode_arg" "$tmp"
    mv -f -- "$tmp" "$target"
    ;;

  site-file-install)
    [[ $# -eq 4 ]] || deny "usage: site-file-install <site-user> <site-root> <relative-path> <staged-path>"
    user="$1"; root_arg="$2"; rel_arg="$3"; staged_arg="$4"
    require_linux_user "$user"
    root_target=$(require_managed_path "$root_arg" "$user")
    case "$rel_arg" in
      ""|"/"|/*|*$'\n'*|".."|"../"*|*"/.."|*"/../"*) deny "unsafe relative path: $rel_arg" ;;
    esac
    target=$(require_safe_path "$root_target" "$root_target/$rel_arg")
    [[ ! -L "$target" ]] || deny "refusing to write through a symlink: $target"
    [[ "$staged_arg" == /tmp/bpanel-upload-* ]] || deny "invalid staged upload path"
    [[ ! -L "$staged_arg" ]] || deny "staged upload cannot be a symlink"
    staged=$(readlink -e -- "$staged_arg") || deny "staged upload not found"
    [[ "$staged" == /tmp/bpanel-upload-* && -f "$staged" ]] || deny "invalid staged upload"
    [[ "$(stat -c '%U' -- "$staged")" == "bpanel" ]] || deny "staged upload must be owned by bpanel"
    parent=$(dirname -- "$target")
    runuser -u "$user" -- mkdir -p -- "$parent"
    harden_site_dir_path "$root_target" "$parent" "$user"
    base=$(basename -- "$target")
    tmp="$parent/.${base}.bpanel-install-$$"
    rm -f -- "$tmp"
    install -o "$user" -g "$BPANEL_SITES_GROUP" -m 0640 -- "$staged" "$tmp"
    mv -f -- "$tmp" "$target"
    rm -f -- "$staged"
    ;;

  site-archive-extract)
    [[ $# -eq 7 ]] || deny "usage: site-archive-extract <site-user> <site-root> <archive-path> <destination-path> <zip|tar.gz> <max-items> <max-bytes>"
    user="$1"; root_arg="$2"; archive_rel="$3"; destination_rel="$4"; archive_kind="$5"
    max_items="$6"; max_bytes="$7"
    require_linux_user "$user"
    [[ "$archive_kind" == "zip" || "$archive_kind" == "tar.gz" ]] || deny "unsupported archive type"
    [[ "$max_items" =~ ^[0-9]+$ && "$max_bytes" =~ ^[0-9]+$ ]] || deny "invalid archive limits"
    root_target=$(require_managed_path "$root_arg" "$user")
    archive_target=$(require_safe_path "$root_target" "$root_target/$archive_rel")
    destination_target=$(require_safe_path "$root_target" "$root_target/$destination_rel")
    [[ -f "$archive_target" && ! -L "$archive_target" ]] || deny "archive not found"
    [[ -d "$destination_target" && ! -L "$destination_target" ]] || deny "archive destination not found"
    tmp_archive=$(mktemp "/tmp/bpanel-extract-XXXXXX")
    trap 'rm -f -- "$tmp_archive"' EXIT
    install -o "$user" -g "$user" -m 0600 -- "$archive_target" "$tmp_archive"
    runuser -u "$user" -- python3 - "$tmp_archive" "$archive_kind" "$destination_target" "$max_items" "$max_bytes" "$archive_target" <<'PY'
import os
import shutil
import stat
import sys
import tarfile
import zipfile

archive_path, archive_kind, destination = sys.argv[1:4]
max_items, max_bytes = int(sys.argv[4]), int(sys.argv[5])
source_archive = os.path.realpath(sys.argv[6])
destination = os.path.realpath(destination)


def safe_target(name):
    """Normalize backslash paths and resolve to a safe absolute path."""
    if "\x00" in name:
        raise ValueError("archive contains an unsafe path")
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized.split("/", 1)[0]:
        raise ValueError("archive contains an absolute path")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ValueError("archive contains an unsafe path")
    target = os.path.abspath(os.path.join(destination, *parts))
    resolved = os.path.realpath(target)
    if os.path.commonpath((destination, resolved)) != destination:
        raise ValueError("archive path escapes destination")
    return target, resolved


def zip_implied_dirs(infos):
    implied = set()
    for info in infos:
        parts = [part for part in info.filename.replace("\\", "/").split("/") if part not in ("", ".")]
        for index in range(1, len(parts)):
            implied.add("/".join(parts[:index]))
    return implied


def _is_dir_entry(info, implied_dirs):
    """Return True if a ZipInfo represents a directory."""
    normalized = info.filename.replace("\\", "/")
    if info.is_dir() or normalized.endswith("/"):
        return True
    mode = (info.external_attr >> 16) & 0o170000
    if stat.S_ISDIR(mode) and info.file_size == 0:
        return True
    if info.file_size == 0 and normalized.rstrip("/") in implied_dirs:
        return True
    return False


def is_source_archive(resolved):
    return resolved == source_archive


def ensure_regular_target(target):
    if os.path.islink(target):
        raise ValueError("refusing to overwrite a symlink")
    if os.path.isdir(target):
        raise ValueError("archive file conflicts with an existing directory")


def ensure_directory_target(target):
    if os.path.islink(target):
        raise ValueError("refusing to overwrite a symlink")
    if os.path.exists(target) and not os.path.isdir(target):
        try:
            if os.path.getsize(target) == 0:
                return
        except OSError:
            pass
        raise ValueError("archive directory conflicts with an existing file")


def validate_zip():
    count = 0
    total = 0
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        implied_dirs = zip_implied_dirs(infos)
        for info in infos:
            count += 1
            if max_items and count > max_items:
                raise ValueError("archive has too many files")
            target, resolved = safe_target(info.filename)
            mode = (info.external_attr >> 16) & 0o170000
            if stat.S_ISLNK(mode):
                raise ValueError("archive symlinks are not allowed")
            if is_source_archive(resolved):
                continue
            if _is_dir_entry(info, implied_dirs):
                ensure_directory_target(target)
                continue
            ensure_regular_target(target)
            total += info.file_size
            if max_bytes and total > max_bytes:
                raise ValueError("archive is too large")


def extract_zip():
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        implied_dirs = zip_implied_dirs(infos)
        for info in infos:
            target, resolved = safe_target(info.filename)
            if is_source_archive(resolved):
                continue
            if _is_dir_entry(info, implied_dirs):
                if os.path.exists(target) and not os.path.isdir(target):
                    os.unlink(target)
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            try:
                with archive.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
            except RuntimeError as exc:
                raise ValueError("archive entry cannot be extracted") from exc


def validate_tar():
    count = 0
    total = 0
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            count += 1
            if max_items and count > max_items:
                raise ValueError("archive has too many files")
            target, resolved = safe_target(member.name)
            if member.issym() or member.islnk() or member.isdev():
                raise ValueError("archive links and devices are not allowed")
            if is_source_archive(resolved):
                continue
            if not member.isdir() and not member.isfile():
                raise ValueError("archive contains unsupported entries")
            if member.isdir():
                ensure_directory_target(target)
                continue
            ensure_regular_target(target)
            total += member.size
            if max_bytes and total > max_bytes:
                raise ValueError("archive is too large")


def extract_tar():
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            target, resolved = safe_target(member.name)
            if is_source_archive(resolved):
                continue
            if member.isdir():
                os.makedirs(target, exist_ok=True)
                continue
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("archive entry cannot be extracted")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with source, open(target, "wb") as dst:
                shutil.copyfileobj(source, dst, length=1024 * 1024)


if archive_kind == "zip":
    validate_zip()
    extract_zip()
else:
    validate_tar()
    extract_tar()
PY
    # The archive may contain an entry with its own filename. Restore the
    # original source archive after extraction so it cannot overwrite itself.
    install -o "$user" -g "$BPANEL_SITES_GROUP" -m 0640 -- "$tmp_archive" "$archive_target"
    fix_site_tree "$destination_target" "$user"
    rm -f -- "$tmp_archive"
    trap - EXIT
    ;;

  panel-user-ensure)
    [[ $# -eq 1 ]] || deny "usage: panel-user-ensure <panel-user>"
    ensure_panel_user_home "$1"
    ;;

  panel-user-password)
    [[ $# -eq 1 ]] || deny "usage: panel-user-password <panel-user>"
    set_panel_user_password "$1"
    ;;

  panel-user-delete)
    [[ $# -eq 1 ]] || deny "usage: panel-user-delete <panel-user>"
    delete_panel_user_runtime "$1"
    ;;

  site-runtime-ensure)
    [[ $# -eq 3 ]] || deny "usage: site-runtime-ensure <site-user> <path> <php-version|none>"
    user="$1"; path="$2"; php_version="$3"
    require_linux_user "$user"
    target=$(require_managed_path "$path" "$user")
    ensure_panel_user_home "$user"
    if [[ -d "$target/public" && ! -e "$target/public_html" ]]; then
      mv "$target/public" "$target/public_html"
    elif [[ -d "$target/public" && -d "$target/public_html" && -z "$(find "$target/public_html" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
      rmdir "$target/public_html"
      mv "$target/public" "$target/public_html"
    fi
    mkdir -p "$target/public_html"
    harden_site_dir_path "$target" "$target/public_html" "$user"
    fix_site_tree "$target" "$user"
    ensure_php_pool "$user" "$target" "$php_version"
    ;;

  site-runtime-move)
    [[ $# -eq 4 ]] || deny "usage: site-runtime-move <site-user> <old-path> <new-path> <php-version|none>"
    user="$1"; old_path="$2"; new_path="$3"; php_version="$4"
    require_linux_user "$user"
    old_target=$(require_managed_path "$old_path")
    new_target=$(require_managed_path "$new_path" "$user")
    old_user="${old_target#${HOME_ROOT}/}"
    old_user="${old_user%%/*}"
    ensure_panel_user_home "$user"
    if [[ "$old_target" != "$new_target" ]]; then
      [[ ! -e "$new_target" ]] || deny "target path already exists: $new_target"
      delete_site_php_pools "$old_user" "$old_target"
      mkdir -p "$(dirname "$new_target")"
      mv "$old_target" "$new_target"
    fi
    if [[ -d "$new_target/public" && ! -e "$new_target/public_html" ]]; then
      mv "$new_target/public" "$new_target/public_html"
    fi
    mkdir -p "$new_target/public_html"
    harden_site_dir_path "$new_target" "$new_target/public_html" "$user"
    fix_site_tree "$new_target" "$user"
    ensure_php_pool "$user" "$new_target" "$php_version"
    ;;

  site-runtime-delete)
    [[ $# -eq 2 ]] || deny "usage: site-runtime-delete <site-user> <path>"
    user="$1"; path="$2"
    require_linux_user "$user"
    target=$(require_managed_path "$path" "$user")
    delete_site_php_pools "$user" "$target"
    exec rm -rf "$target"
    ;;

  rm-site)
    [[ $# -eq 1 ]] || deny "usage: rm-site <path>"
    target=$(require_managed_path "$1")
    relative="${target#${HOME_ROOT}/}"
    [[ "$relative" != */* ]] && deny "refusing to delete a panel user home"
    exec rm -rf "$target"
    ;;

  mkdir-site)
    [[ $# -eq 1 ]] || deny "usage: mkdir-site <path>"
    target=$(require_managed_path "$1")
    install -d -o www-data -g www-data -m 0750 "$target"
    install -d -o www-data -g www-data -m 0750 "$target/public_html"
    ;;

  site-log-read)
    [[ $# -eq 3 ]] || deny "usage: site-log-read <domain> <access|error> <lines>"
    read_site_log "$1" "$2" "$3"
    ;;

  # ---- WP-CLI as www-data ----------------------------------------------
  wp)
    [[ $# -ge 1 ]] || deny "usage: wp <args...>"
    exec runuser -u www-data -- env HOME=/var/www WP_CLI_PHP_ARGS='-d pcre.jit=0' php -d pcre.jit=0 /usr/local/bin/wp "$@"
    ;;

  wp-site)
    [[ $# -ge 2 ]] || deny "usage: wp-site <site-user> <args...>"
    user="$1"; shift
    require_linux_user "$user"
    exec runuser -u "$user" -- env HOME="$HOME_ROOT/$user" WP_CLI_PHP_ARGS='-d pcre.jit=0' php -d pcre.jit=0 /usr/local/bin/wp "$@"
    ;;

  # ---- crontab managed for www-data ------------------------------------
  cron-list)
    user="${1:-www-data}"
    if [[ "$user" != "www-data" ]]; then require_linux_user "$user"; fi
    exec runuser -u "$user" -- crontab -l 2>/dev/null
    ;;
  cron-write)
    # crontab content is fed via stdin
    user="${1:-www-data}"
    if [[ "$user" != "www-data" ]]; then require_linux_user "$user"; fi
    exec runuser -u "$user" -- crontab -
    ;;

  # ---- service status (read-only, no privilege change needed but useful)
  service-status)
    [[ $# -eq 1 ]] || deny "usage: service-status <service>"
    is_allowed_service "$1" || deny "service not allowed: $1"
    exec systemctl status "$1" --no-pager
    ;;

  # ---- terminal command execution as panel Linux user ------------------
  terminal-exec)
    # Execute a whitelisted command as the panel Linux user
    # Args: <site-user> <cwd> [--php-version=<version>] <command> [args...]
    [[ $# -ge 3 ]] || deny "usage: terminal-exec <site-user> <cwd> [--php-version=<version>] <command> [args...]"
    user="$1"; cwd_arg="$2"; shift 2
    php_version=""
    if [[ "${1:-}" == --php-version=* ]]; then
      php_version="${1#--php-version=}"
      require_php_version "$php_version"
      shift
    fi
    [[ $# -ge 1 ]] || deny "usage: terminal-exec <site-user> <cwd> [--php-version=<version>] <command> [args...]"
    cmd="$1"; shift
    require_linux_user "$user"
    id -u "$user" >/dev/null 2>&1 || deny "panel Linux user does not exist: $user"
    target=$(require_terminal_cwd "$cwd_arg" "$user")

    install -d -o "$user" -g "$user" -m 0700 "$HOME_ROOT/$user/.composer" "$HOME_ROOT/$user/.npm"
    # Validate cwd exists immediately before cd to avoid TOCTOU
    [[ -d "$target" ]] || deny "working directory does not exist: $target"
    cd "$target" || deny "failed to change to working directory: $target"
    umask 027
    terminal_env=(
      "HOME=$HOME_ROOT/$user"
      "COMPOSER_HOME=$HOME_ROOT/$user/.composer"
      "npm_config_cache=$HOME_ROOT/$user/.npm"
      "PATH=/usr/local/bin:/usr/bin:/bin"
    )
    php_bin="php"
    if [[ -n "$php_version" ]]; then
      php_bin="php${php_version}"
      command -v "$php_bin" >/dev/null 2>&1 || deny "PHP CLI is not installed: $php_bin"
    fi

    # Whitelist of allowed commands for terminal access
    case "$cmd" in
      php)
        exec runuser -u "$user" -- env "${terminal_env[@]}" "$php_bin" "$@"
        ;;
      composer)
        composer_bin="$(command -v composer || true)"
        [[ -n "$composer_bin" ]] || deny "composer not found"
        exec runuser -u "$user" -- env "${terminal_env[@]}" "$php_bin" "$composer_bin" "$@"
        ;;
      phpunit)
        phpunit_bin="$(command -v phpunit || true)"
        [[ -n "$phpunit_bin" ]] || deny "phpunit not found"
        exec runuser -u "$user" -- env "${terminal_env[@]}" "$php_bin" "$phpunit_bin" "$@"
        ;;
      node|npm|npx|yarn|git)
        exec runuser -u "$user" -- env "${terminal_env[@]}" "$cmd" "$@"
        ;;
      ls|cat|mkdir|rm|cp|mv|chmod|chown|grep|find|tar|zip|unzip|diff|head|tail|less|du|df)
        require_terminal_path_args "$user" "$target" "$@"
        exec runuser -u "$user" -- env "${terminal_env[@]}" "$cmd" "$@"
        ;;
      pwd|echo|touch|date|whoami|which|clear)
        if [[ "$cmd" == "touch" ]]; then
          require_terminal_path_args "$user" "$target" "$@"
        fi
        exec runuser -u "$user" -- env "${terminal_env[@]}" "$cmd" "$@"
        ;;
      curl|wget)
        require_terminal_download_args "$user" "$target" "$@"
        exec runuser -u "$user" -- env "${terminal_env[@]}" "$cmd" "$@"
        ;;
      artisan)
        # artisan is a PHP script, executed via php
        [[ -f artisan ]] || deny "artisan not found in $target"
        exec runuser -u "$user" -- env "${terminal_env[@]}" "$php_bin" artisan "$@"
        ;;
      *)
        echo "Command not allowed: $cmd" >&2
        echo "Allowed commands: php, composer, artisan, node, npm, npx, yarn, git, phpunit, ls, cat, mkdir, rm, cp, mv, chmod, chown, pwd, echo, touch, grep, find, tar, zip, unzip, curl, wget, diff, head, tail, less, du, df, date, whoami, which, clear" >&2
        exit 126
        ;;
    esac
    ;;

  *)
    deny "unknown command: $cmd"
    ;;
esac
