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

ALLOWED_SERVICES=(nginx mariadb redis-server filebrowser php8.3-fpm php8.4-fpm bpanel-api)
ALLOWED_ACTIONS=(start stop restart reload status is-active is-enabled)
SITES_ROOT="/home/bpanel-sites"
NGINX_CONF_DIR="/etc/nginx/conf.d"
PHP_CONF_DIRS=(/etc/php/8.3/fpm/conf.d /etc/php/8.4/fpm/conf.d)
BPANEL_SITES_GROUP="bpanel-sites"

deny() { echo "bpanel-helper: $*" >&2; exit 1; }

is_in() {
  local needle="$1"; shift
  local x
  for x in "$@"; do [[ "$x" == "$needle" ]] && return 0; done
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

require_proto() {
  [[ "$1" == "tcp" || "$1" == "udp" ]] || deny "invalid protocol: $1"
}

require_php_version() {
  [[ "$1" == "8.3" || "$1" == "8.4" ]] || deny "invalid PHP version: $1"
}

require_linux_user() {
  [[ "$1" =~ ^bp_[a-z0-9_]{3,28}$ ]] || deny "invalid site user: $1"
}

ensure_sites_group() {
  getent group "$BPANEL_SITES_GROUP" >/dev/null || groupadd --system "$BPANEL_SITES_GROUP"
  usermod -aG "$BPANEL_SITES_GROUP" bpanel 2>/dev/null || true
  usermod -aG "$BPANEL_SITES_GROUP" www-data 2>/dev/null || true
}

fix_site_tree() {
  local target="$1" user="$2"
  ensure_sites_group
  require_linux_user "$user"
  command -v setfacl >/dev/null 2>&1 || deny "setfacl not found; install the acl package"
  chown -R "$user:$user" "$target"
  if [[ -d "$target" ]]; then
    find "$target" -type d -exec chmod 2750 {} +
    find "$target" -type f -exec chmod 640 {} +
    find "$target" -name wp-config.php -type f -exec chmod 640 {} + 2>/dev/null || true
    setfacl -R -m "g::rwX,g:${BPANEL_SITES_GROUP}:rwX,m::rwX" "$target"
    find "$target" -type d -exec setfacl -m "d:g::rwX,d:g:${BPANEL_SITES_GROUP}:rwX,d:m::rwX" {} +
  else
    chmod 640 "$target"
    [[ "$(basename "$target")" == "wp-config.php" ]] && chmod 640 "$target"
    setfacl -m "g:${BPANEL_SITES_GROUP}:rw" "$target"
  fi
}

require_ip_or_cidr() {
  # Loose check; we trust ufw to do the final parsing.
  [[ "$1" =~ ^[0-9a-fA-F.:/]+$ ]] || deny "invalid IP/CIDR: $1"
}

cmd="${1:-}"
shift || true

case "$cmd" in

  # ---- systemctl --------------------------------------------------------
  systemctl)
    [[ $# -ge 2 ]] || deny "usage: systemctl <service> <action>"
    service="$1"; action="$2"
    is_in "$service" "${ALLOWED_SERVICES[@]}" || deny "service not allowed: $service"
    is_in "$action" "${ALLOWED_ACTIONS[@]}" || deny "action not allowed: $action"
    if [[ "$service" == "nginx" && "$action" == "stop" ]]; then
      deny "refusing to stop nginx (would disconnect the panel)"
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

  # ---- certbot ----------------------------------------------------------
  certbot-issue)
    [[ $# -ge 1 ]] || deny "usage: certbot-issue <domain> [email]"
    domain="$1"; email="${2:-}"
    require_domain "$domain"
    args=(--nginx -d "$domain" --non-interactive --agree-tos --redirect)
    if [[ -n "$email" ]]; then
      require_email "$email"
      args+=(--email "$email")
    else
      args+=(--register-unsafely-without-email)
    fi
    exec certbot "${args[@]}"
    ;;

  certbot-renew)
    exec certbot renew --quiet
    ;;

  # ---- ufw --------------------------------------------------------------
  ufw-status)
    exec ufw status verbose numbered
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
    exec ufw allow "${1}/${2}"
    ;;
  ufw-allow-ip)
    [[ $# -ge 1 && $# -le 3 ]] || deny "usage: ufw-allow-ip <ip> [port] [proto]"
    require_ip_or_cidr "$1"
    if [[ $# -eq 1 ]]; then
      exec ufw allow from "$1"
    fi
    require_port "$2"; require_proto "${3:-tcp}"
    exec ufw allow from "$1" to any port "$2" proto "${3:-tcp}"
    ;;
  ufw-deny-ip)
    [[ $# -ge 1 && $# -le 3 ]] || deny "usage: ufw-deny-ip <ip> [port] [proto]"
    require_ip_or_cidr "$1"
    if [[ $# -eq 1 ]]; then
      exec ufw deny from "$1"
    fi
    require_port "$2"; require_proto "${3:-tcp}"
    exec ufw deny from "$1" to any port "$2" proto "${3:-tcp}"
    ;;
  ufw-delete)
    [[ $# -eq 1 && "$1" =~ ^[0-9]+$ ]] || deny "usage: ufw-delete <number>"
    exec ufw --force delete "$1"
    ;;

  # ---- filesystem -------------------------------------------------------
  chown-www)
    [[ $# -eq 1 ]] || deny "usage: chown-www <path>"
    target=$(require_safe_path "$SITES_ROOT" "$1")
    exec chown -R www-data:www-data "$target"
    ;;

  fix-permissions)
    [[ $# -ge 1 && $# -le 2 ]] || deny "usage: fix-permissions <path> [site-user]"
    target=$(require_safe_path "$SITES_ROOT" "$1")
    if [[ $# -eq 2 ]]; then
      fix_site_tree "$target" "$2"
      exit 0
    fi
    chown -R www-data:www-data "$target"
    find "$target" -type d -exec chmod 755 {} +
    find "$target" -type f -exec chmod 644 {} +
    find "$target" -type d -name uploads -exec chmod 775 {} + 2>/dev/null || true
    ;;

  site-path-fix)
    [[ $# -eq 2 ]] || deny "usage: site-path-fix <path> <site-user>"
    target=$(require_safe_path "$SITES_ROOT" "$1")
    fix_site_tree "$target" "$2"
    ;;

  site-runtime-ensure)
    [[ $# -eq 3 ]] || deny "usage: site-runtime-ensure <site-user> <path> <php-version|none>"
    user="$1"; path="$2"; php_version="$3"
    require_linux_user "$user"
    target=$(require_safe_path "$SITES_ROOT" "$path")
    ensure_sites_group
    if ! id -u "$user" >/dev/null 2>&1; then
      useradd --system --home-dir "$target" --shell /usr/sbin/nologin --user-group "$user"
    fi
    usermod --home "$target" --shell /usr/sbin/nologin "$user" 2>/dev/null || true
    usermod -L "$user" 2>/dev/null || true
    install -d -o "$user" -g "$user" -m 0755 "$target" "$target/public"
    fix_site_tree "$target" "$user"
    if [[ "$php_version" != "none" ]]; then
      require_php_version "$php_version"
      pool_name="bpanel-${user}"
      pool_file="/etc/php/${php_version}/fpm/pool.d/${pool_name}.conf"
      for dir in /etc/php/*/fpm/pool.d; do
        [[ -d "$dir" ]] || continue
        old_file="$dir/${pool_name}.conf"
        if [[ "$old_file" != "$pool_file" && -f "$old_file" ]]; then
          rm -f "$old_file"
          old_version="$(echo "$dir" | awk -F/ '{print $4}')"
          systemctl reload "php${old_version}-fpm" 2>/dev/null || true
        fi
      done
      cat >"$pool_file" <<POOL
[${pool_name}]
user = ${user}
group = ${user}
listen = /run/php/${pool_name}.sock
listen.owner = www-data
listen.group = www-data
listen.mode = 0660
pm = ondemand
pm.max_children = 8
pm.process_idle_timeout = 20s
pm.max_requests = 500
chdir = /
php_admin_value[open_basedir] = ${target}:/tmp:/usr/share/php
php_admin_value[upload_tmp_dir] = /tmp
php_admin_value[session.save_path] = /tmp
POOL
      systemctl reload "php${php_version}-fpm"
    fi
    ;;

  site-runtime-delete)
    [[ $# -eq 2 ]] || deny "usage: site-runtime-delete <site-user> <path>"
    user="$1"; path="$2"
    require_linux_user "$user"
    require_safe_path "$SITES_ROOT" "$path" >/dev/null
    for dir in /etc/php/*/fpm/pool.d; do
      [[ -d "$dir" ]] || continue
      old_file="$dir/bpanel-${user}.conf"
      if [[ -f "$old_file" ]]; then
        rm -f "$old_file"
        old_version="$(echo "$dir" | awk -F/ '{print $4}')"
        systemctl reload "php${old_version}-fpm" 2>/dev/null || true
      fi
    done
    crontab -r -u "$user" 2>/dev/null || true
    pkill -u "$user" 2>/dev/null || true
    userdel "$user" 2>/dev/null || true
    groupdel "$user" 2>/dev/null || true
    ;;

  rm-site)
    [[ $# -eq 1 ]] || deny "usage: rm-site <path>"
    target=$(require_safe_path "$SITES_ROOT" "$1")
    [[ "$target" == "$SITES_ROOT" ]] && deny "refusing to delete the entire sites root"
    exec rm -rf "$target"
    ;;

  mkdir-site)
    [[ $# -eq 1 ]] || deny "usage: mkdir-site <path>"
    target=$(require_safe_path "$SITES_ROOT" "$1")
    install -d -o www-data -g www-data -m 0775 "$target"
    install -d -o www-data -g www-data -m 0775 "$target/public"
    ;;

  # ---- WP-CLI as www-data ----------------------------------------------
  wp)
    [[ $# -ge 1 ]] || deny "usage: wp <args...>"
    exec runuser -u www-data -- /usr/local/bin/wp "$@"
    ;;

  wp-site)
    [[ $# -ge 2 ]] || deny "usage: wp-site <site-user> <args...>"
    user="$1"; shift
    require_linux_user "$user"
    exec runuser -u "$user" -- /usr/local/bin/wp "$@"
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
    is_in "$1" "${ALLOWED_SERVICES[@]}" || deny "service not allowed: $1"
    exec systemctl status "$1" --no-pager
    ;;

  *)
    deny "unknown command: $cmd"
    ;;
esac
