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

Then (operator, 2026-09-29): "Addon cần code thêm rspamd để có thể xem log
chặn mail xem có nhầm không. Thêm config relay smarthost cho exim -> Custom
spf/dns mẫu". Rspamd scans mail from outside; its history is the filtering
log on the Email page, where an administrator can put a sender on the
allowlist when it was a mistake. A smarthost carries outgoing mail for servers
whose port 25 is blocked, and its SPF include goes into every domain's SPF.
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
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse

from passlib.hash import sha512_crypt
from sqlalchemy.orm import Session

from app.core.config import settings as app_settings
from app.core.permissions import is_admin_role
from app.core.secrets import decrypt, encrypt
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
SETTINGS_KEY = "mail"
RSPAMD_KEY_FILE = Path("/etc/bpanel/rspamd-controller.key")
RSPAMD_CONTROLLER = "http://127.0.0.1:11334"
ADDRESS_RE = re.compile(r"^[A-Za-z0-9._%+=-]{1,64}@[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")
# One SPF mechanism of a smarthost, such as include:spf.smtp2go.com or ip4:192.0.2.0/24.
SPF_TERM_RE = re.compile(r"^[+?~-]?(include|a|mx|ip4|ip6|exists):[A-Za-z0-9._:/%{}-]{1,200}$")
RELAY_SECURITY = ("starttls", "ssl")
MAX_ALLOW = 5000


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
    """Install Exim, Dovecot, Rspamd and the webmail, and prove they answer.
    Then the spam filter and the smarthost as they were last saved. Raises if not."""
    shell.privileged("mail-install", helper_args=[hostname()], fallback=["true"], timeout=1500)
    apply_settings()
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
    info = {"installed": False, "exim": False, "dovecot": False, "webmail": False, "port_open": False, "hostname": "",
            "rspamd": False, "spam_filter": False, "relay": ""}
    for line in (result.stdout or "").splitlines():
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key in {"installed", "exim", "dovecot", "webmail", "port_open", "rspamd", "spam_filter"}:
            info[key] = value == "yes"
        elif key in {"hostname", "relay"}:
            info[key] = value
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


# --- settings: the spam filter and the smarthost --------------------------------------------

def _stored() -> dict:
    data = panel_settings._read_raw_lenient().get(SETTINGS_KEY)
    return data if isinstance(data, dict) else {}


def _store(section: str, value: dict) -> None:
    raw = panel_settings._read_raw()
    current = raw.get(SETTINGS_KEY) if isinstance(raw.get(SETTINGS_KEY), dict) else {}
    current[section] = value
    raw[SETTINGS_KEY] = current
    panel_settings._write_raw(raw)


def _score(value, default: float) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return default


def spam_settings() -> dict:
    stored = _stored().get("spam")
    stored = stored if isinstance(stored, dict) else {}
    allow = [str(item) for item in stored.get("allow") or [] if str(item).strip()]
    return {
        "enabled": stored.get("enabled", True) is not False,
        "allow": allow,
        "reject_score": _score(stored.get("reject_score"), 15.0),
        "junk_score": _score(stored.get("junk_score"), 6.0),
    }


def _split_allow(entries: list[str]) -> tuple[list[str], list[str], list[str]]:
    """An allowlist as typed -> (addresses, domains, the cleaned list)."""
    senders, domains, cleaned = [], [], []
    for entry in entries or []:
        item = str(entry).strip().lower()
        if not item or item in cleaned:
            continue
        if "@" in item:
            if not ADDRESS_RE.fullmatch(item):
                raise MailError("Each allowlist line is an email address or a domain, such as friend@example.com or example.com.")
            senders.append(item)
        else:
            try:
                item = normalize_domain(item)
            except MailError as exc:
                raise MailError("Each allowlist line is an email address or a domain, such as friend@example.com or example.com.") from exc
            domains.append(item)
        cleaned.append(item)
    if len(cleaned) > MAX_ALLOW:
        raise MailError("The allowlist is limited to 5000 lines.")
    return senders, domains, cleaned


def _apply_spam(settings: dict) -> None:
    senders, domains, _ = _split_allow(settings["allow"])
    body = {"enabled": settings["enabled"], "senders": senders, "domains": domains,
            "reject_score": settings["reject_score"], "junk_score": settings["junk_score"]}
    try:
        shell.privileged("mail-spam-set", input=json.dumps(body), fallback=["true"], timeout=180)
    except RuntimeError as exc:
        raise MailError(_helper_message(exc), status=502) from exc


def save_spam(enabled: bool, allow: list[str], reject_score: float, junk_score: float) -> dict:
    _, _, cleaned = _split_allow(allow)
    reject, junk = _score(reject_score, 15.0), _score(junk_score, 6.0)
    if not (0 < junk < reject <= 100):
        raise MailError("The Junk score must be above 0 and below the reject score, which is at most 100.")
    settings = {"enabled": bool(enabled), "allow": cleaned, "reject_score": reject, "junk_score": junk}
    if active():
        _apply_spam(settings)
    _store("spam", settings)
    return spam_settings()


def relay_settings() -> dict:
    """The smarthost as the page shows it: whether a password is saved, never the password."""
    stored = _stored().get("relay")
    stored = stored if isinstance(stored, dict) else {}
    port = stored.get("port")
    result = {
        "enabled": bool(stored.get("enabled")),
        "host": str(stored.get("host") or ""),
        "port": port if isinstance(port, int) and 1 <= port <= 65535 else 587,
        "security": stored.get("security") if stored.get("security") in RELAY_SECURITY else "starttls",
        "username": str(stored.get("username") or ""),
        "has_password": bool(stored.get("password")),
        "spf_include": str(stored.get("spf_include") or ""),
    }
    return result


def _relay_password() -> str:
    """The saved smarthost password, for the mail server only.

    Kept out of relay_settings() altogether: that dict reaches the page, the
    SPF record and from there the audit log.
    """
    stored = _stored().get("relay")
    encrypted = stored.get("password") if isinstance(stored, dict) else ""
    if not encrypted:
        return ""
    try:
        return decrypt(encrypted)
    except RuntimeError:
        return ""


def spf_include() -> str:
    """The smarthost's SPF mechanisms, when mail goes out through one."""
    if not active():
        return ""
    relay = relay_settings()
    return relay["spf_include"] if relay["enabled"] else ""


def check_spf_include(value: str) -> str:
    terms = (value or "").split()
    if len(" ".join(terms)) > 255 or not all(SPF_TERM_RE.fullmatch(term) for term in terms):
        raise MailError("The SPF part is one or more mechanisms such as include:spf.smtp2go.com or ip4:192.0.2.1.")
    return " ".join(terms)


def _apply_relay(settings: dict, password: str) -> None:
    body = {"enabled": settings["enabled"], "host": settings["host"], "port": settings["port"],
            "security": settings["security"], "username": settings["username"], "password": password}
    try:
        shell.privileged("mail-relay-set", input=json.dumps(body), sensitive=True, fallback=["true"], timeout=120)
    except RuntimeError as exc:
        raise MailError(_helper_message(exc), status=502) from exc


def save_relay(db: Session, *, enabled: bool, host: str, port: int, security: str, username: str,
               password: str | None, spf_include_value: str) -> dict:
    """Send outgoing mail through a smarthost, or straight out again.

    An empty password keeps the saved one. Turning the relay off keeps the
    host and credentials, so turning it on again is one click. When the SPF
    record changes, every zone still publishing the old one follows.
    """
    host = (host or "").strip().lower().rstrip(".")
    username = (username or "").strip()
    secret = password if password else _relay_password()
    settings = {"enabled": bool(enabled), "host": host, "port": int(port), "security": security,
                "username": username, "spf_include": check_spf_include(spf_include_value)}
    if enabled:
        try:
            ipaddress.ip_address(host)
            raise MailError("Give the smarthost by name, such as smtp.example.com: its certificate is checked against it.")
        except ValueError:
            pass
        if not DOMAIN_RE.fullmatch(host):
            raise MailError("Give the smarthost by name, such as smtp.example.com: its certificate is checked against it.")
        if security not in RELAY_SECURITY:
            raise MailError("Choose STARTTLS or SSL for the smarthost.")
        if not 1 <= int(port) <= 65535:
            raise MailError("The smarthost port is a number from 1 to 65535.")
        for value in (username, secret):
            if not value or value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise MailError("Enter the smarthost's user name and password. Neither can start or end with a space.")
    old_spf = _spf_now()
    if active():
        _apply_relay(settings, secret)
    stored = dict(settings)
    stored["password"] = encrypt(secret) if secret else ""
    _store("relay", stored)
    new_spf = _spf_now()
    zones: list[str] = []
    if old_spf != new_spf:
        from app.services import dns

        try:
            zones = dns.replace_spf(db, old_spf, new_spf)
        except (dns.DnsError, dns.DnsInputError) as exc:
            logger.warning("SPF not updated in the zones: %s", exc)
    return {"relay": relay_settings(), "spf": new_spf, "zones_updated": zones}


def _spf_now() -> str:
    from app.services import dns

    return dns.spf_record()


def relay_test(to: str) -> list[str]:
    """Send one message now and return what Exim logged for it."""
    address = (to or "").strip()
    if not ADDRESS_RE.fullmatch(address.lower()):
        raise MailError("Enter the address to send the test message to.")
    result = shell.privileged("mail-relay-test", helper_args=[address], check=False, fallback=["true"], timeout=150)
    if result.returncode != 0:
        lines = [line for line in (result.stderr or "").splitlines() if line.startswith("bpanel-helper: ")]
        raise MailError(lines[-1][len("bpanel-helper: "):] if lines else "The test message could not be sent.", status=502)
    return [line for line in (result.stdout or "").splitlines() if line.strip()]


def apply_settings() -> None:
    """The saved spam filter and smarthost, onto a freshly installed server."""
    _apply_spam(spam_settings())
    relay = relay_settings()
    secret = _relay_password()
    if relay["enabled"] and secret:
        _apply_relay(relay, secret)


def admin_settings() -> dict:
    from app.services import dns

    return {"spam": spam_settings(), "relay": relay_settings(), "spf": dns.spf_record()}


# --- the filtering log (Rspamd's history) -------------------------------------------------

LOG_VIEWS = {
    "blocked": {"reject", "soft reject"},
    "spam": {"add header", "rewrite subject"},
    "all": None,
}


def _controller(path: str):
    try:
        key = RSPAMD_KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise MailError("The spam filter is not set up on this server. Reinstall the Email addon.", status=503) from exc
    request = urllib.request.Request(RSPAMD_CONTROLLER + path, headers={"Password": key})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - fixed loopback URL
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise MailError("The spam filter is not answering. Check that Rspamd is running.", status=502) from exc


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)] if value else []


def _log_row(row: dict, recipients: list[str]) -> dict:
    symbols = row.get("symbols") if isinstance(row.get("symbols"), dict) else {}
    reasons = []
    for name, info in symbols.items():
        info = info if isinstance(info, dict) else {}
        score = _score(info.get("score"), 0.0)
        if score:
            reasons.append({"name": str(name), "score": score,
                            "options": [str(option) for option in _as_list(info.get("options"))][:3]})
    reasons.sort(key=lambda item: -abs(item["score"]))
    sender_mime = _as_list(row.get("sender_mime"))
    return {
        "time": int(_score(row.get("unix_time"), 0.0)),
        "action": str(row.get("action") or ""),
        "score": _score(row.get("score"), 0.0),
        "required": _score(row.get("required_score"), 0.0),
        "from": sender_mime[0] if sender_mime else str(row.get("sender_smtp") or ""),
        "envelope_from": str(row.get("sender_smtp") or ""),
        "to": recipients,
        "subject": str(row.get("subject") or ""),
        "ip": str(row.get("ip") or ""),
        "size": int(_score(row.get("size"), 0.0)),
        "reasons": reasons[:15],
        "allowed": any(str(name).startswith("BPANEL_ALLOW") for name in symbols),
    }


def spam_log(db: Session, user: User, view: str = "blocked", limit: int = 200) -> dict:
    """What the spam filter decided, newest first. A customer sees only mail
    to their own domains, and only their own recipients on it."""
    if view not in LOG_VIEWS:
        view = "blocked"
    settings = spam_settings()
    if not settings["enabled"]:
        return {"enabled": False, "rows": []}
    data = _controller("/history")
    rows = data.get("rows") if isinstance(data, dict) else []
    admin = is_admin_role(user.role)
    mine = set() if admin else set(domains_for(db, user)) | {account.domain for account in visible_accounts(db, user)}
    wanted = LOG_VIEWS[view]
    result = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if wanted is not None and str(row.get("action") or "") not in wanted:
            continue
        recipients = _as_list(row.get("rcpt_smtp")) or _as_list(row.get("rcpt_mime"))
        if not admin:
            recipients = [item for item in recipients if item.rpartition("@")[2].lower() in mine]
            if not recipients:
                continue
        result.append(_log_row(row, recipients))
    result.sort(key=lambda item: -item["time"])
    return {"enabled": True, "rows": result[: max(1, min(int(limit), 500))],
            "thresholds": {"reject": settings["reject_score"], "junk": settings["junk_score"]}}


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
            {"name": domain, "type": "TXT", "value": dns.spf_record()},
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
