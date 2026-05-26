import hashlib
import re
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.services.shell import shell


LINUX_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{2,31}$")
DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")
HOME_ROOT = Path("/home")
RESERVED_LINUX_USERS = {
    "root", "daemon", "bin", "sys", "sync", "games", "man", "lp", "mail",
    "news", "uucp", "proxy", "www-data", "backup", "list", "irc", "_apt",
    "nobody", "bpanel", "bpanel-sites", "mysql", "redis", "nginx",
}


def linux_user_for_domain(domain: str) -> str:
    """Return a deterministic, Linux-safe username for a website domain."""
    normalized = (domain or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_") or "site"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]
    username = f"bp_{slug[:18]}_{digest}"
    return username[:32]


def validate_linux_user(username: str) -> str:
    if not LINUX_USER_RE.fullmatch(username or "") or username in RESERVED_LINUX_USERS:
        raise ValueError("Invalid site Linux user")
    return username


def linux_user_for_panel_username(username: str) -> str:
    return validate_linux_user((username or "").strip().lower())


def php_fpm_socket(username: Optional[str], php_version: Optional[str] = None) -> Optional[str]:
    if not username:
        return None
    safe_user = validate_linux_user(username)
    if php_version:
        safe_version = php_version.replace(".", "_")
        return f"/run/php/bpanel-{safe_user}-{safe_version}.sock"
    return f"/run/php/bpanel-{safe_user}.sock"


def site_root_for_domain(domain: str) -> str:
    username = linux_user_for_domain(domain)
    return str(HOME_ROOT / username / domain.strip().lower())


def site_root_for_panel_user(username: str, domain: str) -> str:
    return str(HOME_ROOT / linux_user_for_panel_username(username) / domain.strip().lower())


def is_managed_site_path(path: str | Path) -> bool:
    resolved = Path(path).resolve()
    legacy_root = Path(settings.sites_root).resolve()
    if legacy_root == resolved or legacy_root in resolved.parents:
        return True
    try:
        relative = resolved.relative_to(HOME_ROOT)
    except ValueError:
        return False
    parts = relative.parts
    return len(parts) >= 2 and bool(LINUX_USER_RE.fullmatch(parts[0])) and parts[0] not in RESERVED_LINUX_USERS and bool(DOMAIN_RE.fullmatch(parts[1]))


def is_site_root_for_domain(path: str | Path, domain: str) -> bool:
    resolved = Path(path).resolve()
    legacy_root = Path(settings.sites_root).resolve()
    if resolved == legacy_root / domain:
        return True
    try:
        relative = resolved.relative_to(HOME_ROOT)
    except ValueError:
        return False
    parts = relative.parts
    return (
        len(parts) == 2
        and bool(LINUX_USER_RE.fullmatch(parts[0]))
        and parts[0] not in RESERVED_LINUX_USERS
        and parts[1] == domain.strip().lower()
    )


def ensure_panel_user(username: str) -> str:
    linux_user = linux_user_for_panel_username(username)
    shell.privileged(
        "panel-user-ensure",
        helper_args=[linux_user],
        fallback=["mkdir", "-p", str(HOME_ROOT / linux_user)],
    )
    return linux_user


def delete_panel_user(username: str) -> None:
    linux_user = linux_user_for_panel_username(username)
    shell.privileged(
        "panel-user-delete",
        helper_args=[linux_user],
        check=False,
        fallback=["true"],
    )


def ensure_site_runtime(domain: str, root_path: str, php_version: Optional[str] = None, linux_user: Optional[str] = None) -> str:
    username = validate_linux_user(linux_user) if linux_user else linux_user_for_domain(domain)
    helper_args = [username, root_path, php_version or "none"]
    shell.privileged(
        "site-runtime-ensure",
        helper_args=helper_args,
        fallback=["mkdir", "-p", str(Path(root_path) / "public")],
    )
    return username


def move_site_runtime(old_root_path: str, new_root_path: str, linux_user: str, php_version: Optional[str] = None) -> str:
    username = validate_linux_user(linux_user)
    shell.privileged(
        "site-runtime-move",
        helper_args=[username, old_root_path, new_root_path, php_version or "none"],
        fallback=["mv", old_root_path, new_root_path],
    )
    return new_root_path


def fix_site_permissions(root_path: str, linux_user: Optional[str]) -> None:
    if linux_user:
        shell.privileged(
            "fix-permissions",
            helper_args=[root_path, validate_linux_user(linux_user)],
            check=False,
            fallback=["chown", "-R", f"{linux_user}:{linux_user}", root_path],
        )
        return
    shell.privileged(
        "fix-permissions",
        helper_args=[root_path],
        check=False,
        fallback=["chown", "-R", "www-data:www-data", root_path],
    )


def fix_site_path(path: str, linux_user: Optional[str]) -> None:
    if not linux_user:
        return
    shell.privileged(
        "site-path-fix",
        helper_args=[path, validate_linux_user(linux_user)],
        check=False,
        fallback=["chown", "-R", f"{linux_user}:{linux_user}", path],
    )


def delete_site_runtime(root_path: str, linux_user: Optional[str]) -> None:
    if not linux_user:
        return
    shell.privileged(
        "site-runtime-delete",
        helper_args=[validate_linux_user(linux_user), root_path],
        check=False,
        fallback=["true"],
    )
