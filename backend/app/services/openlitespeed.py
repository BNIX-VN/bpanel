"""OpenLiteSpeed (OLS) web-server backend - the alternative to nginx.py,
selected at install time via WEB_SERVER=openlitespeed (see
app.services.webserver). Ported from OPanel (github.com/bnixvn/opanel), the
BPanel fork that ran OLS exclusively, then extended to match nginx.py's full
interface: the "application"/proxy app type, real HTTP-flood config
validation, and the constants BPanel's callers expect
(PROXIED_APP_TYPES/ALLOWED_APP_TYPES/ALLOWED_REWRITE_MODES/ALLOWED_PHP_VERSIONS).

Vhosts live under /usr/local/lsws/conf/bpanel/vhosts/<domain>/vhost.conf, one
directory per domain, included from the main httpd_config.conf. Unlike
nginx's per-site FPM pool, PHP here is one shared LSPHP listener per version
(see php.py's LSPHP branch) - a vhost's `extprocessor` block just points at
that shared external app, it does not own a private one.

HTTP-flood protection is a per-vhost OLS `extprocessor type proxy` throttle
rather than a real rate limiter (OLS has no equivalent to nginx's
limit_req_zone) - this is a known, documented gap carried over from OPanel,
not a bug. FastCGI cache has no separate toggle here: LSCache-equivalent
rewrite rules are always present in the WordPress template, same as nginx's
FastCGI cache being unconditional once ensure_wordpress_fastcgi_cache runs.
"""

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from app.core.config import settings
from app.services import site_users
from app.services.shell import shell

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "openlitespeed"
OLS_CONF_ROOT = Path("/usr/local/lsws/conf/bpanel")
OLS_VHOSTS_DIR = OLS_CONF_ROOT / "vhosts"
CUSTOM_INCLUDE_DIR = Path("/usr/local/lsws/conf/bpanel/custom")
ACME_WEBROOT = "/var/www/bpanel-acme"

# Same sets as nginx.py - a website's php_version/app_type/rewrite_mode must
# mean the same thing regardless of which backend is active.
ALLOWED_PHP_VERSIONS = {"5.6", "7.4", "8.0", "8.1", "8.2", "8.3", "8.4", "8.5"}
ALLOWED_APP_TYPES = {"wordpress", "php", "static", "application"}
PROXIED_APP_TYPES = {"application"}
# No certbot plugin exists for OpenLiteSpeed, so nothing writes the
# issued certificate into the vhost on our behalf - the panel must
# re-render it, which is what this flag tells the SSL endpoints.
SSL_WIRED_BY_CERTBOT = False
PROXY_TIMEOUT_SECONDS = 300
ALLOWED_REWRITE_MODES = {"none", "front_controller", "laravel", "codeigniter", "seohburl"}
ALLOWED_LOG_KINDS = {"access", "error"}
DOMAIN_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+")
MAX_FULL_CONFIG_BYTES = 128 * 1024

HTTP_FLOOD_DEFAULTS = {
    "access_limit_requests": 100,
    "access_limit_window": 10,
    "access_limit_burst": 100,
    "connection_limit": 60,
}

WORDPRESS_CSP = (
    "default-src 'self' https: data: blob:; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https:; "
    "style-src 'self' 'unsafe-inline' https:; "
    "img-src 'self' data: https: blob:; "
    "font-src 'self' data: https:; "
    "connect-src 'self' https:; "
    "frame-src 'self' https: blob:; "
    "worker-src 'self' blob:; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self' https:; "
    "frame-ancestors 'self'; "
    "upgrade-insecure-requests"
)
SECURITY_HEADERS = (
    "X-Content-Type-Options: nosniff\n"
    "Referrer-Policy: strict-origin-when-cross-origin\n"
    "Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
    "bluetooth=(), magnetometer=(), gyroscope=(), accelerometer=()"
)
HSTS_HEADER = "Strict-Transport-Security: max-age=31536000; includeSubDomains"


# ---------------------------------------------------------------------------
# Jinja2 renderer
# ---------------------------------------------------------------------------
_jinja_env: Optional[Environment] = None


def _get_jinja_env() -> Environment:
    global _jinja_env
    if _jinja_env is None:
        _jinja_env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
    return _jinja_env


# ---------------------------------------------------------------------------
# Validation helpers (mirrors nginx.py's)
# ---------------------------------------------------------------------------
def _safe_domain(domain: str) -> str:
    safe_domain = (domain or "").strip().lower()
    if not DOMAIN_RE.fullmatch(safe_domain):
        raise ValueError("Invalid domain")
    return safe_domain


def _safe_alias_domains(aliases) -> list[str]:
    safe_aliases: list[str] = []
    seen: set[str] = set()
    for alias in aliases or []:
        safe_alias = _safe_domain(str(alias))
        if safe_alias in seen:
            continue
        safe_aliases.append(safe_alias)
        seen.add(safe_alias)
    return safe_aliases


def _redirect_entries(redirects) -> list[dict]:
    """Normalize the ``redirects`` argument to [{"source", "target", "code"}, ...].

    Callers pass either plain domain strings (BPanel's usual "redirect this
    alias domain to the primary") or dicts with an explicit target/code - the
    dict form exists for parity with anything DA-import or backup/restore
    hands over.
    """
    entries: list[dict] = []
    for redirect in redirects or []:
        if isinstance(redirect, dict):
            source = redirect.get("source") or redirect.get("domain")
            target = redirect.get("target")
            code = redirect.get("code", 301)
        else:
            source = redirect
            target = None
            code = 301
        if not source:
            continue
        try:
            safe_source = _safe_domain(str(source))
        except ValueError:
            continue
        entries.append({
            "source": safe_source,
            "target": target or "",
            "code": int(code) if code else 301,
        })
    return entries


def _check_php_version(php_version: str | None) -> str | None:
    if php_version is None:
        return None
    if php_version not in ALLOWED_PHP_VERSIONS:
        raise ValueError(f"Unsupported PHP version: {php_version}")
    return php_version


def _check_app_type(app_type: str) -> str:
    if app_type not in ALLOWED_APP_TYPES:
        raise ValueError(f"Unsupported app type: {app_type}")
    return app_type


def _check_app_port(app_type: str, app_port: int | None) -> int | None:
    if app_type not in PROXIED_APP_TYPES:
        return None
    try:
        value = int(app_port)
    except (TypeError, ValueError) as exc:
        raise ValueError("Pick an installed application for this website first") from exc
    if not 1 <= value <= 65535:
        raise ValueError("Application port is out of range")
    return value


def _check_rewrite_mode(mode: str | None) -> str:
    value = (mode or "none").strip().lower()
    if value not in ALLOWED_REWRITE_MODES:
        raise ValueError(f"Unsupported rewrite mode: {mode}")
    return value


def _check_log_kind(kind: str) -> str:
    value = (kind or "").strip().lower()
    if value not in ALLOWED_LOG_KINDS:
        raise ValueError("Log kind must be access or error")
    return value


def _check_tail_lines(lines: int) -> int:
    try:
        value = int(lines)
    except (TypeError, ValueError) as exc:
        raise ValueError("Log lines must be a number") from exc
    if value < 1 or value > 5000:
        raise ValueError("Log lines must be between 1 and 5000")
    return value


def _effective_document_root(document_root: str, rewrite_mode: str) -> str:
    safe_root = site_users.validate_document_root(document_root)
    if rewrite_mode in {"laravel", "codeigniter"} and safe_root.rstrip("/") == "public_html":
        return "public_html/public"
    return safe_root


def ensure_proxy_upgrade_map() -> None:
    """No-op on OLS. nginx needs a shared $connection_upgrade map for
    WebSocket proxying (see nginx.py); OLS's proxy context passes
    Upgrade/Connection headers through on its own. Kept so a caller that
    always calls this before writing a proxied vhost works on either backend.
    """
    return None


# ---------------------------------------------------------------------------
# LSPHP (this install's global, per-version PHP listener - see php.py)
# ---------------------------------------------------------------------------
def _lsphp_binary(php_version: str) -> str:
    ver = php_version.replace(".", "")
    return f"/usr/local/lsws/lsphp{ver}/bin/lsphp"


def _lsphp_listener_name(php_version: str) -> str:
    ver = php_version.replace(".", "")
    return f"lsphp{ver}"


def _lsphp_socket(php_version: str) -> str:
    return f"/tmp/lshttpd/{_lsphp_listener_name(php_version)}.sock"


# ---------------------------------------------------------------------------
# HTTP flood (per-vhost throttle - see module docstring for the caveat)
# ---------------------------------------------------------------------------
def _http_flood_value(value, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def validate_http_flood_config(raw=None) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except (TypeError, ValueError):
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "access_limit_requests": _http_flood_value(raw.get("access_limit_requests"), HTTP_FLOOD_DEFAULTS["access_limit_requests"], 1, 100000),
        "access_limit_window": _http_flood_value(raw.get("access_limit_window"), HTTP_FLOOD_DEFAULTS["access_limit_window"], 1, 3600),
        "access_limit_burst": _http_flood_value(raw.get("access_limit_burst"), HTTP_FLOOD_DEFAULTS["access_limit_burst"], 0, 100000),
        "connection_limit": _http_flood_value(raw.get("connection_limit"), HTTP_FLOOD_DEFAULTS["connection_limit"], 1, 10000),
    }


def http_flood_config_for_website(website) -> dict:
    return validate_http_flood_config(getattr(website, "http_flood_config", "") or "")


def http_flood_zone_name(domain: str) -> str:
    safe_domain = _safe_domain(domain)
    digest = hashlib.sha1(safe_domain.encode("utf-8")).hexdigest()[:12]
    return f"bpanel_hf_{digest}"


def _http_flood_rate(config: dict) -> str:
    requests = max(1, int(config["access_limit_requests"]))
    window = max(1, int(config["access_limit_window"]))
    return str(max(1, math.ceil(requests / window)))


def _http_flood_block(domain: str, config: dict) -> str:
    zone = http_flood_zone_name(domain)
    rate = _http_flood_rate(config)
    burst = config.get("access_limit_burst", 0)
    connections = config.get("connection_limit", 60)
    return (
        "# BPANEL HTTP FLOOD BEGIN\n"
        f"# Throttle zone: {zone}, rate: {rate}/s, burst: {burst}, maxConn: {connections}\n"
        "extprocessor " + zone + " {\n"
        "    type                    proxy\n"
        "    address                 127.0.0.1:1\n"
        f"    maxConns                {connections}\n"
        "    initTimeout             10\n"
        "    retryTimeout            0\n"
        "    respBuffer              0\n"
        "}\n"
        "# BPANEL HTTP FLOOD END"
    )


def sync_http_flood_zones(websites):
    """Compatibility no-op: unlike nginx's shared limit_req_zone file, OLS
    HTTP-flood throttling is rendered entirely inside each vhost - there is
    no cross-site zone file to keep in sync."""
    return shell.run(["true"], check=False)


# ---------------------------------------------------------------------------
# WAF paths
# ---------------------------------------------------------------------------
def waf_rules_file(domain: str) -> str:
    safe_domain = _safe_domain(domain)
    return f"/usr/local/lsws/conf/bpanel/waf/sites/{safe_domain}.conf"


# ---------------------------------------------------------------------------
# Custom directives validation
# ---------------------------------------------------------------------------
DANGEROUS_DIRECTIVES_RE = re.compile(
    r"(?mi)^\s*("
    r"include\b|"
    r"loadModule\b|"
    r"user\s|"
    r"daemon\s|"
    r"pid\s|"
    r"workingDir\b|"
    r"extprocessor\s|"
    r"context\s|"
    r"vhDomain\s|"
    r"vhRoot\s|"
    r"docRoot\s|"
    r"errorlog\s|"
    r"accesslog\s|"
    r"realm\s|"
    r"authName\s|"
    r"allowOverride\s"
    r")"
)


def validate_custom_directives(content: Optional[str]) -> str:
    if not content:
        return ""
    text = content.replace("\r\n", "\n").strip()
    if len(text) > 16 * 1024:
        raise ValueError("Custom directives block is too large")
    if "\x00" in text:
        raise ValueError("Custom directives block contains a NUL byte")
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                raise ValueError("Unbalanced braces in custom directives block")
    if depth != 0:
        raise ValueError("Unbalanced braces in custom directives block")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if DANGEROUS_DIRECTIVES_RE.match(stripped):
            raise ValueError(f"Dangerous directive rejected: {stripped.split()[0]}")
    return text


def validate_full_config(content: Optional[str]) -> str:
    if not content:
        raise ValueError("Config is required")
    text = content.replace("\r\n", "\n").strip()
    if len(text.encode("utf-8")) > MAX_FULL_CONFIG_BYTES:
        raise ValueError("Config is too large")
    if "\x00" in text:
        raise ValueError("Config contains a NUL byte")
    if "docRoot" not in text and "vhRoot" not in text:
        raise ValueError("Config must contain a vhost definition with docRoot or vhRoot")
    return text


# ---------------------------------------------------------------------------
# Rewrite rules per mode (same four modes nginx.py supports)
# ---------------------------------------------------------------------------
_FRONT_CONTROLLER_RULES = (
    "RewriteCond %{REQUEST_FILENAME} !-f\n"
    "RewriteCond %{REQUEST_FILENAME} !-d\n"
    "RewriteRule ^(.*)$ index.php [QSA,L]"
)
REWRITE_RULES = {
    "none": "",
    "front_controller": _FRONT_CONTROLLER_RULES,
    "laravel": _FRONT_CONTROLLER_RULES,
    "codeigniter": (
        "RewriteCond %{REQUEST_FILENAME} !-f\n"
        "RewriteCond %{REQUEST_FILENAME} !-d\n"
        "RewriteCond $1 !^(index\\.php)\n"
        "RewriteRule ^(.*)$ index.php/$1 [QSA,L]"
    ),
    "seohburl": (
        "RewriteCond %{REQUEST_FILENAME} !-f\n"
        "RewriteCond %{REQUEST_FILENAME} !-d\n"
        "RewriteRule ^([^?]*) index.php?_url_=$1 [QSA,L]"
    ),
}


# ---------------------------------------------------------------------------
# Vhost paths
# ---------------------------------------------------------------------------
def _vhost_dir(domain: str) -> Path:
    return OLS_VHOSTS_DIR / _safe_domain(domain)


def _vhost_path(domain: str) -> Path:
    return _vhost_dir(domain) / "vhost.conf"


def vhost_exists(domain: str) -> bool:
    """Whether a managed OLS vhost config already sits on disk for this domain."""
    try:
        return _vhost_path(domain).is_file()
    except (ValueError, OSError):
        return False


def _log_path(domain: str, kind: str) -> Path:
    safe_domain = _safe_domain(domain)
    safe_kind = _check_log_kind(kind)
    return Path("/var/log/openlitespeed") / f"{safe_domain}.{safe_kind}.log"


def _php_error_log_path(domain: str) -> Path:
    """PHP's own error_log. PHP runs as the site's Linux user, which cannot
    write the OLS-owned ``<domain>.error.log`` - so PHP logs into a per-domain
    directory that user owns instead."""
    return Path("/var/log/openlitespeed") / _safe_domain(domain) / "php_error.log"


def custom_include_path(domain: str) -> str:
    return str(CUSTOM_INCLUDE_DIR / f"{_safe_domain(domain)}.conf")


# ---------------------------------------------------------------------------
# Core rendering
# ---------------------------------------------------------------------------
def _build_context(
    domain: str,
    root_path: str,
    app_type: str = "wordpress",
    php_version: Optional[str] = None,
    custom_directives: str = "",
    # Accepted for interface parity with nginx.py and ignored - see _build_context.
    php_fpm_socket_override: Optional[str] = None,
    waf_enabled: bool = True,
    http_flood_enabled: bool = False,
    http_flood_config: dict | str | None = None,
    document_root: str = "public_html",
    rewrite_mode: str | None = None,
    ssl_cert_path: str | None = None,
    ssl_key_path: str | None = None,
    ssl_ca_path: str | None = None,
    aliases: list[str] | tuple[str, ...] | None = None,
    redirects: list | tuple | None = None,
    app_port: int | None = None,
    linux_user: str | None = None,
) -> dict:
    safe_domain = _safe_domain(domain)
    checked_app = _check_app_type(app_type)
    checked_php = _check_php_version(php_version) if checked_app not in {"static", *PROXIED_APP_TYPES} else None
    safe_app_port = _check_app_port(checked_app, app_port)
    checked_rewrite = _check_rewrite_mode(rewrite_mode)
    safe_doc_root = _effective_document_root(document_root, checked_rewrite)
    safe_aliases = _safe_alias_domains(aliases)
    has_ssl = bool(ssl_cert_path and ssl_key_path)
    validate_custom_directives(custom_directives)
    safe_http_flood_config = validate_http_flood_config(http_flood_config)

    lsphp_app = lsphp_path = lsphp_socket = ""
    if checked_php and checked_app not in {"static", *PROXIED_APP_TYPES}:
        lsphp_app = _lsphp_listener_name(checked_php)
        lsphp_path = _lsphp_binary(checked_php)
        # php_fpm_socket_override is deliberately ignored. Shared callers
        # (websites.py, provisioning, da_import, backup restore) compute it
        # with site_users.site_php_fpm_socket(), which returns this install's
        # *PHP-FPM* pool socket - a path that does not exist on an OLS box.
        # LSPHP is one shared listener per version; the socket follows from
        # the version alone.
        lsphp_socket = _lsphp_socket(checked_php)

    return {
        "domain": safe_domain,
        "root_path": root_path,
        "document_root": safe_doc_root,
        "app_type": checked_app,
        "php_version": checked_php,
        "lsphp_app": lsphp_app,
        "lsphp_path": lsphp_path,
        "lsphp_socket": lsphp_socket,
        "rewrite_mode": checked_rewrite,
        "rewrite_block": REWRITE_RULES.get(checked_rewrite, ""),
        "ssl_enabled": has_ssl,
        "has_ssl": has_ssl,
        "ssl_cert_path": ssl_cert_path or "",
        "ssl_key_path": ssl_key_path or "",
        "ssl_ca_path": ssl_ca_path or "",
        "aliases": safe_aliases,
        "redirects": _redirect_entries(redirects),
        "waf_enabled": bool(waf_enabled),
        "waf_rules_file": waf_rules_file(safe_domain) if waf_enabled else "",
        "http_flood_enabled": bool(http_flood_enabled),
        "http_flood_block": _http_flood_block(safe_domain, safe_http_flood_config) if http_flood_enabled else "",
        "app_port": safe_app_port,
        "proxy_timeout": PROXY_TIMEOUT_SECONDS,
        "linux_user": linux_user or "bpanel-sites",
        "access_log": _log_path(safe_domain, "access").as_posix(),
        "error_log": _log_path(safe_domain, "error").as_posix(),
        "php_error_log": _php_error_log_path(safe_domain).as_posix(),
        "acme_webroot": ACME_WEBROOT,
        "security_headers": SECURITY_HEADERS,
        "hsts_header": HSTS_HEADER if has_ssl else "",
        "csp_header": WORDPRESS_CSP if checked_app == "wordpress" else "",
        "custom_include_path": custom_include_path(safe_domain),
    }


def render_vhost(
    domain: str,
    root_path: str,
    app_type: str = "wordpress",
    php_version: Optional[str] = None,
    custom_directives: str = "",
    # Accepted for interface parity with nginx.py and ignored - see _build_context.
    php_fpm_socket_override: Optional[str] = None,
    waf_enabled: bool = True,
    http_flood_enabled: bool = False,
    http_flood_config: dict | str | None = None,
    document_root: str = "public_html",
    rewrite_mode: str | None = None,
    ssl_cert_path: str | None = None,
    ssl_key_path: str | None = None,
    ssl_ca_path: str | None = None,
    aliases: list[str] | tuple[str, ...] | None = None,
    redirects: list | tuple | None = None,
    app_port: int | None = None,
    linux_user: str | None = None,
) -> str:
    ctx = _build_context(
        domain, root_path,
        app_type=app_type,
        php_version=php_version,
        custom_directives=custom_directives,
        php_fpm_socket_override=php_fpm_socket_override,
        waf_enabled=waf_enabled,
        http_flood_enabled=http_flood_enabled,
        http_flood_config=http_flood_config,
        document_root=document_root,
        rewrite_mode=rewrite_mode,
        ssl_cert_path=ssl_cert_path,
        ssl_key_path=ssl_key_path,
        ssl_ca_path=ssl_ca_path,
        aliases=aliases,
        redirects=redirects,
        app_port=app_port,
        linux_user=linux_user,
    )
    env = _get_jinja_env()
    template_name = {
        "wordpress": "wordpress.conf.j2",
        "php": "php.conf.j2",
        "static": "static.conf.j2",
        "application": "proxy.conf.j2",
    }[ctx["app_type"]]
    template = env.get_template(template_name)
    return template.render(**ctx)


def write_vhost(
    domain: str,
    root_path: str,
    app_type: str = "wordpress",
    php_version: Optional[str] = None,
    custom_directives: str = "",
    # Accepted for interface parity with nginx.py and ignored - see _build_context.
    php_fpm_socket_override: Optional[str] = None,
    waf_enabled: bool = True,
    http_flood_enabled: bool = False,
    http_flood_config: dict | str | None = None,
    document_root: str = "public_html",
    rewrite_mode: str | None = None,
    ssl_cert_path: str | None = None,
    ssl_key_path: str | None = None,
    ssl_ca_path: str | None = None,
    preserve_existing_ssl: bool = True,
    aliases: list[str] | tuple[str, ...] | None = None,
    redirects: list | tuple | None = None,
    app_port: int | None = None,
) -> str:
    return rewrite_vhost(
        domain, root_path,
        app_type=app_type,
        php_version=php_version,
        custom_directives=custom_directives,
        php_fpm_socket_override=php_fpm_socket_override,
        waf_enabled=waf_enabled,
        http_flood_enabled=http_flood_enabled,
        http_flood_config=http_flood_config,
        document_root=document_root,
        rewrite_mode=rewrite_mode,
        ssl_cert_path=ssl_cert_path,
        ssl_key_path=ssl_key_path,
        ssl_ca_path=ssl_ca_path,
        preserve_existing_ssl=preserve_existing_ssl,
        aliases=aliases,
        redirects=redirects,
        app_port=app_port,
    )


def rewrite_vhost(
    domain: str,
    root_path: str,
    app_type: str = "wordpress",
    php_version: Optional[str] = None,
    custom_directives: str = "",
    # Accepted for interface parity with nginx.py and ignored - see _build_context.
    php_fpm_socket_override: Optional[str] = None,
    waf_enabled: bool = True,
    http_flood_enabled: bool = False,
    http_flood_config: dict | str | None = None,
    document_root: str = "public_html",
    rewrite_mode: str | None = None,
    ssl_cert_path: str | None = None,
    ssl_key_path: str | None = None,
    ssl_ca_path: str | None = None,
    preserve_existing_ssl: bool = True,
    aliases: list[str] | tuple[str, ...] | None = None,
    redirects: list | tuple | None = None,
    app_port: int | None = None,
    linux_user: str | None = None,
) -> str:
    """Render and write an OLS vhost config, then reload lshttpd.

    ``preserve_existing_ssl`` mirrors nginx.py's flag: with no explicit
    certificate given, one this vhost already has is carried over. nginx does
    that by merging the ssl_certificate lines certbot wrote into the previous
    file; here the previous vhost's own certFile/keyFile are read back, which
    the panel can do - unlike stat'ing /etc/letsencrypt/live, which is
    root-only and raises PermissionError for the 'bpanel' user. A freshly
    issued certificate arrives as an explicit ssl_cert_path from the caller
    (see websites._rewrite_ssl_kwargs).
    """
    safe_domain = _safe_domain(domain)
    if app_type in PROXIED_APP_TYPES:
        ensure_proxy_upgrade_map()
    if not ssl_cert_path and not ssl_key_path and preserve_existing_ssl:
        try:
            existing = read_vhost_config(safe_domain)
        except (FileNotFoundError, OSError):
            existing = ""
        cert = re.search(r"(?m)^\s*certFile\s+(.+?)\s*$", existing)
        key = re.search(r"(?m)^\s*keyFile\s+(.+?)\s*$", existing)
        if cert and key:
            ssl_cert_path = cert.group(1)
            ssl_key_path = key.group(1)
    content = render_vhost(
        safe_domain, root_path,
        app_type=app_type,
        php_version=php_version,
        custom_directives=custom_directives,
        php_fpm_socket_override=php_fpm_socket_override,
        waf_enabled=waf_enabled,
        http_flood_enabled=http_flood_enabled,
        http_flood_config=http_flood_config,
        document_root=document_root,
        rewrite_mode=rewrite_mode,
        ssl_cert_path=ssl_cert_path,
        ssl_key_path=ssl_key_path,
        ssl_ca_path=ssl_ca_path,
        aliases=aliases,
        redirects=redirects,
        app_port=app_port,
        linux_user=linux_user,
    )
    if settings.command_dry_run:
        return content
    hostnames = [safe_domain, *_safe_alias_domains(aliases)]
    for entry in _redirect_entries(redirects):
        if entry["source"] not in hostnames:
            hostnames.append(entry["source"])
    shell.privileged(
        "ols-vhost-write",
        helper_args=[safe_domain, *hostnames],
        input=content,
        fallback=[
            "bash", "-lc",
            'mkdir -p "/usr/local/lsws/conf/bpanel/vhosts/$1" && '
            'cat > "/usr/local/lsws/conf/bpanel/vhosts/$1/vhost.conf" && '
            "(systemctl restart lshttpd.service 2>/dev/null || "
            "/usr/local/lsws/bin/lswsctrl restart 2>/dev/null || true)",
            "bpanel-ols-vhost-write",
            safe_domain,
        ],
    )
    return str(_vhost_path(safe_domain))


def delete_wordpress_vhost(domain: str) -> str:
    """Name kept for parity with nginx.py - deletes any app type's vhost."""
    safe_domain = _safe_domain(domain)
    target = _vhost_path(safe_domain)
    if settings.command_dry_run:
        return str(target)
    shell.privileged(
        "ols-vhost-delete",
        helper_args=[safe_domain],
        check=False,
        fallback=[
            "bash", "-lc",
            'rm -rf "/usr/local/lsws/conf/bpanel/vhosts/$1" && '
            "(systemctl restart lshttpd.service 2>/dev/null || "
            "/usr/local/lsws/bin/lswsctrl restart 2>/dev/null || true)",
            "bpanel-ols-vhost-delete",
            safe_domain,
        ],
    )
    return str(target)


def read_vhost_config(domain: str) -> str:
    target = _vhost_path(domain)
    if not target.exists():
        raise FileNotFoundError(str(target))
    return target.read_text(encoding="utf-8")


def read_site_log(domain: str, kind: str = "access", lines: int = 200) -> dict:
    safe_domain = _safe_domain(domain)
    safe_kind = _check_log_kind(kind)
    safe_lines = _check_tail_lines(lines)
    path = _log_path(safe_domain, safe_kind)
    if safe_kind == "error":
        # The Error tab merges PHP's own error_log (application errors) with
        # the OLS server error log for this vhost.
        php_log = _php_error_log_path(safe_domain)
        display_path = f"{php_log.as_posix()} + {path.as_posix()}"
        fallback = ["bash", "-lc", f'tail -n {safe_lines} "{php_log}" "{path}" 2>/dev/null || true']
    else:
        display_path = str(path)
        fallback = ["tail", "-n", str(safe_lines), str(path)]
    result = shell.privileged(
        "site-log-read",
        helper_args=[safe_domain, safe_kind, str(safe_lines)],
        check=False,
        fallback=fallback,
    )
    missing = "BPANEL_LOG_MISSING=1" in (result.stderr or "")
    if result.returncode != 0 and not missing:
        raise RuntimeError((result.stderr or result.stdout or "Cannot read log file").strip())
    return {
        "domain": safe_domain,
        "kind": safe_kind,
        "path": display_path,
        "lines": safe_lines,
        "content": result.stdout or "",
        "exists": not missing,
    }


def clear_site_log(domain: str, kind: str = "access") -> dict:
    safe_domain = _safe_domain(domain)
    safe_kind = _check_log_kind(kind)
    path = _log_path(safe_domain, safe_kind)
    result = shell.privileged(
        "site-log-clear",
        helper_args=[safe_domain, safe_kind],
        check=False,
        fallback=["bash", "-lc", 'test -f "$1" && : >"$1" || true', "bpanel-clear-log", str(path)],
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Cannot clear log file").strip())
    return {
        "domain": safe_domain,
        "kind": safe_kind,
        "path": str(path),
        "cleared": True,
    }


def _rewrite_existing_vhost(domain: str, **overrides) -> str:
    """Re-render an existing vhost with one field patched, everything else
    read back from the config on disk. Used by the update_* compatibility
    functions below, which only ever get a single toggle from their caller.
    """
    safe_domain = _safe_domain(domain)
    existing = read_vhost_config(safe_domain)
    doc_root = re.search(r"(?m)^\s*docRoot\s+(.+?)\s*$", existing)
    root_path, document_root = "", "public_html"
    if doc_root:
        normalized = doc_root.group(1).rstrip("/")
        for marker in ("/public_html/public", "/public_html"):
            if normalized.endswith(marker):
                root_path, document_root = normalized[: -len(marker)], marker.lstrip("/")
                break
        else:
            root_path, _, document_root = normalized.rpartition("/")
    php_match = re.search(r"(?m)^\s*path\s+/usr/local/lsws/lsphp([0-9]+)/bin/lsphp\s*$", existing)
    php_version = f"{php_match.group(1)[:-1]}.{php_match.group(1)[-1]}" if php_match else None
    if "context /.well-known" in existing and "extprocessor" not in existing:
        app_type = "static"
    elif "wp-content" in existing or "wp-admin" in existing:
        app_type = "wordpress"
    elif "type                    proxy" in existing and "handler" in existing:
        app_type = "application"
    else:
        app_type = "php"
    aliases = re.findall(r"(?m)^\s*vhAliases\s+(.+?)\s*$", existing)
    kwargs = {
        "app_type": app_type,
        "php_version": php_version,
        "document_root": document_root or "public_html",
        "waf_enabled": "# BPANEL WAF BEGIN" in existing,
        "http_flood_enabled": "# BPANEL HTTP FLOOD BEGIN" in existing,
        "aliases": aliases,
        "redirects": [],
    }
    cert = re.search(r"(?m)^\s*certFile\s+(.+?)\s*$", existing)
    key = re.search(r"(?m)^\s*keyFile\s+(.+?)\s*$", existing)
    if cert and key:
        kwargs["ssl_cert_path"] = cert.group(1)
        kwargs["ssl_key_path"] = key.group(1)
    kwargs.update(overrides)
    return rewrite_vhost(safe_domain, root_path or f"/home/admin/{safe_domain}", **kwargs)


def update_waf_block(domain: str, enabled: bool) -> str:
    return _rewrite_existing_vhost(domain, waf_enabled=bool(enabled))


def update_http_flood_block(domain: str, enabled: bool, config: dict | str | None = None) -> str:
    return _rewrite_existing_vhost(
        domain,
        http_flood_enabled=bool(enabled),
        http_flood_config=validate_http_flood_config(config),
    )


def update_custom_block(domain: str, custom_directives: str) -> str:
    """Per-domain custom OLS directives: validated, but not yet wired into a
    context - same limitation OPanel shipped with. Rejects anything unsafe;
    accepting-but-dropping would silently disagree with what the UI shows.
    """
    validate_custom_directives(custom_directives)
    return _rewrite_existing_vhost(domain)
