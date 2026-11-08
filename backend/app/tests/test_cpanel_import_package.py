"""A cPanel import puts the account on the package of its cPanel plan, made
from the plan's limits when the panel has none of that name, and switches its
object cache on (operator, 2026-11-08, as SNPanel v2.5.1)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.entities import User, UserPackage
from app.services import cpanel_import, php_isolation, redis_accounts


@pytest.mark.parametrize("plan, expected", [
    (" Gold  Plan\t", "Gold Plan"), ("default", None), ("Undefined", None), ("", None), ("x" * 150, "x" * 100),
])
def test_package_name(plan, expected):
    assert cpanel_import.package_name(plan) == expected


def test_plan_limits_follow_the_plan():
    values, notes = cpanel_import.plan_limits(
        {"MAXADDON": "3", "MAXSQL": "unlimited", "MAXPOP": "unlimited", "MAXPARK": "2", "BWLIMIT": "1000"}, "2048")
    assert values == {"website_limit": 4, "storage_limit_mb": 2048, "database_limit": 0, "alias_limit": 2,
                      "mail_accounts_limit": 1000}, "mailboxes: 0 allows none here, so unlimited is the most"
    assert "BWLIMIT=1000" in notes[0]
    values, _ = cpanel_import.plan_limits({"MAXADDON": "unlimited", "DISK_BLOCK_LIMIT": "5242880"}, None)
    assert values["website_limit"] == 1000 and values["storage_limit_mb"] == 5120
    assert cpanel_import.plan_limits({}, None)[0]["storage_limit_mb"] == cpanel_import.da_import.DEFAULT_STORAGE_MB


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(User(username="shop", email="shop@example.test", role="end_user", is_active=True,
                     hashed_password="x", token_version=0))
    session.commit()
    monkeypatch.setattr(php_isolation, "sync_user", lambda db, user: [])
    yield session
    session.close()


def _account(plan="Gold", **cp):
    return {"plan": plan, "cp": {"MAXADDON": "2", "MAXSQL": "5", "MAXPOP": "20", **cp}, "quota": "3000"}


def test_a_new_package_is_made_and_the_account_put_on_it(db):
    item = {"username": "shop"}
    cpanel_import.apply_package(db, _account(), item)
    package = db.query(UserPackage).filter(UserPackage.name == "Gold").one()
    assert (package.website_limit, package.storage_limit_mb, package.database_limit, package.mail_accounts_limit) == (3, 3000, 5, 20)
    assert package.owner_id is None and package.terminal_enabled is False
    user = db.query(User).filter(User.username == "shop").one()
    assert user.package_id == package.id and user.website_limit == 3 and item["package"] == "Gold"


def test_an_existing_package_is_used_as_it_is(db):
    db.add(UserPackage(name="GOLD", website_limit=50, storage_limit_mb=99))
    db.commit()
    cpanel_import.apply_package(db, _account("gold"), {"username": "shop"})
    assert db.query(UserPackage).count() == 1
    assert db.query(UserPackage).one().website_limit == 50
    assert db.query(User).one().package_id == db.query(UserPackage).one().id


def test_cpanels_own_plans_and_resellers_packages_are_not_used(db):
    reseller = User(username="res", email="r@example.test", role="reseller", is_active=True, hashed_password="x", token_version=0)
    db.add(reseller)
    db.commit()
    db.add(UserPackage(name="Silver", owner_id=reseller.id))
    db.commit()
    item = {"username": "shop"}
    cpanel_import.apply_package(db, _account("Silver"), item)
    cpanel_import.apply_package(db, _account("default"), item)
    assert db.query(User).filter(User.username == "shop").one().package_id is None
    assert any("reseller" in w for w in item["warnings"])


def test_the_object_cache_is_switched_on_or_the_report_says_why(db, monkeypatch):
    calls = []
    monkeypatch.setattr(redis_accounts, "problem", lambda user: None)
    monkeypatch.setattr(redis_accounts, "apply", lambda user: calls.append(user.username))
    item = {"username": "shop"}
    cpanel_import.enable_object_cache(db, item)
    assert calls == ["shop"] and item["object_cache"] is True
    assert db.query(User).filter(User.username == "shop").one().redis_enabled is True

    db.query(User).filter(User.username == "shop").one().redis_enabled = False
    db.commit()
    monkeypatch.setattr(redis_accounts, "problem", lambda user: "not-installed")
    item = {"username": "shop"}
    cpanel_import.enable_object_cache(db, item)
    assert "object_cache" not in item and item["warnings"][0].startswith("Object cache not switched on:")

    monkeypatch.setattr(redis_accounts, "problem", lambda user: None)
    monkeypatch.setattr(redis_accounts, "apply", lambda user: (_ for _ in ()).throw(RuntimeError("did not start")))
    item = {"username": "shop"}
    cpanel_import.enable_object_cache(db, item)
    assert db.query(User).filter(User.username == "shop").one().redis_enabled is False
    assert "did not start" in item["warnings"][0]
