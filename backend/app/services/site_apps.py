"""Application slots served by proxying to a local port.

A site app is the record behind `app_type` "proxy" and "nodejs": it says which
loopback port nginx should forward the domain to, and — for node apps — what the
panel has to run to keep something listening there.

Port allocation is the part that has to be right. A port handed out twice means
two sites silently answering for each other, so the DB holds the unique
constraint and the kernel gets the final say through `ss` before a port is used.
"""

import re
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import SiteApp, User, Website
from app.services import site_users
from app.services.shell import shell

# Deliberately above the common framework defaults (3000, 8080) so a customer
# experimenting by hand does not collide with an allocated slot.
PORT_RANGE_START = 21000
PORT_RANGE_END = 21999

APP_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}[a-z0-9]$|^[a-z0-9]$")
APP_KINDS = {"proxy", "node"}
START_KINDS = {"node", "npm", "npx", "yarn"}
NODE_MAJOR_RE = re.compile(r"^(1[0-9]|[2-9][0-9])$")
DEFAULT_MEMORY_MB = 512
MIN_MEMORY_MB = 64
MAX_MEMORY_MB = 16384


def validate_name(name: str) -> str:
    value = (name or "").strip().lower()
    if not APP_NAME_RE.fullmatch(value):
        raise ValueError("App name may only use lowercase letters, digits, hyphen and underscore")
    return value


def validate_kind(kind: str) -> str:
    value = (kind or "").strip().lower()
    if value not in APP_KINDS:
        raise ValueError(f"Unsupported app kind. Allowed: {', '.join(sorted(APP_KINDS))}")
    return value


def validate_port(port: int | str) -> int:
    try:
        value = int(port)
    except (TypeError, ValueError) as exc:
        raise ValueError("Port must be a number") from exc
    if not PORT_RANGE_START <= value <= PORT_RANGE_END:
        raise ValueError(f"Port must be between {PORT_RANGE_START} and {PORT_RANGE_END}")
    return value


def validate_app_root(app_root: str) -> str:
    """The app directory, relative to the website root.

    Reuses the document-root rules so an app cannot be pointed outside the site
    or at a path with shell-hostile characters.
    """
    value = (app_root or "app").strip().strip("/")
    if not value:
        value = "app"
    return site_users.validate_document_root(value)


def validate_memory_mb(memory_mb: int | str | None, ceiling: int | None = None) -> int:
    if memory_mb in (None, ""):
        value = DEFAULT_MEMORY_MB
    else:
        try:
            value = int(memory_mb)
        except (TypeError, ValueError) as exc:
            raise ValueError("Memory limit must be a number of MB") from exc
    if not MIN_MEMORY_MB <= value <= MAX_MEMORY_MB:
        raise ValueError(f"Memory limit must be between {MIN_MEMORY_MB} and {MAX_MEMORY_MB} MB")
    if ceiling and value > ceiling:
        raise ValueError(f"This package allows at most {ceiling} MB per app")
    return value


def validate_node_major(node_major: str | None) -> str | None:
    if node_major in (None, ""):
        return None
    value = str(node_major).strip()
    if not NODE_MAJOR_RE.fullmatch(value):
        raise ValueError("Node version must be a major version number, for example 20 or 22")
    return value


def validate_start(start_kind: str | None, start_arg: str | None, app_root: str) -> tuple[str, str]:
    """Structured start command: a known launcher plus one argument.

    Never a free-form shell string — this ends up inside a systemd unit written
    by root, so the launcher is picked from a fixed set and the argument is
    checked for shell metacharacters and path escapes.
    """
    kind = (start_kind or "").strip().lower()
    if kind not in START_KINDS:
        raise ValueError(f"Start command must be one of: {', '.join(sorted(START_KINDS))}")
    arg = (start_arg or "").strip()
    if not arg:
        raise ValueError("Start command needs an argument, for example a script name or entry file")
    if any(char in arg for char in " \t\r\n\x00'\"\\;&|<>$`()*?[]{}!#~"):
        raise ValueError("Start argument may not contain spaces or shell characters")

    if kind == "node":
        if not arg.endswith(".js") and not arg.endswith(".mjs") and not arg.endswith(".cjs"):
            raise ValueError("node must be given a .js, .mjs or .cjs entry file")
        # Resolve against the app directory and refuse anything that climbs out.
        base = Path("/") / app_root
        target = (base / arg).resolve(strict=False)
        try:
            target.relative_to(base.resolve(strict=False))
        except ValueError as exc:
            raise ValueError("Entry file must be inside the app directory") from exc
    elif not re.fullmatch(r"[A-Za-z0-9._@/-]{1,120}", arg):
        raise ValueError("Script or package name contains characters that are not allowed")
    return kind, arg


def listening_ports() -> set[int]:
    """Ports the kernel currently has a TCP listener on.

    Best effort: if `ss` is missing the DB constraint still prevents handing the
    same port to two apps, we just lose the check against unmanaged processes.
    """
    result = shell.run(["ss", "-ltnH"], check=False)
    if result.returncode != 0:
        return set()
    ports: set[int] = set()
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        local = fields[3]
        _, _, port = local.rpartition(":")
        if port.isdigit():
            ports.add(int(port))
    return ports


def reserved_ports(db: Session, exclude_app_id: int | None = None) -> set[int]:
    query = select(SiteApp.port)
    if exclude_app_id is not None:
        query = query.where(SiteApp.id != exclude_app_id)
    return {row for row in db.scalars(query) if row}


def allocate_port(db: Session, preferred: int | None = None, exclude_app_id: int | None = None) -> int:
    taken = reserved_ports(db, exclude_app_id) | listening_ports()
    if preferred is not None:
        candidate = validate_port(preferred)
        if candidate in taken:
            raise ValueError(f"Port {candidate} is already in use")
        return candidate
    for candidate in range(PORT_RANGE_START, PORT_RANGE_END + 1):
        if candidate not in taken:
            return candidate
    raise ValueError("No free application port left on this server")


def app_limit_for(user: User) -> int:
    package = getattr(user, "package", None)
    return int(getattr(package, "node_apps_limit", 0) or 0) if package else 0


def memory_ceiling_for(user: User) -> int:
    package = getattr(user, "package", None)
    ceiling = int(getattr(package, "node_app_memory_mb", 0) or 0) if package else 0
    return ceiling or DEFAULT_MEMORY_MB


def count_apps_for_owner(db: Session, owner_id: int) -> int:
    return db.query(SiteApp).join(Website).filter(Website.owner_id == owner_id).count()


def ensure_app_quota(db: Session, user: User, is_admin: bool = False) -> None:
    if is_admin:
        return
    limit = app_limit_for(user)
    if limit <= 0:
        raise ValueError("Application hosting is not enabled for this package")
    if count_apps_for_owner(db, user.id) >= limit:
        raise ValueError(f"This package allows at most {limit} application(s)")


def primary_app(website: Website) -> Optional[SiteApp]:
    apps: Iterable[SiteApp] = getattr(website, "apps", None) or []
    return next(iter(apps), None)


def app_port_for_website(website: Website) -> Optional[int]:
    app = primary_app(website)
    return app.port if app else None


def app_directory(website: Website, app: SiteApp) -> Path:
    return site_users.document_root(website.root_path, validate_app_root(app.app_root))
