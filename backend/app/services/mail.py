"""Email addon: mailboxes on this server, and single sign-on into the webmail.

Operator, 2026-09-29: "phát triển addon email server exim dovecot kết hợp
webmail (https://github.com/bnixvn/webmail) có thể làm SSO login". Chosen with
them: the webmail on the panel's own port (2096) and on webmail.<domain> once
that name points here; mail kept in the customer's home, so it counts toward
their disk space and goes into their backups; DKIM from the first version,
published automatically when DNS Manager is on; a number of mailboxes in each
package, with administrators not held to it.

The helper installs and configures Exim, Dovecot and the webmail
(mail-install). The panel owns the list of mailboxes - the mail_accounts rows -
and hands the whole of it to the helper's mail-sync after every change. The
helper writes what Exim and Dovecot read and answers with each domain's DKIM
public key, which goes into the domain's zone when this server serves its DNS.

Single sign-on: the panel signs a token naming one mailbox with the secret in
/etc/bpanel/webmail-sso.key, which only root, the panel and the webmail can
read. The webmail turns it into a session once, within a minute, and opens the
mailbox as Dovecot's master user; the mailbox password is never needed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import time
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse

from passlib.hash import sha512_crypt
from sqlalchemy.orm import Session

from app.core.config import settings as app_settings
from app.core.permissions import is_admin_role
from app.models.entities import MailAccount, User, Website, WebsiteAlias
from app.services import addons, panel_settings, site_users
from app.services.shell import shell
from app.services.storage_quota import path_usage_bytes

logger = logging.getLogger("bpanel.mail")

SSO_KEY_FILE = Path("/etc/bpanel/webmail-sso.key")
DKIM_CACHE = Path(os.environ.get("BPANEL_DATA_DIR", "/var/lib/bpanel")) / "mail-dkim.json"
WEBMAIL_PORT = 2096
SSO_TOKEN_SECONDS = 60
DEFAULT_QUOTA_MB = 1024
MAX_QUOTA_MB = 1024 * 1024
MIN_PASSWORD = 8
MAX_PASSWORD = 128
# What the helper accepts; checked here first so the customer gets a sentence
# instead of a failed sync.
LOCAL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")
DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")
# Client ports, as the helper opens them.
PORTS = {"imap": 993, "pop3": 995, "smtps": 465, "submission": 587}


class MailError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def active() -> bool:
    return addons.is_installed(addons.MAIL)


def _helper_message(exc: Exception) -> str:
    """The helper's own sentence out of shell.privileged's RuntimeError."""
    lines = [line for line in str(exc).splitlines() if line.startswith("bpanel-helper: ")]
    return lines[-1][len("bpanel-helper: "):] if lines else "The mail server did not accept the change."


# --- the machine (through the helper) ------------------------------------------

def hostname() -> str:
    """The mail server's name: the panel's domain, else the machine's own."""
    candidates = (
        app_settings.panel_domain,
        urlparse(panel_settings.configured_panel_url() or "").hostname or "",
        socket.getfqdn(),
    )
    for candidate in candidates:
        name = (candidate or "").strip().lower().rstrip(".")
        if DOMAIN_RE.fullmatch(name):
            return name
    raise MailError("The mail server needs a name. Give the panel a domain first, in Settings.")


def install() -> dict:
    """Install Exim, Dovecot and the webmail, and prove they answer. Raises if not."""
    shell.privileged("mail-install", helper_args=[hostname()], fallback=["true"], timeout=1500)
    return server_status()


def stop() -> dict:
    """Stop the three services and close the ports. Mail and mailboxes stay."""
    shell.privileged("mail-remove", fallback=["true"], timeout=300)
    return server_status()


def server_status() -> dict:
    result = shell.privileged(
        "mail-status",
        check=False,
        fallback=["bash", "-lc", "echo installed=no"],
    )
    info = {"installed": False, "exim": False, "dovecot": False, "webmail": False, "port_open": False, "hostname": ""}
    for line in (result.stdout or "").splitlines():
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key in {"installed", "exim", "dovecot", "webmail", "port_open"}:
            info[key] = value == "yes"
        elif key == "hostname":
            info["hostname"] = value
    return info


def outbound_smtp_open(timeout: float = 5.0) -> bool:
    """Whether this server can reach another mail server on port 25.

    Many VPS providers block it until asked. Mail then queues and bounces
    days later, which is worth knowing before a customer finds out.
    """
    try:
        with socket.create_connection(("gmail-smtp-in.l.google.com", 25), timeout=timeout):
            return True
    except OSError:
        return False


def panel_host() -> str:
    host = (urlparse(panel_settings.configured_panel_url() or "").hostname or "").lower()
    return host or hostname()


def webmail_url() -> str:
    """The webmail on the panel's own name and certificate."""
    host = panel_host()
    try:
        if ipaddress.ip_address(host).version == 6:
            host = f"[{host}]"
    except ValueError:
        pass
    return f"https://{host}:{WEBMAIL_PORT}"


# --- who may use which domain --------------------------------------------------

def _domain_owners(db: Session) -> dict[str, int]:
    """Every website domain and alias on the server, and whose account it is in."""
    owners = {website.domain.lower(): website.owner_id for website in db.query(Website).all()}
    for alias in db.query(WebsiteAlias).join(Website).all():
        owners.setdefault(alias.domain.lower(), alias.website.owner_id)
    return owners


def domains_for(db: Session, user: User) -> list[str]:
    """The domains this person may make mailboxes on: their own websites' and
    aliases', or every one on the server for an administrator."""
    owners = _domain_owners(db)
    if is_admin_role(user.role):
        return sorted(owners)
    return sorted(domain for domain, owner_id in owners.items() if owner_id == user.id)


def normalize_local(value: str) -> str:
    local = (value or "").strip().lower()
    if not LOCAL_RE.fullmatch(local) or ".." in local:
        raise MailError("The mailbox name may use letters, digits, dots, hyphens and underscores, such as info or sales.")
    return local


def normalize_domain(value: str) -> str:
    domain = (value or "").strip().lower().rstrip(".")
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise MailError("That is not a valid domain name.") from exc
    if not DOMAIN_RE.fullmatch(domain):
        raise MailError("That is not a valid domain name.")
    return domain


def check_password(password: str) -> str:
    password = password or ""
    if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        raise MailError("The password needs 8 to 128 characters.")
    if any(ord(char) < 32 for char in password):
        raise MailError("The password cannot contain control characters.")
    return password


def check_quota(value) -> int:
    try:
        quota = int(value if value is not None else DEFAULT_QUOTA_MB)
    except (TypeError, ValueError) as exc:
        raise MailError("The mailbox size is a number of MB; 0 means no limit of its own.") from exc
    if not 0 <= quota <= MAX_QUOTA_MB:
        raise MailError("The mailbox size is a number of MB; 0 means no limit of its own.")
    return quota


def hash_password(password: str) -> str:
    # SHA512-CRYPT at glibc's default 5000 rounds: what Dovecot checks on every
    # IMAP login, so passlib's default of 656000 would cost each one a second.
    return "{SHA512-CRYPT}" + sha512_crypt.using(rounds=5000).hash(password)


# --- mailboxes ------------------------------------------------------------------

def linux_user_of(owner: User) -> str:
    return site_users.linux_user_for_panel_username(owner.username)


def box_path(owner: User, account: MailAccount) -> str:
    return f"/home/{linux_user_of(owner)}/mail/{account.domain}/{account.local_part}"


def account_view(account: MailAccount, owner: User | None, *, usage: bool = True) -> dict:
    return {
        "id": account.id,
        "address": account.address,
        "local_part": account.local_part,
        "domain": account.domain,
        "quota_mb": account.quota_mb,
        "used_bytes": path_usage_bytes(box_path(owner, account)) if usage and owner else 0,
        "owner_id": account.owner_id,
        "owner": owner.username if owner else "",
        "created_at": account.created_at.isoformat() if account.created_at else None,
    }


def visible_accounts(db: Session, user: User) -> list[MailAccount]:
    query = db.query(MailAccount)
    if not is_admin_role(user.role):
        query = query.filter(MailAccount.owner_id == user.id)
    return query.order_by(MailAccount.domain, MailAccount.local_part).all()


def list_accounts(db: Session, user: User) -> list[dict]:
    owners = {row.id: row for row in db.query(User).all()}
    return [account_view(account, owners.get(account.owner_id)) for account in visible_accounts(db, user)]


def limit_for(db: Session, user: User) -> dict:
    used = db.query(MailAccount).filter(MailAccount.owner_id == user.id).count()
    if is_admin_role(user.role):
        return {"limit": None, "used": used}
    return {"limit": int(user.mail_accounts_limit or 0), "used": used}


def get_account(db: Session, user: User, account_id: int) -> MailAccount:
    account = db.query(MailAccount).filter(MailAccount.id == account_id).first()
    # Someone else's mailbox does not exist, as far as a customer can tell.
    if account is None or (not is_admin_role(user.role) and account.owner_id != user.id):
        raise MailError("There is no such mailbox.", status=404)
    return account


def create_account(db: Session, actor: User, local_part: str, domain: str, password: str, quota_mb=None) -> MailAccount:
    if not active():
        raise MailError("The Email addon is not installed.", status=409)
    local = normalize_local(local_part)
    domain = normalize_domain(domain)
    admin = is_admin_role(actor.role)
    owner_id = _domain_owners(db).get(domain)
    if owner_id is None or (not admin and owner_id != actor.id):
        raise MailError("Mailboxes can only be made on the domains of your own websites.")
    check_password(password)
    quota = check_quota(quota_mb)
    owner = db.query(User).filter(User.id == owner_id).first()
    if owner is None:
        raise MailError("That domain's website has no owner.")
    if not admin:
        used = db.query(MailAccount).filter(MailAccount.owner_id == owner.id).count()
        limit = int(owner.mail_accounts_limit or 0)
        if used >= limit:
            raise MailError("All the mailboxes in your hosting package are in use.", status=403)
    if db.query(MailAccount).filter(MailAccount.domain == domain, MailAccount.local_part == local).first():
        raise MailError("That address already exists.", status=409)
    account = MailAccount(owner_id=owner.id, domain=domain, local_part=local,
                          password_hash=hash_password(password), quota_mb=quota)
    db.add(account)
    db.flush()
    try:
        sync(db)
    except MailError:
        db.rollback()
        raise
    db.commit()
    db.refresh(account)
    return account


def update_account(db: Session, actor: User, account_id: int, *, password: str | None = None, quota_mb=None) -> MailAccount:
    account = get_account(db, actor, account_id)
    if password is not None:
        account.password_hash = hash_password(check_password(password))
    if quota_mb is not None:
        account.quota_mb = check_quota(quota_mb)
    db.flush()
    try:
        sync(db)
    except MailError:
        db.rollback()
        raise
    db.commit()
    db.refresh(account)
    return account


def delete_account(db: Session, actor: User, account_id: int) -> str:
    """Delete a mailbox and the mail in it."""
    account = get_account(db, actor, account_id)
    owner = db.query(User).filter(User.id == account.owner_id).first()
    address, domain, local = account.address, account.domain, account.local_part
    db.delete(account)
    db.flush()
    try:
        sync(db)
    except MailError:
        db.rollback()
        raise
    db.commit()
    # Only once Exim no longer delivers there.
    if owner is not None:
        result = shell.privileged("mail-delete-box", helper_args=[linux_user_of(owner), domain, local],
                                  check=False, fallback=["true"], timeout=300)
        if result.returncode != 0:
            logger.warning("Mailbox %s is deleted but its mail is still on disk: %s", address, result.stderr)
    return address


# --- the whole list, to the mail server ------------------------------------------

def payload(db: Session) -> dict:
    owners = {row.id: row for row in db.query(User).all()}
    boxes = []
    for account in db.query(MailAccount).order_by(MailAccount.domain, MailAccount.local_part).all():
        owner = owners.get(account.owner_id)
        if owner is None:
            continue
        boxes.append({
            "local": account.local_part,
            "domain": account.domain,
            "user": linux_user_of(owner),
            "hash": account.password_hash,
            "quota_mb": int(account.quota_mb or 0),
            # A suspended account's mailboxes still receive; they cannot log in.
            "active": bool(owner.is_active),
        })
    return {"mailboxes": boxes}


def _save_dkim(keys: dict[str, str]) -> None:
    DKIM_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=str(DKIM_CACHE.parent), delete=False) as tmp:
        json.dump(keys, tmp, sort_keys=True)
        tmp_path = Path(tmp.name)
    tmp_path.replace(DKIM_CACHE)


def dkim_keys() -> dict[str, str]:
    """Each mail domain's DKIM public key, as the last sync reported it."""
    try:
        data = json.loads(DKIM_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def sync(db: Session) -> dict:
    """Hand every mailbox to the mail server, then publish DKIM where we can."""
    if not active():
        raise MailError("The Email addon is not installed.", status=409)
    try:
        result = shell.privileged(
            "mail-sync",
            input=json.dumps(payload(db)),
            timeout=300,
            fallback=["bash", "-lc", "echo '{\"mailboxes\": 0, \"domains\": [], \"dkim\": {}}'"],
        )
    except RuntimeError as exc:
        raise MailError(_helper_message(exc), status=502) from exc
    try:
        report = json.loads((result.stdout or "").strip().splitlines()[-1])
    except (IndexError, ValueError) as exc:
        raise MailError("The mail server gave an answer the panel could not read.", status=502) from exc
    keys = {str(domain): str(key) for domain, key in (report.get("dkim") or {}).items()}
    _save_dkim(keys)
    published: dict[str, list[str]] = {}
    from app.services import dns

    for domain, key in keys.items():
        try:
            names = dns.mail_records(db, domain, key)
        except (dns.DnsError, dns.DnsInputError) as exc:
            # DNS is never the reason a mailbox cannot be made.
            logger.warning("No mail DNS records for %s: %s", domain, exc)
            continue
        if names:
            published[domain] = names
    return {"mailboxes": report.get("mailboxes", 0), "domains": report.get("domains", []), "dns": published}


def sync_quietly(db: Session) -> dict | None:
    """sync() for the places that must not fail because of mail: startup, a
    restore, deleting a user."""
    try:
        if not active():
            return None
        return sync(db)
    except Exception:  # noqa: BLE001 - mail is never the reason something else fails
        logger.warning("Mail sync failed", exc_info=True)
        db.rollback()
        return None


# --- what a customer needs to know -------------------------------------------------

def webmail_hosts() -> set[str]:
    result = shell.privileged("mail-webmail-hosts", check=False, fallback=["true"])
    return {line.strip() for line in (result.stdout or "").splitlines() if line.strip()}


def domain_overview(db: Session, user: User) -> list[dict]:
    """Each domain with mailboxes this person can see: its webmail address and
    the DNS records mail needs, for a domain whose DNS is elsewhere."""
    accounts = visible_accounts(db, user)
    if not accounts:
        return []
    counts: dict[str, int] = {}
    for account in accounts:
        counts[account.domain] = counts.get(account.domain, 0) + 1
    hosts = webmail_hosts()
    keys = dkim_keys()
    server = hostname()
    from app.services import dns

    overview = []
    for domain in sorted(counts):
        records = [
            {"name": domain, "type": "MX", "value": f"10 {server}"},
            {"name": domain, "type": "TXT", "value": "v=spf1 a mx ~all"},
            {"name": f"_dmarc.{domain}", "type": "TXT", "value": "v=DMARC1; p=none"},
            {"name": f"webmail.{domain}", "type": "A", "value": dns.default_zone_ip()},
        ]
        if keys.get(domain):
            records.insert(2, {"name": f"{dns.DKIM_SELECTOR}._domainkey.{domain}", "type": "TXT",
                               "value": f"v=DKIM1; k=rsa; p={keys[domain]}"})
        overview.append({
            "domain": domain,
            "mailboxes": counts[domain],
            "webmail": f"https://webmail.{domain}" if domain in hosts else "",
            "records": records,
        })
    return overview


def client_settings() -> dict:
    server = hostname()
    return {
        "hostname": server,
        "imap": {"host": server, "port": PORTS["imap"], "security": "SSL/TLS"},
        "pop3": {"host": server, "port": PORTS["pop3"], "security": "SSL/TLS"},
        "smtp": {"host": server, "port": PORTS["smtps"], "security": "SSL/TLS"},
        "submission": {"host": server, "port": PORTS["submission"], "security": "STARTTLS"},
        "webmail": webmail_url(),
    }


def enable_webmail_host(db: Session, user: User, domain: str) -> str:
    """webmail.<domain> with its own certificate. The name has to point here."""
    domain = normalize_domain(domain)
    if not any(account.domain == domain for account in visible_accounts(db, user)):
        raise MailError("Make a mailbox on this domain first.", status=404)
    name = f"webmail.{domain}"
    if name in _domain_owners(db):
        raise MailError("That webmail address is already a website on this server.", status=409)
    args = [domain]
    if app_settings.ssl_email:
        args.append(app_settings.ssl_email)
    result = shell.privileged("mail-webmail-host", helper_args=args, check=False, fallback=["true"], timeout=300)
    if result.returncode != 0:
        lines = [line for line in (result.stderr or "").splitlines() if line.startswith("bpanel-helper: ")]
        raise MailError(lines[-1][len("bpanel-helper: "):] if lines else "Could not set up the webmail address.", status=502)
    return f"https://{name}"


def disable_webmail_host(db: Session, user: User, domain: str) -> None:
    domain = normalize_domain(domain)
    if not any(account.domain == domain for account in visible_accounts(db, user)):
        raise MailError("There is no such mail domain.", status=404)
    shell.privileged("mail-webmail-host-remove", helper_args=[domain], check=False, fallback=["true"])


# --- single sign-on ----------------------------------------------------------------

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sso_token(address: str, *, now: float | None = None, key: str | None = None) -> str:
    """What the webmail's /api/auth/sso accepts: payload.signature, base64url."""
    if key is None:
        try:
            key = SSO_KEY_FILE.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise MailError("The webmail is not set up on this server. Reinstall the Email addon.", status=503) from exc
    if not key:
        raise MailError("The webmail is not set up on this server. Reinstall the Email addon.", status=503)
    issued = int(now if now is not None else time.time())
    body = _b64(json.dumps({"email": address, "exp": issued + SSO_TOKEN_SECONDS,
                            "nonce": secrets.token_urlsafe(16)}, separators=(",", ":")).encode())
    signature = _b64(hmac.new(key.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{signature}"


def sso_url(db: Session, user: User, account_id: int) -> str:
    account = get_account(db, user, account_id)
    return f"{webmail_url()}/api/auth/sso?token={sso_token(account.address)}"


# --- disk space and backups ----------------------------------------------------------

def restore_accounts(db: Session, user: User, entries: list, stage_mail) -> list[str]:
    """Bring back a user backup's mailboxes: the rows, then the mail.

    stage_mail(domain, local) returns a staged directory holding that
    mailbox's mail from the archive, or None. An address that belongs to
    another account here is refused, like a domain would be.
    """
    restored = []
    owned = set(_domain_owners(db))
    for entry in entries or []:
        try:
            local = normalize_local(str(entry.get("local_part") or ""))
            domain = normalize_domain(str(entry.get("domain") or ""))
        except MailError as exc:
            raise ValueError(f"Invalid mailbox in backup: {exc.message}") from exc
        secret = str(entry.get("password_hash") or "")
        if not secret.startswith("{SHA512-CRYPT}$6$"):
            raise ValueError(f"Invalid password hash for {local}@{domain} in backup")
        if domain not in owned:
            # The website did not come back; the mail still does, under this user.
            logger.info("Restoring %s@%s with no website for its domain", local, domain)
        existing = db.query(MailAccount).filter(MailAccount.domain == domain, MailAccount.local_part == local).first()
        if existing is not None and existing.owner_id != user.id:
            raise ValueError(f"Mailbox already belongs to another user: {local}@{domain}")
        if existing is None:
            existing = MailAccount(owner_id=user.id, domain=domain, local_part=local,
                                   password_hash=secret, quota_mb=check_quota(entry.get("quota_mb")),
                                   created_at=datetime.utcnow())
            db.add(existing)
        else:
            existing.password_hash = secret
            existing.quota_mb = check_quota(entry.get("quota_mb"))
        db.flush()
        staged = stage_mail(domain, local)
        if staged:
            shell.privileged("mail-import", helper_args=[linux_user_of(user), domain, local, str(staged)],
                             fallback=["true"], timeout=1800)
        restored.append(f"{local}@{domain}")
    return restored
