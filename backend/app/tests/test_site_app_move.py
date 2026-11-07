"""Moving an application to another account (operator, 2026-11-07), and the
Rename dialog drawn on every page, not only on Email's."""
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import site_apps as api
from app.api import websites as websites_api
from app.core.database import Base
from app.core.security import hash_password
from app.models.entities import DatabaseAccount, SiteApp, User, Website

PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_JSX = (PROJECT_ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    people = {}
    for name, role, apps in (("admin", "admin", 0), ("alice", "end_user", 2), ("bob", "end_user", 0)):
        people[name] = User(username=name, email=f"{name}@example.test", role=role, is_active=True,
                            hashed_password=hash_password("pw-" + name), token_version=0, node_apps_limit=apps)
        db.add(people[name])
    db.commit()
    app = SiteApp(owner_id=people["admin"].id, name="shop", kind="node", port=21001,
                  env="DATABASE_URL=mysql://admin_shop:x@localhost/admin_shop")
    db.add(app)
    db.add(DatabaseAccount(owner_id=people["admin"].id, db_name="admin_shop", db_user="admin_shop", db_password="x"))
    db.add(DatabaseAccount(owner_id=people["admin"].id, db_name="admin_other", db_user="admin_other", db_password="x"))
    db.commit()
    moved = []

    def fake_move(target_app, owner, check_only=False):
        moved.append((target_app.name, owner.username))
        target_app.owner = owner
        target_app.owner_id = owner.id

    monkeypatch.setattr(api.site_apps, "move_to_owner", fake_move)
    monkeypatch.setattr(websites_api.file_manager, "read_text_file",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no .env")))
    monkeypatch.setattr(api, "log_action", lambda *a, **k: None)
    yield db, people, app, moved
    db.close()


def _move(env, who, owner):
    db, people, app, _ = env
    return api.move_site_app(app.id, api.SiteAppOwnerChange(owner_id=people[owner].id), db=db,
                             current_user=people[who])


def test_an_administrator_hands_an_app_and_its_database_to_a_customer(env):
    db, people, app, moved = env
    _move(env, "admin", "alice")
    assert moved == [("shop", "alice")]
    db.expire_all()
    assert db.get(SiteApp, app.id).owner_id == people["alice"].id
    owners = {d.db_name: d.owner_id for d in db.query(DatabaseAccount).all()}
    assert owners == {"admin_shop": people["alice"].id, "admin_other": people["admin"].id}, \
        "only the database the app names goes with it"


def test_a_customer_cannot_move_one(env):
    with pytest.raises(HTTPException) as caught:
        _move(env, "alice", "bob")
    assert caught.value.status_code == 403


def test_not_to_its_own_owner(env):
    with pytest.raises(HTTPException) as caught:
        _move(env, "admin", "admin")
    assert caught.value.status_code == 400


def test_not_to_an_account_with_no_room_for_apps(env):
    with pytest.raises(HTTPException) as caught:
        _move(env, "admin", "bob")
    assert caught.value.status_code == 409 and "not enabled" in caught.value.detail
    assert env[3] == [], "nothing moved"


def test_not_while_it_serves_a_website_the_new_owner_does_not_own(env):
    db, people, app, moved = env
    db.add(Website(domain="shop.test", owner_id=people["admin"].id, root_path="/home/admin/shop.test",
                   linux_user="admin", app_id=app.id))
    db.commit()
    with pytest.raises(HTTPException) as caught:
        _move(env, "admin", "alice")
    assert caught.value.status_code == 409 and "shop.test" in caught.value.detail
    assert moved == []


def test_the_page_offers_it_to_whoever_manages_accounts():
    assert "canManageUsers && <button" in APP_JSX and "setSiteAppMove({ app, owner_id: '' })" in APP_JSX
    assert "`/site-apps/${app.id}/owner`" in APP_JSX


def test_the_dialogs_are_drawn_on_every_page():
    # Inside renderMailModals the Rename dialog only ever appeared on the Email
    # page: the Domains tab's button did nothing (2026-11-07).
    mail_modals = APP_JSX[APP_JSX.index("function renderMailModals() {"):]
    mail_modals = mail_modals[:mail_modals.index("\n  }\n")]
    assert "renameSite &&" not in mail_modals
    shell = APP_JSX[APP_JSX.index('return <main className="app-shell">'):]
    assert "{renameSite && <div" in shell and "{siteAppMove && <div" in shell


def test_a_rename_rewrites_every_form_the_old_address_is_stored_in():
    # Elementor and the block editor keep links JSON-escaped (https:\/\/old);
    # only //old was replaced, and 182 escaped links stayed on legiang360.com.
    from app.services import wordpress
    forms = dict(wordpress._address_forms("legiang360.com", "cms.legiang360.com"))
    assert forms["//legiang360.com"] == "//cms.legiang360.com"
    assert forms[r"\/\/legiang360.com"] == r"\/\/cms.legiang360.com"
    assert forms["%2F%2Flegiang360.com"] == "%2F%2Fcms.legiang360.com"
