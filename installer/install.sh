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
PANEL_HOSTNAME="${PANEL_HOSTNAME:-}"
PANEL_DOMAIN=""
PANEL_PORT="${PANEL_PORT:-2222}"
SERVER_IP=""
ENABLE_SSL="${ENABLE_SSL:-auto}"
SSL_EMAIL="${SSL_EMAIL:-}"
NODE_MAJOR="${NODE_MAJOR:-22}"
PHP_DEFAULT="${PHP_DEFAULT:-8.3}"
PHP_VERSIONS="${PHP_VERSIONS:-8.3 8.4}"
APP_DIR="${APP_DIR:-/opt/bpanel}"
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

detect_server_ip() {
  hostname -I 2>/dev/null | awk '{print $1}' || true
}

find_sshd() {
  if command -v sshd >/dev/null 2>&1; then
    command -v sshd
    return 0
  fi
  for candidate in /usr/sbin/sshd /usr/local/sbin/sshd; do
    [[ -x "$candidate" ]] && { echo "$candidate"; return 0; }
  done
  return 1
}

validate_port() {
  [[ "$1" =~ ^[0-9]{1,5}$ ]] || fail "Invalid PANEL_PORT: $1"
  (( $1 >= 1 && $1 <= 65535 )) || fail "PANEL_PORT out of range: $1"
}

detect_ssh_ports() {
  local sshd_bin
  sshd_bin="$(find_sshd || true)"
  {
    if [[ -n "$sshd_bin" ]]; then
      "$sshd_bin" -T 2>/dev/null | awk '$1 == "port" {print $2}'
    fi
    if [[ -n "${SSH_CONNECTION:-}" ]]; then
      awk '{print $4}' <<<"$SSH_CONNECTION"
    fi
    awk '
      tolower($1) == "port" && $2 ~ /^[0-9]+$/ { print $2 }
      tolower($1) == "listenaddress" {
        for (i = 2; i <= NF; i++) {
          value = $i
          gsub(/^\[/, "", value)
          gsub(/\]$/, "", value)
          if (value ~ /:[0-9]+$/) {
            sub(/^.*:/, "", value)
            print value
          }
        }
      }
    ' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null
  } | awk '$1 ~ /^[0-9]+$/ && $1 >= 1 && $1 <= 65535 {print $1}' | sort -nu
}

is_domain_name() {
  [[ "$1" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]]
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
  validate_port "$PANEL_PORT"
  if [[ -n "$PANEL_URL" ]]; then
    PANEL_URL="${PANEL_URL%/}"
    if [[ "$PANEL_URL" =~ ^https?:// ]]; then
      PANEL_HOSTNAME="$(echo "$PANEL_URL" | sed -E 's#^https?://([^/:]+).*#\1#')"
      parsed_port="$(echo "$PANEL_URL" | sed -nE 's#^https?://[^/:]+:([0-9]+).*#\1#p')"
    else
      PANEL_HOSTNAME="$(echo "$PANEL_URL" | sed -E 's#^([^/:]+).*#\1#')"
      parsed_port="$(echo "$PANEL_URL" | sed -nE 's#^[^/:]+:([0-9]+).*#\1#p')"
    fi
    if [[ -n "${parsed_port:-}" ]]; then
      PANEL_PORT="$parsed_port"
      validate_port "$PANEL_PORT"
    fi
  fi

  if [[ -z "$PANEL_HOSTNAME" ]]; then
    read -rp "Enter panel hostname (optional, blank = server IP): " PANEL_HOSTNAME
  fi
  PANEL_HOSTNAME="${PANEL_HOSTNAME#http://}"
  PANEL_HOSTNAME="${PANEL_HOSTNAME#https://}"
  PANEL_HOSTNAME="${PANEL_HOSTNAME%%/*}"
  if [[ "$PANEL_HOSTNAME" == *:* ]]; then
    parsed_port="${PANEL_HOSTNAME##*:}"
    PANEL_HOSTNAME="${PANEL_HOSTNAME%%:*}"
    [[ -n "$parsed_port" ]] && PANEL_PORT="$parsed_port"
    validate_port "$PANEL_PORT"
  fi
  if [[ -z "${PANEL_URL:-}" ]]; then
    read -rp "Enter panel port [${PANEL_PORT}]: " panel_port_answer
    if [[ -n "$panel_port_answer" ]]; then
      PANEL_PORT="$panel_port_answer"
      validate_port "$PANEL_PORT"
    fi
  fi

  if [[ -z "$PANEL_HOSTNAME" ]]; then
    SERVER_IP="$(detect_server_ip)"
    [[ -n "$SERVER_IP" ]] || fail "Cannot detect server IP. Set PANEL_HOSTNAME manually."
    PANEL_DOMAIN=""
    PANEL_URL="http://${SERVER_IP}:${PANEL_PORT}"
    ENABLE_SSL="no"
    return 0
  fi

  PANEL_DOMAIN="$PANEL_HOSTNAME"

  if [[ "$PANEL_DOMAIN" == "localhost" || "$PANEL_DOMAIN" == "127.0.0.1" || "$PANEL_DOMAIN" =~ ^[0-9.]+$ ]]; then
    ENABLE_SSL="no"
    PANEL_URL="http://${PANEL_DOMAIN}:${PANEL_PORT}"
  elif [[ "$ENABLE_SSL" == "auto" ]]; then
    if ! is_domain_name "$PANEL_DOMAIN"; then
      fail "Invalid panel domain: $PANEL_DOMAIN"
    fi
    read -rp "Enable Let's Encrypt SSL for ${PANEL_DOMAIN}:${PANEL_PORT}? [Y/n]: " ssl_answer
    ssl_answer="${ssl_answer:-Y}"
    if [[ "$ssl_answer" =~ ^[Nn]$ ]]; then
      ENABLE_SSL="no"
      PANEL_URL="http://${PANEL_DOMAIN}:${PANEL_PORT}"
    else
      ENABLE_SSL="yes"
      PANEL_URL="https://${PANEL_DOMAIN}:${PANEL_PORT}"
    fi
  elif [[ "$ENABLE_SSL" == "yes" ]]; then
    is_domain_name "$PANEL_DOMAIN" || fail "Invalid panel domain: $PANEL_DOMAIN"
    PANEL_URL="https://${PANEL_DOMAIN}:${PANEL_PORT}"
  else
    ENABLE_SSL="no"
    PANEL_URL="http://${PANEL_DOMAIN}:${PANEL_PORT}"
  fi

  if [[ "$ENABLE_SSL" == "yes" && -z "$SSL_EMAIL" ]]; then
    read -rp "Enter email for Let's Encrypt registration: " SSL_EMAIL
    [[ -n "$SSL_EMAIL" ]] || fail "Email is required to issue SSL"
  fi
}

install_base_packages() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y software-properties-common ca-certificates curl gnupg git composer nginx mariadb-server redis-server openssh-server python3 python3-pip python3-venv certbot python3-certbot-nginx tar openssl unzip ufw phpmyadmin acl
  systemctl enable --now nginx mariadb redis-server
  systemctl enable --now ssh 2>/dev/null || systemctl enable --now sshd 2>/dev/null || true
}

install_nodejs() {
  curl -fsSL --connect-timeout 10 --max-time 180 "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
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

install_ioncube_loader() {
  local version="$1" arch url tmp archive loader target_dir target loader_ini_dir
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
  tmp="$(mktemp -d)" || fail "Cannot create ionCube temporary directory"
  archive="${tmp}/ioncube_loaders.tar.gz"
  if ! curl -fsSL --connect-timeout 10 --max-time 300 "$url" -o "$archive"; then
    rm -rf -- "$tmp"
    fail "Failed to download ionCube Loader"
  fi
  if ! tar -xzf "$archive" -C "$tmp"; then
    rm -rf -- "$tmp"
    fail "Failed to unpack ionCube Loader"
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
      fail "ionCube Loader failed to load for PHP ${version}"
    fi
  fi
  echo "ionCube Loader enabled for PHP ${version}"
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
    install_ioncube_loader "$version"

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

configure_fastcgi_cache() {
  install -d -o www-data -g www-data -m 0755 /var/cache/nginx/bpanel-fastcgi
  cat >/etc/nginx/conf.d/00-bpanel-fastcgi-cache.conf <<'NGINX'
fastcgi_cache_path /var/cache/nginx/bpanel-fastcgi levels=1:2 keys_zone=BPANEL_FASTCGI:100m inactive=60m max_size=512m use_temp_path=off;
fastcgi_cache_key "$scheme$request_method$host$request_uri";
NGINX
}

write_modsec_base_conf() {
  install -d -o root -g root -m 0755 /etc/nginx/modsec /etc/nginx/modsec/sites
  {
    [[ -f /etc/modsecurity/modsecurity.conf ]] && echo "Include /etc/modsecurity/modsecurity.conf"
    echo "SecRuleEngine On"
    echo "SecRequestBodyAccess On"
    [[ -f /etc/modsecurity/crs/crs-setup.conf ]] && echo "Include /etc/modsecurity/crs/crs-setup.conf"
    [[ -f /etc/modsecurity/crs/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf ]] && echo "Include /etc/modsecurity/crs/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf"
    if compgen -G "/usr/share/modsecurity-crs/rules/*.conf" >/dev/null; then
      echo "Include /usr/share/modsecurity-crs/rules/*.conf"
    fi
    [[ -f /etc/modsecurity/crs/RESPONSE-999-EXCLUSION-RULES-AFTER-CRS.conf ]] && echo "Include /etc/modsecurity/crs/RESPONSE-999-EXCLUSION-RULES-AFTER-CRS.conf"
    if compgen -G "/etc/nginx/modsec/comodo/*.conf" >/dev/null; then
      echo "Include /etc/nginx/modsec/comodo/*.conf"
    fi
    if compgen -G "/etc/nginx/modsec/comodo/rules/*.conf" >/dev/null; then
      echo "Include /etc/nginx/modsec/comodo/rules/*.conf"
    fi
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

write_http_flood_nginx_conf() {
  install -d -o root -g root -m 0755 /etc/nginx/bpanel /etc/nginx/conf.d
  if [[ ! -f /etc/nginx/bpanel/http-flood-zones.conf ]]; then
    cat >/etc/nginx/bpanel/http-flood-zones.conf <<'CONF'
# Managed by BPanel. Shared zones for per-website HTTP flood protection.
map $cookie_bpanel_http_flood_ok $bpanel_http_flood_key {
    default $binary_remote_addr;
    1 "";
}
limit_conn_zone $bpanel_http_flood_key zone=bpanel_conn_flood:10m;
CONF
  fi
  cat >/etc/nginx/conf.d/00-bpanel-http-flood.conf <<'CONF'
# Managed by BPanel. Shared zones for per-website HTTP flood protection.
include /etc/nginx/bpanel/http-flood-zones.conf;
CONF
  rm -f /etc/nginx/conf.d/bpanel-http-flood.conf /etc/nginx/bpanel/http-flood-server.conf 2>/dev/null || true
  chown root:root /etc/nginx/conf.d/00-bpanel-http-flood.conf /etc/nginx/bpanel/http-flood-zones.conf
  chmod 0644 /etc/nginx/conf.d/00-bpanel-http-flood.conf /etc/nginx/bpanel/http-flood-zones.conf
}

write_waf_default_rules() {
  install -d -o root -g root -m 0755 /etc/nginx/modsec
  cat >/etc/nginx/modsec/bpanel-default.conf <<'RULES'
# BPanel default WAF rules. CRS remains the main ruleset; these protect common
# high-risk paths and payloads even when third-party rules are not installed.
SecRule REQUEST_URI "@rx (?i)(?:/\.env|/wp-config\.php|/\.git/|/composer\.(?:json|lock)|/vendor/phpunit|/etc/passwd)" "id:1001001,phase:1,deny,status:403,log,msg:'BPanel blocked sensitive file probe'"
SecRule REQUEST_URI|ARGS|REQUEST_HEADERS "@rx (?:\.\./|\.\.\\)" "id:1001002,phase:2,deny,status:403,log,msg:'BPanel blocked path traversal'"
SecRule ARGS|REQUEST_HEADERS|REQUEST_BODY "@rx (?i)(?:union\s+select|sleep\s*\(|benchmark\s*\(|load_file\s*\(|into\s+outfile|information_schema|extractvalue\s*\()" "id:1001003,phase:2,deny,status:403,log,msg:'BPanel blocked SQL injection pattern'"
SecRule ARGS|REQUEST_HEADERS|REQUEST_BODY "@rx (?i)(?:<script|javascript:|onerror\s*=|onload\s*=|document\.cookie|<iframe|base64_decode\s*\()" "id:1001004,phase:2,deny,status:403,log,msg:'BPanel blocked XSS pattern'"
SecRule ARGS|REQUEST_HEADERS|REQUEST_BODY "@rx (?i)(?:/bin/(?:bash|sh)|cmd\.exe|powershell|wget\s+https?://|curl\s+https?://|;\s*(?:id|whoami|uname)\b)" "id:1001005,phase:2,deny,status:403,log,msg:'BPanel blocked command injection pattern'"
SecRule REQUEST_URI "@rx (?i)(?:/wp-config\.php|/readme\.html|/license\.txt|/wp-content/(?:uploads|cache|upgrade)/.*\.php|/wp-admin/includes/.*\.php|/wp-includes/.*\.php)" "id:1001101,phase:1,deny,status:403,log,msg:'BPanel blocked WordPress sensitive path'"
SecRule REQUEST_URI "@streq /xmlrpc.php" "id:1001102,phase:1,deny,status:403,log,msg:'BPanel blocked WordPress XML-RPC'"
SecRule ARGS:author "@rx ^[0-9]+$" "id:1001103,phase:2,deny,status:403,log,msg:'BPanel blocked WordPress author enumeration'"
SecRule REQUEST_URI "@rx (?i)(?:/wp-admin/install\.php|/wp-admin/upgrade\.php|/wp-admin/setup-config\.php)" "id:1001104,phase:1,deny,status:403,log,msg:'BPanel blocked WordPress installer probe'"
SecRule REQUEST_URI "@rx (?i)(?:^/(?:artisan|server\.php)$|/\.env(?:\.|$)|/vendor/|/storage/(?:logs|framework|app)/|/bootstrap/cache/)" "id:1001201,phase:1,deny,status:403,log,msg:'BPanel blocked Laravel sensitive path'"
SecRule REQUEST_URI|ARGS|REQUEST_BODY "@rx (?i)(?:_ignition/execute-solution|_debugbar|php://filter|phar://|expect://|data://)" "id:1001202,phase:2,deny,status:403,log,msg:'BPanel blocked Laravel debug/RCE probe'"
SecRule REQUEST_URI "@rx (?i)(?:/configuration\.php|/(?:attachments|downloads|templates_c|crons)/(?:.*\.php|.*)?|/vendor/|/install/)" "id:1001301,phase:1,deny,status:403,log,msg:'BPanel blocked WHMCS sensitive path'"
SecRule REQUEST_URI "@rx (?i)(?:/(?:admin|admincp|whmcs-admin)/(?:setup|install|upgrade)|/modules/.*/(?:callback|hook)\.php\.bak)" "id:1001302,phase:1,deny,status:403,log,msg:'BPanel blocked WHMCS admin probe'"
SecRule REQUEST_URI "@rx (?i)(?:/(?:application|system)/(?:config|logs|cache|core|helpers|libraries)/|/writable/(?:logs|cache|session|uploads)/|/app/Config/)" "id:1001401,phase:1,deny,status:403,log,msg:'BPanel blocked CodeIgniter sensitive path'"
SecRule REQUEST_URI|ARGS "@rx (?i)(?:/\.env|/index\.php/_debugbar|/index\.php/profiler|CI_ENVIRONMENT\s*=)" "id:1001402,phase:2,deny,status:403,log,msg:'BPanel blocked CodeIgniter env/debug probe'"
RULES
}

install_waf_engine() {
  export DEBIAN_FRONTEND=noninteractive
  if ! dpkg -s libnginx-mod-http-modsecurity >/dev/null 2>&1; then
    apt-get update
    apt-get install -y libnginx-mod-http-modsecurity modsecurity-crs libmodsecurity3 || \
      apt-get install -y libnginx-mod-http-modsecurity libmodsecurity3
  fi
  install -d -o root -g root -m 0755 /etc/nginx/modsec /etc/nginx/modsec/comodo /etc/nginx/modsec/sites
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
  systemctl reload nginx || true
}

install_wp_cli() {
  if ! command -v wp >/dev/null 2>&1; then
    curl -fsSL --connect-timeout 10 --max-time 180 -o /usr/local/bin/wp https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar
    chmod +x /usr/local/bin/wp
  fi
}

copy_sources() {
  mkdir -p "$APP_DIR" "$BACKUP_ROOT"
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
  if ! getent group bpanel-sites >/dev/null; then
    groupadd --system bpanel-sites
  fi
  if ! getent group bpanel-sftp >/dev/null; then
    groupadd --system bpanel-sftp
  fi
  if ! id -u bpanel >/dev/null 2>&1; then
    useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin --user-group bpanel
  fi
  usermod -aG www-data bpanel || true
  usermod -aG bpanel-sites bpanel || true
  usermod -aG bpanel-sites www-data || true

  # Allow bpanel to write into /etc/nginx/conf.d (vhost files).
  install -d -o root -g bpanel -m 2775 /etc/nginx/conf.d
  # setgid so new files inherit the bpanel group; allows future writes.
  chmod g+s /etc/nginx/conf.d || true

  # Make the panel data dirs writable by bpanel.
  install -d -o bpanel -g bpanel -m 0750 "$APP_DIR"
  install -d -o bpanel -g bpanel -m 0750 "$BACKUP_ROOT"

  # MariaDB: create an admin user that bpanel can use without password
  # (auth via a defaults-file in ~bpanel/.my.cnf, mode 0600).
  local mariadb_password
  mariadb_password="$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-32)"
  mariadb -e "
    CREATE USER IF NOT EXISTS 'bpanel'@'localhost' IDENTIFIED BY '${mariadb_password}';
    GRANT ALL PRIVILEGES ON *.* TO 'bpanel'@'localhost' WITH GRANT OPTION;
    FLUSH PRIVILEGES;
  " 2>/dev/null || mysql -e "
    CREATE USER IF NOT EXISTS 'bpanel'@'localhost' IDENTIFIED BY '${mariadb_password}';
    GRANT ALL PRIVILEGES ON *.* TO 'bpanel'@'localhost' WITH GRANT OPTION;
    FLUSH PRIVILEGES;
  "

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

setup_sftp_access() {
  local sshd_config="/etc/ssh/sshd_config" backup
  getent group bpanel-sftp >/dev/null || groupadd --system bpanel-sftp
  install -d -o root -g root -m 0755 /run/sshd
  rm -f /etc/ssh/sshd_config.d/99-bpanel-sftp.conf 2>/dev/null || true
  touch "$sshd_config"
  backup="${sshd_config}.bpanel.bak"
  cp "$sshd_config" "$backup"
  sed -i '/^# BEGIN BPANEL SFTP USERS$/,/^# END BPANEL SFTP USERS$/d' "$sshd_config"
  cat >>"$sshd_config" <<'SSHD'
# BEGIN BPANEL SFTP USERS
# Allow BPanel Linux users to log in with SFTP using their panel password.
Match Group bpanel-sftp
    PasswordAuthentication yes
    X11Forwarding no
    AllowTcpForwarding no
# END BPANEL SFTP USERS
SSHD
  if ! sshd -t; then
    cp "$backup" "$sshd_config"
    fail "Invalid SSHD configuration for BPanel SFTP users"
  fi
  systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
}

install_privileged_helper() {
  install -m 0750 -o root -g bpanel "${SCRIPT_DIR}/files/bpanel-helper.sh" /usr/local/sbin/bpanel-helper
  sed -i "s#^APP_DIR=\"/opt/bpanel\"#APP_DIR=\"${APP_DIR}\"#" /usr/local/sbin/bpanel-helper
  install -m 0755 -o root -g root "${SCRIPT_DIR}/update.sh" /usr/local/sbin/bpanel-update
  install -m 0440 -o root -g root "${SCRIPT_DIR}/files/bpanel-sudoers" /etc/sudoers.d/bpanel
  visudo -c -f /etc/sudoers.d/bpanel >/dev/null
  install -m 0755 -o root -g root "${SCRIPT_DIR}/rescue-ufw-blocklist.sh" /usr/local/sbin/bpanel-rescue-ufw-blocklist
}

install_panel_cli() {
  install -m 0755 -o root -g root "${SCRIPT_DIR}/files/bpanelctl" /usr/local/sbin/bpanel
  ln -sfn /usr/local/sbin/bpanel /usr/local/sbin/bpanelctl
  sed -i "s#APP_DIR=\"\${APP_DIR:-/opt/bpanel}\"#APP_DIR=\"\${APP_DIR:-${APP_DIR}}\"#" /usr/local/sbin/bpanel /usr/local/sbin/bpanelctl 2>/dev/null || true
}

validate_privileged_helper() {
  sudo -u bpanel env HOME="$APP_DIR" sudo -n /usr/local/sbin/bpanel-helper wp --info >/dev/null
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
REDIS_URL=redis://localhost:6379/0
RATE_LIMIT_BACKEND=redis
ALLOWED_ORIGINS=${PANEL_URL}
BACKUP_ROOT=${BACKUP_ROOT}
SSL_EMAIL=${SSL_EMAIL}
PANEL_URL=${PANEL_URL}
PANEL_DOMAIN=${PANEL_DOMAIN}
PANEL_PORT=${PANEL_PORT}
PANEL_SSL_CERT=
PANEL_SSL_KEY=
FRONTEND_DIST=${APP_DIR}/frontend/dist
ENV

  BPANEL_USE_HELPER=true BPANEL_ADMIN_PASSWORD="$ADMIN_PASSWORD" python -m app.seed
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
    if curl -fsS --connect-timeout 2 --max-time 5 "http://127.0.0.1:${PANEL_PORT}/api/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  journalctl -u bpanel-api -n 80 --no-pager || true
  fail "bpanel-api did not respond at http://127.0.0.1:${PANEL_PORT}/api/health"
}

setup_systemd() {
  cat >/usr/local/sbin/bpanel-api-start <<STARTER
#!/usr/bin/env bash
# Trusted forwarders: only the local Nginx (127.0.0.1) is allowed to set
# X-Forwarded-For / X-Forwarded-Proto. Anything else (direct hits on
# the configured panel port) cannot spoof the audit log IP or the login rate-limit key.
set -euo pipefail
cd ${APP_DIR}/backend
args=(app.main:app --host 0.0.0.0 --port "\${PANEL_PORT:-2222}" --proxy-headers --forwarded-allow-ips "127.0.0.1")
if [[ -n "\${PANEL_SSL_CERT:-}" && -n "\${PANEL_SSL_KEY:-}" && -f "\${PANEL_SSL_CERT}" && -f "\${PANEL_SSL_KEY}" ]]; then
  args+=(--ssl-certfile "\${PANEL_SSL_CERT}" --ssl-keyfile "\${PANEL_SSL_KEY}")
fi
exec ${APP_DIR}/backend/.venv/bin/uvicorn "\${args[@]}"
STARTER
  chmod 0755 /usr/local/sbin/bpanel-api-start

  cat >/etc/systemd/system/bpanel-api.service <<SERVICE
[Unit]
Description=BPanel API
After=network.target mariadb.service

[Service]
Type=exec
User=bpanel
Group=bpanel
SupplementaryGroups=www-data bpanel-sites
WorkingDirectory=${APP_DIR}/backend
EnvironmentFile=${APP_DIR}/backend/.env
Environment=HOME=${APP_DIR}
Environment=BPANEL_USE_HELPER=true
ExecStart=/usr/local/sbin/bpanel-api-start
Restart=always
RestartSec=3

# Hardening. These settings must not block the sudo helper; privileged work is
# restricted by /usr/local/sbin/bpanel-helper and /etc/sudoers.d/bpanel.
NoNewPrivileges=false
ProtectSystem=false
ProtectHome=false
ReadWritePaths=${APP_DIR} /home ${BACKUP_ROOT} /etc/nginx/conf.d /tmp /var/lib/bpanel
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

  install -d -o bpanel -g bpanel -m 0750 /var/lib/bpanel
  cat >/etc/systemd/system/bpanel-backup-scheduler.service <<SERVICE
[Unit]
Description=BPanel scheduled backup runner
After=network.target mariadb.service

[Service]
Type=oneshot
User=bpanel
Group=bpanel
SupplementaryGroups=www-data bpanel-sites
WorkingDirectory=${APP_DIR}/backend
EnvironmentFile=${APP_DIR}/backend/.env
Environment=HOME=${APP_DIR}
Environment=BPANEL_USE_HELPER=true
ExecStart=${APP_DIR}/backend/.venv/bin/python -m app.services.backup_scheduler
NoNewPrivileges=false
ProtectSystem=false
ProtectHome=false
ReadWritePaths=${APP_DIR} /home ${BACKUP_ROOT} /etc/nginx/conf.d /tmp /var/lib/bpanel
PrivateTmp=true

[Install]
WantedBy=multi-user.target
SERVICE

  cat >/etc/systemd/system/bpanel-backup-scheduler.timer <<'SERVICE'
[Unit]
Description=Run BPanel scheduled backups every minute

[Timer]
OnBootSec=90s
OnUnitActiveSec=60s
AccuracySec=15s
Persistent=true

[Install]
WantedBy=timers.target
SERVICE

  systemctl daemon-reload
  systemctl enable --now bpanel-api
  systemctl enable --now bpanel-backup-scheduler.timer
  if id -u bpanel >/dev/null 2>&1; then
    sudo -u bpanel env HOME="$APP_DIR" sudo -n /usr/local/sbin/bpanel-helper certbot-auto-renew-install >/dev/null 2>&1 || true
    sudo -u bpanel env HOME="$APP_DIR" sudo -n /usr/local/sbin/bpanel-helper nginx-blocklist-timer-install >/dev/null 2>&1 || true
  fi
  wait_for_backend
}

write_tools_nginx_config() {
  local api_scheme="http" tools_scheme="http" pma_secure="false" ssl_block=""
  if [[ -n "${PANEL_SSL_CERT:-}" && -n "${PANEL_SSL_KEY:-}" && -f "${PANEL_SSL_CERT}" && -f "${PANEL_SSL_KEY}" ]]; then
    api_scheme="https"
    tools_scheme="https"
    pma_secure="true"
    printf -v ssl_block '\n    listen 443 ssl default_server;\n    ssl_certificate %s;\n    ssl_certificate_key %s;' "$PANEL_SSL_CERT" "$PANEL_SSL_KEY"
  fi

  cat >/etc/nginx/conf.d/00-bpanel-tools.conf <<NGINX
server {
    listen 80 default_server;${ssl_block}
    server_name _;
    client_max_body_size 1100M;

    location = /phpmyadmin {
        return 301 /phpmyadmin/;
    }

    location /phpmyadmin/ {
        alias /usr/share/phpmyadmin/;
        index index.php;
        try_files \$uri \$uri/ =404;
    }

    location ~ ^/phpmyadmin/(.+\.php)$ {
        alias /usr/share/phpmyadmin/\$1;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME /usr/share/phpmyadmin/\$1;
        fastcgi_param SCRIPT_NAME /phpmyadmin/\$1;
        fastcgi_pass unix:/run/php/php${PHP_DEFAULT}-fpm.sock;
        fastcgi_read_timeout 300;
    }
}
NGINX

  local host
  host="${PANEL_DOMAIN:-$SERVER_IP}"
  [[ -n "$host" ]] || host="$(detect_server_ip)"
  sed -i -E "/api\/databases\/phpmyadmin-sso/s#'[^']+/api/databases/phpmyadmin-sso/'#'${api_scheme}://127.0.0.1:${PANEL_PORT}/api/databases/phpmyadmin-sso/'#" /usr/share/phpmyadmin/bpanel-signon.php 2>/dev/null || true
  sed -i -E "s#('secure' => )(true|false)#\1${pma_secure}#" /etc/phpmyadmin/conf.d/bpanel-signon.php /usr/share/phpmyadmin/bpanel-signon.php 2>/dev/null || true
  sed -i -E "/PmaAbsoluteUri/s#'https?://[^']+/phpmyadmin/'#'${tools_scheme}://${host}/phpmyadmin/'#" /etc/phpmyadmin/conf.d/bpanel-signon.php 2>/dev/null || true
}


setup_phpmyadmin_sso() {
  local blowfish_secret
  blowfish_secret="$(openssl rand -hex 32)"
  local pma_host pma_scheme pma_secure
  pma_host="${PANEL_DOMAIN:-$SERVER_IP}"
  [[ -n "$pma_host" ]] || pma_host="$(detect_server_ip)"
  pma_scheme="http"
  pma_secure="false"
  if [[ "$ENABLE_SSL" == "yes" ]]; then
    pma_scheme="https"
    pma_secure="true"
  fi

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
    'secure' => ${pma_secure},
    'httponly' => true,
    'samesite' => 'Lax',
];
\$cfg['Servers'][\$i]['SignonURL'] = '/phpmyadmin/bpanel-signon.php';
\$cfg['Servers'][\$i]['host'] = 'localhost';
\$cfg['Servers'][\$i]['AllowNoPassword'] = false;
\$cfg['Servers'][\$i]['only_db'] = '';
\$cfg['SessionSavePath'] = '/var/lib/php/sessions';
\$cfg['PmaAbsoluteUri'] = '${pma_scheme}://${pma_host}/phpmyadmin/';
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
    'secure' => __BPANEL_PMA_COOKIE_SECURE__,
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

$apiUrl = '__BPANEL_API_BASE__' . rawurlencode($token);
$ch = curl_init($apiUrl);
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT => 5,
    CURLOPT_SSL_VERIFYPEER => false,
    CURLOPT_SSL_VERIFYHOST => false,
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

  local api_scheme="http"
  if [[ "$ENABLE_SSL" == "yes" ]]; then
    api_scheme="https"
  fi
  sed -i "s#__BPANEL_API_BASE__#${api_scheme}://127.0.0.1:${PANEL_PORT}/api/databases/phpmyadmin-sso/#" /usr/share/phpmyadmin/bpanel-signon.php
  sed -i "s#__BPANEL_PMA_COOKIE_SECURE__#${pma_secure}#" /usr/share/phpmyadmin/bpanel-signon.php

  chown root:www-data /etc/phpmyadmin/conf.d/bpanel-signon.php
  chmod 640 /etc/phpmyadmin/conf.d/bpanel-signon.php
  chmod 644 /usr/share/phpmyadmin/bpanel-signon.php
}

setup_nginx() {
  rm -f /etc/nginx/sites-enabled/default /etc/nginx/conf.d/default.conf 2>/dev/null || true
  rm -f /etc/nginx/sites-enabled/bpanel.conf /etc/nginx/sites-available/bpanel.conf 2>/dev/null || true
  write_tools_nginx_config
  nginx -t
  systemctl reload nginx
}

setup_firewall() {
  local default_port seen_ssh_ports ssh_port
  ufw_delete_bpanel_rules() {
    local pattern="$1" number
    while read -r number; do
      [[ -n "$number" ]] || continue
      ufw --force delete "$number" >/dev/null 2>&1 || true
    done < <(
      ufw status numbered 2>/dev/null \
        | awk -v pattern="$pattern" '
            index($0, "bpanel:PanelZone") {
              line = $0
              if (!match(line, /^\[[[:space:]]*[0-9]+\]/)) {
                next
              }
              number = substr(line, RSTART, RLENGTH)
              gsub(/[^0-9]/, "", number)
              sub(/^\[[[:space:]]*[0-9]+\][[:space:]]*/, "", line)
              split(line, parts, /[[:space:]]+ALLOW[[:space:]]+/)
              target = parts[1]
              if (target == pattern || target == pattern " (v6)") {
                print number
              }
            }
          ' \
        | sort -rn
    )
  }
  ufw_panel_allow_port() {
    local port="$1"
    [[ "$port" =~ ^[0-9]+$ ]] || return 0
    ufw_delete_bpanel_rules "${port}/tcp"
    ufw insert 1 allow "${port}/tcp" comment "bpanel:PanelZone" >/dev/null 2>&1 \
      || ufw insert 1 allow "${port}/tcp" >/dev/null 2>&1 \
      || ufw allow "${port}/tcp" >/dev/null 2>&1 \
      || true
  }
  ufw_panel_allow_app() {
    local app="$1"
    ufw_delete_bpanel_rules "$app"
    ufw insert 1 allow "$app" comment "bpanel:PanelZone" >/dev/null 2>&1 \
      || ufw insert 1 allow "$app" >/dev/null 2>&1 \
      || ufw allow "$app" >/dev/null 2>&1 \
      || true
  }

  ufw default deny incoming || true
  ufw default allow outgoing || true
  ufw_panel_allow_app OpenSSH
  seen_ssh_ports="$(detect_ssh_ports)"
  while read -r ssh_port; do
    [[ -n "$ssh_port" ]] || continue
    [[ "$ssh_port" == "22" ]] && continue
    ufw_panel_allow_port "$ssh_port"
  done <<<"$seen_ssh_ports"
  ufw_panel_allow_app 'Nginx Full'
  for default_port in 465 587 "${PANEL_PORT}"; do
    ufw_panel_allow_port "$default_port"
  done
  ufw --force enable || true
}

setup_ssl() {
  if [[ "$ENABLE_SSL" != "yes" ]]; then
    return 0
  fi

  certbot certonly --standalone \
    -d "$PANEL_DOMAIN" \
    --email "$SSL_EMAIL" \
    --agree-tos \
    --non-interactive \
    --pre-hook "systemctl stop nginx || true" \
    --post-hook "systemctl start nginx || true" \
    --deploy-hook "install -d -o root -g bpanel -m 0750 /etc/bpanel && install -m 0640 -o root -g bpanel /etc/letsencrypt/live/${PANEL_DOMAIN}/fullchain.pem /etc/bpanel/panel-fullchain.pem && install -m 0640 -o root -g bpanel /etc/letsencrypt/live/${PANEL_DOMAIN}/privkey.pem /etc/bpanel/panel-privkey.pem && systemctl restart bpanel-api || true"
  install -d -o root -g bpanel -m 0750 /etc/bpanel
  install -m 0640 -o root -g bpanel "/etc/letsencrypt/live/${PANEL_DOMAIN}/fullchain.pem" /etc/bpanel/panel-fullchain.pem
  install -m 0640 -o root -g bpanel "/etc/letsencrypt/live/${PANEL_DOMAIN}/privkey.pem" /etc/bpanel/panel-privkey.pem
  PANEL_SSL_CERT=/etc/bpanel/panel-fullchain.pem
  PANEL_SSL_KEY=/etc/bpanel/panel-privkey.pem
  sed -i \
    -e "s#^PANEL_SSL_CERT=.*#PANEL_SSL_CERT=/etc/bpanel/panel-fullchain.pem#" \
    -e "s#^PANEL_SSL_KEY=.*#PANEL_SSL_KEY=/etc/bpanel/panel-privkey.pem#" \
    -e "s#^PANEL_URL=.*#PANEL_URL=${PANEL_URL}#" \
    -e "s#^ALLOWED_ORIGINS=.*#ALLOWED_ORIGINS=${PANEL_URL}#" \
    "${APP_DIR}/backend/.env"
  write_tools_nginx_config
  nginx -t
  systemctl reload nginx
  systemctl restart bpanel-api
  for _ in {1..20}; do
    if curl -kfsS --connect-timeout 2 --max-time 5 "https://127.0.0.1:${PANEL_PORT}/api/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  journalctl -u bpanel-api -n 80 --no-pager || true
  fail "bpanel-api did not respond after enabling panel SSL"
}

print_summary() {
  echo ""
  echo "=================================================="
  echo "Panel URL: ${PANEL_URL}"
  echo "User: admin"
  echo "Password: ${ADMIN_PASSWORD}"
  echo "=================================================="
}

write_login_info() {
  local tmp
  (
    if command -v flock >/dev/null 2>&1; then
      flock -x 9
    fi
    tmp="$(mktemp /root/login.txt.XXXXXX)"
    chmod 600 "$tmp"
    cat >"$tmp" <<INFO
Panel URL: ${PANEL_URL}
User: admin
Password: ${ADMIN_PASSWORD}
INFO
    mv -f "$tmp" /root/login.txt
  ) 9>/root/.bpanel-login.lock
  chmod 600 /root/login.txt
}

source_version() {
  if [[ -f "${PROJECT_ROOT}/VERSION" ]]; then
    tr -d '[:space:]' <"${PROJECT_ROOT}/VERSION"
    return 0
  fi
  sed -nE 's/^APP_VERSION = "([^"]+)"/\1/p' "${PROJECT_ROOT}/backend/app/core/version.py" 2>/dev/null | head -n 1
}

write_update_state() {
  local version now
  version="$(source_version)"
  version="${version:-1.0.0}"
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  install -d -o bpanel -g bpanel -m 0750 /var/lib/bpanel
  cat >/var/lib/bpanel/update-status.json <<STATE
{
  "current_version": "${version}",
  "latest_tag": "v${version}",
  "latest_version": "${version}",
  "last_checked_at": "${now}",
  "last_update_finished_at": "${now}",
  "last_update_ref": "v${version}",
  "last_update_status": "installed"
}
STATE
  chown bpanel:bpanel /var/lib/bpanel/update-status.json 2>/dev/null || true
  chmod 0640 /var/lib/bpanel/update-status.json
}

cleanup_release_source() {
  [[ "${CLEAN_RELEASE_SOURCE:-true}" == "true" ]] || return 0
  [[ "$PROJECT_ROOT" == "/opt/bpanel-source" ]] || return 0
  [[ ! -d "${PROJECT_ROOT}/.git" ]] || return 0
  log "Removing release source from ${PROJECT_ROOT}"
  cd /
  rm -rf "$PROJECT_ROOT" /tmp/bpanel-release /tmp/bpanel-release.zip
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

  log "Configuring Nginx FastCGI cache"
  configure_fastcgi_cache

  log "Installing Nginx ModSecurity WAF engine"
  if ! install_waf_engine; then
    echo "WARNING: WAF engine installation failed; continuing without ModSecurity."
  fi

  log "Installing WP-CLI"
  install_wp_cli

  log "Copying source to ${APP_DIR}"
  copy_sources

  log "Building frontend"
  build_frontend

  log "Creating bpanel system user, MariaDB credentials and filesystem ACLs"
  setup_panel_user

  log "Configuring SFTP access for panel users"
  setup_sftp_access

  log "Installing privileged helper and sudoers rule"
  install_privileged_helper

  log "Installing SSH maintenance menu"
  install_panel_cli

  log "Validating privileged helper"
  validate_privileged_helper

  log "Configuring backend"
  setup_backend

  log "Creating systemd service (hardened, runs as bpanel user)"
  setup_systemd

  log "Configuring phpMyAdmin SSO"
  setup_phpmyadmin_sso

  log "Preparing Nginx for customer websites"
  setup_nginx

  log "Configuring firewall"
  setup_firewall

  log "Configuring SSL"
  setup_ssl

  write_login_info
  write_update_state

  print_summary
  cleanup_release_source
}

main "$@"
