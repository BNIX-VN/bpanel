"""Redis per account addon: each hosting account's own Redis (operator, 2026-10-27).

DirectAdmin-style. An account turns on a Redis of its own; it runs as the
account's Linux user (bpanel-redis@<user>.service, a template unit the root
helper installs) and is reached only through /home/<user>/.redis/redis.sock.
It is a cache: nothing is saved, a restart empties it. The helper's redis-*
verbs own the instances; this module decides who may run one and how big,
and keeps the instances in step with the database:

- the memory an account's Redis may hold is its package's redis_memory_mb,
  or its own when it has no package, as node_apps_limit is; 0 = not allowed;
- an instance runs while the addon is installed, the account has switched it
  on, is not suspended and is allowed one;
- a change to any of those (a package edited or switched, a custom limit, a
  suspension) re-applies it, and a limit that drops to 0 turns the switch off.
  Deleting the account removes it in the helper's own account deletion, so
  every path that deletes one is covered.

The server's own Redis on 127.0.0.1:6379 is no business of this module.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app.core.permissions import is_admin_role
from app.models.entities import User
from app.services import site_users
from app.services.shell import shell

logger = logging.getLogger("bpanel.redis_accounts")

DEFAULT_MB = 64
MAX_MB = 4096
# Root's, world-readable: whether an account has an instance to stop.
CONF_DIR = Path("/etc/bpanel-redis")

# Why an account cannot turn its Redis on, said on its page and in a refusal.
PROBLEM_TEXT = {
    "not-installed": "The Redis per account addon is not installed.",
    "admin": "Administrators turn on a customer's Redis by logging in as the customer.",
    "no-linux-user": "This account has no Linux user to run Redis as.",
    "suspended": "This account is suspended.",
    "not-allowed": "Redis is not part of this account's package.",
}


def installed() -> bool:
    from app.services import addons

    return addons.is_installed(addons.REDIS_ACCOUNTS)


def linux_user(user: Optional[User]) -> Optional[str]:
    """The Linux user an account's Redis runs as; None for an administrator,
    whose account is not a hosting account."""
    if user is None or is_admin_role(user.role):
        return None
    try:
        return site_users.linux_user_for_panel_username(user.username)
    except ValueError:
        return None


def socket_path(name: str) -> str:
    return f"/home/{name}/.redis/redis.sock"


def limit_mb(user: Optional[User]) -> int:
    """The package's limit; an account without a package has its own."""
    if user is None:
        return 0
    package = getattr(user, "package", None)
    value = getattr(package, "redis_memory_mb", 0) if package is not None else getattr(user, "redis_memory_mb", 0)
    return max(0, min(MAX_MB, int(value or 0)))


def problem(user: User) -> Optional[str]:
    """Why this account may not run a Redis now, or None if it may."""
    if not installed():
        return "not-installed"
    if is_admin_role(user.role):
        return "admin"
    if linux_user(user) is None:
        return "no-linux-user"
    if not user.is_active:
        return "suspended"
    if limit_mb(user) <= 0:
        return "not-allowed"
    return None


def _slice(user: User) -> str:
    # The account's resource-limits slice, as the terminal gets it: its Redis
    # counts against the account whether or not the Resource limits addon is on.
    from app.services.resource_limits import account_slice

    return account_slice(user)


def _helper(verb: str, args: Optional[list[str]] = None, timeout: float = 60) -> str:
    result = shell.privileged(verb, args or [], check=False, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or f"{verb} failed").strip())
    return result.stdout or ""


# --- the addon --------------------------------------------------------------------

def install() -> None:
    """The template unit, and redis-server only if the box has none. Raises
    with the helper's reason."""
    _helper("redis-install", timeout=600)


def uninstall(db: Session) -> int:
    """Every account's Redis stopped and removed, and every switch turned off:
    installing the addon again starts with nobody's Redis on. Returns how many
    accounts had it on. The switches go off even when the helper fails, as
    the addon is removed either way."""
    try:
        _helper("redis-uninstall", timeout=300)
    finally:
        count = db.query(User).filter(User.redis_enabled.is_(True)).update(
            {User.redis_enabled: False}, synchronize_session=False)
        db.commit()
    return int(count or 0)


# --- one account -------------------------------------------------------------------

def apply(user: User) -> None:
    """Start the account's Redis with its current limit, or restart it if the
    limit or its slice moved. Raises RuntimeError when the helper refuses."""
    name = linux_user(user)
    if name is None:
        raise RuntimeError(PROBLEM_TEXT["no-linux-user"])
    _helper("redis-user-apply", [name, str(limit_mb(user)), _slice(user)])


def remove(name: str) -> None:
    _helper("redis-user-remove", [name])


def flush(user: User) -> None:
    name = linux_user(user)
    if name is None:
        raise RuntimeError(PROBLEM_TEXT["no-linux-user"])
    _helper("redis-user-flush", [name])


def parse_status(text: str) -> dict:
    """The helper's "state=active used_memory=123 configured=yes"."""
    values = dict(part.split("=", 1) for part in (text or "").split() if "=" in part)
    used = values.get("used_memory", "0")
    return {
        "running": values.get("state") == "active",
        "used_bytes": int(used) if used.isdigit() else 0,
        "configured": values.get("configured") == "yes",
    }


def instance_status(name: str) -> dict:
    try:
        return parse_status(_helper("redis-user-status", [name], timeout=20))
    except RuntimeError:
        return {"running": False, "used_bytes": 0, "configured": False}


def _has_instance(name: str) -> bool:
    try:
        return (CONF_DIR / f"{name}.conf").exists()
    except OSError:
        return False


def reconcile(db: Session, user: User) -> str:
    """Bring one account's Redis in step with the database: "applied",
    "removed" or "none". Raises RuntimeError when the helper refuses."""
    if not installed():
        return "none"
    # By name rather than linux_user(): an account just made an administrator
    # still has the instance it ran as a customer, and it has to go.
    try:
        name = site_users.linux_user_for_panel_username(user.username)
    except ValueError:
        return "none"
    if user.redis_enabled and (limit_mb(user) <= 0 or is_admin_role(user.role)):
        # No longer allowed: off, not merely stopped, so a later raise of the
        # limit does not start it behind the customer's back.
        user.redis_enabled = False
        db.commit()
    if user.redis_enabled and user.is_active:
        apply(user)
        return "applied"
    # Off, or suspended (the switch is kept for the unsuspend): nothing runs.
    if _has_instance(name):
        remove(name)
        return "removed"
    return "none"


def reconcile_quietly(db: Session, user: Optional[User]) -> None:
    """reconcile() for the places that must not fail because of it."""
    if user is None or not installed():
        return
    try:
        reconcile(db, user)
    except Exception:  # noqa: BLE001 - Redis must never break the change that triggered it
        logger.warning("The Redis of %s was not updated", getattr(user, "username", "?"), exc_info=True)


def reconcile_in_background(user_ids: Iterable[int]) -> None:
    """After a package changed: the request does not wait on one helper call
    per account."""
    ids = sorted({int(user_id) for user_id in user_ids})
    if not ids or not installed():
        return

    def run() -> None:
        from app.core.database import SessionLocal

        with SessionLocal() as session:
            for user in session.query(User).filter(User.id.in_(ids)).all():
                reconcile_quietly(session, user)

    threading.Thread(target=run, name="bpanel-redis-sync", daemon=True).start()


def view(user: User) -> dict:
    """What the account's Redis page shows."""
    name = linux_user(user)
    limit = limit_mb(user)
    is_installed = installed()
    reason = problem(user)
    state = {"running": False, "used_bytes": 0}
    if is_installed and name and user.redis_enabled:
        state = instance_status(name)
    return {
        "installed": is_installed,
        "allowed": name is not None and limit > 0,
        "problem": reason,
        "detail": PROBLEM_TEXT.get(reason) if reason else None,
        "limit_mb": limit,
        "enabled": bool(user.redis_enabled),
        "running": bool(state["running"]),
        "used_bytes": int(state["used_bytes"]),
        "user": name,
        "socket": socket_path(name) if name else None,
    }


def accounts(db: Session) -> list[dict]:
    """Every hosting account's switch and limit, for an administrator. No
    helper call per account: the page lists, it does not measure."""
    rows = []
    for user in db.query(User).order_by(User.username).all():
        if is_admin_role(user.role):
            continue
        rows.append({
            "id": user.id,
            "username": user.username,
            "package_name": user.package.name if user.package else None,
            "limit_mb": limit_mb(user),
            "enabled": bool(user.redis_enabled),
            "active": bool(user.is_active),
        })
    return rows
