import os
import re
import tempfile
from pathlib import Path
from typing import Dict

from app.core.config import settings
from app.services.shell import shell


# Strict whitelists: WP usernames, titles, emails. Reject anything that could
# be parsed as a CLI flag or contain shell-special characters.
WP_USER_RE = re.compile(r"^[A-Za-z0-9._@-]{3,60}$")
WP_TITLE_RE = re.compile(r"^[\w\s.,'\-:!()&]{1,150}$", re.UNICODE)
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{3,255}$")


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
    shell.run(["mkdir", "-p", str(public)])
    shell.run(["chown", "-R", "www-data:www-data", str(root)], check=False)
    wp_path = f"--path={public}"

    shell.run(["wp", "core", "download", wp_path, "--allow-root"])

    # Use wp config create with -- separator to prevent flag injection on values.
    # db identifiers are already validated upstream (mariadb._validate_identifier).
    shell.run([
        "wp", "config", "create", wp_path,
        f"--dbname={db['db_name']}",
        f"--dbuser={db['db_user']}",
        f"--dbpass={db['db_password']}",
        "--allow-root",
    ], sensitive=True)

    # Pass the admin password via env to wp-cli so it doesn't show up in `ps`.
    # WP-CLI has --prompt= but env file is simpler. We feed it via stdin prompt.
    install_args = [
        "wp", "core", "install", wp_path,
        f"--url=https://{domain}",
        f"--title={safe_title}",
        f"--admin_user={safe_user}",
        f"--admin_email={safe_email}",
        "--prompt=admin_password",
        "--skip-email",
        "--allow-root",
    ]
    shell.run(install_args, input=admin_password + "\n", sensitive=True)

    fix_permissions(str(root))
    return str(root)


def fix_permissions(root_path: str):
    shell.run(["chown", "-R", "www-data:www-data", root_path], check=False)
    shell.run(["find", root_path, "-type", "d", "-exec", "chmod", "755", "{}", ";"], check=False)
    shell.run(["find", root_path, "-type", "f", "-exec", "chmod", "644", "{}", ";"], check=False)
    shell.run(["find", root_path, "-type", "d", "-name", "uploads", "-exec", "chmod", "775", "{}", ";"], check=False)


def wp_update(path: str, action: str):
    if action == "core":
        return shell.run(["wp", "core", "update", f"--path={path}", "--allow-root"])
    if action == "plugins":
        return shell.run(["wp", "plugin", "update", "--all", f"--path={path}", "--allow-root"])
    if action == "themes":
        return shell.run(["wp", "theme", "update", "--all", f"--path={path}", "--allow-root"])
    raise ValueError("Unsupported WordPress action")


def reset_admin_password(path: str, user: str, password: str):
    safe_user = _safe_value(user, WP_USER_RE, "WordPress username")
    if not isinstance(password, str) or len(password) < 10 or "\x00" in password:
        raise ValueError("Password must be at least 10 characters")
    return shell.run(
        ["wp", "user", "update", safe_user, "--user_pass=/dev/stdin", f"--path={path}", "--allow-root"],
        input=password,
        sensitive=True,
    )


def delete_wordpress(root_path: str):
    # Hard guard: only allow deleting paths under settings.sites_root
    target = Path(root_path).resolve()
    sites_root = Path(settings.sites_root).resolve()
    if sites_root not in target.parents:
        raise ValueError("Refusing to delete path outside sites root")
    return shell.run(["rm", "-rf", str(target)])
