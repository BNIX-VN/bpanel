import re
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from app.core.config import settings
from app.services import site_users
from app.services.shell import shell

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "nginx"

ALLOWED_PHP_VERSIONS = {"5.6", "7.4", "8.0", "8.1", "8.2", "8.3", "8.4", "8.5"}
ALLOWED_APP_TYPES = {"wordpress", "php", "static"}
ALLOWED_LOG_KINDS = {"access", "error"}
DOMAIN_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+")
MAX_FULL_CONFIG_BYTES = 128 * 1024
WAF_BLOCK = """    # BPANEL WAF BEGIN
    modsecurity on;
    modsecurity_rules_file /etc/nginx/modsec/bpanel-main.conf;
    # BPANEL WAF END"""
FASTCGI_CACHE_SERVER_BLOCK = """    # BPANEL FASTCGI CACHE SERVER BEGIN
    set $bpanel_skip_cache 0;
    if ($request_method = POST) { set $bpanel_skip_cache 1; }
    if ($query_string != "") { set $bpanel_skip_cache 1; }
    if ($request_uri ~* "/wp-admin/|/wp-login.php|/xmlrpc.php|wp-.*.php|/feed/|sitemap(_index)?\\.xml") { set $bpanel_skip_cache 1; }
    if ($http_cookie ~* "comment_author|wordpress_[a-f0-9]+|wordpress_logged_in|wp-postpass|woocommerce_items_in_cart|woocommerce_cart_hash|wp_woocommerce_session|edd_items_in_cart") { set $bpanel_skip_cache 1; }
    add_header X-FastCGI-Cache $upstream_cache_status always;
    # BPANEL FASTCGI CACHE SERVER END"""
FASTCGI_CACHE_LOCATION_BLOCK = """        # BPANEL FASTCGI CACHE LOCATION BEGIN
        fastcgi_cache BPANEL_FASTCGI;
        fastcgi_cache_valid 200 301 302 10m;
        fastcgi_cache_valid 404 1m;
        fastcgi_cache_bypass $bpanel_skip_cache;
        fastcgi_no_cache $bpanel_skip_cache;
        fastcgi_cache_lock on;
        fastcgi_cache_use_stale error timeout invalid_header updating http_500 http_503;
        # BPANEL FASTCGI CACHE LOCATION END"""

# Block-opening directives that nest scopes; matched against the original
# text so the trailing ``{`` is preserved.
DANGEROUS_BLOCKS = re.compile(
    r"(?mi)(?:^|[;{}\s])\s*("
    r"server\s*\{|"
    r"http\s*\{|"
    r"events\s*\{|"
    r"stream\s*\{|"
    r"upstream\s+[@A-Za-z0-9_][A-Za-z0-9_]*\s*\{"
    r")"
)

# Single-line directives. Matched against text where ``{``, ``}``, and ``;``
# are turned into newlines so directives written on the same physical line
# as their enclosing block are still seen by the line-start anchor.
DANGEROUS_DIRECTIVES = re.compile(
    r"(?mi)^\s*("
    r"include\s+|"            # arbitrary file inclusion
    r"load_module\b|"         # load shared object
    r"user\s+|"               # change worker UID
    r"daemon\s+|"
    r"pid\s+|"
    r"working_directory\b|"
    r"lua_|"                  # ngx_lua
    r"perl_|"                 # ngx_http_perl
    r"js_|"                   # njs scripting
    r"pcre_jit\b|"
    # ---- routing / upstream subversion ----
    r"proxy_pass\b|"
    r"fastcgi_pass\b|"
    r"uwsgi_pass\b|"
    r"scgi_pass\b|"
    r"grpc_pass\b|"
    # ---- arbitrary file read / serve ----
    r"alias\s+|"
    r"root\s+|"
    r"auth_basic_user_file\b|"
    r"try_files\s+|"          # remap request to arbitrary file
    # ---- arbitrary file write via logging ----
    r"access_log\s+|"
    r"error_log\s+|"
    # ---- HTTP response control / phishing primitives ----
    r"return\s+|"             # forced redirects, body injection
    r"error_page\s+|"         # remap error responses to attacker URI
    r"rewrite\s+|"
    r"add_header\s+|"         # override security headers
    r"more_set_headers\b|"
    r"more_clear_headers\b|"
    r"auth_request\b|"        # delegate auth to attacker endpoint
    r"sub_filter\b|"          # rewrite response body
    r"sub_filter_once\b|"
    r"addition_before_body\b|"
    r"addition_after_body\b|"
    # ---- cert path override ----
    r"ssl_certificate\b|"
    r"ssl_certificate_key\b|"
    r"ssl_trusted_certificate\b"
    r")"
)


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


def _vhost_path(domain: str) -> Path:
    safe_domain = (domain or "").lower()
    if not DOMAIN_RE.fullmatch(safe_domain):
        raise ValueError("Invalid domain")
    return Path(settings.nginx_sites_available) / f"{safe_domain}.conf"


def _safe_domain(domain: str) -> str:
    safe_domain = (domain or "").strip().lower()
    if not DOMAIN_RE.fullmatch(safe_domain):
        raise ValueError("Invalid domain")
    return safe_domain


def _check_log_kind(kind: str) -> str:
    if kind not in ALLOWED_LOG_KINDS:
        raise ValueError("Log kind must be access or error")
    return kind


def _check_tail_lines(lines: int) -> int:
    try:
        value = int(lines)
    except (TypeError, ValueError) as exc:
        raise ValueError("Log lines must be a number") from exc
    if value < 1 or value > 5000:
        raise ValueError("Log lines must be between 1 and 5000")
    return value


def _log_path(domain: str, kind: str) -> Path:
    safe_domain = _safe_domain(domain)
    safe_kind = _check_log_kind(kind)
    return Path("/var/log/nginx") / f"{safe_domain}.{safe_kind}.log"


def validate_custom_nginx(content: Optional[str]) -> str:
    """Sanitize and validate a custom nginx block before rendering it inside a server { } scope."""
    if not content:
        return ""
    text = content.replace("\r\n", "\n").strip()
    if len(text) > 16 * 1024:
        raise ValueError("Custom nginx block is too large")
    # Balanced braces only (allow nested blocks inside server scope).
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                raise ValueError("Unbalanced braces in custom nginx block")
    if depth != 0:
        raise ValueError("Unbalanced braces in custom nginx block")
    if DANGEROUS_BLOCKS.search(text):
        raise ValueError(
            "Custom block must not nest server/http/events/stream/upstream blocks"
        )
    # Normalize so the line-anchored deny-list also catches directives
    # written on the same line as their enclosing block, e.g.
    # ``location /api { proxy_pass http://attacker; }`` would otherwise
    # slip past a plain ``^\s*proxy_pass`` match.
    normalized = re.sub(r"[{};]", "\n", text)
    if DANGEROUS_DIRECTIVES.search(normalized):
        raise ValueError(
            "Custom block must not contain disallowed directives (proxy_pass, alias, "
            "return, add_header, ssl_certificate, ...)"
        )
    if "\x00" in text:
        raise ValueError("Custom nginx block contains a NUL byte")
    return text


def validate_full_nginx_config(content: Optional[str]) -> str:
    if content is None:
        raise ValueError("Nginx config is required")
    text = content.replace("\r\n", "\n").strip() + "\n"
    if len(text.encode("utf-8")) > MAX_FULL_CONFIG_BYTES:
        raise ValueError("Nginx config is too large")
    if "\x00" in text:
        raise ValueError("Nginx config contains a NUL byte")
    if "server" not in text or "{" not in text:
        raise ValueError("Nginx config must contain a server block")
    return text


def _has_ssl_config(content: str) -> bool:
    return "ssl_certificate" in content or "listen 443" in content


def _merge_certbot_ssl_config(new_content: str, existing_content: str) -> str:
    server_name = "_"
    if "server_name " in new_content:
        server_name = new_content.split("server_name ", 1)[1].split(";", 1)[0].strip()
    ssl_lines = []
    seen_ssl_lines = set()
    for line in existing_content.splitlines():
        if (
            "ssl_certificate" in line
            or "include /etc/letsencrypt/options-ssl-nginx.conf" in line
            or "ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem" in line
        ) and line.strip() not in seen_ssl_lines:
            ssl_lines.append(line)
            seen_ssl_lines.add(line.strip())
    https_lines = []
    for line in new_content.splitlines():
        if "listen 80;" in line:
            https_lines.append(line.replace("listen 80;", "listen 443 ssl;"))
        else:
            https_lines.append(line)
        if "server_name" in line and ssl_lines:
            https_lines.extend(ssl_lines)
    redirect_block = "\n".join([
        "server {",
        "    listen 80;",
        f"    server_name {server_name};",
        "    return 301 https://$host$request_uri;",
        "}",
        "",
    ])
    return redirect_block + "\n".join(https_lines) + "\n"


def _ensure_hsts_header(content: str) -> str:
    security_headers = [
        ('Strict-Transport-Security', '    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;'),
        ('Permissions-Policy', '    add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=(), bluetooth=(), magnetometer=(), gyroscope=(), accelerometer=()" always;'),
        ('Content-Security-Policy', '    add_header Content-Security-Policy "default-src \'self\' https: data: blob:; script-src \'self\' \'unsafe-inline\' \'unsafe-eval\' https:; style-src \'self\' \'unsafe-inline\' https:; img-src \'self\' data: https: blob:; font-src \'self\' data: https:; connect-src \'self\' https:; frame-src \'self\' https:; object-src \'none\'; base-uri \'self\'; form-action \'self\' https:; frame-ancestors \'self\'; upgrade-insecure-requests" always;'),
    ]
    headers_to_add = [header for name, header in security_headers if name not in content]
    if not headers_to_add:
        return content
    marker = '    add_header X-XSS-Protection "1; mode=block" always;'
    if marker in content:
        return content.replace(marker, f"{marker}\n" + "\n".join(headers_to_add), 1)
    server_marker = "    server_tokens off;"
    if server_marker in content:
        return content.replace(server_marker, f"{server_marker}\n" + "\n".join(headers_to_add), 1)
    return content


def _php_fpm_socket(php_version: str | None = None) -> str:
    version = _check_php_version(php_version) or settings.default_php_version
    if version not in ALLOWED_PHP_VERSIONS:
        raise ValueError(f"Unsupported PHP version: {version}")
    return f"/run/php/php{version}-fpm.sock"


def _replace_php_fpm_socket(content: str, php_version: str) -> str:
    _check_php_version(php_version)
    return re.sub(
        r"fastcgi_pass\s+unix:/run/php/php[0-9.]+-fpm\.sock;",
        f"fastcgi_pass unix:{_php_fpm_socket(php_version)};",
        content,
    )


def _replace_fastcgi_socket(content: str, socket_path: str) -> str:
    if not re.fullmatch(r"/run/php/[A-Za-z0-9_.-]+\.sock", socket_path or ""):
        raise ValueError("Invalid PHP-FPM socket path")
    return re.sub(
        r"fastcgi_pass\s+unix:[^;]+;",
        f"fastcgi_pass unix:{socket_path};",
        content,
    )


def _replace_custom_block(content: str, custom: str) -> str:
    """Swap content between BPANEL CUSTOM markers."""
    pattern = re.compile(
        r"(    # BPANEL CUSTOM BEGIN\n)(.*?)(\n?    # BPANEL CUSTOM END)",
        re.DOTALL,
    )
    new_inner = ""
    if custom.strip():
        new_inner = "    " + custom.replace("\n", "\n    ")
    if pattern.search(content):
        return pattern.sub(
            lambda _m: f"    # BPANEL CUSTOM BEGIN\n{new_inner}\n    # BPANEL CUSTOM END",
            content,
        )
    # Fallback: insert before the closing brace.
    return content.rstrip()[:-1] + (
        "\n    # BPANEL CUSTOM BEGIN\n"
        + (new_inner + "\n" if new_inner else "")
        + "    # BPANEL CUSTOM END\n}\n"
    )


def _replace_waf_block(content: str, enabled: bool) -> str:
    pattern = re.compile(
        r"\n?    # BPANEL WAF BEGIN\n.*?\n    # BPANEL WAF END",
        re.DOTALL,
    )
    cleaned = pattern.sub("", content)
    if not enabled:
        return cleaned.rstrip() + "\n"
    if "    server_tokens off;" in cleaned:
        return cleaned.replace("    server_tokens off;", f"    server_tokens off;\n{WAF_BLOCK}", 1)
    if "    server_name " in cleaned:
        return re.sub(r"(    server_name [^;]+;)", f"\\1\n{WAF_BLOCK}", cleaned, count=1)
    match = re.search(r"server\s*\{", cleaned)
    if match:
        insert_at = match.end()
        return cleaned[:insert_at] + "\n" + WAF_BLOCK + cleaned[insert_at:]
    raise ValueError("Cannot find server block for WAF directives")


def _replace_fastcgi_cache_blocks(content: str, enabled: bool = True) -> str:
    server_pattern = re.compile(
        r"\n?    # BPANEL FASTCGI CACHE SERVER BEGIN\n.*?\n    # BPANEL FASTCGI CACHE SERVER END",
        re.DOTALL,
    )
    location_pattern = re.compile(
        r"\n?        # BPANEL FASTCGI CACHE LOCATION BEGIN\n.*?\n        # BPANEL FASTCGI CACHE LOCATION END",
        re.DOTALL,
    )
    cleaned = server_pattern.sub("", content)
    cleaned = location_pattern.sub("", cleaned)
    cleaned = re.sub(r"\n?\s*add_header\s+X-FastCGI-Cache\s+[^;]+;", "", cleaned)
    if not enabled:
        return cleaned.rstrip() + "\n"
    if "fastcgi_pass" not in cleaned:
        raise ValueError("Cannot find a PHP FastCGI location")

    if "    client_max_body_size " in cleaned:
        cleaned = re.sub(
            r"(    client_max_body_size [^;]+;)",
            lambda match: f"{match.group(1)}\n\n{FASTCGI_CACHE_SERVER_BLOCK}",
            cleaned,
            count=1,
        )
    elif "    server_tokens off;" in cleaned:
        cleaned = cleaned.replace("    server_tokens off;", f"    server_tokens off;\n\n{FASTCGI_CACHE_SERVER_BLOCK}", 1)
    else:
        cleaned = re.sub(
            r"(    server_name [^;]+;)",
            lambda match: f"{match.group(1)}\n\n{FASTCGI_CACHE_SERVER_BLOCK}",
            cleaned,
            count=1,
        )

    if re.search(r"fastcgi_read_timeout\s+[^;]+;", cleaned):
        return re.sub(
            r"(        fastcgi_read_timeout\s+[^;]+;)",
            lambda match: f"{match.group(1)}\n{FASTCGI_CACHE_LOCATION_BLOCK}",
            cleaned,
            count=1,
        )
    return re.sub(
        r"(        fastcgi_pass\s+[^;]+;)",
        lambda match: f"{match.group(1)}\n{FASTCGI_CACHE_LOCATION_BLOCK}",
        cleaned,
        count=1,
    )


def _test_and_reload(target: Path, old_content: Optional[str]) -> None:
    test = shell.privileged("nginx-test", check=False, fallback=["nginx", "-t"])
    if test.returncode != 0:
        if old_content is not None:
            target.write_text(old_content, encoding="utf-8")
        raise RuntimeError((test.stderr or test.stdout or "nginx -t failed").strip())
    shell.privileged("nginx-reload", fallback=["bash", "-lc", "nginx -t && systemctl reload nginx"])


def render_vhost(
    domain: str,
    root_path: str,
    app_type: str = "wordpress",
    php_version: Optional[str] = None,
    custom_directives: str = "",
    php_fpm_socket_override: Optional[str] = None,
    waf_enabled: bool = True,
) -> str:
    if not DOMAIN_RE.fullmatch((domain or "").lower()):
        raise ValueError("Invalid domain")
    _check_app_type(app_type)
    _check_php_version(php_version)
    resolved_root = Path(root_path).resolve()
    if not site_users.is_site_root_for_domain(resolved_root, domain):
        raise ValueError("root_path must be the managed root for this domain")
    safe_custom = validate_custom_nginx(custom_directives)

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=False)
    template_name = {
        "wordpress": "wordpress.conf.j2",
        "php": "php.conf.j2",
        "static": "static.conf.j2",
    }[app_type]
    template = env.get_template(template_name)
    php_fpm_socket = php_fpm_socket_override or _php_fpm_socket(php_version)

    rendered = template.render(
        domain=domain,
        root_path=str(resolved_root),
        php_fpm_socket=php_fpm_socket,
        custom_directives=safe_custom,
        waf_enabled=bool(waf_enabled),
    )
    return rendered


# Back-compat shim for older imports.
def render_wordpress_vhost(domain: str, root_path: str, php_version: Optional[str] = None) -> str:
    return render_vhost(domain, root_path, app_type="wordpress", php_version=php_version)


def write_vhost(
    domain: str,
    root_path: str,
    app_type: str = "wordpress",
    php_version: Optional[str] = None,
    custom_directives: str = "",
    php_fpm_socket_override: Optional[str] = None,
    waf_enabled: bool = True,
) -> str:
    content = render_vhost(
        domain,
        root_path,
        app_type=app_type,
        php_version=php_version,
        custom_directives=custom_directives,
        php_fpm_socket_override=php_fpm_socket_override,
        waf_enabled=waf_enabled,
    )
    target = _vhost_path(domain)
    if settings.command_dry_run:
        return content
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if _has_ssl_config(existing):
            target.with_suffix(target.suffix + ".bak").write_text(existing, encoding="utf-8")
            return str(target)
    target.write_text(content, encoding="utf-8")
    shell.privileged("nginx-reload", fallback=["bash", "-lc", "nginx -t && systemctl reload nginx"])
    return str(target)


def write_wordpress_vhost(domain: str, root_path: str, php_version: Optional[str] = None) -> str:
    return write_vhost(domain, root_path, app_type="wordpress", php_version=php_version)


def rewrite_vhost(
    domain: str,
    root_path: str,
    app_type: str,
    php_version: str,
    custom_directives: str = "",
    php_fpm_socket_override: Optional[str] = None,
    waf_enabled: bool = True,
) -> str:
    target = _vhost_path(domain)
    content = render_vhost(
        domain,
        root_path,
        app_type=app_type,
        php_version=php_version,
        custom_directives=custom_directives,
        php_fpm_socket_override=php_fpm_socket_override,
        waf_enabled=waf_enabled,
    )
    if settings.command_dry_run:
        return content
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        target.with_suffix(target.suffix + ".bak").write_text(existing, encoding="utf-8")
        if _has_ssl_config(existing):
            content = _merge_certbot_ssl_config(content, existing)
    old_content = target.read_text(encoding="utf-8") if target.exists() else None
    target.write_text(content, encoding="utf-8")
    _test_and_reload(target, old_content)
    return str(target)


def rewrite_wordpress_vhost(domain: str, root_path: str, php_version: str) -> str:
    return rewrite_vhost(domain, root_path, app_type="wordpress", php_version=php_version)


def update_custom_block(domain: str, custom_directives: str) -> str:
    target = _vhost_path(domain)
    safe_custom = validate_custom_nginx(custom_directives)
    if settings.command_dry_run:
        return safe_custom
    if not target.exists():
        raise FileNotFoundError(str(target))
    existing = target.read_text(encoding="utf-8")
    new_content = _replace_custom_block(existing, safe_custom)
    target.with_suffix(target.suffix + ".bak").write_text(existing, encoding="utf-8")
    target.write_text(new_content, encoding="utf-8")
    _test_and_reload(target, existing)
    return str(target)


def set_wordpress_php_version(domain: str, php_version: str) -> str:
    target = _vhost_path(domain)
    if settings.command_dry_run:
        return _php_fpm_socket(php_version)
    if not target.exists():
        raise FileNotFoundError(str(target))
    existing = target.read_text(encoding="utf-8")
    target.write_text(_replace_php_fpm_socket(existing, php_version), encoding="utf-8")
    shell.privileged("nginx-reload", fallback=["bash", "-lc", "nginx -t && systemctl reload nginx"])
    return str(target)


def harden_existing_wordpress_vhost(
    domain: str,
    root_path: str,
    php_version: str | None = None,
    php_fpm_socket_override: Optional[str] = None,
    waf_enabled: bool = True,
) -> str:
    target = _vhost_path(domain)
    content = render_vhost(
        domain,
        root_path,
        app_type="wordpress",
        php_version=php_version,
        php_fpm_socket_override=php_fpm_socket_override,
        waf_enabled=waf_enabled,
    )
    if settings.command_dry_run:
        return content
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if _has_ssl_config(existing):
            updated = _ensure_hsts_header(existing)
            if php_fpm_socket_override:
                updated = _replace_fastcgi_socket(updated, php_fpm_socket_override)
            elif php_version:
                updated = _replace_php_fpm_socket(updated, php_version)
            updated = _replace_waf_block(updated, waf_enabled)
            target.write_text(updated, encoding="utf-8")
            shell.privileged("nginx-reload", fallback=["bash", "-lc", "nginx -t && systemctl reload nginx"])
            return str(target)
    target.write_text(content, encoding="utf-8")
    shell.privileged("nginx-reload", fallback=["bash", "-lc", "nginx -t && systemctl reload nginx"])
    return str(target)


def delete_wordpress_vhost(domain: str):
    target = _vhost_path(domain)
    if settings.command_dry_run:
        return str(target)
    target.unlink(missing_ok=True)
    shell.privileged("nginx-reload", fallback=["bash", "-lc", "nginx -t && systemctl reload nginx"])
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
    result = shell.privileged(
        "site-log-read",
        helper_args=[safe_domain, safe_kind, str(safe_lines)],
        check=False,
        fallback=["tail", "-n", str(safe_lines), str(path)],
    )
    missing = "BPANEL_LOG_MISSING=1" in (result.stderr or "")
    if result.returncode != 0 and not missing:
        raise RuntimeError((result.stderr or result.stdout or "Cannot read log file").strip())
    return {
        "domain": safe_domain,
        "kind": safe_kind,
        "path": str(path),
        "lines": safe_lines,
        "content": result.stdout or "",
        "exists": not missing,
    }


def update_full_config(domain: str, content: str) -> str:
    target = _vhost_path(domain)
    safe_content = validate_full_nginx_config(content)
    if settings.command_dry_run:
        return safe_content
    if not target.exists():
        raise FileNotFoundError(str(target))
    existing = target.read_text(encoding="utf-8")
    target.with_suffix(target.suffix + ".bak").write_text(existing, encoding="utf-8")
    target.write_text(safe_content, encoding="utf-8")
    _test_and_reload(target, existing)
    return str(target)


def update_waf_block(domain: str, enabled: bool) -> str:
    target = _vhost_path(domain)
    if settings.command_dry_run:
        return _replace_waf_block("server {\n    server_name example.com;\n}\n", enabled)
    if not target.exists():
        raise FileNotFoundError(str(target))
    existing = target.read_text(encoding="utf-8")
    new_content = _replace_waf_block(existing, enabled)
    target.with_suffix(target.suffix + ".bak").write_text(existing, encoding="utf-8")
    target.write_text(new_content, encoding="utf-8")
    _test_and_reload(target, existing)
    return str(target)


def ensure_wordpress_fastcgi_cache(domain: str) -> str:
    target = _vhost_path(domain)
    if settings.command_dry_run:
        return _replace_fastcgi_cache_blocks(
            "server {\n    server_name example.com;\n    client_max_body_size 1100M;\n    location ~ \\.php$ {\n        fastcgi_pass unix:/run/php/php8.3-fpm.sock;\n        fastcgi_read_timeout 300;\n    }\n}\n",
            True,
        )
    if not target.exists():
        raise FileNotFoundError(str(target))
    existing = target.read_text(encoding="utf-8")
    new_content = _replace_fastcgi_cache_blocks(existing, True)
    if new_content == existing:
        return str(target)
    target.with_suffix(target.suffix + ".bak").write_text(existing, encoding="utf-8")
    target.write_text(new_content, encoding="utf-8")
    _test_and_reload(target, existing)
    return str(target)
