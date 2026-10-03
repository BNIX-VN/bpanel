"""The reseller role: customers, a share of the server, own packages.

Decided with the operator (2026-10-03), as in OPanel: a reseller gets a total
share from the admin (customers, websites, disk, mailboxes, applications) and
divides it between its own account and its customers; it manages its
customers, logs in as them, keeps packages of its own and hosts sites of its
own. Nothing server-wide.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import auth as auth_api
from app.core.database import Base, get_db
from app.core.security import hash_password
from app.models.entities import DatabaseAccount, User, UserPackage, Website
from app.services import site_users

PASSWORD = "PasswordLongEnough1"


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(User(username="root_admin", email="a@example.com", role="admin", is_active=True,
                hashed_password=hash_password(PASSWORD)))
    db.add(User(username="direct", email="d@example.com", role="end_user", is_active=True,
                website_limit=5, hashed_password=hash_password(PASSWORD)))
    db.commit()

    def get_test_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    from app.main import app

    app.dependency_overrides[get_db] = get_test_db
    monkeypatch.setattr(auth_api, "_enforce_rate_limit", lambda key: None)
    # Each of these waits out a Redis connection that is not there.
    monkeypatch.setattr(auth_api, "_record_success", lambda *a, **k: None)
    monkeypatch.setattr(auth_api, "_record_failure", lambda *a, **k: None)
    # No Linux accounts in a test.
    monkeypatch.setattr(site_users, "ensure_panel_user", lambda *a, **k: "")
    monkeypatch.setattr(site_users, "delete_panel_user", lambda *a, **k: None)
    monkeypatch.setattr(site_users, "set_panel_user_password", lambda *a, **k: None)
    monkeypatch.setattr(site_users, "retire_shared_login_password", lambda *a, **k: None)
    client = TestClient(app)
    try:
        yield db, client
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()


def _login(client, name):
    client.cookies.clear()
    response = client.post("/api/auth/login", data={"username": name, "password": PASSWORD})
    assert response.status_code == 200, response.text


def _call(client, method, path, **kwargs):
    headers = {"X-CSRF-Token": client.cookies.get("bpanel_csrf", "")}
    return client.request(method, path, headers=headers, **kwargs)


def _user(db, name):
    db.expire_all()
    return db.query(User).filter(User.username == name).one()


ACCOUNT = {"email": "x@example.com", "password": PASSWORD}
OWN = {"website_limit": 1, "storage_limit_mb": 1000, "mail_accounts_limit": 2}
POOL = {"pool_user_limit": 2, "pool_website_limit": 5, "pool_storage_limit_mb": 3000,
        "pool_mail_accounts_limit": 10, "pool_app_limit": 0}
SMALL = {"website_limit": 2, "storage_limit_mb": 1000, "mail_accounts_limit": 4}


def _reseller(client):
    _login(client, "root_admin")
    created = _call(client, "POST", "/api/users", json={"username": "shop", "role": "reseller", **ACCOUNT, **OWN, **POOL})
    assert created.status_code == 200, created.text
    assert created.json()["role"] == "reseller" and created.json()["pool_website_limit"] == 5
    _login(client, "shop")


def test_a_reseller_creates_customers_inside_its_share(env):
    db, client = env
    _reseller(client)
    made = _call(client, "POST", "/api/users", json={"username": "cust1", "role": "admin", **ACCOUNT, **SMALL})
    assert made.status_code == 200, made.text
    # Always its own end user, whatever was asked for.
    assert made.json()["role"] == "end_user" and made.json()["reseller_id"] == _user(db, "shop").id

    # websites: own 1 + 2 + 3 = 6 > 5.
    over = _call(client, "POST", "/api/users", json={"username": "cust2", **ACCOUNT, **{**SMALL, "website_limit": 3}})
    assert over.status_code == 400 and "websites" in over.json()["detail"]
    # storage: 1000 + 1000 + 1001 > 3000.
    big = _call(client, "POST", "/api/users", json={"username": "cust2", **ACCOUNT, **{**SMALL, "storage_limit_mb": 1001}})
    assert big.status_code == 400 and "storage" in big.json()["detail"]

    assert _call(client, "POST", "/api/users", json={"username": "cust2", **ACCOUNT, **{**SMALL, "website_limit": 1,
                                                                                       "storage_limit_mb": 500}}).status_code == 200
    third = _call(client, "POST", "/api/users", json={"username": "cust3", **ACCOUNT, "website_limit": 0,
                                                     "storage_limit_mb": 0, "mail_accounts_limit": 0})
    assert third.status_code == 400 and "customers" in third.json()["detail"]

    pool = _call(client, "GET", "/api/users/pool").json()
    assert pool["customers"] == 2 and pool["allocated_website_limit"] == 4 and pool["pool_website_limit"] == 5


def test_a_reseller_sees_and_manages_its_customers_only(env):
    db, client = env
    _reseller(client)
    cust = _call(client, "POST", "/api/users", json={"username": "cust1", **ACCOUNT, **SMALL}).json()
    direct = _user(db, "direct")

    listed = [row["username"] for row in _call(client, "GET", "/api/users").json()]
    assert listed == ["cust1"]
    assert set(_call(client, "GET", "/api/users/storage-usage").json()) == {str(cust["id"])}
    assert _call(client, "PATCH", f"/api/users/{direct.id}", json={"is_active": False}).status_code == 404
    assert _call(client, "DELETE", f"/api/users/{direct.id}").status_code == 404
    assert _call(client, "POST", f"/api/users/{direct.id}/password", json={"password": PASSWORD + "x"}).status_code == 404
    assert _call(client, "POST", f"/api/users/{direct.id}/suspend").status_code == 404

    # Its customers: limits within the share, suspend, but no roles.
    assert _call(client, "PATCH", f"/api/users/{cust['id']}", json={"website_limit": 4}).status_code == 200
    assert _call(client, "PATCH", f"/api/users/{cust['id']}", json={"website_limit": 5}).status_code == 400
    assert _call(client, "PATCH", f"/api/users/{cust['id']}", json={"role": "reseller"}).status_code == 403
    assert _call(client, "POST", f"/api/users/{cust['id']}/suspend").status_code == 200
    assert _user(db, "cust1").is_active is False
    # Its own limits are the admin's to set.
    assert _call(client, "PATCH", f"/api/users/{_user(db, 'shop').id}", json={"website_limit": 9}).status_code == 403
    # Nothing server-wide.
    assert _call(client, "GET", "/api/users/audit/log").status_code == 403
    assert _call(client, "DELETE", f"/api/users/{cust['id']}").status_code == 200


def test_a_reseller_logs_in_as_a_customer_and_comes_back(env):
    db, client = env
    _reseller(client)
    cust = _call(client, "POST", "/api/users", json={"username": "cust1", **ACCOUNT, **SMALL}).json()
    assert _call(client, "POST", f"/api/auth/impersonate/{_user(db, 'direct').id}").status_code == 404
    assert _call(client, "POST", f"/api/auth/impersonate/{_user(db, 'root_admin').id}").status_code == 404
    assert _call(client, "POST", f"/api/auth/impersonate/{cust['id']}").status_code == 200
    me = client.get("/api/auth/session").json()["user"]
    assert me["username"] == "cust1" and me["impersonator"] == "shop"
    assert _call(client, "POST", "/api/auth/impersonation/return").status_code == 200
    assert client.get("/api/auth/session").json()["user"]["username"] == "shop"


def test_a_reseller_keeps_packages_of_its_own(env):
    db, client = env
    _login(client, "root_admin")
    assert _call(client, "POST", "/api/packages", json={"name": "Basic"}).status_code == 200
    _reseller(client)
    # The same name is free per owner.
    made = _call(client, "POST", "/api/packages", json={"name": "Basic", "website_limit": 2, "storage_limit_mb": 500,
                                                       "mail_accounts_limit": 4, "node_apps_limit": 1})
    assert made.status_code == 200, made.text
    assert made.json()["owner_id"] == _user(db, "shop").id
    assert _call(client, "POST", "/api/packages", json={"name": "Basic"}).status_code == 409
    # No terminal to hand out: the reseller has none itself.
    assert _call(client, "POST", "/api/packages", json={"name": "Shell", "terminal_enabled": True}).status_code == 400
    assert [p["name"] for p in _call(client, "GET", "/api/packages").json()] == ["Basic"]
    admin_package = db.query(UserPackage).filter(UserPackage.owner_id.is_(None)).one()
    assert _call(client, "PATCH", f"/api/packages/{admin_package.id}", json={"name": "taken"}).status_code == 404
    assert _call(client, "DELETE", f"/api/packages/{admin_package.id}").status_code == 404

    # A customer on the reseller's package; the admin's package is not its to give.
    assert _call(client, "POST", "/api/users", json={"username": "cust1", **ACCOUNT,
                                                     "package_id": admin_package.id}).status_code == 404
    cust = _call(client, "POST", "/api/users", json={"username": "cust1", **ACCOUNT, "package_id": made.json()["id"]})
    assert cust.status_code == 200, cust.text
    assert cust.json()["website_limit"] == 2
    # Growing the package grows every customer on it, so it must still fit.
    assert _call(client, "PATCH", f"/api/packages/{made.json()['id']}", json={"website_limit": 5}).status_code == 400
    assert _call(client, "PATCH", f"/api/packages/{made.json()['id']}", json={"website_limit": 4}).status_code == 200
    assert _user(db, "cust1").website_limit == 4

    _login(client, "root_admin")
    assert [p["name"] for p in _call(client, "GET", "/api/packages").json()] == ["Basic"]
    assert _call(client, "GET", "/api/packages").json()[0]["owner_id"] is None


def test_the_admin_keeps_the_shares_consistent(env):
    db, client = env
    _reseller(client)
    cust = _call(client, "POST", "/api/users", json={"username": "cust1", **ACCOUNT, **SMALL}).json()
    _login(client, "root_admin")
    shop = _user(db, "shop")
    # A share smaller than what is already handed out.
    assert _call(client, "PATCH", f"/api/users/{shop.id}", json={"pool_website_limit": 2}).status_code == 400
    assert _call(client, "PATCH", f"/api/users/{shop.id}", json={"pool_website_limit": 3}).status_code == 200
    # A reseller with customers keeps its role and its account.
    assert _call(client, "PATCH", f"/api/users/{shop.id}", json={"role": "end_user"}).status_code == 400
    assert _call(client, "DELETE", f"/api/users/{shop.id}").status_code == 400
    # Moving the admin's own customer under the reseller must fit its share.
    direct = _user(db, "direct")
    moved = _call(client, "PATCH", f"/api/users/{direct.id}", json={"reseller_id": shop.id})
    assert moved.status_code == 400  # direct has 5 websites; 1 + 2 + 5 > 3
    assert _call(client, "PATCH", f"/api/users/{cust['id']}", json={"reseller_id": 0}).json()["reseller_id"] is None
    assert _call(client, "GET", f"/api/users/{shop.id}/pool").json()["customers"] == 0
    assert _call(client, "PATCH", f"/api/users/{shop.id}", json={"role": "end_user"}).status_code == 200
    assert _user(db, "shop").pool_website_limit == 0


def test_an_end_user_has_no_reseller_powers(env):
    db, client = env
    _login(client, "direct")
    assert _call(client, "GET", "/api/users").status_code == 403
    assert _call(client, "POST", "/api/users", json={"username": "sneaky", **ACCOUNT}).status_code == 403
    assert _call(client, "GET", "/api/packages").status_code == 403
    assert _call(client, "GET", "/api/users/pool").status_code == 403
    assert _call(client, "POST", f"/api/auth/impersonate/{_user(db, 'root_admin').id}").status_code == 403


def _site(db, owner, domain):
    site = Website(domain=domain, owner_id=owner.id, root_path=f"/home/{owner.username}/{domain}",
                   document_root="public_html", linux_user=owner.username, php_version="8.4",
                   app_type="php", status="active")
    db.add(site)
    db.flush()
    db.add(DatabaseAccount(owner_id=owner.id, website_id=site.id, db_name=domain.split(".")[0],
                           db_user=domain.split(".")[0], db_password="x"))
    db.commit()
    return site


def test_a_reseller_sees_its_own_and_its_customers_sites_and_nobody_elses(env, monkeypatch):
    from app.api import websites as websites_api

    db, client = env
    _reseller(client)
    _call(client, "POST", "/api/users", json={"username": "cust1", **ACCOUNT, **SMALL})
    _site(db, _user(db, "shop"), "shopsite.com")
    theirs = _site(db, _user(db, "cust1"), "custsite.com")
    other = _site(db, _user(db, "direct"), "othersite.com")
    monkeypatch.setattr(websites_api.nginx, "read_site_log",
                        lambda domain, kind, lines: {"domain": domain, "kind": kind, "path": "/x", "lines": lines})

    domains = sorted(w["domain"] for w in _call(client, "GET", "/api/websites").json())
    assert domains == ["custsite.com", "shopsite.com"]
    names = sorted(d["db_name"] for d in _call(client, "GET", "/api/databases").json())
    assert names == ["custsite", "shopsite"]
    assert _call(client, "GET", f"/api/websites/{theirs.id}/logs").status_code == 200
    assert _call(client, "GET", f"/api/websites/{other.id}/logs").status_code == 403
    # Server-wide settings stay the admin's.
    assert _call(client, "GET", f"/api/websites/{theirs.id}/nginx-config").status_code == 403

    # The customer still sees only its own.
    _login(client, "cust1")
    assert [w["domain"] for w in _call(client, "GET", "/api/websites").json()] == ["custsite.com"]


def test_a_reseller_reaches_its_customers_mail_and_zones_only(env):
    """Mail and DNS ask the same rule set, below the API (the addons need not
    be installed for the services to answer)."""
    from app.models.entities import DnsZone, MailAccount, MailDomain
    from app.services import dns, mail

    db, client = env
    _reseller(client)
    _call(client, "POST", "/api/users", json={"username": "cust1", **ACCOUNT, **SMALL})
    shop, cust, direct = _user(db, "shop"), _user(db, "cust1"), _user(db, "direct")
    rows = {}
    for owner, name in ((shop, "shop.com"), (cust, "cust.com"), (direct, "direct.com")):
        rows[name] = MailDomain(domain=name, owner_id=owner.id)
        db.add(rows[name])
        db.add(DnsZone(name=name, owner_id=owner.id))
    db.flush()
    box = MailAccount(owner_id=direct.id, domain="direct.com", local_part="info", password_hash="x")
    theirs = MailAccount(owner_id=cust.id, domain="cust.com", local_part="info", password_hash="x")
    db.add_all([box, theirs])
    db.commit()

    assert mail.get_domain(db, shop, rows["cust.com"].id).domain == "cust.com"
    assert mail.get_account(db, shop, theirs.id).domain == "cust.com"
    with pytest.raises(mail.MailError) as refused:
        mail.get_domain(db, shop, rows["direct.com"].id)
    assert refused.value.status == 404
    with pytest.raises(mail.MailError):
        mail.get_account(db, shop, box.id)
    # The customer itself: its own only, not its reseller's.
    with pytest.raises(mail.MailError):
        mail.get_domain(db, cust, rows["shop.com"].id)

    assert sorted(zone["name"] for zone in dns.list_zones(db, shop)) == ["cust.com", "shop.com"]
    assert dns.may_edit(db, shop, "cust.com") == "cust.com"
    with pytest.raises(dns.DnsError):
        dns.may_edit(db, shop, "direct.com")
    assert [zone["name"] for zone in dns.list_zones(db, cust)] == ["cust.com"]
