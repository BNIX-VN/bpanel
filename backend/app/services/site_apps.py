"""Application slots served by proxying to a local port.

A site app is the record behind `app_type` "proxy" and "nodejs": it says which
loopback port nginx should forward the domain to, and — for node apps — what the
panel has to run to keep something listening there.

Port allocation is the part that has to be right. A port handed out twice means
two sites silently answering for each other, so the DB holds the unique
constraint and the kernel gets the final say through `ss` before a port is used.
"""

import hashlib
import os
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
# proxy: the panel only routes. node/docker: the panel owns the process too.
APP_KINDS = {"proxy", "node", "docker"}
MANAGED_KINDS = {"node", "docker"}
START_KINDS = {"node", "npm", "npx", "yarn"}
NODE_MAJOR_RE = re.compile(r"^(1[0-9]|[2-9][0-9])$")
IMAGE_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,159}(:[A-Za-z0-9._-]{1,127})?(@sha256:[a-f0-9]{64})?$")
CPU_LIMIT_RE = re.compile(r"^[0-9]{1,2}(\.[0-9])?$")
ENV_KEY_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
# Registries a customer may pull from. Anything else has to go through an admin,
# because "pull whatever you like" on a shared host is a supply-chain decision,
# not a convenience setting.
DEFAULT_ALLOWED_REGISTRIES = ("docker.io", "ghcr.io", "quay.io", "registry.k8s.io", "public.ecr.aws")
MAX_ENV_LINES = 64
MAX_ENV_VALUE = 4096
CONTROL_ACTIONS = {"start", "stop", "restart", "status", "is-active", "is-enabled", "enable", "disable"}
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


# --- container and environment validation -----------------------------------

def allowed_registries() -> tuple[str, ...]:
    raw = os.environ.get("BPANEL_ALLOWED_REGISTRIES", "")
    if not raw.strip():
        return DEFAULT_ALLOWED_REGISTRIES
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def validate_image(image: str, enforce_registry: bool = True) -> str:
    """Validate a container image reference and where it comes from."""
    value = (image or "").strip()
    if not value:
        raise ValueError("Container image is required")
    if not IMAGE_RE.fullmatch(value) or value.startswith("-") or ".." in value:
        raise ValueError("Container image reference contains characters that are not allowed")
    if not enforce_registry:
        return value
    # The first path component is a registry host only when something follows it
    # and it looks like a host. Without that check "nginx:1.27" reads as the
    # registry "nginx" with port "1.27", and a plain Docker Hub image is refused.
    head = value.split("/", 1)[0]
    is_registry = "/" in value and ("." in head or ":" in head or head == "localhost")
    registry = head if is_registry else "docker.io"
    if registry not in allowed_registries():
        raise ValueError(f"Images from {registry} are not allowed. Allowed: {', '.join(allowed_registries())}")
    return value


def validate_container_port(port: int | str | None) -> int:
    if port in (None, ""):
        return 3000
    try:
        value = int(port)
    except (TypeError, ValueError) as exc:
        raise ValueError("Container port must be a number") from exc
    if not 1 <= value <= 65535:
        raise ValueError("Container port is out of range")
    return value


def validate_cpu_limit(cpu_limit: str | float | None) -> str:
    if cpu_limit in (None, ""):
        return "1"
    value = str(cpu_limit).strip()
    if not CPU_LIMIT_RE.fullmatch(value) or float(value) <= 0:
        raise ValueError("CPU limit must be a number such as 0.5, 1 or 2")
    return value


def validate_env(env: str | None) -> str:
    """Normalise KEY=value lines for the app's EnvironmentFile.

    The helper re-validates every line before root writes it; this is the copy
    that produces a readable error for the person typing it.
    """
    lines: list[str] = []
    for raw in (env or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Environment line is missing '=': {line[:40]}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not ENV_KEY_RE.fullmatch(key):
            raise ValueError(f"Environment name must be UPPER_SNAKE_CASE: {key[:40]}")
        if any(char in value for char in "\r\n\x00"):
            raise ValueError(f"Environment value for {key} contains a line break")
        if len(value) > MAX_ENV_VALUE:
            raise ValueError(f"Environment value for {key} is too long")
        lines.append(f"{key}={value}")
    if len(lines) > MAX_ENV_LINES:
        raise ValueError(f"At most {MAX_ENV_LINES} environment variables are supported")
    return "\n".join(lines)


# --- runtime lifecycle ------------------------------------------------------

def site_root_of(website: Website) -> str:
    return str(Path(website.root_path).resolve())


def unit_name(website: Website, app: SiteApp) -> str:
    """Mirror of the helper's own derivation, for display only.

    Control commands pass the website and app name and let the helper derive the
    unit, so a caller can never aim systemctl at a unit it does not own.
    """
    digest = hashlib.sha256(site_root_of(website).encode("utf-8")).hexdigest()[:8]
    linux_user = website.linux_user or "www-data"
    return f"bpanel-app-{linux_user}-{digest}-{validate_name(app.name)}"


def _require_linux_user(website: Website) -> str:
    if not website.linux_user:
        raise ValueError("This website has no Linux user, so it cannot run a managed application")
    return site_users.validate_linux_user(website.linux_user)


def write_runtime(website: Website, app: SiteApp) -> str:
    """Generate and reload the systemd unit for a managed app."""
    if app.kind not in MANAGED_KINDS:
        raise ValueError("Only Node.js and container applications have a managed runtime")
    linux_user = _require_linux_user(website)
    helper_args = [
        linux_user,
        site_root_of(website),
        validate_name(app.name),
        "node" if app.kind == "node" else "docker",
        f"--port={validate_port(app.port)}",
        f"--memory={validate_memory_mb(app.memory_limit_mb)}",
        f"--dir={validate_app_root(app.app_root)}",
        f"--cpus={validate_cpu_limit(app.cpu_limit)}",
    ]
    if app.kind == "node":
        start_kind, start_arg = validate_start(app.start_kind, app.start_arg, validate_app_root(app.app_root))
        helper_args += [
            f"--node-major={validate_node_major(app.node_major) or '22'}",
            f"--exec={start_kind}",
            f"--arg={start_arg}",
        ]
    else:
        helper_args += [
            f"--image={validate_image(app.image)}",
            f"--container-port={validate_container_port(app.container_port)}",
        ]
    result = shell.privileged(
        "site-app-write",
        helper_args=helper_args,
        input=validate_env(app.env) + "\n",
        fallback=["bash", "-lc", "cat >/dev/null && echo dry-run-unit"],
    )
    return (result.stdout or "").strip()


def control(website: Website, app: SiteApp, action: str) -> str:
    if action not in CONTROL_ACTIONS:
        raise ValueError(f"Unsupported action. Allowed: {', '.join(sorted(CONTROL_ACTIONS))}")
    linux_user = _require_linux_user(website)
    result = shell.privileged(
        "site-app-control",
        helper_args=[linux_user, site_root_of(website), validate_name(app.name), action],
        check=False,
        fallback=["bash", "-lc", "echo dry-run"],
    )
    return ((result.stdout or "") + (result.stderr or "")).strip()


def is_running(website: Website, app: SiteApp) -> bool:
    if app.kind not in MANAGED_KINDS:
        return False
    try:
        return control(website, app, "is-active").splitlines()[0].strip() == "active"
    except (RuntimeError, ValueError, IndexError):
        return False


def logs(website: Website, app: SiteApp, lines: int = 200) -> str:
    linux_user = _require_linux_user(website)
    safe_lines = max(1, min(2000, int(lines or 200)))
    result = shell.privileged(
        "site-app-logs",
        helper_args=[linux_user, site_root_of(website), validate_name(app.name), str(safe_lines)],
        check=False,
        fallback=["bash", "-lc", "echo 'no journal in development'"],
    )
    return (result.stdout or "") or (result.stderr or "")


def delete_runtime(website: Website, app: SiteApp) -> None:
    if app.kind not in MANAGED_KINDS or not website.linux_user:
        return
    shell.privileged(
        "site-app-delete",
        helper_args=[site_users.validate_linux_user(website.linux_user), site_root_of(website), validate_name(app.name)],
        check=False,
        fallback=["bash", "-lc", "true"],
    )


def install_dependencies(website: Website, app: SiteApp) -> str:
    if app.kind != "node":
        raise ValueError("Only Node.js applications install dependencies")
    linux_user = _require_linux_user(website)
    result = shell.privileged(
        "site-app-install-deps",
        helper_args=[
            linux_user,
            site_root_of(website),
            validate_app_root(app.app_root),
            validate_node_major(app.node_major) or "22",
        ],
        check=False,
        timeout=960,
        fallback=["bash", "-lc", "echo dry-run-install"],
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "npm install failed").strip()[-4000:])
    return (result.stdout or "").strip()[-4000:]


def pull_image(app: SiteApp) -> str:
    if app.kind != "docker":
        raise ValueError("Only container applications pull an image")
    result = shell.privileged(
        "site-app-pull",
        helper_args=[validate_image(app.image)],
        check=False,
        timeout=960,
        fallback=["bash", "-lc", "echo dry-run-pull"],
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "docker pull failed").strip()[-4000:])
    return (result.stdout or "").strip()[-4000:]


# --- server side runtime availability ---------------------------------------

def docker_status() -> dict:
    result = shell.privileged("docker-status", check=False, fallback=["bash", "-lc", "echo installed=no"])
    parsed = {}
    for line in (result.stdout or "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            parsed[key.strip()] = value.strip()
    return {
        "installed": parsed.get("installed") == "yes",
        "version": parsed.get("version", ""),
        "active": parsed.get("active", ""),
    }


def install_docker() -> str:
    result = shell.privileged(
        "docker-install",
        check=False,
        timeout=1800,
        fallback=["bash", "-lc", "echo dry-run-docker-install"],
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Docker install failed").strip()[-4000:])
    return (result.stdout or "").strip()[-4000:]


def installed_node_majors() -> list[str]:
    result = shell.privileged("node-list", check=False, fallback=["bash", "-lc", "true"])
    majors = [line.strip() for line in (result.stdout or "").splitlines() if NODE_MAJOR_RE.fullmatch(line.strip())]
    return sorted(majors, key=int)


def install_node(major: str) -> str:
    safe_major = validate_node_major(major)
    if not safe_major:
        raise ValueError("Node version is required")
    result = shell.privileged(
        "node-install",
        helper_args=[safe_major],
        check=False,
        timeout=900,
        fallback=["bash", "-lc", "echo dry-run-node-install"],
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Node install failed").strip()[-4000:])
    return (result.stdout or "").strip()[-4000:]
