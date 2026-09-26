"""Optional parts of the panel, installed only where they are wanted.

Everything here is off until an administrator asks for it. A server that hosts
WordPress has no reason to carry a container runtime, its firewall rules or its
upgrades, and a customer has no reason to see a section of the panel their
package does not include.

The state lives beside the panel's other settings rather than in the database,
so the answer to "is this installed" costs nothing and is available to code that
has no session to hand.
"""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import HTTPException, status

ADDONS_DIR = Path(os.environ.get("BPANEL_DATA_DIR", "/var/lib/bpanel"))
ADDONS_FILE = ADDONS_DIR / "addons.json"

APPLICATION = "application"
FAIL2BAN = "fail2ban"
MCP = "mcp"
NOTIFICATIONS = "notifications"

# What an administrator sees in the Addons page. The version is the addon's own:
# it moves when the addon changes, independently of the panel's version.
CATALOGUE: dict[str, dict] = {
    FAIL2BAN: {
        "name": "Fail2ban",
        "version": "1.0.0",
        "summary": "Stops SSH password guessing by banning an address that keeps getting it wrong.",
        "details": [
            "sshd on a public address collects hundreds of password attempts a day with nobody watching; one live customer server logged 679 failures in 24 hours.",
            "Five failures within an hour bans an address for an hour, and longer each time it comes back, up to a week.",
            "Never bans the server itself: loopback and every address the machine holds are on the ignore list.",
        ],
        "notes": [
            "The ban action is pinned to iptables-multiport rather than left for fail2ban to detect. A machine that once had ufw keeps its ufw chains, which is enough for fail2ban to pick wrong and hand every ban to a firewall that is not running.",
            "On install the panel bans an address that is never routed, then checks it really is in iptables. If it is not, the install fails rather than leaving a service that looks healthy and protects nothing.",
            "Turning the addon off only stops the service: the package, the jail file and the ban history all stay.",
        ],
        "keeps_data_on_uninstall": True,
    },
    MCP: {
        "name": "AI assistants (MCP)",
        "version": "1.0.0",
        "summary": "Lets Claude Code, Cursor or VS Code read and operate the panel with a personal token.",
        "details": [
            "Each person creates their own token, and it acts with exactly their own permissions: an administrator's reaches the whole server, a customer's reaches only their own websites, databases, backups and files.",
            "A token is read-only unless the person ticks Allow actions when creating it. A read-only token is not even shown the tools that write.",
            "Nothing new listens on the network. The assistant talks to the panel's own address, over the panel's own certificate.",
        ],
        "notes": [
            "Needs a real certificate. MCP clients refuse a self-signed one, so on a panel still using the self-signed certificate this addon cannot be reached at all.",
            "Works with clients that send a Bearer token - Claude Code, Cursor, VS Code. The claude.ai and ChatGPT web connectors need OAuth, which this does not have.",
            "Turning the addon off closes the endpoint and leaves the tokens alone. Removing it revokes every token on the server.",
        ],
        # Stop is reversible and keeps the tokens; uninstall is the one that
        # revokes them, and the Addons page says so before it happens.
        "keeps_data_on_uninstall": False,
    },
    NOTIFICATIONS: {
        "name": "Notifications",
        "version": "1.0.0",
        "summary": "Tells administrators and customers what needs their attention, by email and Telegram.",
        "details": [
            "Administrators hear about the server: a service that stopped, a disk filling up, the firewall off, a failed backup, malware, certificates about to expire, a panel update.",
            "Every account hears about itself: a sign-in from a new place, a password or two-factor change, a suspension, and its own backups, malware, certificates and storage.",
            "Email goes through the SMTP server you set; Telegram through a bot you create with @BotFather. Each person picks their channels and mutes what they do not want.",
        ],
        "notes": [
            "Email needs an SMTP account (host, port, sender address). Mail sent straight from the server usually lands in spam.",
            "Turning the addon off stops every message and keeps the settings, each person's choices and the delivery log.",
        ],
        "keeps_data_on_uninstall": True,
    },
    APPLICATION: {
        "name": "Application",
        "version": "1.0.0",
        "summary": "Runs Node.js apps, containers and Docker Compose, and puts them behind a domain with Nginx.",
        "details": [
            "Installs Docker and the Node.js versions you need; none of it is in a default install.",
            "Each app gets its own internal port, its own memory and CPU limits, and runs as the customer's user.",
            "Set a website to Application mode and Nginx points at the app you installed.",
        ],
        "notes": [
            "Backups do not yet include application data (the apps directory and named volumes).",
            "Docker image and volume size is not counted against a customer's disk quota.",
        ],
        # Nothing is deleted when this goes away, so turning it off is safe to
        # try; see uninstall() for what actually happens.
        "keeps_data_on_uninstall": True,
    },
}


def _read() -> dict:
    try:
        with ADDONS_FILE.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(data: dict) -> None:
    ADDONS_DIR.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=str(ADDONS_DIR), delete=False) as tmp:
        json.dump(data, tmp, ensure_ascii=True, indent=2, sort_keys=True)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(ADDONS_FILE)


def known(slug: str) -> dict:
    entry = CATALOGUE.get(slug)
    if not entry:
        raise HTTPException(status_code=404, detail=f"No such addon: {slug}")
    return entry


def is_installed(slug: str) -> bool:
    record = _read().get(slug)
    return bool(record and record.get("installed"))


def installed_slugs() -> list[str]:
    return sorted(slug for slug in CATALOGUE if is_installed(slug))


def state() -> list[dict]:
    """The catalogue with each addon's installed state folded in."""
    stored = _read()
    entries = []
    for slug, entry in sorted(CATALOGUE.items()):
        record = stored.get(slug) or {}
        entries.append({
            "slug": slug,
            **entry,
            "installed": bool(record.get("installed")),
            "installed_version": record.get("version") or "",
            "installed_at": record.get("installed_at") or "",
        })
    return entries


def install(slug: str) -> dict:
    entry = known(slug)
    from datetime import datetime, timezone

    data = _read()
    data[slug] = {
        "installed": True,
        "version": entry["version"],
        "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _write(data)
    return data[slug]


def uninstall(slug: str) -> dict:
    """Turn an addon off without touching anything it created.

    Applications keep their files, their containers' volumes and their rows in
    the database; the panel simply stops offering the feature and stops the units
    so nothing keeps running behind a section nobody can see. Installing again
    picks up where it left off.
    """
    known(slug)
    data = _read()
    record = data.get(slug) or {}
    record["installed"] = False
    data[slug] = record
    _write(data)
    return record


def adopt_existing(slug: str, in_use: bool) -> bool:
    """Count a feature already in use as installed, once.

    The addon split arrives as an update, and a server that has been running
    applications for months must not lose them the moment the panel restarts.
    If there is no record either way and the feature is demonstrably in use, it
    was installed before there was anything to record. Only ever runs when the
    file has no entry, so an administrator who later removes the addon does not
    find it back after the next restart.
    """
    if not in_use:
        return False
    data = _read()
    if slug in data:
        return False
    install(slug)
    return True


def require(slug: str) -> None:
    """Refuse an API call that belongs to an addon nobody installed."""
    entry = known(slug)   # a slug that is not in the catalogue is a bug, not a 409
    if not is_installed(slug):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The {entry['name']} addon is not installed. Install it from the Addons page first.",
        )


def require_application() -> None:
    """FastAPI dependency for every route the Application addon owns."""
    require(APPLICATION)
