"""A website backup's database comes back when the backup is restored (1.20.3).

create_backup() puts the site's SQL dump in the archive at database/, and its
own comment said restore reads it from there - but restore_backup() skipped
database/, so the dump the backup had taken could never be put back. The
restore now imports it on request, through an account MariaDB confines to the
site's one schema: the archive may be one the owner uploaded.
"""
import io
import re
import subprocess
import tarfile
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import maintenance
from app.core.config import settings
from app.core.database import Base
from app.core.secrets import encrypt
from app.models.entities import DatabaseAccount, User, Website
from app.schemas.schemas import RestoreBackup
from app.services import backup, mariadb

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DUMP = b"CREATE TABLE wp_posts (id int);\nINSERT INTO wp_posts VALUES (1);\n"


def _archive(root: Path, domain: str, name: str, with_dump: bool = True) -> str:
    folder = root / domain
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    with tarfile.open(path, "w:gz") as tar:
        page = b"<?php echo 1;"
        info = tarfile.TarInfo("site/index.php")
        info.size = len(page)
        tar.addfile(info, io.BytesIO(page))
        if with_dump:
            info = tarfile.TarInfo(f"database/{domain}-20261120000000.sql")
            info.size = len(DUMP)
            tar.addfile(info, io.BytesIO(DUMP))
    return str(path)


@pytest.fixture
def env(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    alice = User(username="alice", email="alice@example.test", role="end_user", is_active=True,
                 hashed_password="x", token_version=0)
    db.add(alice)
    db.commit()
    site = Website(domain="shop.test", owner_id=alice.id, root_path="/home/alice/shop.test", linux_user="alice",
                   app_type="static")
    bare = Website(domain="bare.test", owner_id=alice.id, root_path="/home/alice/bare.test", linux_user="alice",
                   app_type="static")
    db.add_all([site, bare])
    db.commit()
    db.add(DatabaseAccount(owner_id=alice.id, website_id=site.id, db_name="shop_db", db_user="shop_user",
                           db_password=encrypt("site-password")))
    db.commit()
    monkeypatch.setattr(settings, "backup_root", str(tmp_path / "backups"))
    monkeypatch.setattr(backup, "restore_backup", lambda website, backup_file: website.root_path)
    monkeypatch.setattr(maintenance.site_users, "ensure_site_runtime", lambda *a, **k: None)
    monkeypatch.setattr(maintenance.wordpress, "fix_permissions", lambda *a, **k: None)
    logged = []
    monkeypatch.setattr(maintenance, "log_action", lambda db, uid, action, target, detail=None: logged.append(detail))
    imports = []

    def fake_import(db_name, sql_file, *, db_user=None, db_password=None):
        imports.append({"db_name": db_name, "sql": Path(sql_file).read_bytes(), "db_user": db_user,
                        "db_password": db_password})

    monkeypatch.setattr(mariadb, "import_database_scoped", fake_import)
    yield db, alice, site, bare, tmp_path / "backups", imports, logged
    db.close()


def _restore(db, user, website, backup_file, restore_database):
    payload = RestoreBackup(website_id=website.id, backup_file=backup_file, restore_database=restore_database)
    return maintenance.restore_backup(payload, db=db, current_user=user)


def test_the_database_comes_back_with_the_files_when_asked(env):
    db, alice, site, _bare, root, imports, logged = env
    archive = _archive(root, site.domain, "shop.test-20261120000000.tar.gz")
    result = _restore(db, alice, site, archive, True)
    assert result["database_restored"] is True and result["note"] == ""
    # Into the site's own database, as the site's own login, with the dump
    # the backup carried.
    assert imports == [{"db_name": "shop_db", "sql": DUMP, "db_user": "shop_user", "db_password": "site-password"}]
    assert logged[-1].endswith("(files and database)")


def test_files_only_unless_asked(env):
    # An API client from before 1.20.3 sends no restore_database: it gets what
    # it always got.
    db, alice, site, _bare, root, imports, _logged = env
    archive = _archive(root, site.domain, "shop.test-20261120000001.tar.gz")
    assert RestoreBackup(website_id=site.id, backup_file=archive).restore_database is False
    result = _restore(db, alice, site, archive, False)
    assert result["database_restored"] is False and imports == []


def test_a_backup_without_a_dump_says_so(env):
    db, alice, site, _bare, root, imports, _logged = env
    archive = _archive(root, site.domain, "shop.test-20261120000002.tar.gz", with_dump=False)
    result = _restore(db, alice, site, archive, True)
    assert result["database_restored"] is False and imports == []
    assert "no database dump" in result["note"]


def test_a_website_without_a_database_says_so(env):
    db, alice, _site, bare, root, imports, _logged = env
    archive = _archive(root, bare.domain, "bare.test-20261120000000.tar.gz")
    result = _restore(db, alice, bare, archive, True)
    assert result["database_restored"] is False and imports == []
    assert "No database is linked" in result["note"]


def test_a_failed_import_is_an_error_that_says_the_files_are_back(env, monkeypatch):
    db, alice, site, _bare, root, _imports, logged = env
    archive = _archive(root, site.domain, "shop.test-20261120000003.tar.gz")

    def refuse(*_a, **_k):
        raise RuntimeError("Database import failed: ERROR 1142 (42000): CREATE USER command denied")

    monkeypatch.setattr(mariadb, "import_database_scoped", refuse)
    with pytest.raises(HTTPException) as caught:
        _restore(db, alice, site, archive, True)
    assert caught.value.status_code == 400
    assert "files were restored, but the database import failed" in caught.value.detail
    assert "files only" in logged[-1]


def test_an_unreadable_stored_password_leaves_it_to_a_temporary_login(env, monkeypatch):
    db, alice, site, _bare, root, imports, _logged = env
    account = db.query(DatabaseAccount).filter(DatabaseAccount.db_name == "shop_db").one()
    account.db_password = "fernet:not-a-token"
    db.commit()
    archive = _archive(root, site.domain, "shop.test-20261120000004.tar.gz")
    assert _restore(db, alice, site, archive, True)["database_restored"] is True
    assert imports[-1]["db_password"] is None


# --- the import itself ----------------------------------------------------------

@pytest.fixture
def mysql(monkeypatch, tmp_path):
    """mysql and the panel's own SQL, recorded instead of run."""
    monkeypatch.setattr(settings, "command_dry_run", False)
    calls, sql = [], []
    outcomes = []

    def fake_run(args, stdin=None, capture_output=False, check=False):
        defaults = next(a.split("=", 1)[1] for a in args if a.startswith("--defaults-file="))
        calls.append({"args": args, "defaults": Path(defaults).read_text(encoding="utf-8"),
                      "body": stdin.read()})
        code, err = outcomes.pop(0) if outcomes else (0, b"")
        return subprocess.CompletedProcess(args, code, b"", err)

    monkeypatch.setattr(mariadb.subprocess, "run", fake_run)
    monkeypatch.setattr(mariadb, "_run_sql", lambda text, check=True: sql.append(text))
    dump = tmp_path / "restore.sql"
    dump.write_bytes(DUMP)
    return calls, sql, outcomes, str(dump)


def test_the_import_runs_as_the_sites_login_never_the_panels(mysql):
    calls, sql, _outcomes, dump = mysql
    mariadb.import_database_scoped("shop_db", dump, db_user="shop_user", db_password="site-password")
    (call,) = calls
    assert call["args"][0] == "mysql" and call["args"][-1] == "shop_db"
    assert "user=shop_user\n" in call["defaults"] and 'password="site-password"\n' in call["defaults"]
    # The password is in the 0600 file, never in argv; and the file is gone.
    assert not any("site-password" in arg for arg in call["args"])
    assert not Path(call["args"][1].split("=", 1)[1]).exists()
    assert ".my.cnf" not in " ".join(call["args"])
    assert call["body"] == DUMP and sql == []


def test_without_a_password_a_temporary_login_does_it_and_is_dropped(mysql):
    calls, sql, _outcomes, dump = mysql
    mariadb.import_database_scoped("shop_db", dump, db_user="shop_user", db_password=None)
    (call,) = calls
    create, drop = sql
    user = call["defaults"].split("user=")[1].split("\n")[0]
    assert user.startswith(mariadb.RESTORE_USER_PREFIX)
    # Rights on this one schema, with _ escaped so shop_db does not also
    # cover shopXdb.
    assert f"CREATE USER '{user}'@'localhost'" in create
    assert f"GRANT ALL PRIVILEGES ON `shop\\_db`.* TO '{user}'@'localhost'" in create
    assert "WITH GRANT OPTION" not in create and "*.*" not in create
    assert drop == f"DROP USER IF EXISTS '{user}'@'localhost';\n"
    # Hex: nothing in it an option file would read as a comment or an escape.
    password = call["defaults"].split("password=")[1].split("\n")[0]
    assert re.fullmatch(r'"[0-9a-f]{48}"', password)


# On .88, 2026-11-20: an unquoted `password=` line is cut at the first `#`,
# and random_password() puts a `#` in about one password in three - the
# temporary login was refused with ERROR 1045 on the second live run.
@pytest.mark.parametrize("password, line", [
    ("abc#def", 'password="abc#def"'),
    ("a;b c", 'password="a;b c"'),
    ("back\\slash", 'password="back\\\\slash"'),
    ('say "hi"', "password='say \"hi\"'"),
])
def test_the_password_reads_back_from_the_option_file_as_it_is(mysql, password, line):
    calls, _sql, _outcomes, dump = mysql
    mariadb.import_database_scoped("shop_db", dump, db_user="shop_user", db_password=password)
    assert line + "\n" in calls[0]["defaults"]


def test_a_password_no_option_file_can_hold_goes_to_a_temporary_login(mysql):
    calls, sql, _outcomes, dump = mysql
    mariadb.import_database_scoped("shop_db", dump, db_user="shop_user", db_password="it's \"both\"")
    (call,) = calls
    assert mariadb.RESTORE_USER_PREFIX in call["defaults"] and len(sql) == 2


def test_a_refused_stored_password_falls_back_to_a_temporary_login(mysql):
    calls, sql, outcomes, dump = mysql
    outcomes.append((1, b"ERROR 1045 (28000): Access denied for user 'shop_user'@'localhost'"))
    mariadb.import_database_scoped("shop_db", dump, db_user="shop_user", db_password="stale")
    assert len(calls) == 2 and len(sql) == 2
    assert "user=shop_user\n" in calls[0]["defaults"]
    assert mariadb.RESTORE_USER_PREFIX in calls[1]["defaults"]


def test_the_temporary_login_is_dropped_even_when_the_import_fails(mysql):
    _calls, sql, outcomes, dump = mysql
    outcomes.append((1, b"ERROR 1142 (42000): CREATE USER command denied"))
    with pytest.raises(RuntimeError, match="1142"):
        mariadb.import_database_scoped("shop_db", dump)
    assert sql[-1].startswith("DROP USER IF EXISTS 'bprst_")


def test_a_statement_error_with_the_sites_login_is_not_retried(mysql):
    # Only a refused login falls back: an error part-way through the dump
    # means statements already ran, and running them again would not help.
    calls, sql, outcomes, dump = mysql
    outcomes.append((1, b"ERROR 1062 (23000) at line 2: Duplicate entry"))
    with pytest.raises(RuntimeError, match="1062"):
        mariadb.import_database_scoped("shop_db", dump, db_user="shop_user", db_password="site-password")
    assert len(calls) == 1 and sql == []


@pytest.mark.parametrize("name", ["", "shop-db", "shop;db", "a" * 65, "Shop"])
def test_only_a_plain_schema_name_is_imported_into(mysql, name):
    _calls, _sql, _outcomes, dump = mysql
    with pytest.raises(ValueError):
        mariadb.import_database_scoped(name, dump)


def test_the_restore_dialog_asks_with_the_box_ticked():
    app = (PROJECT_ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
    body = app.split("async function restoreBackup(file) {")[1].split("\n  }\n")[0]
    assert "restore_database: Boolean(choice.database)" in body
    assert "name: 'database'" in body and "checked: true" in body
