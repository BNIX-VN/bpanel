import re
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from app.core.config import settings
from app.services.shell import shell

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "nginx"

ALLOWED_PHP_VERSIONS = {"8.3", "8.4"}
ALLOWED_APP_TYPES = {"wordpress", "static"}
DOMAIN_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+")

# Directives that must never appear inside a per-site custom block.
DANGEROUS_DIRECTIVES = re.compile(
    r"(?mi)^\s*("
    r"server\s*\{|"  # nesting server blocks
    r"http\s*\{|"
    r"include\s+|"
    r"load_module|"
    r"user\s+|"
    r"events\s*\{|"
    r"daemon\s+|"
    r"pid\s+|"
    r"working_directory|"
    r"lua_|"
    r"pcre_jit"
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
    if DANGEROUS_DIRECTIVES.search(text):
        raise ValueError(
            "Custom block must not contain server/http/events/include or module-loading directives"
        )
    if "\x00" in text:
        raise ValueError("Custom nginx block contains a NUL byte")
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
    version = _check_php_version(php_version) or settings.php_fpm_service.removeprefix("php").removesuffix("-fpm")
    if version not in ALLOWED_PHP_VERSIONS:
        raise ValueError(f"Unsupported PHP version derived from settings: {version}")
    return f"/run/php/php{version}-fpm.sock"


def _replace_php_fpm_socket(content: str, php_version: str) -> str:
    _check_php_version(php_version)
    return re.sub(
        r"fastcgi_pass\s+unix:/run/php/php[0-9.]+-fpm\.sock;",
        f"fastcgi_pass unix:{_php_fpm_socket(php_version)};",
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


def render_vhost(
    domain: str,
    root_path: str,
    app_type: str = "wordpress",
    php_version: Optional[str] = None,
    custom_directives: str = "",
) -> str:
    if not DOMAIN_RE.fullmatch((domain or "").lower()):
        raise ValueError("Invalid domain")
    _check_app_type(app_type)
    _check_php_version(php_version)
    sites_root = Path(settings.sites_root).resolve()
    resolved_root = Path(root_path).resolve()
    if sites_root != resolved_root and sites_root not in resolved_root.parents:
        raise ValueError("root_path must live under sites_root")
    safe_custom = validate_custom_nginx(custom_directives)

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=False)
    template_name = "wordpress.conf.j2" if app_type == "wordpress" else "static.conf.j2"
    template = env.get_template(template_name)
    php_fpm_socket = _php_fpm_socket(php_version)

    rendered = template.render(
        domain=domain,
        root_path=str(resolved_root),
        php_fpm_socket=php_fpm_socket,
        custom_directives=safe_custom,
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
) -> str:
    content = render_vhost(domain, root_path, app_type=app_type, php_version=php_version, custom_directives=custom_directives)
    target = Path(settings.nginx_sites_available) / f"{domain}.conf"
    if settings.command_dry_run:
        return content
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if _has_ssl_config(existing):
            shell.run(["cp", str(target), f"{target}.bak"], check=False)
            return str(target)
    target.write_text(content, encoding="utf-8")
    shell.run(["nginx", "-t"])
    shell.run(["systemctl", "reload", "nginx"])
    return str(target)


def write_wordpress_vhost(domain: str, root_path: str, php_version: Optional[str] = None) -> str:
    return write_vhost(domain, root_path, app_type="wordpress", php_version=php_version)


def rewrite_vhost(
    domain: str,
    root_path: str,
    app_type: str,
    php_version: str,
    custom_directives: str = "",
) -> str:
    target = Path(settings.nginx_sites_available) / f"{domain}.conf"
    content = render_vhost(domain, root_path, app_type=app_type, php_version=php_version, custom_directives=custom_directives)
    if settings.command_dry_run:
        return content
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        shell.run(["cp", str(target), f"{target}.bak"], check=False)
        if _has_ssl_config(existing):
            content = _merge_certbot_ssl_config(content, existing)
    old_content = target.read_text(encoding="utf-8") if target.exists() else None
    target.write_text(content, encoding="utf-8")
    result = shell.run(["nginx", "-t"], check=False)
    if result.returncode != 0:
        if old_content is not None:
            target.write_text(old_content, encoding="utf-8")
        shell.run(["nginx", "-t"], check=False)
        raise RuntimeError((result.stderr or result.stdout or "nginx -t failed").strip())
    shell.run(["systemctl", "reload", "nginx"])
    return str(target)


def rewrite_wordpress_vhost(domain: str, root_path: str, php_version: str) -> str:
    return rewrite_vhost(domain, root_path, app_type="wordpress", php_version=php_version)


def update_custom_block(domain: str, custom_directives: str) -> str:
    target = Path(settings.nginx_sites_available) / f"{domain}.conf"
    safe_custom = validate_custom_nginx(custom_directives)
    if settings.command_dry_run:
        return safe_custom
    if not target.exists():
        raise FileNotFoundError(str(target))
    existing = target.read_text(encoding="utf-8")
    new_content = _replace_custom_block(existing, safe_custom)
    shell.run(["cp", str(target), f"{target}.bak"], check=False)
    target.write_text(new_content, encoding="utf-8")
    result = shell.run(["nginx", "-t"], check=False)
    if result.returncode != 0:
        target.write_text(existing, encoding="utf-8")
        shell.run(["nginx", "-t"], check=False)
        raise RuntimeError((result.stderr or result.stdout or "nginx -t failed").strip())
    shell.run(["systemctl", "reload", "nginx"])
    return str(target)


def set_wordpress_php_version(domain: str, php_version: str) -> str:
    target = Path(settings.nginx_sites_available) / f"{domain}.conf"
    if settings.command_dry_run:
        return _php_fpm_socket(php_version)
    if not target.exists():
        raise FileNotFoundError(str(target))
    existing = target.read_text(encoding="utf-8")
    target.write_text(_replace_php_fpm_socket(existing, php_version), encoding="utf-8")
    shell.run(["nginx", "-t"])
    shell.run(["systemctl", "reload", "nginx"])
    return str(target)


def harden_existing_wordpress_vhost(domain: str, root_path: str, php_version: str | None = None) -> str:
    target = Path(settings.nginx_sites_available) / f"{domain}.conf"
    content = render_vhost(domain, root_path, app_type="wordpress", php_version=php_version)
    if settings.command_dry_run:
        return content
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if _has_ssl_config(existing):
            updated = _replace_php_fpm_socket(_ensure_hsts_header(existing), php_version) if php_version else _ensure_hsts_header(existing)
            target.write_text(updated, encoding="utf-8")
            shell.run(["nginx", "-t"])
            shell.run(["systemctl", "reload", "nginx"])
            return str(target)
    target.write_text(content, encoding="utf-8")
    shell.run(["nginx", "-t"])
    shell.run(["systemctl", "reload", "nginx"])
    return str(target)


def delete_wordpress_vhost(domain: str):
    target = Path(settings.nginx_sites_available) / f"{domain}.conf"
    if settings.command_dry_run:
        return str(target)
    target.unlink(missing_ok=True)
    shell.run(["nginx", "-t"])
    shell.run(["systemctl", "reload", "nginx"])
    return str(target)
