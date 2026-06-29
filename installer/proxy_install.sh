#!/usr/bin/env bash
# Install independent reverse-proxy configuration as BPanel menu option 14.
#
# Usage:
#   bash proxy_install.sh
#   bpanel
#   choose 14

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/bpanel}"
BPANEL_CLI="${BPANEL_CLI:-/usr/local/sbin/bpanel}"
BPANELCTL="${BPANELCTL:-/usr/local/sbin/bpanelctl}"
PROXY_CONFIGURATOR="${PROXY_CONFIGURATOR:-/usr/local/sbin/bpanel-proxy-config}"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

if [[ "${EUID}" -ne 0 ]]; then
  fail "Please run as root on the BPanel server."
fi

[[ -d "${APP_DIR}/backend" ]] || fail "${APP_DIR}/backend not found. Set APP_DIR if BPanel is installed elsewhere."
[[ -x "${APP_DIR}/backend/.venv/bin/python" ]] || fail "${APP_DIR}/backend/.venv/bin/python not found."
[[ -f "${APP_DIR}/backend/.env" ]] || fail "${APP_DIR}/backend/.env not found."
[[ -f "${BPANEL_CLI}" ]] || fail "${BPANEL_CLI} not found."

install -d -m 750 -o root -g bpanel /etc/bpanel
if [[ ! -f /etc/bpanel/reverse-proxies.json ]]; then
  printf '%s\n' '{"domains":{}}' >/etc/bpanel/reverse-proxies.json
fi
chown root:bpanel /etc/bpanel/reverse-proxies.json
chmod 0640 /etc/bpanel/reverse-proxies.json
cat >"${PROXY_CONFIGURATOR}" <<'PYPROXY'
#!/usr/bin/env python3
"""Configure trusted reverse proxies for BPanel websites."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


APP_DIR = Path(os.environ.get("APP_DIR", "/opt/bpanel"))
VENV_PYTHON = APP_DIR / "backend" / ".venv" / "bin" / "python"
if Path(sys.executable) != VENV_PYTHON and VENV_PYTHON.exists():
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])

STATE_PATH = Path(os.environ.get("BPANEL_PROXY_STATE", "/etc/bpanel/reverse-proxies.json"))
VHOST_DIR = Path(os.environ.get("BPANEL_NGINX_VHOST_DIR", "/etc/nginx/conf.d"))
TRUSTED_PROXY_CONFIG = VHOST_DIR / "00-bpanel-trusted-proxies.conf"
PROXY_FASTCGI_PARAMS = Path("/etc/nginx/bpanel/proxy-fastcgi-params.conf")
CACHE_DIR = Path("/var/cache/nginx/bpanel-fastcgi")
DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")
SERVER_BLOCK_RE = re.compile(
    r"\n?\s*# BPANEL REVERSE PROXY BEGIN\n.*?\n\s*# BPANEL REVERSE PROXY END",
    re.DOTALL,
)
FASTCGI_BLOCK_RE = re.compile(
    r"\s*# BPANEL REVERSE PROXY FASTCGI BEGIN\n.*?\n\s*# BPANEL REVERSE PROXY FASTCGI END",
    re.DOTALL,
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def require_root() -> None:
    if os.geteuid() != 0:
        fail("Run as root, normally from the bpanel menu.")


def validate_domain(domain: str) -> str:
    value = domain.strip().lower().rstrip(".")
    if not DOMAIN_RE.fullmatch(value):
        fail(f"Invalid domain: {domain}")
    return value


def validate_proxy_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError as exc:
        fail(f"Invalid proxy IP: {value}")
        raise exc


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"domains": {}}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        fail(f"Cannot read {STATE_PATH}: {exc}")
    if not isinstance(data, dict) or not isinstance(data.get("domains"), dict):
        fail(f"Invalid proxy state in {STATE_PATH}")
    return data


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o640)
    try:
        shutil.chown(temp, user="root", group="bpanel")
    except LookupError:
        shutil.chown(temp, user="root", group="root")
    temp.replace(STATE_PATH)


def panel_websites() -> list[dict]:
    backend = APP_DIR / "backend"
    if not backend.exists():
        fail(f"BPanel backend not found: {backend}")
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    from app.core.database import SessionLocal
    from app.models.entities import Website

    db = SessionLocal()
    try:
        rows = db.query(Website).order_by(Website.domain.asc()).all()
        return [
            {
                "domain": row.domain,
                "root_path": row.root_path,
                "app_type": row.app_type or "wordpress",
            }
            for row in rows
        ]
    finally:
        db.close()


def website_for_domain(domain: str) -> dict | None:
    return next((item for item in panel_websites() if item["domain"] == domain), None)


def vhost_path(domain: str) -> Path:
    return VHOST_DIR / f"{domain}.conf"


def fix_nginx_shared_permissions() -> None:
    try:
        if VHOST_DIR.exists():
            shutil.chown(VHOST_DIR, user="root", group="bpanel")
            os.chmod(VHOST_DIR, 0o2775)
        if PROXY_FASTCGI_PARAMS.parent.exists():
            shutil.chown(PROXY_FASTCGI_PARAMS.parent, user="root", group="bpanel")
            os.chmod(PROXY_FASTCGI_PARAMS.parent, 0o2775)
        if PROXY_FASTCGI_PARAMS.exists():
            shutil.chown(PROXY_FASTCGI_PARAMS, user="root", group="bpanel")
            os.chmod(PROXY_FASTCGI_PARAMS, 0o664)
        if TRUSTED_PROXY_CONFIG.exists():
            shutil.chown(TRUSTED_PROXY_CONFIG, user="root", group="bpanel")
            os.chmod(TRUSTED_PROXY_CONFIG, 0o664)
    except (LookupError, OSError) as exc:
        fail(f"Cannot fix Nginx shared config permissions: {exc}")


def fix_vhost_permissions(target: Path) -> None:
    fix_nginx_shared_permissions()
    try:
        for path in (target, target.with_suffix(target.suffix + ".bak")):
            if not path.exists():
                continue
            shutil.chown(path, user="root", group="bpanel")
            os.chmod(path, 0o664)
    except (LookupError, OSError) as exc:
        fail(f"Cannot fix Nginx vhost permissions for {target}: {exc}")


def fix_all_vhost_permissions() -> None:
    fix_nginx_shared_permissions()
    for website in panel_websites():
        target = vhost_path(website["domain"])
        if target.exists():
            fix_vhost_permissions(target)


def trusted_proxy_ips(state: dict) -> list[str]:
    values = {
        validate_proxy_ip(config.get("proxy_ip", ""))
        for config in state["domains"].values()
        if isinstance(config, dict) and config.get("proxy_ip")
    }
    return sorted(values, key=lambda value: (ipaddress.ip_address(value).version, ipaddress.ip_address(value)))


def trusted_proxy_config_text(state: dict) -> str:
    ips = trusted_proxy_ips(state)
    if not ips:
        return ""
    lines = [
        "# Generated by bpanel-proxy-config. Do not edit manually.",
        "# Direct clients keep their source IP; only these proxy IPs may supply X-Forwarded-For.",
        *(f"set_real_ip_from {proxy_ip};" for proxy_ip in ips),
        "real_ip_header X-Forwarded-For;",
        "real_ip_recursive on;",
        "",
    ]
    return "\n".join(lines)


def write_trusted_proxy_config(state: dict) -> None:
    text = trusted_proxy_config_text(state)
    if not text:
        TRUSTED_PROXY_CONFIG.unlink(missing_ok=True)
        return
    TRUSTED_PROXY_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    TRUSTED_PROXY_CONFIG.write_text(text, encoding="utf-8")
    fix_nginx_shared_permissions()


def remove_known_wordpress_proxy_block(root_path: str) -> None:
    wp = Path(root_path) / "public_html" / "wp-config.php"
    if not wp.exists():
        return
    text = wp.read_text(encoding="utf-8", errors="ignore")
    blocks = (
        """// Honor HTTPS terminated by the trusted reverse proxy.
if ( ! empty( $_SERVER['HTTP_X_FORWARDED_PROTO'] ) ) {
        $forwarded_proto = strtolower( trim( explode( ',', $_SERVER['HTTP_X_FORWARDED_PROTO'] )[0] ) );
        if ( $forwarded_proto === 'https' ) {
                $_SERVER['HTTPS'] = 'on';
                $_SERVER['SERVER_PORT'] = '443';
        }
}

""",
        """// Honor HTTPS terminated by a reverse proxy.
if ( ! empty( $_SERVER['HTTP_X_FORWARDED_PROTO'] ) ) {
        $forwarded_proto = strtolower( trim( explode( ',', $_SERVER['HTTP_X_FORWARDED_PROTO'] )[0] ) );
        if ( $forwarded_proto === 'https' ) {
                $_SERVER['HTTPS'] = 'on';
                $_SERVER['SERVER_PORT'] = '443';
        }
}

""",
        """if ( isset($_SERVER['HTTP_X_FORWARDED_PROTO']) && strpos($_SERVER['HTTP_X_FORWARDED_PROTO'], 'https') !== false ) {
    $_SERVER['HTTPS'] = 'on';
}
""",
    )
    updated = text
    for block in blocks:
        updated = updated.replace(block, "")
    if updated != text:
        wp.write_text(updated, encoding="utf-8")


def remove_legacy_proxy_lines(text: str, proxy_ip: str) -> str:
    escaped = re.escape(proxy_ip)
    pattern = re.compile(rf"(?m)^\s*set_real_ip_from\s+{escaped};\s*$\n?")
    if not pattern.search(text):
        return text
    text = pattern.sub("", text)
    text = re.sub(r"(?m)^\s*real_ip_header\s+X-Forwarded-For;\s*$\n?", "", text, count=1)
    text = re.sub(r"(?m)^\s*real_ip_recursive\s+on;\s*$\n?", "", text, count=1)
    text = re.sub(r"(?m)^\s*#.*SafeLine\s*$\n?", "", text, count=1)
    return text


def strip_proxy_config(text: str, proxy_ip: str = "") -> str:
    text = SERVER_BLOCK_RE.sub("", text)
    text = FASTCGI_BLOCK_RE.sub("\n        include fastcgi_params;", text)
    text = re.sub(
        r'(?m)^\s*fastcgi_cache_key\s+"\$scheme\$request_method\$host\$http_x_forwarded_proto\$request_uri";\s*$\n?',
        "",
        text,
    )
    if proxy_ip:
        text = remove_legacy_proxy_lines(text, proxy_ip)
    return text


def cleanup_vhost_proxy_config(domain: str, proxy_ip: str = "") -> tuple[Path, str] | None:
    target = vhost_path(domain)
    if not target.exists():
        return None
    old_text = target.read_text(encoding="utf-8")
    text = strip_proxy_config(old_text, proxy_ip)
    if text == old_text:
        fix_vhost_permissions(target)
        return None
    target.with_suffix(target.suffix + ".bak").write_text(old_text, encoding="utf-8")
    target.write_text(text, encoding="utf-8")
    fix_vhost_permissions(target)
    return target, old_text


def test_and_reload(rollbacks: list[tuple[Path, str]]) -> None:
    test = subprocess.run(["nginx", "-t"], check=False, capture_output=True, text=True)
    if test.returncode != 0:
        for target, old_text in rollbacks:
            if old_text:
                target.write_text(old_text, encoding="utf-8")
            else:
                target.unlink(missing_ok=True)
            fix_vhost_permissions(target) if target.parent == VHOST_DIR and target.name != TRUSTED_PROXY_CONFIG.name else fix_nginx_shared_permissions()
        fail((test.stderr or test.stdout or "nginx -t failed").strip())
    reload_result = subprocess.run(["systemctl", "reload", "nginx"], check=False, capture_output=True, text=True)
    if reload_result.returncode != 0:
        for target, old_text in rollbacks:
            if old_text:
                target.write_text(old_text, encoding="utf-8")
            else:
                target.unlink(missing_ok=True)
            fix_vhost_permissions(target) if target.parent == VHOST_DIR and target.name != TRUSTED_PROXY_CONFIG.name else fix_nginx_shared_permissions()
        subprocess.run(["systemctl", "reload", "nginx"], check=False)
        fail((reload_result.stderr or reload_result.stdout or "nginx reload failed").strip())
    fix_nginx_shared_permissions()


def clear_fastcgi_cache() -> None:
    try:
        resolved = CACHE_DIR.resolve()
    except OSError:
        return
    if resolved != Path("/var/cache/nginx/bpanel-fastcgi"):
        fail(f"Refusing to clear unexpected cache directory: {resolved}")
    if not resolved.exists():
        return
    for path in resolved.rglob("*"):
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)
    for path in sorted((item for item in resolved.rglob("*") if item.is_dir()), reverse=True):
        path.rmdir()


def apply_proxy_state(state: dict, cleanup_domains: dict[str, str] | None = None) -> None:
    old_global = TRUSTED_PROXY_CONFIG.read_text(encoding="utf-8") if TRUSTED_PROXY_CONFIG.exists() else ""
    write_trusted_proxy_config(state)
    rollbacks: list[tuple[Path, str]] = [(TRUSTED_PROXY_CONFIG, old_global)]
    for domain, proxy_ip in (cleanup_domains or {}).items():
        website = website_for_domain(domain)
        if website:
            rollback = cleanup_vhost_proxy_config(domain, proxy_ip)
            if rollback:
                rollbacks.append(rollback)
            remove_known_wordpress_proxy_block(website["root_path"])
    test_and_reload(rollbacks)
    clear_fastcgi_cache()


def cleanup_domains_from_state(state: dict, extra: dict[str, str] | None = None) -> dict[str, str]:
    domains = {
        domain: config.get("proxy_ip", "") if isinstance(config, dict) else ""
        for domain, config in state["domains"].items()
    }
    if extra:
        domains.update(extra)
    return domains


def enable_and_save(domain: str, proxy_ip: str) -> None:
    if not website_for_domain(domain):
        fail(f"Domain is not registered in BPanel: {domain}")
    state = load_state()
    old_proxy_ip = state["domains"].get(domain, {}).get("proxy_ip", "")
    state["domains"][domain] = {"proxy_ip": proxy_ip}
    apply_proxy_state(state, cleanup_domains_from_state(state, {domain: old_proxy_ip or proxy_ip}))
    save_state(state)
    print(f"Proxy enabled: {domain} via {proxy_ip}")


def disable_and_save(domain: str) -> None:
    state = load_state()
    config = state["domains"].get(domain, {})
    proxy_ip = config.get("proxy_ip", "")
    state["domains"].pop(domain, None)
    apply_proxy_state(state, cleanup_domains_from_state(state, {domain: proxy_ip}))
    save_state(state)
    print(f"Proxy disabled: {domain}")


def apply_saved(domain: str) -> None:
    state = load_state()
    config = state["domains"].get(domain)
    if not config:
        return
    proxy_ip = validate_proxy_ip(config.get("proxy_ip", ""))
    if not website_for_domain(domain) or not vhost_path(domain).exists():
        print(f"Proxy skipped, domain is not currently installed: {domain}")
        return
    apply_proxy_state(state, cleanup_domains_from_state(state, {domain: proxy_ip}))
    print(f"Proxy reapplied: {domain} via {proxy_ip}")


def apply_all() -> None:
    state = load_state()
    apply_proxy_state(state, cleanup_domains_from_state(state))


def interactive_menu() -> None:
    websites = panel_websites()
    if not websites:
        print("No domains found in BPanel.")
        return
    state = load_state()
    print("BPanel reverse proxy configuration")
    for index, website in enumerate(websites, start=1):
        config = state["domains"].get(website["domain"])
        status = f"proxy {config['proxy_ip']}" if config else "direct"
        print(f"{index}) {website['domain']} [{status}]")
    print("0) Cancel")
    selected = input("Choose domain: ").strip()
    if selected == "0":
        return
    try:
        website = websites[int(selected) - 1]
    except (ValueError, IndexError):
        fail("Invalid selection")
    domain = website["domain"]
    current = state["domains"].get(domain, {}).get("proxy_ip", "")
    prompt = f"Proxy server IP{f' [{current}]' if current else ''} (type OFF to disable): "
    value = input(prompt).strip()
    if value.lower() == "off":
        disable_and_save(domain)
        return
    if not value:
        if current:
            value = current
        else:
            fail("Proxy IP is required")
    enable_and_save(domain, validate_proxy_ip(value))


def main() -> None:
    require_root()
    command = sys.argv[1] if len(sys.argv) > 1 else "menu"
    if command == "menu":
        interactive_menu()
        return
    if command == "enable" and len(sys.argv) == 4:
        enable_and_save(validate_domain(sys.argv[2]), validate_proxy_ip(sys.argv[3]))
        return
    if command == "disable" and len(sys.argv) == 3:
        disable_and_save(validate_domain(sys.argv[2]))
        return
    if command == "apply" and len(sys.argv) == 3:
        apply_saved(validate_domain(sys.argv[2]))
        return
    if command == "apply-all" and len(sys.argv) == 2:
        apply_all()
        return
    if command == "fix-permissions" and len(sys.argv) == 2:
        fix_all_vhost_permissions()
        print("Nginx vhost permissions fixed")
        return
    fail("Usage: bpanel-proxy-config [menu|enable DOMAIN IP|disable DOMAIN|apply DOMAIN|apply-all|fix-permissions]")


if __name__ == "__main__":
    main()
PYPROXY

chmod 0755 "${PROXY_CONFIGURATOR}"
chown root:root "${PROXY_CONFIGURATOR}"
"${PROXY_CONFIGURATOR}" fix-permissions

patch_cli() {
  local cli="$1"
  [[ -f "$cli" ]] || return 0
  python3 - "$cli" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

if "reverse_proxy_config_menu()" not in text:
    marker = "\nmenu() {\n"
    fn = '''
reverse_proxy_config_menu() {
  if [[ ! -x /usr/local/sbin/bpanel-proxy-config ]]; then
    fail "/usr/local/sbin/bpanel-proxy-config not found. Run proxy_install.sh first."
  fi
  /usr/local/sbin/bpanel-proxy-config menu
}

'''
    if marker not in text:
        raise SystemExit("Cannot find menu() in bpanel CLI")
    text = text.replace(marker, "\n" + fn + "menu() {\n", 1)

if 'echo "14) Configure reverse proxy"' not in text:
    text = text.replace(
        '    echo "0) Exit"\n',
        '    echo "14) Configure reverse proxy"\n    echo "0) Exit"\n',
        1,
    )

if "14) reverse_proxy_config_menu ;;" not in text:
    text = text.replace(
        "      0) exit 0 ;;\n",
        "      14) reverse_proxy_config_menu ;;\n      0) exit 0 ;;\n",
        1,
    )

if "configure-proxy|--configure-proxy" not in text:
    route = "  configure-proxy|--configure-proxy) reverse_proxy_config_menu ;;\n"
    text = text.replace(
        "  status|--status) show_status ;;\n",
        route + "  status|--status) show_status ;;\n",
        1,
    )

if "|configure-proxy|" not in text:
    text = text.replace("|update]", "|configure-proxy|update]")

path.write_text(text, encoding="utf-8")
PY
}

patch_cli "${BPANEL_CLI}"
ln -sfn "${BPANEL_CLI}" "${BPANELCTL}"

echo "Installed: ${PROXY_CONFIGURATOR}"
echo "Patched menu: ${BPANEL_CLI}"
echo "Run: bpanel, then choose 14"
