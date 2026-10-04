"""A suspended site stays suspended until it is unsuspended.

The update's per-site refresh rebuilds every vhost through
_rewrite_website_vhost, which wrote the full vhost whatever the site's status:
every update that refreshed sites gave every suspended site its PHP back.
Suspension also never locked the Linux user (the helper had no
panel-user-lock), so the customer kept SFTP. And unsuspending did not bring the
site's PHP pool back, which the update's sweep of unused pools removes from a
suspended site: 502 after unsuspend. Found on a 1.2.0 -> 1.3.0 update test,
2026-10-04.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import auth as auth_api
from app.api import websites as websites_api
from app.core.database import Base, get_db
from app.core.security import hash_password
from app.models.entities import User, Website
from app.services import nginx, site_users

PASSWORD = "Correct-Horse-Battery-9"
UPDATE_SH = Path(__file__).resolve().parents[3] / "installer" / "update.sh"


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(User(username="root_admin", email="a@example.com", role="admin", is_active=True,
                hashed_password=hash_password(PASSWORD)))
    customer = User(username="shopper", email="s@example.com", role="end_user", is_active=True,
                    hashed_password=hash_password(PASSWORD))
    db.add(customer)
    db.commit()
    db.add(Website(domain="shop.test", owner_id=customer.id, root_path="/home/shopper/shop.test",
                   document_root="public_html", linux_user="shopper", php_version="8.4",
                   app_type="php", status="active", waf_enabled=True))
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
    monkeypatch.setattr(auth_api, "_record_success", lambda *a, **k: None)
    monkeypatch.setattr(auth_api, "_record_failure", lambda *a, **k: None)

    # Record what reaches nginx and the helper instead of doing it.
    events = []
    monkeypatch.setattr(nginx, "delete_wordpress_vhost", lambda domain: events.append(("delete", domain)))
    monkeypatch.setattr(nginx, "write_vhost", lambda domain, root, **kw: events.append(("write", domain, kw)) or "")
    monkeypatch.setattr(nginx, "rewrite_vhost", lambda domain, root, **kw: events.append(("full", domain, kw)) or "")
    monkeypatch.setattr(site_users.shell, "privileged",
                        lambda name, **kw: events.append(("helper", name, tuple(kw.get("helper_args") or ()))))
    monkeypatch.setattr(site_users, "ensure_site_runtime",
                        lambda domain, root, php, user: events.append(("runtime", domain, php)) or user)
    client = TestClient(app)
    try:
        yield db, client, events
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()


def _login(client):
    client.cookies.clear()
    assert client.post("/api/auth/login", data={"username": "root_admin", "password": PASSWORD}).status_code == 200


def _call(client, method, path):
    return client.request(method, path, headers={"X-CSRF-Token": client.cookies.get("bpanel_csrf", "")})


def _site(db):
    db.expire_all()
    return db.query(Website).filter(Website.domain == "shop.test").one()


def test_suspending_writes_the_suspended_vhost_and_locks_the_user(env):
    db, client, events = env
    _login(client)
    customer = db.query(User).filter(User.username == "shopper").one()
    assert _call(client, "POST", f"/api/users/{customer.id}/suspend").status_code == 200

    writes = [e for e in events if e[0] == "write" and e[1] == "shop.test"]
    assert writes and writes[-1][2]["app_type"] == "static" and writes[-1][2]["custom_directives"] == "# SUSPENDED"
    assert ("helper", "panel-user-lock", ("shopper",)) in events


def test_a_rewrite_of_a_suspended_site_keeps_it_suspended(env):
    """What the update's refresh does to every site, and an SSL renewal or an
    alias change to one."""
    db, _client, events = env
    site = _site(db)
    site.status = "suspended"
    db.commit()

    websites_api._rewrite_website_vhost(site)

    assert not [e for e in events if e[0] == "full"], "a suspended site got its full vhost back"
    writes = [e for e in events if e[0] == "write"]
    assert writes and writes[-1][2]["app_type"] == "static" and writes[-1][2]["preserve_existing_ssl"] is False


def test_unsuspending_brings_the_full_vhost_back(env):
    db, client, events = env
    _login(client)
    customer = db.query(User).filter(User.username == "shopper").one()
    assert _call(client, "POST", f"/api/users/{customer.id}/suspend").status_code == 200
    events.clear()
    assert _call(client, "POST", f"/api/users/{customer.id}/unsuspend").status_code == 200

    assert _site(db).status == "active"
    full = [e for e in events if e[0] == "full" and e[1] == "shop.test"]
    assert full and full[-1][2]["app_type"] == "php" and full[-1][2]["waf_enabled"] is True
    # The PHP pool first: the update's sweep of unused pools removes a
    # suspended site's, and the old unsuspend then answered 502.
    assert events.index(("runtime", "shop.test", "8.4")) < events.index(full[-1])
    assert ("helper", "panel-user-unlock", ("shopper",)) in events
    # And a later rewrite (the next update) leaves it active.
    events.clear()
    websites_api._rewrite_website_vhost(_site(db))
    assert [e for e in events if e[0] == "full"]


def test_the_update_locks_users_suspended_before_the_lock_worked():
    text = UPDATE_SH.read_text(encoding="utf-8")
    refresh = text[text.index('log "Refreshing managed site configuration"'):]
    refresh = refresh[:refresh.index("step_mark_done")]
    rewrite = refresh.index("websites_api._rewrite_website_vhost(website)")
    lock = refresh.index("site_users.lock_linux_user(website.linux_user)")
    assert rewrite < lock
    assert 'if website.status == "suspended" and website.linux_user:' in refresh[rewrite:lock]
