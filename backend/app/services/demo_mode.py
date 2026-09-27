"""Demo mode: public accounts that can look at everything and change nothing.

Operator, 2026-09-28: "phát triển addon: chế độ demo mode" - view only, one
administrator and one customer account, and buttons on the sign-in page that
log straight into either.

A demo server hands its passwords to anyone who asks, so the rule is enforced
where every signed-in request passes (api.deps.get_current_user) rather than in
the pages: a demo account's request that would change something is refused,
and so are the few reads that hand over more than a screen shows - file
contents, downloads, database access, the terminal.

The configuration lives in the panel settings under ``demo_mode``:

    {"accounts": {"admin": {"username": "demo", "password": "..."},
                  "customer": {"username": "khachhang", "password": "..."}}}

The passwords are stored as they are because the sign-in page shows them; that
is the point of them. They are never the account's SFTP or SSH password: the
panel password stopped reaching the Linux account long before this existed.
"""

from __future__ import annotations

import re
import secrets

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.permissions import is_admin_role
from app.core.security import hash_password
from app.models.entities import User
from app.services import addons, panel_settings

SETTINGS_KEY = "demo_mode"
SLOTS = ("admin", "customer")
MIN_PASSWORD = 6
MAX_PASSWORD = 128

REFUSED_CHANGE = "This is a demo: you can look at everything, but changes are not saved."
REFUSED_READ = "This is a demo: file contents, downloads, database access and the terminal are not available."

# The only writes a demo visitor needs. Signing out revokes their own token
# and nothing else (see api.auth.logout).
ALLOWED_WRITES = frozenset({
    ("POST", "/api/auth/logout"),
})

# Reads that hand over more than a page shows. Every other GET is fine for a
# visitor: the panel never returns a stored secret (S3 keys, the SMTP password,
# bot and API tokens are write-only), so what remains is what the screens show.
# test_demo_mode.py lists every GET route in the app and fails on one that is in
# neither this set nor its reviewed list, so a new route gets looked at.
BLOCKED_READS = frozenset({
    "/api/databases/{database_id}/download",
    "/api/databases/phpmyadmin-sso/{token}",
    "/api/maintenance/app-files/{app_id}/download",
    "/api/maintenance/app-files/{app_id}/read",
    "/api/maintenance/backups/{website_id}/download",
    "/api/maintenance/files/{website_id}/download",
    "/api/maintenance/files/{website_id}/read",
    "/api/maintenance/user-backups-download",
    # Asks Telegram, with the stored bot token, who has written to the bot.
    "/api/notifications/telegram/chats",
})

_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_IPV4 = re.compile(r"\b(\d{1,3}\.\d{1,3})\.\d{1,3}\.\d{1,3}\b")
_IP_FIELD = re.compile(r"\bip=\S+")


def _config() -> dict:
    raw = panel_settings._read_raw_lenient().get(SETTINGS_KEY)
    return raw if isinstance(raw, dict) else {}


def accounts() -> dict[str, dict]:
    """The configured slots, whether or not the addon is on."""
    stored = _config().get("accounts")
    stored = stored if isinstance(stored, dict) else {}
    result: dict[str, dict] = {}
    for slot in SLOTS:
        entry = stored.get(slot)
        if isinstance(entry, dict) and entry.get("username"):
            result[slot] = {"username": str(entry["username"]), "password": str(entry.get("password") or "")}
    return result


def active() -> bool:
    return addons.is_installed(addons.DEMO)


def demo_usernames() -> set[str]:
    if not active():
        return set()
    return {entry["username"] for entry in accounts().values()}


def is_demo_user(user: User | None) -> bool:
    return user is not None and user.username in demo_usernames()


def is_demo_session(user: User | None, payload: dict | None) -> bool:
    """A visitor in a demo account.

    Not an administrator who used "Login as" on the demo customer to set it up:
    that session carries the ``imp`` claim, which only the impersonate endpoint
    issues and only to an administrator.
    """
    if payload and payload.get("imp"):
        return False
    return is_demo_user(user)


def route_template(request: Request) -> str:
    """The matched route as the lists above spell it: "/api/.../{website_id}/read".

    Matching the template rather than the URL means an id or a query string
    cannot step around an entry. FastAPI 0.141 gives an included router's route
    its path without the "/api" prefix it was mounted under, while older
    versions include it; both come out the same here.
    """
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if not template:
        return request.url.path
    if not template.startswith("/api/") and request.url.path.startswith("/api/"):
        template = "/api" + template
    return template


def enforce(request: Request, user: User, payload: dict | None) -> None:
    """Refuse what a demo visitor may not do. Called for every signed-in request."""
    if not is_demo_session(user, payload):
        return
    method = request.method.upper()
    path = route_template(request)
    if method in _READ_METHODS:
        if path in BLOCKED_READS:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=REFUSED_READ)
        return
    if (method, path) in ALLOWED_WRITES:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=REFUSED_CHANGE)


def mask_ips(text: str) -> str:
    """Hide visitors' addresses from other visitors.

    Everyone in a demo account is the same user to the panel, so the audit log
    would otherwise show each visitor where the others came from.
    """
    if not text:
        return text
    text = _IP_FIELD.sub("ip=hidden", text)
    return _IPV4.sub(lambda match: f"{match.group(1)}.x.x", text)


def public_view() -> dict:
    """What the sign-in page shows. Empty unless the addon is on."""
    configured = accounts() if active() else {}
    items = [{"slot": slot, **configured[slot]} for slot in SLOTS if slot in configured]
    return {"enabled": bool(items), "accounts": items}


def _retire(user: User) -> None:
    """Make a public password stop working, and end the sessions it opened."""
    user.hashed_password = hash_password(secrets.token_urlsafe(32))
    user.token_version = (user.token_version or 0) + 1


def _publish(user: User, password: str) -> None:
    user.hashed_password = hash_password(password)


def configure(db: Session, caller: User, requested: dict) -> dict:
    """Set the two slots. ``requested`` maps a slot to {username, password} or None.

    An account that leaves the demo gets a random password: its old one is on
    the sign-in page and in every screenshot of it.
    """
    chosen: dict[str, dict] = {}
    for slot in SLOTS:
        entry = requested.get(slot)
        if not entry:
            continue
        username = str(entry.get("username") or "").strip()
        password = str(entry.get("password") or "")
        if not username:
            continue
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            raise HTTPException(status_code=400, detail="That account does not exist.")
        if user.id == caller.id:
            raise HTTPException(status_code=400, detail="You cannot make your own account a demo account.")
        if slot == "admin" and not is_admin_role(user.role):
            raise HTTPException(status_code=400, detail="The administrator demo account must be an administrator.")
        if slot == "customer" and is_admin_role(user.role):
            raise HTTPException(
                status_code=400, detail="The customer demo account must be a customer, not an administrator.",
            )
        if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
            raise HTTPException(status_code=400, detail="A demo password must be 6 to 128 characters.")
        chosen[slot] = {"username": username, "password": password, "user": user}

    previous = {entry["username"] for entry in accounts().values()}
    kept = {entry["username"] for entry in chosen.values()}
    for username in previous - kept:
        user = db.query(User).filter(User.username == username).first()
        if user is not None:
            _retire(user)
    if active():
        for entry in chosen.values():
            _publish(entry["user"], entry["password"])
    db.commit()

    settings = panel_settings._read_raw()
    settings[SETTINGS_KEY] = {"accounts": {
        slot: {"username": entry["username"], "password": entry["password"]} for slot, entry in chosen.items()
    }}
    panel_settings._write_raw(settings)
    return admin_view(db)


def switch_on(db: Session) -> list[str]:
    """Installing the addon: the configured passwords work again."""
    names = []
    for entry in accounts().values():
        user = db.query(User).filter(User.username == entry["username"]).first()
        if user is not None and len(entry["password"]) >= MIN_PASSWORD:
            _publish(user, entry["password"])
            names.append(user.username)
    db.commit()
    return names


def switch_off(db: Session) -> list[str]:
    """Removing the addon: the accounts turn back into ordinary ones, so their
    public passwords must stop working first. The slots are kept."""
    names = []
    for entry in accounts().values():
        user = db.query(User).filter(User.username == entry["username"]).first()
        if user is not None:
            _retire(user)
            names.append(user.username)
    db.commit()
    return names


def admin_view(db: Session) -> dict:
    users = db.query(User).order_by(User.username).all()
    return {
        "accounts": {slot: accounts().get(slot) for slot in SLOTS},
        "candidates": {
            "admin": [user.username for user in users if is_admin_role(user.role)],
            "customer": [user.username for user in users if not is_admin_role(user.role)],
        },
    }
