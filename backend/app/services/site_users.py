import hashlib
import re
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.services.shell import shell


LINUX_USER_RE = re.compile(r"^bp_[a-z0-9_]{3,28}$")


def linux_user_for_domain(domain: str) -> str:
    """Return a deterministic, Linux-safe username for a website domain."""
    normalized = (domain or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_") or "site"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]
    username = f"bp_{slug[:18]}_{digest}"
    return username[:32]


def validate_linux_user(username: str) -> str:
    if not LINUX_USER_RE.fullmatch(username or ""):
        raise ValueError("Invalid site Linux user")
    return username


def php_fpm_socket(username: Optional[str]) -> Optional[str]:
    if not username:
        return None
    safe_user = validate_linux_user(username)
    return f"/run/php/bpanel-{safe_user}.sock"


def ensure_site_runtime(domain: str, root_path: str, php_version: Optional[str] = None) -> str:
    username = linux_user_for_domain(domain)
    helper_args = [username, root_path, php_version or "none"]
    shell.privileged(
        "site-runtime-ensure",
        helper_args=helper_args,
        fallback=["mkdir", "-p", str(Path(root_path) / "public")],
    )
    return username


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
