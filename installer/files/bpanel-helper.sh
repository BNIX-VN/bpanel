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

deny() { echo "bpanel-helper: $*" >&2; exit 1; }

is_in() {
  local needle="$1"; shift
  local x
  for x in "$@"; do [[ "$x" == "$needle" ]] && return 0; done
  return 1
}

require_safe_path() {
  local prefix="$1" path="$2"
  case "$path" in
    *$'\n'*|*$'\0'*|*..*) deny "unsafe path: $path" ;;
    "") deny "empty path" ;;
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
    [[ $# -eq 1 ]] || deny "usage: fix-permissions <path>"
    target=$(require_safe_path "$SITES_ROOT" "$1")
    chown -R www-data:www-data "$target"
    find "$target" -type d -exec chmod 755 {} +
    find "$target" -type f -exec chmod 644 {} +
    find "$target" -type d -name uploads -exec chmod 775 {} + 2>/dev/null || true
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

  # ---- crontab managed for www-data ------------------------------------
  cron-list)
    exec runuser -u www-data -- crontab -l 2>/dev/null
    ;;
  cron-write)
    # crontab content is fed via stdin
    exec runuser -u www-data -- crontab -
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
