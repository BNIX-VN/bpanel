"""A database can be linked to a website, and an account backup carries every
database the account owns (operator, 2026-11-08).

BPanel had no way to link a database to a website; and an account backup
dumped only the databases a website pointed at, so an application's database,
made on the Databases page, was in no backup at all.
"""
import json
import tarfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import databases as api
from app.core.database import Base
from app.core.secrets import encrypt
from app.models.entities import DatabaseAccount, User, Website
from app.schemas.schemas import DatabaseWebsiteUpdate
from app.services import backup


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    people = {}
    for name, role in (("admin", "admin"), ("alice", "end_user"), ("bob", "end_user")):
        people[name] = User(username=name, email=f"{name}@example.test", role=role, is_active=True,
                            hashed_password="x", token_version=0)
        db.add(people[name])
    db.commit()
    sites = {}
    for domain, owner in (("shop.test", "alice"), ("blog.test", "alice"), ("bob.test", "bob")):
        sites[domain] = Website(domain=domain, owner_id=people[owner].id, root_path=f"/home/{owner}/{domain}",
                                linux_user=owner)
        db.add(sites[domain])
    db.commit()
    dbs = {}
    for name, owner, site in (("shop_db", "alice", "shop.test"), ("app_db", "alice", None), ("bob_db", "bob", None)):
        dbs[name] = DatabaseAccount(owner_id=people[owner].id, website_id=sites[site].id if site else None,
                                    db_name=name, db_user=name, db_password=encrypt("secret-password"))
        db.add(dbs[name])
    db.commit()
    monkeypatch.setattr(api, "log_action", lambda *a, **k: None)
    yield db, people, sites, dbs
    db.close()


def _link(env, who, database, website):
    db, people, sites, dbs = env
    return api.link_database_website(dbs[database].id, DatabaseWebsiteUpdate(website_id=sites[website].id if website else None),
                                     request=SimpleNamespace(client=None, headers={}), db=db, current_user=people[who])


def test_a_customer_links_and_unlinks_their_own_database(env):
    db, _, sites, dbs = env
    assert _link(env, "alice", "app_db", "blog.test").website_id == sites["blog.test"].id
    assert _link(env, "alice", "app_db", None).website_id is None


def test_a_website_takes_one_database(env):
    with pytest.raises(HTTPException) as err:
        _link(env, "alice", "app_db", "shop.test")
    assert err.value.status_code == 409 and "shop_db" in err.value.detail


def test_never_another_accounts_website_or_database(env):
    with pytest.raises(HTTPException) as err:
        _link(env, "alice", "app_db", "bob.test")
    assert err.value.status_code == 400
    with pytest.raises(HTTPException) as err:
        _link(env, "alice", "bob_db", "shop.test")
    assert err.value.status_code in (403, 404)


def test_the_account_backup_carries_the_database_no_website_points_at(env, tmp_path, monkeypatch):
    db, people, _, _ = env
    monkeypatch.setattr(backup.settings, "backup_root", str(tmp_path / "backups"))
    monkeypatch.setattr(backup, "_ensure_user_dir", lambda path: (path.mkdir(parents=True, exist_ok=True), path)[1])
    monkeypatch.setattr(backup, "_collect_applications", lambda user, db, tmp_dir: [])
    monkeypatch.setattr(backup, "_add_tree", lambda *a, **k: None)
    monkeypatch.setattr(backup.mariadb, "export_database",
                        lambda name, out: open(out, "w", encoding="utf-8").write(f"-- dump of {name}\n"))
    from app.services import mail
    monkeypatch.setattr(mail, "backup_manifest", lambda db, user: {})
    archive = backup.create_user_backup(people["alice"], db)
    with tarfile.open(archive) as tar:
        names = tar.getnames()
        manifest = json.load(tar.extractfile(backup.BACKUP_MANIFEST))
    listed = {entry["db_name"]: entry for entry in manifest["databases"]}
    assert set(listed) == {"shop_db", "app_db"}, "bob's database is not alice's"
    assert listed["shop_db"]["website_domain"] == "shop.test"
    assert listed["shop_db"]["sql_member"] == "databases/shop.test.sql", "a site's dump is not taken twice"
    assert listed["app_db"]["website_domain"] == "" and listed["app_db"]["sql_member"] == "databases/db-app_db.sql"
    assert "databases/db-app_db.sql" in names and "databases/shop.test.sql" in names


def test_restore_brings_back_every_listed_database_and_refuses_anothers(env, tmp_path, monkeypatch):
    db, people, sites, _ = env
    created = []
    monkeypatch.setattr(backup.mariadb, "create_database_credentials", lambda *a, **k: created.append(a[:2]))
    monkeypatch.setattr(backup.mariadb, "import_database", lambda *a, **k: None)
    monkeypatch.setattr(backup.mariadb, "user_exists", lambda name: False)
    monkeypatch.setattr(backup, "_extract_member_to_file", lambda *a, **k: None)
    entries = [{"db_name": "app_db", "db_user": "app_db", "db_password": "p", "website_domain": ""},
               {"db_name": "new_db", "db_user": "new_db", "db_password": "p", "website_domain": "blog.test"}]
    assert backup._restore_databases(entries, people["alice"], db, tmp_path / "a.tar.gz", tmp_path) == ["app_db", "new_db"]
    new = db.query(DatabaseAccount).filter(DatabaseAccount.db_name == "new_db").one()
    assert new.owner_id == people["alice"].id and new.website_id == sites["blog.test"].id
    with pytest.raises(ValueError, match="another account"):
        backup._restore_databases([{"db_name": "bob_db", "db_user": "bob_db"}], people["alice"], db, tmp_path, tmp_path)
    monkeypatch.setattr(backup.mariadb, "user_exists", lambda name: True)
    with pytest.raises(ValueError, match="already exists on this server"):
        backup._restore_databases([{"db_name": "other_db", "db_user": "someone"}], people["alice"], db, tmp_path, tmp_path)
    with pytest.raises(ValueError, match="Invalid database"):
        backup._restore_databases([{"db_name": "x; DROP", "db_user": "x"}], people["alice"], db, tmp_path, tmp_path)
