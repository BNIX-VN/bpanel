"""Install and remove the panel's optional features.

Only an administrator sees this: an addon changes the server, not one account.
Every other user is told what exists so they know what to ask for, without being
able to turn it on.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.permissions import Role, ensure_role, is_admin_role
from app.models.entities import SiteApp, User
from app.services import addons, fail2ban, site_apps
from app.services.audit import log_action

router = APIRouter(prefix="/addons", tags=["addons"])


def _install_failure(exc: Exception) -> str:
    """The helper's own words, not a stack trace.

    shell.privileged wraps a failure as "Command failed: <the whole command
    line>" then a newline then stderr. The command line is noise to whoever is
    reading the panel; the stderr is the sentence the helper wrote for them.
    """
    text = str(exc).strip()
    _, separator, stderr = text.partition(chr(10))
    message = (stderr if separator else text).strip()
    for prefix in ("bpanel-helper: ", "ERROR: "):
        if message.startswith(prefix):
            message = message[len(prefix):]
    return message[:500] or "The install failed and said nothing about why."


@router.get("")
def list_addons(current_user: User = Depends(get_current_user)):
    """What the panel can do, and what it is currently doing.

    Readable by every role: the sections a customer cannot see are the ones an
    addon has not been installed for, and a blank panel with no explanation is
    worse than one that says which feature is missing.
    """
    ensure_role(current_user.role, Role.end_user)
    entries = addons.state()
    if not is_admin_role(current_user.role):
        # A customer has no business knowing how the server is put together.
        for entry in entries:
            entry.pop("notes", None)
    return {"items": entries, "can_manage": is_admin_role(current_user.role)}


@router.post("/{slug}/install")
def install_addon(slug: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    entry = addons.known(slug)
    if slug == addons.FAIL2BAN:
        # Unlike Application, there is nothing to configure afterwards: this
        # either protects the machine or it does not. The helper proves a ban
        # reaches iptables and raises if it does not, so a failure here means
        # the addon is not recorded as installed - which is the truth.
        #
        # Say why. Letting the RuntimeError out gave the operator "500
        # internal server error" and nothing else, while the helper had
        # already written the reason - "could not install fail2ban", "a test
        # ban never reached iptables - check banaction in ...". A 500 is an
        # answer nobody can act on, and on a live report it cost an afternoon
        # of log reading to get back to a message that had existed all along.
        try:
            fail2ban.install()
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=_install_failure(exc)) from exc
    record = addons.install(slug)
    log_action(db, current_user.id, "install_addon", slug, record.get("version", ""))
    return {
        "slug": slug,
        "name": entry["name"],
        "installed": True,
        "version": record.get("version", ""),
        # The runtimes an application needs are installed from the Application
        # page itself, which can report progress; saying so here saves someone
        # wondering why Docker did not appear.
        "next_step": "Open the Application page to install Docker or the Node.js versions you need."
        if slug == addons.APPLICATION else (
            "SSH is protected now. Banned addresses are listed on the Firewall page."
            if slug == addons.FAIL2BAN else ""
        ),
    }


@router.post("/{slug}/uninstall")
def uninstall_addon(slug: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Turn an addon off. Nothing it created is deleted.

    The units are stopped, because a panel that no longer shows a feature should
    not keep running it where nobody can see or manage it. Everything else — the
    files, the volumes, the rows — stays exactly where it is, so installing the
    addon again brings it all back.
    """
    ensure_role(current_user.role, Role.admin)
    entry = addons.known(slug)
    stopped: list[str] = []
    failed: list[str] = []
    if slug == addons.APPLICATION:
        for app in db.query(SiteApp).all():
            try:
                site_apps.control(app, "stop")
                stopped.append(app.name)
            except (RuntimeError, ValueError):
                # Already gone, or never deployed. Not a reason to refuse.
                failed.append(app.name)
    if slug == addons.FAIL2BAN:
        try:
            fail2ban.stop()
            stopped.append("fail2ban")
        except RuntimeError:
            failed.append("fail2ban")
    revoked = 0
    if slug == addons.MCP:
        # The one addon whose removal destroys something, and the reason its
        # catalogue entry says keeps_data_on_uninstall is false. A token is a
        # way into this server; leaving them valid against an endpoint that
        # answers again the moment someone reinstalls is not "keeping data".
        from app.api import mcp as mcp_api
        revoked = mcp_api.revoke_all(db)
    addons.uninstall(slug)
    log_action(db, current_user.id, "uninstall_addon", slug, f"stopped {len(stopped)} revoked {revoked}")
    return {
        "slug": slug,
        "name": entry["name"],
        "installed": False,
        "stopped": stopped,
        "could_not_stop": failed,
        "revoked_tokens": revoked,
        "kept": "The package, the jail configuration and the ban history are all kept."
        if slug == addons.FAIL2BAN
        else (f"{revoked} MCP token(s) were revoked. Assistants using them can no longer reach the panel."
              if slug == addons.MCP
              else "Application directories, volumes and panel data are all kept."),
    }
