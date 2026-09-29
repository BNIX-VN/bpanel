"""Email addon (operator, 2026-09-29: "phát triển addon email server exim dovecot
kết hợp webmail (https://github.com/bnixvn/webmail) có thể làm SSO login").

Chosen with the operator: the webmail on the panel's port 2096 and on
webmail.<domain>; mail in the customer's home, counted and backed up with the
account; DKIM from the first version, published when DNS Manager is on; a
number of mailboxes in each package, administrators not held to it.

The helper is replaced by a fake that answers mail-sync the way the real one
does, so what is tested is what the panel hands to the mail server. The helper's
own behaviour was proved on the .88 test server (delivery, IMAP with a verified
certificate, the master login, submission, DKIM verified with dkimpy, SSO).
"""
import base64
import hashlib
import hmac
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import create_access_token, hash_password
from app.models.entities import MailAccount, User, Website, WebsiteAlias
from app.services import addons, dns, mail, panel_settings, server_network, storage_quota
from app.tests.test_dns import FakePowerDNS

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HELPER = (PROJECT_ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")
APP_JSX = (PROJECT_ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
# The helper's own check on a hash, so the panel never sends one it refuses.
HELPER_HASH_RE = re.compile(r"^\{SHA512-CRYPT\}\$6\$(rounds=[0-9]{4,9}\$)?[./A-Za-z0-9]{1,16}\$[./A-Za-z0-9]{86}$")


class FakeHelper:
    """The mail verbs of bpanel-helper, recorded."""

    def __init__(self):
        self.calls: list[tuple[str, list, str | None]] = []
        self.synced: dict = {"mailboxes": []}
        self.webmail_hosts: set[str] = set()
        self.fail_sync = ""
        self.spam: dict | None = None
        self.relay: dict | None = None
        self.sensitive: set[str] = set()

    def privileged(self, command, helper_args=None, check=True, input=None, sensitive=False, fallback=None, timeout=None):
        args = list(helper_args or [])
        self.calls.append((command, args, input))
        if sensitive:
            self.sensitive.add(command)
        stdout, stderr, code = "", "", 0
        if command == "mail-spam-set":
            self.spam = json.loads(input)
        elif command == "mail-relay-set":
            self.relay = json.loads(input)
        elif command == "mail-relay-test":
            stdout = f"2026-09-29 11:00:00 1xAAAA-00000000aaa-0000 => {args[0]} R=bpanel_smarthost T=bpanel_smarthost_smtp C=\"250 OK\"\n"
        if command == "mail-sync":
            if self.fail_sync:
                if check:
                    raise RuntimeError(f"Command failed: sudo -n bpanel-helper mail-sync\nbpanel-helper: {self.fail_sync}")
                return SimpleNamespace(returncode=1, stdout="", stderr=f"bpanel-helper: {self.fail_sync}")
            self.synced = json.loads(input)
            domains = sorted({box["domain"] for box in self.synced["mailboxes"]})
            stdout = json.dumps({"mailboxes": len(self.synced["mailboxes"]), "domains": domains,
                                 "dkim": {domain: f"KEY{domain.replace('.', '')}" for domain in domains}})
        elif command == "mail-webmail-hosts":
            stdout = "\n".join(sorted(self.webmail_hosts))
        elif command == "mail-webmail-host":
            self.webmail_hosts.add(args[0])
            stdout = f"https://webmail.{args[0]}"
        elif command == "mail-status":
            stdout = "installed=yes\nexim=yes\ndovecot=yes\nwebmail=yes\nport_open=yes\nhostname=panel.example.vn\n"
        return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)

    def verbs(self):
        return [call[0] for call in self.calls]


@pytest.fixture
def env(monkeypatch, tmp_path):
    stored: dict = {"panel_url": "https://panel.example.vn:2222",
                    "dns": {"nameservers": ["ns1.bnix.vn", "ns2.bnix.vn"], "zone_ip": "203.0.113.10",
                            "ttl": 3600, "auto_zone": True}}
    monkeypatch.setattr(panel_settings, "_read_raw", lambda: dict(stored))
    monkeypatch.setattr(panel_settings, "_read_raw_lenient", lambda: dict(stored))
    monkeypatch.setattr(panel_settings, "_write_raw", lambda data: stored.update(data))
    monkeypatch.setattr(addons, "ADDONS_DIR", tmp_path)
    monkeypatch.setattr(addons, "ADDONS_FILE", tmp_path / "addons.json")
    monkeypatch.setattr(server_network, "ipv4_addresses", lambda: ["203.0.113.10"])
    monkeypatch.setattr(mail, "DKIM_CACHE", tmp_path / "mail-dkim.json")
    key_file = tmp_path / "webmail-sso.key"
    key_file.write_text("shared-secret-for-tests\n", encoding="utf-8")
    monkeypatch.setattr(mail, "SSO_KEY_FILE", key_file)
    helper = FakeHelper()
    monkeypatch.setattr(mail, "shell", helper)
    fake_dns = FakePowerDNS()
    monkeypatch.setattr(dns, "_request", fake_dns)
    addons.install(addons.MAIL)

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    for name, role, limit in (("owner", "admin", 10), ("khach", "end_user", 2), ("other", "end_user", 10)):
        db.add(User(username=name, email=f"{name}@example.test", hashed_password=hash_password("pw-" + name),
                    role=role, is_active=True, token_version=0, mail_accounts_limit=limit))
    db.commit()
    ids = {user.username: user.id for user in db.query(User).all()}
    for domain, owner in (("khach.vn", "khach"), ("other.vn", "other"), ("admin.vn", "owner")):
        db.add(Website(domain=domain, owner_id=ids[owner], root_path=f"/home/{owner}/{domain}", linux_user=owner))
    db.commit()
    site = db.query(Website).filter(Website.domain == "khach.vn").one()
    db.add(WebsiteAlias(website_id=site.id, domain="khach-alias.vn", mode="alias"))
    db.commit()

    from app.main import app

    def get_test_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = get_test_db

    def user(name):
        db.expire_all()
        return db.query(User).filter(User.username == name).one()

    def as_(name):
        token = create_access_token(name, {"role": user(name).role, "tv": 0})
        return {"Authorization": f"Bearer {token}"}

    yield SimpleNamespace(client=TestClient(app), db=db, helper=helper, dns=fake_dns, user=user, as_=as_,
                          stored=stored, tmp=tmp_path)
    app.dependency_overrides.pop(get_db, None)
    db.close()


def _create(env, who, local, domain, password="mailbox-pass-1", quota=1024):
    return env.client.post("/api/mail/accounts", headers=env.as_(who),
                           json={"local_part": local, "domain": domain, "password": password, "quota_mb": quota})


# --- who may make which mailbox ---------------------------------------------------

def test_a_customer_makes_mailboxes_on_their_own_domains_and_aliases(env):
    assert _create(env, "khach", "info", "khach.vn").status_code == 200
    assert _create(env, "khach", "sales", "khach-alias.vn").status_code == 200
    boxes = env.helper.synced["mailboxes"]
    assert {(box["local"], box["domain"], box["user"]) for box in boxes} == {
        ("info", "khach.vn", "khach"), ("sales", "khach-alias.vn", "khach")}


def test_a_customer_cannot_make_a_mailbox_on_someone_elses_domain(env):
    response = _create(env, "khach", "ceo", "other.vn")
    assert response.status_code == 400
    assert env.db.query(MailAccount).count() == 0
    assert "mail-sync" not in env.helper.verbs()


def test_an_administrator_makes_one_on_any_domain_and_it_belongs_to_the_domain_owner(env):
    response = _create(env, "owner", "support", "other.vn")
    assert response.status_code == 200
    assert response.json()["owner"] == "other"
    assert env.helper.synced["mailboxes"][0]["user"] == "other"


def test_the_package_limit_counts_mailboxes_and_administrators_are_not_held_to_it(env):
    assert _create(env, "khach", "a", "khach.vn").status_code == 200
    assert _create(env, "khach", "b", "khach.vn").status_code == 200
    refused = _create(env, "khach", "c", "khach.vn")
    assert refused.status_code == 403
    assert refused.json()["detail"] == "All the mailboxes in your hosting package are in use."
    # An administrator making one for the same customer is not refused.
    assert _create(env, "owner", "c", "khach.vn").status_code == 200


def test_an_address_exists_once(env):
    assert _create(env, "khach", "info", "khach.vn").status_code == 200
    assert _create(env, "owner", "INFO", "khach.vn").status_code == 409


@pytest.mark.parametrize("local", ["", ".info", "info.", "in..fo", "a+b", "a b", "ạ", "x" * 65])
def test_names_the_mail_server_would_refuse_are_refused_first(env, local):
    assert _create(env, "khach", local, "khach.vn").status_code in (400, 422)


def test_a_short_password_is_refused(env):
    assert _create(env, "khach", "info", "khach.vn", password="short").status_code == 400


def test_the_password_reaches_the_mail_server_only_as_a_hash_it_accepts(env):
    _create(env, "khach", "info", "khach.vn", password="mailbox-pass-1")
    sent = env.helper.synced["mailboxes"][0]["hash"]
    assert HELPER_HASH_RE.fullmatch(sent)
    assert "mailbox-pass-1" not in json.dumps(env.helper.synced)
    from passlib.hash import sha512_crypt

    assert sha512_crypt.verify("mailbox-pass-1", sent.removeprefix("{SHA512-CRYPT}"))
    # glibc's default cost: Dovecot checks it on every IMAP login.
    assert "rounds=" not in sent


def test_a_failed_sync_leaves_no_mailbox_behind(env):
    env.helper.fail_sync = "invalid mailbox owner"
    response = _create(env, "khach", "info", "khach.vn")
    assert response.status_code == 502
    assert response.json()["detail"] == "invalid mailbox owner"
    assert env.db.query(MailAccount).count() == 0


def test_every_route_needs_the_addon(env):
    addons.uninstall(addons.MAIL)
    assert env.client.get("/api/mail/overview", headers=env.as_("khach")).status_code == 409


# --- changing and deleting -----------------------------------------------------------

def test_a_customer_sees_and_changes_only_their_own_mailboxes(env):
    mine = _create(env, "khach", "info", "khach.vn").json()
    theirs = _create(env, "other", "info", "other.vn").json()
    listed = env.client.get("/api/mail/overview", headers=env.as_("khach")).json()
    assert [row["address"] for row in listed["accounts"]] == ["info@khach.vn"]
    assert listed["limit"] == {"limit": 2, "used": 1}
    assert env.client.put(f"/api/mail/accounts/{theirs['id']}", headers=env.as_("khach"),
                          json={"quota_mb": 5}).status_code == 404
    assert env.client.delete(f"/api/mail/accounts/{theirs['id']}", headers=env.as_("khach")).status_code == 404
    changed = env.client.put(f"/api/mail/accounts/{mine['id']}", headers=env.as_("khach"),
                             json={"quota_mb": 50, "password": "another-pass-2"})
    assert changed.status_code == 200 and changed.json()["quota_mb"] == 50
    box = [b for b in env.helper.synced["mailboxes"] if b["domain"] == "khach.vn"][0]
    assert box["quota_mb"] == 50


def test_deleting_a_mailbox_stops_delivery_before_its_mail_goes(env):
    account = _create(env, "khach", "info", "khach.vn").json()
    env.helper.calls.clear()
    assert env.client.delete(f"/api/mail/accounts/{account['id']}", headers=env.as_("khach")).status_code == 200
    assert env.helper.verbs() == ["mail-sync", "mail-delete-box"]
    assert env.helper.calls[1][1] == ["khach", "khach.vn", "info"]
    assert env.helper.synced["mailboxes"] == []


def test_a_suspended_account_keeps_receiving_but_cannot_sign_in(env):
    _create(env, "khach", "info", "khach.vn")
    response = env.client.patch(f"/api/users/{env.user('khach').id}", headers=env.as_("owner"), json={"is_active": False})
    assert response.status_code == 200
    assert env.helper.synced["mailboxes"][0]["active"] is False


# --- single sign-on --------------------------------------------------------------------

def _webmail_verifies(token: str, secret: str, now: int) -> str:
    """The webmail's own check (bnixvn/webmail, _verify_sso_token), restated."""
    body, _, signature = token.partition(".")
    expected = base64.urlsafe_b64encode(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    assert hmac.compare_digest(signature, expected)
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    assert now <= payload["exp"] <= now + 120 and payload["nonce"]
    return payload["email"]


def test_the_webmail_link_opens_the_mailbox_without_its_password(env):
    account = _create(env, "khach", "info", "khach.vn").json()
    response = env.client.post(f"/api/mail/accounts/{account['id']}/webmail", headers=env.as_("khach"))
    assert response.status_code == 200
    url = response.json()["url"]
    assert url.startswith("https://panel.example.vn:2096/api/auth/sso?token=")
    token = url.split("token=", 1)[1]
    assert _webmail_verifies(token, "shared-secret-for-tests", int(time.time())) == "info@khach.vn"


def test_each_link_is_different_and_nobody_opens_another_customers_mailbox(env):
    account = _create(env, "other", "info", "other.vn").json()
    assert env.client.post(f"/api/mail/accounts/{account['id']}/webmail", headers=env.as_("khach")).status_code == 404
    first = env.client.post(f"/api/mail/accounts/{account['id']}/webmail", headers=env.as_("owner")).json()["url"]
    second = env.client.post(f"/api/mail/accounts/{account['id']}/webmail", headers=env.as_("owner")).json()["url"]
    assert first != second


def test_a_token_signed_with_another_key_is_not_one_the_webmail_accepts():
    token = mail.sso_token("a@b.vn", key="one-key")
    with pytest.raises(AssertionError):
        _webmail_verifies(token, "another-key", int(time.time()))


# --- DKIM and DNS ------------------------------------------------------------------------

def test_dkim_dmarc_and_webmail_go_into_the_domains_zone_with_dns_manager_on(env):
    addons.install(addons.DNS)
    dns.create_zone(env.db, "khach.vn", env.user("khach").id)
    _create(env, "khach", "info", "khach.vn")
    fake = env.dns
    assert dns._untxt(fake.rrset("khach.vn", "bpanel._domainkey.khach.vn.", "TXT")[0]) == "v=DKIM1; k=rsa; p=KEYkhachvn"
    assert dns._untxt(fake.rrset("khach.vn", "_dmarc.khach.vn.", "TXT")[0]) == "v=DMARC1; p=none"
    assert fake.rrset("khach.vn", "webmail.khach.vn.", "A") == ["203.0.113.10"]


def test_a_customers_own_dmarc_and_webmail_records_are_left_alone(env):
    addons.install(addons.DNS)
    zone = dns.create_zone(env.db, "khach.vn", env.user("khach").id)
    dns.add_record(zone, {"name": "_dmarc", "type": "TXT", "content": "v=DMARC1; p=reject"}, admin=True)
    dns.add_record(zone, {"name": "webmail", "type": "CNAME", "content": "mail.google.com"}, admin=True)
    _create(env, "khach", "info", "khach.vn")
    assert dns._untxt(env.dns.rrset("khach.vn", "_dmarc.khach.vn.", "TXT")[0]) == "v=DMARC1; p=reject"
    assert env.dns.rrset("khach.vn", "webmail.khach.vn.", "A") is None


def test_the_dkim_record_is_not_rewritten_when_nothing_changed(env):
    addons.install(addons.DNS)
    dns.create_zone(env.db, "khach.vn", env.user("khach").id)
    _create(env, "khach", "info", "khach.vn")
    assert dns.mail_records(env.db, "khach.vn", "KEYkhachvn") == []


def test_without_dns_manager_the_page_lists_the_records_to_add_elsewhere(env):
    _create(env, "khach", "info", "khach.vn")
    overview = env.client.get("/api/mail/overview", headers=env.as_("khach")).json()
    records = {(r["name"], r["type"]): r["value"] for r in overview["mail_domains"][0]["records"]}
    assert records[("khach.vn", "MX")] == "10 panel.example.vn"
    assert records[("bpanel._domainkey.khach.vn", "TXT")] == "v=DKIM1; k=rsa; p=KEYkhachvn"
    assert overview["client"]["imap"] == {"host": "panel.example.vn", "port": 993, "security": "SSL/TLS"}


def test_webmail_on_the_customers_own_domain(env):
    _create(env, "khach", "info", "khach.vn")
    assert env.client.post("/api/mail/domains/other.vn/webmail", headers=env.as_("khach")).status_code == 404
    response = env.client.post("/api/mail/domains/khach.vn/webmail", headers=env.as_("khach"))
    assert response.status_code == 200 and response.json()["url"] == "https://webmail.khach.vn"
    overview = env.client.get("/api/mail/overview", headers=env.as_("khach")).json()
    assert overview["mail_domains"][0]["webmail"] == "https://webmail.khach.vn"


# --- disk space and backups ----------------------------------------------------------------

def test_mail_counts_toward_the_accounts_disk_space(env, monkeypatch):
    seen = []
    monkeypatch.setattr(storage_quota, "path_usage_bytes", lambda path: seen.append(str(path)) or 0)
    storage_quota.user_storage_used_bytes(env.db, env.user("khach"))
    assert "/home/khach/mail" in seen


def test_restoring_a_backup_brings_the_mailboxes_back_under_the_user(env, tmp_path):
    from passlib.hash import sha512_crypt

    secret = "{SHA512-CRYPT}" + sha512_crypt.using(rounds=5000).hash("from-backup-1")
    staged = tmp_path / "stage"
    staged.mkdir()
    restored = mail.restore_accounts(env.db, env.user("khach"), [
        {"local_part": "info", "domain": "khach.vn", "password_hash": secret, "quota_mb": 300},
    ], lambda domain, local: staged)
    env.db.commit()
    assert restored == ["info@khach.vn"]
    row = env.db.query(MailAccount).one()
    assert (row.owner_id, row.password_hash, row.quota_mb) == (env.user("khach").id, secret, 300)
    assert ("mail-import", ["khach", "khach.vn", "info", str(staged)]) in [(c[0], c[1]) for c in env.helper.calls]


def test_a_backup_cannot_take_someone_elses_address(env):
    _create(env, "other", "info", "other.vn")
    with pytest.raises(ValueError):
        mail.restore_accounts(env.db, env.user("khach"), [
            {"local_part": "info", "domain": "other.vn", "password_hash": "{SHA512-CRYPT}$6$x$" + "a" * 86},
        ], lambda domain, local: None)


def test_a_backup_cannot_carry_a_password_in_the_clear(env):
    with pytest.raises(ValueError):
        mail.restore_accounts(env.db, env.user("khach"), [
            {"local_part": "info", "domain": "khach.vn", "password_hash": "plaintext"},
        ], lambda domain, local: None)


# --- the helper's side, read as text --------------------------------------------------------

def _function(name: str) -> str:
    return HELPER.split(f"{name}() {{", 1)[1].split("\n}\n", 1)[0]


def test_only_a_signed_in_mailbox_is_dkim_signed_and_only_as_its_own_domain():
    conf = _function("mail_write_exim_conf")
    assert "dkim_domain = \\${if def:authenticated_id" in conf
    assert "{\\${domain:\\$authenticated_id}}{no}{yes}}" in conf
    assert "condition = \\${if eqi{\\${domain:\\$h_from:}}{\\${domain:\\$authenticated_id}}{no}{yes}}" in conf
    # No open relay: anyone not signed in only reaches mailboxes here.
    assert "require message = Relay not permitted\n          domains = +local_domains" in conf


def test_the_helper_never_follows_a_link_in_a_customers_mail_directory():
    # Its embedded Python has a bare "}" of its own, so up to the next function.
    sync = HELPER.split("mail_sync() {", 1)[1].split("\nmail_box_path() {", 1)[0]
    assert "os.O_NOFOLLOW" in sync and "dir_fd=parent_fd" in sync and "os.fchown(fd" in sync
    restore = _function("mail_import")
    assert restore.index("chmod 2750 {} +") < restore.index('chown "${user}:bpanel" "$work"')


def test_secrets_are_made_unreadable_before_they_are_written():
    webmail = _function("mail_install_webmail")
    for path in ('"${WEBMAIL_ENV}.new"', '"${WEBMAIL_SSO_KEY_FILE}.new"', '"${MAIL_DOVECOT_DIR}/masters.new"'):
        assert webmail.index(f"/dev/null {path}") < webmail.index(f">{path}")
    assert "umask 027" not in HELPER


def test_the_webmails_own_administration_is_not_reachable():
    block = _function("mail_webmail_proxy_block")
    assert "location ^~ /admin { return 404; }" in block
    assert "location ^~ /api/admin/ { return 404; }" in block


def test_the_email_page_opens_the_webmail_tab_on_the_click_itself():
    block = APP_JSX.split("async function openWebmail(account)")[1].split("async function enableWebmailHost")[0]
    assert block.index("window.open('', '_blank')") < block.index("await request(")
    assert "tab.opener = null" in block


# --- the spam filter (operator, 2026-09-29: "xem log chặn mail xem có nhầm không") ---------

def _spam(env, who="owner", **body):
    payload = {"enabled": True, "allow": [], "reject_score": 15, "junk_score": 6, **body}
    return env.client.put("/api/mail/settings/spam", headers=env.as_(who), json=payload)


def test_the_allowlist_is_split_into_addresses_and_domains_for_the_mail_server(env):
    response = _spam(env, allow=["Friend@Example.com", "partner.vn", "friend@example.com", ""], reject_score=20, junk_score=8)
    assert response.status_code == 200
    assert response.json()["allow"] == ["friend@example.com", "partner.vn"]
    assert env.helper.spam == {"enabled": True, "senders": ["friend@example.com"], "domains": ["partner.vn"],
                               "reject_score": 20.0, "junk_score": 8.0}


@pytest.mark.parametrize("body", [
    {"allow": ["not an address@"]},
    {"allow": ["bad domain"]},
    {"reject_score": 5, "junk_score": 6},
    {"reject_score": 5, "junk_score": 5},
])
def test_spam_settings_the_mail_server_would_refuse_are_refused_first(env, body):
    assert _spam(env, **body).status_code == 400
    assert env.helper.spam is None


def test_only_an_administrator_sets_the_spam_filter_or_the_smarthost(env):
    assert _spam(env, who="khach").status_code == 403
    assert env.client.get("/api/mail/settings", headers=env.as_("khach")).status_code == 403
    assert env.client.put("/api/mail/settings/relay", headers=env.as_("khach"), json={"enabled": False}).status_code == 403
    assert env.client.post("/api/mail/relay/test", headers=env.as_("khach"), json={"to": "a@b.vn"}).status_code == 403


ROWS = [
    {"unix_time": 1700000300, "action": "reject", "score": 16.2, "required_score": 15, "sender_smtp": "x@spam.test",
     "sender_mime": "x@spam.test", "rcpt_smtp": ["info@khach.vn", "info@other.vn"], "subject": "Win a prize",
     "ip": "198.51.100.7", "size": 2048,
     "symbols": {"RBL_SPAMHAUS": {"score": 4.0, "options": ["zen"]}, "BAYES_SPAM": {"score": 5.1}, "ARC_NA": {"score": 0}}},
    {"unix_time": 1700000200, "action": "add header", "score": 7.0, "required_score": 15, "sender_smtp": "news@shop.test",
     "rcpt_smtp": ["sales@khach.vn"], "subject": "Sale", "symbols": {}},
    {"unix_time": 1700000100, "action": "no action", "score": -99.0, "required_score": 15, "sender_smtp": "friend@example.com",
     "rcpt_smtp": ["info@other.vn"], "subject": "Hi", "symbols": {"BPANEL_ALLOW_SENDER": {"score": -50}}},
]


def test_a_customer_sees_the_log_of_mail_to_their_own_domains_only(env, monkeypatch):
    monkeypatch.setattr(mail, "_controller", lambda path: {"rows": ROWS})
    blocked = env.client.get("/api/mail/spam/log?view=blocked", headers=env.as_("khach")).json()
    assert [row["subject"] for row in blocked["rows"]] == ["Win a prize"]
    # The other customer's recipient on the same message is not shown.
    assert blocked["rows"][0]["to"] == ["info@khach.vn"]
    reasons = blocked["rows"][0]["reasons"]
    assert [reason["name"] for reason in reasons] == ["BAYES_SPAM", "RBL_SPAMHAUS"]
    everything = env.client.get("/api/mail/spam/log?view=all", headers=env.as_("khach")).json()
    assert [row["subject"] for row in everything["rows"]] == ["Win a prize", "Sale"]


def test_an_administrator_sees_every_decision_and_what_the_allowlist_let_through(env, monkeypatch):
    monkeypatch.setattr(mail, "_controller", lambda path: {"rows": ROWS})
    rows = env.client.get("/api/mail/spam/log?view=all", headers=env.as_("owner")).json()["rows"]
    assert [row["subject"] for row in rows] == ["Win a prize", "Sale", "Hi"]
    assert rows[0]["to"] == ["info@khach.vn", "info@other.vn"]
    assert rows[2]["allowed"] is True and rows[0]["allowed"] is False
    junk = env.client.get("/api/mail/spam/log?view=spam", headers=env.as_("owner")).json()["rows"]
    assert [row["subject"] for row in junk] == ["Sale"]


def test_with_the_filter_off_there_is_no_log_to_ask_for(env, monkeypatch):
    _spam(env, enabled=False)
    monkeypatch.setattr(mail, "_controller", lambda path: pytest.fail("asked a stopped Rspamd"))
    assert env.client.get("/api/mail/spam/log", headers=env.as_("owner")).json() == {"enabled": False, "rows": []}


# --- the smarthost (operator: "Thêm config relay smarthost cho exim -> Custom spf/dns mẫu") ---

def _relay(env, **body):
    payload = {"enabled": True, "host": "mail.smtp2go.com", "port": 587, "security": "starttls",
               "username": "bnix", "password": "s3cret^:;pw", "spf_include": "include:spf.smtp2go.com", **body}
    return env.client.put("/api/mail/settings/relay", headers=env.as_("owner"), json=payload)


def test_the_smarthost_password_reaches_the_mail_server_and_nowhere_else(env):
    response = _relay(env)
    assert response.status_code == 200
    assert env.helper.relay["password"] == "s3cret^:;pw"
    # Its command line is not logged, the settings file holds it encrypted,
    # and no answer carries it back.
    assert "mail-relay-set" in env.helper.sensitive
    assert "s3cret" not in json.dumps(env.stored)
    assert "s3cret" not in response.text
    settings = env.client.get("/api/mail/settings", headers=env.as_("owner")).json()
    assert settings["relay"]["has_password"] is True and "password" not in settings["relay"]


def test_an_empty_password_keeps_the_saved_one(env):
    _relay(env)
    assert _relay(env, password=None, port=2525).status_code == 200
    assert env.helper.relay["password"] == "s3cret^:;pw" and env.helper.relay["port"] == 2525


def test_turning_the_smarthost_off_keeps_its_settings_for_next_time(env):
    _relay(env)
    assert _relay(env, enabled=False, password=None).status_code == 200
    assert env.helper.relay["enabled"] is False
    saved = env.client.get("/api/mail/settings", headers=env.as_("owner")).json()["relay"]
    assert (saved["host"], saved["username"], saved["has_password"]) == ("mail.smtp2go.com", "bnix", True)


@pytest.mark.parametrize("body", [
    {"host": "203.0.113.5"},
    {"host": "not a host"},
    {"security": "none"},
    {"password": " padded"},
    {"username": ""},
    {"spf_include": "v=spf1 include:x.com ~all"},
    {"spf_include": "include:x.com; rm -rf /"},
])
def test_smarthost_settings_the_mail_server_would_refuse_are_refused_first(env, body):
    assert _relay(env, **body).status_code == 400
    assert env.helper.relay is None


def test_the_smarthosts_spf_goes_into_every_zone_still_on_the_old_record(env):
    addons.install(addons.DNS)
    dns.create_zone(env.db, "khach.vn", env.user("khach").id)
    zone = dns.create_zone(env.db, "other.vn", env.user("other").id)
    # This customer wrote their own SPF; it stays theirs.
    dns.delete_record(zone, {"name": "@", "type": "TXT", "content": "v=spf1 a mx ~all"}, admin=True)
    dns.add_record(zone, {"name": "@", "type": "TXT", "content": "v=spf1 include:_spf.google.com ~all"}, admin=True)
    response = _relay(env)
    assert response.json()["spf"] == "v=spf1 a mx include:spf.smtp2go.com ~all"
    assert response.json()["zones_updated"] == ["khach.vn"]
    assert [dns._untxt(c) for c in env.dns.rrset("khach.vn", "khach.vn.", "TXT")] == ["v=spf1 a mx include:spf.smtp2go.com ~all"]
    assert [dns._untxt(c) for c in env.dns.rrset("other.vn", "other.vn.", "TXT")] == ["v=spf1 include:_spf.google.com ~all"]
    # A zone made from now on has it too.
    dns.create_zone(env.db, "admin.vn", env.user("owner").id)
    assert [dns._untxt(c) for c in env.dns.rrset("admin.vn", "admin.vn.", "TXT")] == ["v=spf1 a mx include:spf.smtp2go.com ~all"]
    # And back when the smarthost goes.
    assert _relay(env, enabled=False, password=None).json()["zones_updated"] == ["admin.vn", "khach.vn"]
    assert [dns._untxt(c) for c in env.dns.rrset("khach.vn", "khach.vn.", "TXT")] == ["v=spf1 a mx ~all"]


def test_the_mail_domains_list_shows_the_spf_with_the_smarthost(env):
    _relay(env)
    _create(env, "khach", "info", "khach.vn")
    overview = env.client.get("/api/mail/overview", headers=env.as_("khach")).json()
    records = {(r["name"], r["type"]): r["value"] for r in overview["mail_domains"][0]["records"]}
    assert records[("khach.vn", "TXT")] == "v=spf1 a mx include:spf.smtp2go.com ~all"


def test_the_test_message_reports_what_exim_logged(env):
    response = env.client.post("/api/mail/relay/test", headers=env.as_("owner"), json={"to": "me@gmail.com"})
    assert response.status_code == 200
    assert "=> me@gmail.com R=bpanel_smarthost" in response.json()["lines"][0]
    assert env.client.post("/api/mail/relay/test", headers=env.as_("owner"), json={"to": "nobody"}).status_code == 400


def test_a_fresh_install_gets_the_saved_spam_filter_and_smarthost(env):
    _spam(env, allow=["partner.vn"], reject_score=12, junk_score=5)
    _relay(env)
    env.helper.spam = env.helper.relay = None
    mail.install()
    assert env.helper.spam["domains"] == ["partner.vn"] and env.helper.spam["reject_score"] == 12
    assert env.helper.relay["host"] == "mail.smtp2go.com" and env.helper.relay["password"] == "s3cret^:;pw"


# --- the helper's side of it, read as text ---------------------------------------------------------

def _rspamd_conf() -> str:
    # Rspamd's own config blocks end in a bare "}", so up to the next function.
    return HELPER.split("mail_write_rspamd_conf() {", 1)[1].split("mail_rspamd_answers() {", 1)[0]


def test_the_rspamd_controller_asks_everyone_for_its_key():
    conf = _rspamd_conf()
    # override.d, so the stock secure_ip list (loopback without a password) is replaced, not merged.
    assert '"$MAIL_RSPAMD_OVERRIDE/worker-controller.inc"' in conf and "secure_ip = [];" in conf
    assert 'bind_socket = "127.0.0.1:11334";' in conf and 'bind_socket = "127.0.0.1:11333";' in conf


def test_the_allowlist_is_a_score_so_allowed_mail_stays_in_the_log():
    conf = _rspamd_conf()
    assert conf.count("score = -50.0;") == 4
    assert 'action = "accept"' not in conf and "prefilter = true" not in conf


def test_the_smarthost_only_gets_the_password_over_verified_tls():
    relay = HELPER.split("mail_relay_set() {", 1)[1].split("\nmail_relay_test() {", 1)[0]
    for line in ('"  hosts_require_auth = *"', '"  hosts_require_tls = *"', '"  tls_verify_hosts = *"'):
        assert line in relay
    # A list split before expansion: ";" as separator, since ":" is inside it.
    assert '"  client_send = <; ^%s^%s"' in relay and '"  client_send = <; ; %s ; %s"' in relay
    assert "base64d" in relay
