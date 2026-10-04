"""The dashboard's status summary: one request, every part best effort.

The dashboard used to repeat the sidebar as three groups of links. It now
says what the sidebar cannot: how things stand. Each part is read on its own,
a part that fails is left out rather than failing the page, and nothing here
waits on the network - opening the dashboard must stay cheap.
"""
from __future__ import annotations

import logging
import platform
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.access import scope_owner
from app.core.permissions import is_admin_role
from app.core.version import APP_VERSION
from app.models.entities import BackupSchedule, DatabaseAccount, DnsZone, MailAccount, MailDomain, SiteApp, User, Website
from app.services import addons, firewall, maldet, malware_scan, panel_settings, server_network, updates, waf
from app.services.shell import shell
from app.services.system import list_services

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
logger = logging.getLogger(__name__)
UNSECURED_SHOWN = 5
# A scan that ran to the end. An interrupted or failed one says nothing about
# whether the files are clean, so the card reports the last one that finished.
FINISHED_SCANS = {"done", "infected"}


def _safe(read: Callable[[], Any], default: Any = None) -> Any:
    try:
        return read()
    except Exception as exc:  # noqa: BLE001 - one broken probe must not blank the dashboard
        logger.warning("dashboard: %s failed: %s", getattr(read, "__name__", "probe"), exc)
        return default


def _services() -> dict:
    # The units the Services page lists. PHP-FPM pools run all the time here,
    # unlike OpenLiteSpeed's on-demand lsphp, so a stopped one is news.
    names = list_services()
    result = shell.run(["systemctl", "is-active", *names], check=False)
    states = (result.stdout or "").split()[: len(names)]
    states += ["unknown"] * (len(names) - len(states))
    stopped = [name for name, state in zip(names, states, strict=True) if state != "active"]
    return {"total": len(names), "running": len(names) - len(stopped), "stopped": stopped}


def _waf_engine() -> str:
    output = waf.status().stdout or ""
    if "not-installed" in output:
        return "off"
    return "on" if "installed" in output else "unknown"


def _malware() -> dict:
    jobs = panel_settings.list_malware_scan_jobs(limit=20)
    last = next((job for job in jobs if job.get("status") in FINISHED_SCANS), None)
    from app.services import addons

    return {
        "addon": addons.is_installed(addons.MALWARE),
        "installed": bool(maldet.installed() or malware_scan.clamav_installed()),
        "running": any(job.get("status") in {"queued", "running"} for job in jobs),
        "last_scan": {
            "status": last.get("status"),
            "infected": int(last.get("infected") or 0),
            "finished_at": last.get("finished_at") or last.get("updated_at") or last.get("started_at"),
        } if last else None,
    }


def _backups(db: Session) -> dict:
    schedules = db.query(BackupSchedule).filter(BackupSchedule.is_active.is_(True)).all()
    ran = [s for s in schedules if s.last_run_at]
    latest = max(ran, key=lambda s: s.last_run_at) if ran else None
    failed = [s.id for s in schedules if (s.last_status or "").lower() in {"error", "failed"}]
    return {
        "schedules": len(schedules),
        "last_run_at": latest.last_run_at.isoformat() if latest else None,
        "last_status": latest.last_status if latest else None,
        "failed": len(failed),
    }


def _server_ipv4() -> str:
    """The address a customer points a domain at (cPanel's "Shared IP")."""
    addresses = server_network.ipv4_addresses()
    return addresses[0] if addresses else ""


def _os_name() -> str:
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return platform.system()


def _uptime_seconds() -> int:
    try:
        return int(float(Path("/proc/uptime").read_text(encoding="ascii").split()[0]))
    except (OSError, ValueError, IndexError):
        return 0


def _server_details() -> dict:
    """The administrator's "Server information": all local reads, no probes."""
    return {
        "hostname": socket.getfqdn(),
        "os": _os_name(),
        "kernel": platform.release(),
        "uptime_seconds": _uptime_seconds(),
        "panel_version": APP_VERSION,
    }


def _accounts(db: Session) -> dict:
    return {
        "end_users": db.query(User).filter(User.role == "end_user").count(),
        "resellers": db.query(User).filter(User.role == "reseller").count(),
    }


@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    admin = is_admin_role(current_user.role)
    # A reseller's dashboard counts its customers' sites with its own.
    site_query = scope_owner(db.query(Website), Website.owner_id, db, current_user)
    db_query = scope_owner(db.query(DatabaseAccount), DatabaseAccount.owner_id, db, current_user)
    sites = site_query.all()
    unsecured = sorted(site.domain for site in sites if not site.ssl_enabled)
    summary: dict[str, Any] = {
        "websites": {
            "total": len(sites),
            "suspended": sum(1 for site in sites if site.status == "suspended"),
            "waf_on": sum(1 for site in sites if site.waf_enabled),
        },
        "ssl": {
            "total": len(sites),
            "secured": len(sites) - len(unsecured),
            "unsecured": unsecured[:UNSECURED_SHOWN],
            "unsecured_count": len(unsecured),
        },
        "databases": {"total": db_query.count()},
        "server": {"ipv4": _safe(_server_ipv4, "")},
    }
    if admin:
        summary["firewall"] = {"enabled": _safe(firewall.is_enabled)}
        summary["waf"] = {"engine": _safe(_waf_engine, "unknown")}
        summary["malware"] = _safe(_malware)
        summary["services"] = _safe(_services)
        summary["updates"] = _safe(updates.cached_release_summary)
        summary["backups"] = _safe(lambda: _backups(db))
        summary["server"].update(_safe(_server_details, {}))
        summary["accounts"] = _safe(lambda: _accounts(db))
        if _safe(lambda: addons.is_installed(addons.MAIL), False):
            summary["mail"] = _safe(lambda: {"domains": db.query(MailDomain).count(),
                                             "mailboxes": db.query(MailAccount).count()})
        if _safe(lambda: addons.is_installed(addons.DNS), False):
            summary["dns"] = _safe(lambda: {"zones": db.query(DnsZone).count()})
        if _safe(lambda: addons.is_installed(addons.APPLICATION), False):
            summary["applications"] = _safe(lambda: {"total": db.query(SiteApp).count()})
    return summary
