import re
import secrets as _secrets
from pathlib import Path
from typing import Dict

from app.core.config import settings
from app.services.shell import shell


# Strict whitelists for values fed to WP-CLI to prevent flag injection.
WP_USER_RE = re.compile(r"^[A-Za-z0-9._@-]{3,60}$")
WP_TITLE_RE = re.compile(r"^[\w\s.,'\-:!()&]{1,150}$", re.UNICODE)
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{3,255}$")


WP_SALT_KEYS = (
    "AUTH_KEY", "SECURE_AUTH_KEY", "LOGGED_IN_KEY", "NONCE_KEY",
    "AUTH_SALT", "SECURE_AUTH_SALT", "LOGGED_IN_SALT", "NONCE_SALT",
)


def _generate_wp_salts() -> str:
    lines = []
    for key in WP_SALT_KEYS:
        salt = _secrets.token_urlsafe(48).replace("'", "")
        lines.append(f"define('{key}', '{salt}');")
    return "\n".join(lines)


def _render_wp_config(db_name: str, db_user: str, db_password: str) -> str:
    """Render wp-config.php directly so the DB password never appears in argv.

    PHP single-quoted strings only need ' and \\ escaping.
    """
    def esc(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")

    return (
        "<?php\n"
        f"define('DB_NAME', '{esc(db_name)}');\n"
        f"define('DB_USER', '{esc(db_user)}');\n"
        f"define('DB_PASSWORD', '{esc(db_password)}');\n"
        "define('DB_HOST', 'localhost');\n"
        "define('DB_CHARSET', 'utf8mb4');\n"
        "define('DB_COLLATE', '');\n"
        "\n"
        "$table_prefix = 'wp_';\n"
        "\n"
        f"{_generate_wp_salts()}\n"
        "\n"
        "define('WP_DEBUG', false);\n"
        "define('DISALLOW_FILE_EDIT', true);\n"
        "if ( ! defined('ABSPATH') ) {\n"
        "    define('ABSPATH', __DIR__ . '/');\n"
        "}\n"
        "require_once ABSPATH . 'wp-settings.php';\n"
    )


def _safe_value(value: str, pattern: re.Pattern, label: str) -> str:
    value = (value or "").strip()
    if value.startswith("-") or "\x00" in value or not pattern.fullmatch(value):
        raise ValueError(f"Invalid {label}")
    return value


def site_root(domain: str) -> str:
    return str(Path(settings.sites_root) / domain)


def install_wordpress(domain: str, db: Dict[str, str], title: str, admin_user: str, admin_password: str, admin_email: str) -> str:
    safe_user = _safe_value(admin_user, WP_USER_RE, "WordPress admin username")
    safe_title = _safe_value(title, WP_TITLE_RE, "WordPress site title")
    safe_email = _safe_value(admin_email, EMAIL_RE, "WordPress admin email")
    if not isinstance(admin_password, str) or len(admin_password) < 10 or "\x00" in admin_password:
        raise ValueError("WordPress admin password must be at least 10 characters")

    root = Path(site_root(domain))
    public = root / "public"
    # Create site directory with proper ownership via the helper.
    shell.privileged(
        "mkdir-site",
        helper_args=[str(root)],
        fallback=["bash", "-lc", f"mkdir -p {public} && chown -R www-data:www-data {root}"],
    )
    wp_path = f"--path={public}"

    # WP-CLI runs as www-data through the helper.
    shell.privileged("wp", helper_args=["core", "download", wp_path, "--allow-root"], fallback=["wp", "core", "download", wp_path, "--allow-root"])

    # Render wp-config.php directly to avoid leaking the DB password through
    # argv (which would be visible to other local users via /proc/<pid>/cmdline
    # or `ps auxww` while wp config create runs).
    config_path = public / "wp-config.php"
    config_content = _render_wp_config(db["db_name"], db["db_user"], db["db_password"])
    if not settings.command_dry_run:
        config_path.write_text(config_content, encoding="utf-8")
        try:
            config_path.chmod(0o640)
        except PermissionError:
            pass
    shell.privileged(
        "chown-www",
        helper_args=[str(public)],
        check=False,
        fallback=["chown", "-R", "www-data:www-data", str(public)],
    )

    install_args = [
        "core", "install", wp_path,
        f"--url=https://{domain}",
        f"--title={safe_title}",
        f"--admin_user={safe_user}",
        f"--admin_email={safe_email}",
        "--prompt=admin_password",
        "--skip-email",
        "--allow-root",
    ]
    shell.privileged(
        "wp",
        helper_args=install_args,
        fallback=["wp", *install_args],
        input=admin_password + "\n",
        sensitive=True,
    )

    fix_permissions(str(root))
    return str(root)


def fix_permissions(root_path: str):
    return shell.privileged(
        "fix-permissions",
        helper_args=[root_path],
        check=False,
        fallback=["bash", "-lc", (
            f"chown -R www-data:www-data {root_path} && "
            f"find {root_path} -type d -exec chmod 755 {{}} + && "
            f"find {root_path} -type f -exec chmod 644 {{}} + && "
            f"find {root_path} -type d -name uploads -exec chmod 775 {{}} + 2>/dev/null || true"
        )],
    )


def wp_update(path: str, action: str):
    if action == "core":
        args = ["core", "update", f"--path={path}", "--allow-root"]
    elif action == "plugins":
        args = ["plugin", "update", "--all", f"--path={path}", "--allow-root"]
    elif action == "themes":
        args = ["theme", "update", "--all", f"--path={path}", "--allow-root"]
    else:
        raise ValueError("Unsupported WordPress action")
    return shell.privileged("wp", helper_args=args, fallback=["wp", *args])


def reset_admin_password(path: str, user: str, password: str):
    safe_user = _safe_value(user, WP_USER_RE, "WordPress username")
    if not isinstance(password, str) or len(password) < 10 or "\x00" in password:
        raise ValueError("Password must be at least 10 characters")
    args = ["user", "update", safe_user, "--user_pass=/dev/stdin", f"--path={path}", "--allow-root"]
    return shell.privileged(
        "wp",
        helper_args=args,
        fallback=["wp", *args],
        input=password,
        sensitive=True,
    )


def delete_wordpress(root_path: str):
    target = Path(root_path).resolve()
    sites_root = Path(settings.sites_root).resolve()
    if sites_root not in target.parents:
        raise ValueError("Refusing to delete path outside sites root")
    return shell.privileged(
        "rm-site",
        helper_args=[str(target)],
        fallback=["rm", "-rf", str(target)],
    )
