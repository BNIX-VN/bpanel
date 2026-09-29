"""Email: mailboxes, the webmail and single sign-on into it (services/mail.py).

Every route needs the addon. A customer sees and changes the mailboxes of
their own account and makes new ones on their own websites' domains, up to
their package's limit; an administrator sees every mailbox and makes them on
any domain. Opening the webmail from here needs no mailbox password.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.permissions import Role, ensure_role, is_admin_role
from app.models.entities import User
from app.services import addons, mail
from app.services.audit import log_action

router = APIRouter(prefix="/mail", tags=["mail"], dependencies=[Depends(addons.require_mail)])


class AccountIn(BaseModel):
    local_part: str = Field(max_length=64)
    domain: str = Field(max_length=253)
    password: str = Field(max_length=mail.MAX_PASSWORD)
    quota_mb: int = Field(default=mail.DEFAULT_QUOTA_MB, ge=0, le=mail.MAX_QUOTA_MB)


class AccountChange(BaseModel):
    password: str | None = Field(default=None, max_length=mail.MAX_PASSWORD)
    quota_mb: int | None = Field(default=None, ge=0, le=mail.MAX_QUOTA_MB)


def _answer(action):
    """Run a mail change and turn its failures into HTTP answers."""
    try:
        return action()
    except mail.MailError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@router.get("/overview")
def overview(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Everything the Email page shows, in one request."""
    ensure_role(current_user.role, Role.end_user)
    return _answer(lambda: {
        "accounts": mail.list_accounts(db, current_user),
        "domains": mail.domains_for(db, current_user),
        "limit": mail.limit_for(db, current_user),
        "mail_domains": mail.domain_overview(db, current_user),
        "client": mail.client_settings(),
        "is_admin": is_admin_role(current_user.role),
    })


@router.get("/status")
def status(current_user: User = Depends(get_current_user)):
    """The mail server itself, for administrators."""
    ensure_role(current_user.role, Role.admin)
    return {**mail.server_status(), "outbound_smtp": mail.outbound_smtp_open()}


@router.post("/accounts")
def create_account(payload: AccountIn, request: Request, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    account = _answer(lambda: mail.create_account(
        db, current_user, payload.local_part, payload.domain, payload.password, payload.quota_mb))
    log_action(db, current_user.id, "mail_create", account.address, f"quota {account.quota_mb} MB", request=request)
    return mail.account_view(account, db.query(User).filter(User.id == account.owner_id).first())


@router.put("/accounts/{account_id}")
def update_account(account_id: int, payload: AccountChange, request: Request, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    account = _answer(lambda: mail.update_account(
        db, current_user, account_id, password=payload.password, quota_mb=payload.quota_mb))
    changed = [part for part, value in (("password", payload.password), ("quota", payload.quota_mb)) if value is not None]
    log_action(db, current_user.id, "mail_update", account.address, ",".join(changed), request=request)
    return mail.account_view(account, db.query(User).filter(User.id == account.owner_id).first())


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int, request: Request, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    address = _answer(lambda: mail.delete_account(db, current_user, account_id))
    log_action(db, current_user.id, "mail_delete", address, "", request=request)
    return {"ok": True, "address": address}


@router.post("/accounts/{account_id}/webmail")
def open_webmail(account_id: int, request: Request, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    """A one-time link that opens this mailbox in the webmail, signed in."""
    ensure_role(current_user.role, Role.end_user)
    url = _answer(lambda: mail.sso_url(db, current_user, account_id))
    account = mail.get_account(db, current_user, account_id)
    log_action(db, current_user.id, "mail_webmail_sso", account.address, "", request=request)
    return {"url": url}


@router.post("/domains/{domain}/webmail")
def enable_webmail_host(domain: str, request: Request, db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    """webmail.<domain>, with its own certificate; the name must point here."""
    ensure_role(current_user.role, Role.end_user)
    url = _answer(lambda: mail.enable_webmail_host(db, current_user, domain))
    log_action(db, current_user.id, "mail_webmail_host", domain, url, request=request)
    return {"url": url}


@router.delete("/domains/{domain}/webmail")
def disable_webmail_host(domain: str, request: Request, db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    _answer(lambda: mail.disable_webmail_host(db, current_user, domain))
    log_action(db, current_user.id, "mail_webmail_host_remove", domain, "", request=request)
    return {"ok": True}


@router.post("/sync")
def sync(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Hand every mailbox to the mail server again, and republish DKIM."""
    ensure_role(current_user.role, Role.admin)
    result = _answer(lambda: mail.sync(db))
    log_action(db, current_user.id, "mail_sync", "", f"{result['mailboxes']} mailboxes", request=request)
    return result


# --- the spam filter, its log, and the smarthost ----------------------------------------

class SpamIn(BaseModel):
    enabled: bool = True
    # One address or domain per entry; mail from them is never blocked.
    allow: list[str] = Field(default_factory=list, max_length=mail.MAX_ALLOW)
    reject_score: float = Field(default=15, gt=0, le=100)
    junk_score: float = Field(default=6, gt=0, le=100)


class RelayIn(BaseModel):
    enabled: bool = False
    host: str = Field(default="", max_length=253)
    port: int = Field(default=587, ge=1, le=65535)
    security: str = Field(default="starttls", max_length=10)
    username: str = Field(default="", max_length=256)
    # Empty keeps the saved password.
    password: str | None = Field(default=None, max_length=512)
    spf_include: str = Field(default="", max_length=255)


class RelayTestIn(BaseModel):
    to: str = Field(max_length=254)


@router.get("/settings")
def get_settings(current_user: User = Depends(get_current_user)):
    """The spam filter and the smarthost. The smarthost password never leaves."""
    ensure_role(current_user.role, Role.admin)
    return mail.admin_settings()


@router.put("/settings/spam")
def save_spam(payload: SpamIn, request: Request, db: Session = Depends(get_db),
              current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    saved = _answer(lambda: mail.save_spam(payload.enabled, payload.allow, payload.reject_score, payload.junk_score))
    log_action(db, current_user.id, "mail_spam_settings", "on" if saved["enabled"] else "off",
               f"reject {saved['reject_score']} junk {saved['junk_score']} allow {len(saved['allow'])}", request=request)
    return saved


@router.put("/settings/relay")
def save_relay(payload: RelayIn, request: Request, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    result = _answer(lambda: mail.save_relay(
        db, enabled=payload.enabled, host=payload.host, port=payload.port, security=payload.security,
        username=payload.username, password=payload.password, spf_include_value=payload.spf_include))
    relay = result["relay"]
    log_action(db, current_user.id, "mail_relay_settings",
               f"{relay['host']}:{relay['port']}" if relay["enabled"] else "off",
               f"spf zones updated {len(result['zones_updated'])}", request=request)
    return result


@router.post("/relay/test")
def relay_test(payload: RelayTestIn, request: Request, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_user)):
    """Send one message now, and say what happened to it."""
    ensure_role(current_user.role, Role.admin)
    lines = _answer(lambda: mail.relay_test(payload.to))
    log_action(db, current_user.id, "mail_relay_test", payload.to, "", request=request)
    return {"lines": lines}


@router.get("/spam/log")
def spam_log(view: str = "blocked", limit: int = 200, db: Session = Depends(get_db),
             current_user: User = Depends(get_current_user)):
    """What the spam filter decided. A customer sees mail to their own domains."""
    ensure_role(current_user.role, Role.end_user)
    return _answer(lambda: mail.spam_log(db, current_user, view, limit))
