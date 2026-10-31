"""The migration addons - DirectAdmin Import, cPanel Import, FastPanel Import -
as OPanel has them (operator, 2026-10-27: "bpanel không có các addon import
cpanel, import DirectAdmin, import FastPanel").

What must hold: each is an addon, off until installed, and with it off its
archives are never restored and its endpoints refuse; a cPanel or FastPanel
archive is laid out the way a DirectAdmin one is and goes through the same
importer (Nginx vhosts, PHP-FPM pools, databases, aliases, certificates); an
old server signed in to over SSH packs each account picked in a private
folder that is removed whatever happens, and its root login is never kept -
not in the job, the log, the database or on disk; Backups > Restore lists
only the panel's own backups and each Migration page only its own panel's.
DirectAdmin restore was part of Backups > Restore before: a server that used
it keeps it.
"""
import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.datastructures import UploadFile

from app.api import maintenance
from app.models.entities import AuditLog, Base, DatabaseAccount, User, Website, WebsiteAlias
from app.schemas.schemas import RestoreListRequest, RestoreRunRequest, RestoreSource
from app.services import (
    addons, cpanel_import, da_import, fastpanel_import, mariadb, migrate_ssh, nginx, restore_sources, site_users, waf,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP = (PROJECT_ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
NAVIGATION = (PROJECT_ROOT / "frontend" / "src" / "lib" / "navigation.jsx").read_text(encoding="utf-8")
FEATURES = (PROJECT_ROOT / "frontend" / "src" / "lib" / "features.jsx").read_text(encoding="utf-8")
HELPER = (PROJECT_ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")
ADMIN = SimpleNamespace(id=1, role="admin")

KEY = "-----BEGIN PRIVATE KEY-----\nMIIkey\n-----END PRIVATE KEY-----"
CERT = "-----BEGIN CERTIFICATE-----\nMIIleaf\n-----END CERTIFICATE-----"
CHAIN = "-----BEGIN CERTIFICATE-----\nMIIca\n-----END CERTIFICATE-----"
SSH = {"kind": "ssh", "panel": "cpanel", "host": "cp.example.com", "password": "r00t-pw"}


def _installed(monkeypatch, *slugs):
    monkeypatch.setattr(addons, "is_installed", lambda slug: slug in slugs)


@pytest.fixture
def folders(monkeypatch, tmp_path):
    monkeypatch.setattr(restore_sources.settings, "backup_root", str(tmp_path / "bpanel"))
    monkeypatch.setattr(restore_sources.settings, "command_dry_run", False)
    found = SimpleNamespace(root=tmp_path, da=tmp_path / "da", cpanel=tmp_path / "cpanel", fastpanel=tmp_path / "fastpanel",
                            inbox=tmp_path / "inbox", users=tmp_path / "bpanel" / "users")
    for folder in (found.da, found.cpanel, found.fastpanel, found.inbox, found.users / "restore"):
        folder.mkdir(parents=True)
    monkeypatch.setattr(da_import, "DA_BACKUP_DIR", found.da)
    monkeypatch.setattr(cpanel_import, "BACKUP_DIR", found.cpanel)
    monkeypatch.setattr(fastpanel_import, "BACKUP_DIR", found.fastpanel)
    monkeypatch.setattr(restore_sources, "INBOX_DIR", found.inbox)
    for module in (da_import, cpanel_import, fastpanel_import):
        monkeypatch.setattr(module, "BACKUP_DIR_IS_DEFAULT" if module is not da_import else "DA_BACKUP_DIR_IS_DEFAULT",
                            False)
    return found


# --- names ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, kind, account", [
    ("cpmove-bob.tar.gz", "cpanel", "bob"),
    ("backup-10.18.2026_01-02-03_carol.tar.gz", "cpanel", "carol"),
    ("fastpanel-dave.tar.gz", "fastpanel", "dave"),
    ("user.admin.alice.tar.zst", "directadmin", "alice"),
    ("user-erin-20261027020000.tar.gz", "bpanel", "erin"),
    # Any other tar is DirectAdmin's; its account is read from the archive.
    ("backup-carol.tar.bz2", "directadmin", ""),
])
def test_each_kind_is_known_by_its_name(name, kind, account):
    assert restore_sources.archive_kind(name) == kind
    assert restore_sources.account_of(kind, name) == account


# --- off means off ---------------------------------------------------------------------

def test_they_are_addons_and_off_until_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(addons, "ADDONS_DIR", tmp_path)
    monkeypatch.setattr(addons, "ADDONS_FILE", tmp_path / "addons.json")
    for slug in ("directadmin", "cpanel", "fastpanel"):
        assert slug in addons.CATALOGUE and not addons.is_installed(slug)
    addons.install("cpanel")
    assert addons.is_installed("cpanel") and not addons.is_installed("fastpanel")


def test_with_its_addon_off_an_archive_is_listed_marked_and_never_restored(folders, monkeypatch):
    _installed(monkeypatch)
    (folders.cpanel / "cpmove-bob.tar.gz").write_bytes(b"x")
    (folders.da / "user.admin.al.tar.zst").write_bytes(b"x")
    rows = {row["kind"]: row for row in restore_sources.list_source({"kind": "local"}, db=None)["items"]}
    assert "cPanel Import addon" in rows["cpanel"]["error"]
    assert "DirectAdmin Import addon" in rows["directadmin"]["error"]
    with pytest.raises(restore_sources.RestoreSourceError, match="cPanel Import addon"):
        restore_sources.fetch({"kind": "local"}, "@cpanel/cpmove-bob.tar.gz", 1, db=None)
    payload = RestoreRunRequest(source={"kind": "local"}, items=[{"key": "@cpanel/cpmove-bob.tar.gz"}])
    with pytest.raises(HTTPException) as caught:
        maintenance.restore_run(payload, request=None, db=None, current_user=ADMIN)
    assert caught.value.status_code == 400 and "cPanel Import addon" in caught.value.detail


def test_with_its_addon_off_the_upload_the_ssh_source_and_the_old_endpoints_refuse(folders, monkeypatch):
    _installed(monkeypatch)
    upload = UploadFile(file=io.BytesIO(b"x"), filename="cpmove-bob.tar.gz")
    with pytest.raises(HTTPException) as caught:
        maintenance._save_restore_upload(upload)
    assert caught.value.status_code == 400 and "cPanel Import addon" in caught.value.detail
    assert not list(folders.cpanel.iterdir())
    with pytest.raises(restore_sources.RestoreSourceError, match="cPanel Import addon"):
        restore_sources.list_source(dict(SSH), db=None)
    with pytest.raises(HTTPException) as caught:
        maintenance.list_da_backups(current_user=ADMIN)
    assert caught.value.status_code == 409


# --- each page its own kind -------------------------------------------------------------

def test_backups_restore_lists_only_the_panels_own_and_each_page_its_own(folders, monkeypatch):
    _installed(monkeypatch, "directadmin", "cpanel")
    (folders.users / "bob").mkdir()
    (folders.users / "bob" / "user-bob-20261027020000.tar.gz").write_bytes(b"x")
    (folders.cpanel / "cpmove-carol.tar.gz").write_bytes(b"x")
    (folders.da / "user.admin.dave.tar.zst").write_bytes(b"x")

    class Query:
        def filter(self, *a):
            return self

        def __iter__(self):
            return iter([])

    db = SimpleNamespace(query=lambda *a: Query())

    def listed(kinds):
        result = maintenance.restore_list(RestoreListRequest(source={"kind": "local"}, kinds=kinds), db=db,
                                          current_user=ADMIN)
        return sorted(row["kind"] for row in result["items"])

    assert listed(["bpanel"]) == ["bpanel"]
    assert listed(["cpanel"]) == ["cpanel"]
    assert listed(["directadmin"]) == ["directadmin"]
    assert listed(None) == ["bpanel", "cpanel", "directadmin"]


def test_an_archive_uploaded_on_the_wrong_page_says_where_it_goes(folders, monkeypatch):
    _installed(monkeypatch, "directadmin", "cpanel")
    for name, mode, where in (("user.admin.al.tar.zst", "bpanel", "Migration > DirectAdmin"),
                              ("cpmove-bob.tar.gz", "directadmin", "Migration > cPanel"),
                              ("user-al-20261027020000.tar.gz", "cpanel", "Backups > Restore")):
        with pytest.raises(HTTPException) as caught:
            maintenance._save_restore_upload(UploadFile(file=io.BytesIO(b"x"), filename=name), mode)
        assert caught.value.status_code == 400 and f"restore it from {where}" in caught.value.detail, name
    # FastPanel accounts are packed by the panel itself; there is nothing to upload.
    _installed(monkeypatch, "fastpanel")
    with pytest.raises(HTTPException) as caught:
        maintenance._save_restore_upload(UploadFile(file=io.BytesIO(b"x"), filename="fastpanel-bob.tar.gz"))
    assert "straight off the server" in caught.value.detail


def test_a_cpanel_upload_lands_in_its_folder_and_never_over_another(folders, monkeypatch):
    _installed(monkeypatch, "cpanel")
    path, name = maintenance._save_restore_upload(UploadFile(file=io.BytesIO(b"one"), filename="cpmove-bob.tar.gz"))
    assert Path(path) == folders.cpanel / "cpmove-bob.tar.gz" and name == "cpmove-bob.tar.gz"
    again = cpanel_import.save_upload("cpmove-bob.tar.gz", io.BytesIO(b"two"))
    assert again.parent == folders.cpanel and again.name != "cpmove-bob.tar.gz"
    assert cpanel_import.account_of(again.name) == "bob", "the account stays at the end of the name"
    assert (folders.cpanel / "cpmove-bob.tar.gz").read_bytes() == b"one"
    with pytest.raises(ValueError):
        cpanel_import.save_upload("bob.tar.gz", io.BytesIO(b"x"))
    (folders.root / "cpmove-eve.tar.gz").write_bytes(b"x")
    for bad in (str(folders.root / "cpmove-eve.tar.gz"), "notes.txt", "cpmove-missing.tar.gz", ""):
        with pytest.raises(FileNotFoundError):
            cpanel_import.resolve_path(bad)


def test_local_keys_name_only_the_migration_folders(folders, monkeypatch):
    _installed(monkeypatch, "cpanel", "fastpanel")
    (folders.cpanel / "cpmove-bob.tar.gz").write_bytes(b"x")
    (folders.fastpanel / "fastpanel-bob.tar.gz").write_bytes(b"x")
    assert restore_sources.local_archive("@cpanel/cpmove-bob.tar.gz") == (
        folders.cpanel / "cpmove-bob.tar.gz", "cpanel", "cpanel")
    assert restore_sources.local_archive("@fastpanel/fastpanel-bob.tar.gz")[1] == "fastpanel"
    for bad in ("@cpanel/../da/x.tar.gz", "@cpanel/user.admin.x.tar.zst", "@fastpanel/cpmove-bob.tar.gz",
                "@cpanel/missing-cpmove.tar.gz"):
        with pytest.raises(restore_sources.RestoreSourceError):
            restore_sources.local_archive(bad)
    assert restore_sources.delete_local("@cpanel/cpmove-bob.tar.gz") == "cpmove-bob.tar.gz"
    assert not (folders.cpanel / "cpmove-bob.tar.gz").exists()


def test_a_download_of_a_cpanel_archive_keeps_its_account_in_the_name(folders):
    def pull(destination):
        Path(destination).write_bytes(b"archive")

    first = restore_sources._stage_foreign(pull, "cpmove-bob.tar.gz", "cpanel")
    second = restore_sources._stage_foreign(pull, "cpmove-bob.tar.gz", "cpanel")
    assert Path(first).name == "cpmove-bob.tar.gz" and Path(second).parent == folders.cpanel
    assert cpanel_import.account_of(Path(second).name) == "bob" and first != second
    with pytest.raises(ValueError):
        restore_sources._stage_foreign(pull, "user.admin.bob.tar.zst", "cpanel")


# --- the old server over SSH ----------------------------------------------------------------

def test_the_ssh_source_needs_a_panel_and_a_login_and_signs_in_as_root():
    source = RestoreSource(**SSH)
    assert source.username == "root" and source.panel == "cpanel"
    with pytest.raises(ValidationError):
        RestoreSource(kind="ssh", host="cp.example.com", password="x")
    with pytest.raises(ValidationError):
        RestoreSource(kind="ssh", panel="cpanel", host="cp.example.com")
    with pytest.raises(ValidationError):
        RestoreSource(kind="ssh", panel="plesk", host="cp.example.com", password="x")
    assert RestoreSource(kind="ssh", panel="fastpanel", host="fp.example.com", private_key=KEY).private_key


def test_an_ssh_restore_is_queued_with_the_root_login_in_memory_only(monkeypatch):
    _installed(monkeypatch, "cpanel")
    submitted, logged = [], []
    monkeypatch.setattr(maintenance._backup_job_executor, "submit", lambda fn, *args: submitted.append(args))
    monkeypatch.setattr(maintenance, "log_action", lambda *a, **k: logged.append(a))
    monkeypatch.setattr(maintenance, "_backup_jobs", {})
    payload = RestoreRunRequest(source=dict(SSH), items=[{"key": "bob", "username": "bob"}])
    with pytest.raises(HTTPException, match="List the server first"):
        maintenance.restore_run(payload, request=None, db=None, current_user=ADMIN)
    payload = RestoreRunRequest(source={**SSH, "host_key": "SHA256:abc"}, items=[{"key": "bob", "username": "bob"}])
    job = maintenance.restore_run(payload, request=None, db=None, current_user=ADMIN)
    source = submitted[0][2]
    assert source["kind"] == "ssh" and source["username"] == "root" and source["password"] == "r00t-pw"
    assert job["results"] == [{"name": "bob", "username": "bob", "kind": "cpanel", "status": "queued", "detail": ""}]
    assert "r00t-pw" not in repr(maintenance._backup_jobs) and "r00t-pw" not in repr(job)
    assert "r00t-pw" not in repr(logged) and "cPanel server root@cp.example.com:22" in repr(logged)
    # A pick is an account name, never a path or a command.
    for bad in ("../etc", "bob;reboot", "Bob", "bob\n"):
        with pytest.raises(restore_sources.RestoreSourceError):
            restore_sources.check_key(source, bad)
    assert restore_sources.key_kind(source, "bob") == "cpanel"


def test_an_ssh_account_is_packed_and_lands_in_its_panels_folder(folders, monkeypatch):
    _installed(monkeypatch, "cpanel")
    seen = {}

    class Session:
        pass

    from contextlib import contextmanager

    @contextmanager
    def fake_ssh(source, pinned=""):
        seen["pinned"] = pinned
        yield Session(), {"type": "ssh-ed25519", "fingerprint": pinned}

    def pack(session, panel, account, stage, ensure_room, on_status=None, on_progress=None):
        ensure_room(10)
        on_status(f"Packing {account} on the other server")
        return stage(f"cpmove-{account}.tar.gz", lambda destination: Path(destination).write_bytes(b"cp"))

    heard = []
    monkeypatch.setattr(restore_sources, "_ssh", fake_ssh)
    monkeypatch.setattr(restore_sources.migrate_ssh, "pack_and_fetch", pack)
    with pytest.raises(restore_sources.RestoreSourceError, match="List the server first"):
        restore_sources.fetch(dict(SSH), "bob", 0, db=None)
    path, is_copy = restore_sources.fetch({**SSH, "host_key": "SHA256:pinned"}, "bob", 0, db=None,
                                          on_status=heard.append)
    assert Path(path) == folders.cpanel / "cpmove-bob.tar.gz" and is_copy
    assert seen["pinned"] == "SHA256:pinned", "the root login only goes to the server that was listed"
    assert heard == ["Packing bob on the other server"]


def test_the_account_lists_are_read():
    rows = migrate_ssh.parse_cpanel_accounts(json.dumps({"data": {"acct": [
        {"user": "bob", "domain": "Bob.test", "diskused": "1.5G", "suspended": 0},
        {"user": "bad user", "domain": "x.test"},
        {"user": "eve", "domain": "eve.test", "diskused": "none", "suspended": 1}]}}))
    assert [(r["key"], r["domain"], r["size"], r["note"], r["kind"], r["where"]) for r in rows] == [
        ("bob", "bob.test", int(1.5 * 1024 ** 3), "", "cpanel", "ssh"), ("eve", "eve.test", 0, "suspended", "cpanel", "ssh")]
    assert migrate_ssh.parse_cpanel_accounts("TRUEUSERDOMAINS\nbob.test: bob\n")[0]["key"] == "bob"
    with pytest.raises(migrate_ssh.MigrateError):
        migrate_ssh.parse_cpanel_accounts("NOT_CPANEL")
    rows = migrate_ssh.parse_directadmin_accounts("al\tuser\tadmin\tal.test\tno\t120.5\nrs\treseller\tadmin\trs.test\tyes\t\n")
    assert [(r["key"], r["domain"], r["note"]) for r in rows] == [("al", "al.test", ""), ("rs", "rs.test", "reseller, suspended")]
    assert rows[0]["size"] == int(120.5 * 1024 ** 2)
    with pytest.raises(migrate_ssh.MigrateError):
        migrate_ssh.parse_directadmin_accounts("NOT_DIRECTADMIN")
    rows = migrate_ssh.parse_fastpanel_accounts("bob\tbob.test,shop.test\t1234\nmail\t\t0\nBad\tx.test\t1\n")
    assert [(r["key"], r["domain"], r["note"], r["kind"]) for r in rows] == [("bob", "bob.test", "2 site(s)", "fastpanel")]
    with pytest.raises(migrate_ssh.MigrateError):
        migrate_ssh.parse_fastpanel_accounts("NOT_FASTPANEL")


class _FakeServer:
    """What the other server answers, and what it was asked."""

    def __init__(self, panel, fail_pack=False):
        self.panel, self.fail_pack, self.commands, self.removed = panel, fail_pack, [], []
        self.folder = "/home/bpanel-migrate.Ab12Cd34Ef"

    def run(self, client, command, timeout):
        self.commands.append(command)
        if command.startswith("umask 077; mktemp"):
            return 0, self.folder + "\n", ""
        if command.startswith("rm -rf -- "):
            self.removed.append(command)
            return 0, "", ""
        if "pkgacct" in command or "taskq" in command:
            return (1, "", "pkgacct: no such user") if self.fail_pack else (0, "", "")
        if command.startswith("grep -l '^usertype=admin'"):
            return 0, "/usr/local/directadmin/data/users/admin/user.conf\n", ""
        if command.startswith("chown"):
            return 0, "", ""
        if command.startswith("U="):
            return (1, "", "no sites for bob") if self.fail_pack else (0, "fastpanel-bob.tar.gz\n", "")
        if command.startswith("find "):
            name = "cpmove-bob.tar.gz" if self.panel == "cpanel" else "user.admin.bob.tar.zst"
            return 0, f"{name}\t1234\n", ""
        raise AssertionError(command)

    def open_sftp(self):
        server = self

        class Sftp:
            def stat(self, path):
                return SimpleNamespace(st_size=1234)

            def get(self, remote, local, callback=None):
                server.downloaded = remote
                Path(local).write_bytes(b"archive")

            def close(self):
                pass

        return Sftp()


def _stage_into(folder):
    def stage(name, pull):
        destination = folder / name
        pull(str(destination))
        return str(destination)
    return stage


@pytest.mark.parametrize("panel, name", [("cpanel", "cpmove-bob.tar.gz"), ("directadmin", "user.admin.bob.tar.zst"),
                                         ("fastpanel", "fastpanel-bob.tar.gz")])
def test_an_account_is_packed_there_downloaded_and_the_folder_removed(tmp_path, monkeypatch, panel, name):
    server = _FakeServer(panel)
    monkeypatch.setattr(migrate_ssh, "_exec", server.run)
    monkeypatch.setattr(migrate_ssh.time, "sleep", lambda s: None)
    rooms = []
    got = migrate_ssh.pack_and_fetch(server, panel, "bob", _stage_into(tmp_path), rooms.append)
    assert Path(got) == tmp_path / name and Path(got).read_bytes() == b"archive"
    assert rooms == [1234], "the disk here is asked before the download"
    assert server.downloaded == f"{server.folder}/{name}"
    assert server.removed == [f"rm -rf -- {server.folder}"]
    if panel == "fastpanel":
        pack = next(c for c in server.commands if c.startswith("U="))
        assert pack.startswith(f"U=bob W={server.folder} bash -c ")
        return
    pack = next(c for c in server.commands if "pkgacct" in c or "taskq" in c)
    if panel == "cpanel":
        assert pack.startswith(f"/usr/local/cpanel/scripts/pkgacct bob {server.folder} ")
    else:
        assert "select%30=bob" in pack and "owner=admin" in pack and "local%5Fpath=%2Fhome%2Fbpanel-migrate.Ab12Cd34Ef" in pack
        # Full backup: the data categories must be selected or DA writes a
        # metadata-only archive. option0 (%30) is the domains/website files.
        assert "option%30=domain" in pack and "database%5Fdata" in pack and "email%5Fdata" in pack
        # The reliable path on every DA version: task.queue + dataskq, never the
        # `taskq --run` subcommand that old DA accepts but does not execute.
        assert "task.queue" in pack and "dataskq" in pack and "taskq --run" not in pack


def test_a_failed_pack_still_removes_the_folder_there(tmp_path, monkeypatch):
    server = _FakeServer("cpanel", fail_pack=True)
    monkeypatch.setattr(migrate_ssh, "_exec", server.run)
    with pytest.raises(migrate_ssh.MigrateError, match="no such user"):
        migrate_ssh.pack_and_fetch(server, "cpanel", "bob", _stage_into(tmp_path), lambda size: None)
    assert server.removed and not list(tmp_path.iterdir())
    with pytest.raises(ValueError):
        migrate_ssh.pack_and_fetch(server, "cpanel", "bob; reboot", _stage_into(tmp_path), lambda size: None)
    # Only the folder mktemp printed is ever removed.
    server.folder = "/"
    with pytest.raises(migrate_ssh.MigrateError, match="Unexpected work folder"):
        migrate_ssh.pack_and_fetch(server, "cpanel", "bob", _stage_into(tmp_path), lambda size: None)
    assert server.removed == ["rm -rf -- /home/bpanel-migrate.Ab12Cd34Ef"]


def test_the_fastpanel_pack_script_puts_only_checked_names_in_commands():
    script = migrate_ssh._FASTPANEL_PACK
    assert "grep -Eq '^[A-Za-z0-9_]{1,64}$'" in script and "--transform=s#^var/www/$U/data/www/" in script
    assert "--single-transaction" in script and 'echo "fastpanel-$U.tar.gz"' in script
    assert "bpanel/aliases.tsv" in script and "opanel/" not in script


def test_the_root_login_is_never_written_anywhere():
    """It lives in the request and the worker's arguments; nothing that writes
    - the job, the log, the database, a file - is handed it."""
    run = (PROJECT_ROOT / "backend" / "app" / "api" / "maintenance.py").read_text(encoding="utf-8")
    run = run.split('@router.post("/restore/run")')[1].split("\n@router")[0]
    assert "_backup_job_executor.submit(_run_restore_job" in run
    assert 'results.append({"name": name, "username": item.username, "kind": kind' in run
    for module in (migrate_ssh, restore_sources):
        text = Path(module.__file__).read_text(encoding="utf-8")
        assert "open(" not in text.split("def _ssh(")[-1].split("\ndef ")[0], module.__name__
    assert restore_sources.describe({**SSH, "port": 2222}) == "cPanel server root@cp.example.com:2222"
    assert "r00t-pw" not in restore_sources.describe(dict(SSH))


# --- a cPanel account, through the DirectAdmin importer --------------------------------------

def test_cpanels_userdata_is_read():
    data = cpanel_import.parse_userdata(
        "---\naddon_domains:\n  shop.test: shop.bob.test\ncp_php_magic_include_path.conf: 0\n"
        "main_domain: bob.test\nparked_domains:\n  - bob.net\nsub_domains:\n  - shop.bob.test\n  - blog.bob.test\n"
        "documentroot: '/home/bob/public_html'\n")
    assert data["main_domain"] == "bob.test" and data["addon_domains"] == {"shop.test": "shop.bob.test"}
    assert data["parked_domains"] == ["bob.net"] and data["sub_domains"] == ["shop.bob.test", "blog.bob.test"]
    assert data["documentroot"] == "/home/bob/public_html"


def _tar(path: Path, files: dict, prefix: str = "") -> Path:
    with tarfile.open(path, "w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"{prefix}{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def _cpmove(folder: Path) -> Path:
    return _tar(folder / "cpmove-bob.tar.gz", {
        "cp/bob": "USER=bob\nCONTACTEMAIL=bob@mail.test\nDNS=bob.test\n",
        "userdata/main": ("---\naddon_domains:\n  shop.test: shop.bob.test\nmain_domain: bob.test\n"
                          "parked_domains:\n  - bob.net\nsub_domains:\n  - shop.bob.test\n  - blog.bob.test\n"),
        "userdata/bob.test": "documentroot: /home/bob/public_html\nhomedir: /home/bob\nphpversion: ea-php74\n",
        "userdata/shop.bob.test": "documentroot: /home/bob/public_html/shop.test\nhomedir: /home/bob\n",
        "userdata/blog.bob.test": "documentroot: /home/bob/public_html/blog\nhomedir: /home/bob\n",
        "homedir/public_html/index.php": "<?php echo 'main';",
        "homedir/public_html/wp-config.php": ("<?php define('DB_NAME', 'bob_wp'); define('DB_USER', 'bob_wp');"
                                              " define('DB_PASSWORD', 'site-db-pw'); define('DB_HOST', 'localhost');"),
        "homedir/public_html/shop.test/index.html": "shop",
        "homedir/public_html/blog/index.php": "<?php echo 'blog';",
        "homedir/mail/bob.test/info/cur/1": "mail",
        "mysql/bob_wp.sql": "CREATE TABLE t (id int);",
        "mysql/bob_wp.create": "CREATE DATABASE bob_wp;",
        "mysql/roundcube.sql": "-- cPanel's own",
        "apache_tls/bob.test": "\n".join([KEY, CERT, CHAIN]),
        "cron/bob": "MAILTO=\"\"\n*/5 * * * * php /home/bob/public_html/cron.php\n",
        "dnszones/bob.test.db": "$TTL 14400\n",
    }, prefix="cpmove-bob/")


@pytest.fixture
def importer(monkeypatch, tmp_path, folders):
    """The DirectAdmin importer with everything that touches the machine
    recorded instead: what it would copy, create and write."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(da_import, "SessionLocal", session_factory)
    monkeypatch.setattr(da_import, "STAGE_BASE", tmp_path / "stage")
    done = SimpleNamespace(files={}, databases=[], imported=[], certificates=[], vhosts={}, session=session_factory)

    def import_site_files(root_path, linux_user, staged):
        public = Path(staged) / "public_html"
        done.files[Path(root_path).name] = sorted(str(p.relative_to(public)).replace("\\", "/")
                                                  for p in public.rglob("*") if p.is_file())

    monkeypatch.setattr(site_users, "ensure_panel_user", lambda username, password=None: username)
    monkeypatch.setattr(site_users, "generate_login_password", lambda: "sftp-generated")
    monkeypatch.setattr(site_users, "site_root_for_panel_user", lambda user, domain: str(tmp_path / "home" / user / domain))
    monkeypatch.setattr(site_users, "ensure_site_runtime", lambda domain, root, php=None, user=None: user)
    monkeypatch.setattr(site_users, "import_site_files", import_site_files)
    monkeypatch.setattr(site_users, "fix_site_permissions", lambda *a, **k: None)
    monkeypatch.setattr(site_users, "site_php_fpm_socket", lambda *a, **k: "/run/php/bob.sock")
    monkeypatch.setattr(waf, "default_enabled_rule_ids", lambda: [])
    monkeypatch.setattr(waf, "sync_site_rules", lambda *a, **k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(nginx, "write_vhost", lambda domain, root, **k: done.vhosts.setdefault(domain, []).append(k))
    monkeypatch.setattr(nginx, "rewrite_vhost", lambda domain, root, **k: done.vhosts.setdefault(domain, []).append(k))
    monkeypatch.setattr(mariadb, "create_database_credentials",
                        lambda name, user, password, **k: done.databases.append((name, user, password)))
    monkeypatch.setattr(mariadb, "import_database", lambda name, path: done.imported.append(name))
    # The dump as it is: mkstemp's open handle would keep Windows from
    # deleting the real temporary copy.
    monkeypatch.setattr(da_import, "_temporary_sql_file", lambda sql: Path(sql))
    monkeypatch.setattr(da_import, "_domain_ip_addresses", lambda domain: set())
    from app.services import dns, ssl as ssl_service

    monkeypatch.setattr(dns, "sync_quietly", lambda db: None)

    def install_manual_ssl(domain, cert, key, ca, aliases=None):
        done.certificates.append((domain, cert.decode().strip(), key.decode().strip(), ca.decode().strip(), aliases))
        return {"cert": f"/etc/ssl/{domain}.crt", "key": f"/etc/ssl/{domain}.key", "ca": ""}

    monkeypatch.setattr(ssl_service, "install_manual_ssl", install_manual_ssl)
    return done


def test_a_cpanel_account_comes_over_whole(importer, folders):
    archive = _cpmove(folders.cpanel)
    result = cpanel_import.import_cpanel_backup(str(archive), replace_own=True)
    summary = result["summary"][0]

    # The main, addon and subdomain become websites; the addon's backing
    # subdomain does not.
    assert sorted(summary["imported_domains"]) == ["blog.bob.test", "bob.test", "shop.test"]
    with importer.session() as db:
        assert sorted(site.domain for site in db.query(Website)) == ["blog.bob.test", "bob.test", "shop.test"]
        assert db.query(User).filter_by(username="bob").one().email == "bob@mail.test"
        # The database, with the password the site already uses; cPanel's own is left.
        account = db.query(DatabaseAccount).filter_by(db_name="bob_wp").one()
        assert account.website_id == db.query(Website).filter_by(domain="bob.test").one().id
        # The parked domain is an alias of the main website, in its vhost too.
        alias = db.query(WebsiteAlias).one()
        assert (alias.domain, alias.mode, alias.website.domain) == ("bob.net", "alias", "bob.test")
    assert importer.imported == ["bob_wp"] and importer.databases == [("bob_wp", "bob_wp", "site-db-pw")]
    assert any(call.get("aliases") == ["bob.net"] for call in importer.vhosts["bob.test"])
    # Nested document roots were moved out of public_html before it was copied.
    assert importer.files["bob.test"] == ["index.php", "wp-config.php"]
    assert importer.files["shop.test"] == ["index.html"] and importer.files["blog.bob.test"] == ["index.php"]
    # The certificate from apache_tls, split into key, certificate and chain.
    assert importer.certificates == [("bob.test", CERT, KEY, CHAIN, ["bob.net"])]
    assert summary["ssl_imported_domains"] == ["bob.test"]
    # What was not imported is said, and none of it reads as a failure.
    warnings = " | ".join(summary["warnings"])
    assert "1 mailbox(es)" in warnings and "1 cron job(s)" in warnings and "1 DNS zone(s)" in warnings
    assert f"PHP 7.4 on cPanel and runs {da_import.DEFAULT_PHP_VERSION}" in warnings
    assert result["errors"] == []
    assert result["credentials"][0] == "# BPanel cPanel import credentials"
    assert archive.exists(), "the archive stays until the restore job is done with it"
    assert not list((folders.root / "stage").iterdir()), "the stage is cleaned up"


def test_a_parked_domain_that_is_a_website_here_stays_where_it_is(importer, folders):
    with importer.session() as db:
        owner = User(username="alice", email="a@x.test", hashed_password="x", role="end_user")
        db.add(owner)
        db.flush()
        db.add(Website(domain="bob.net", owner_id=owner.id, root_path="/home/alice/bob.net", linux_user="alice",
                       php_version="8.3", app_type="php"))
        db.commit()
    result = cpanel_import.import_cpanel_backup(str(_cpmove(folders.cpanel)), replace_own=True)
    assert "Parked domain bob.net is a website here already" in " | ".join(result["summary"][0]["warnings"])
    with importer.session() as db:
        assert db.query(WebsiteAlias).count() == 0


def test_a_cpanel_import_stages_where_the_helper_copies_from():
    """The helper's site-populate takes sources only under the import's stage
    folder; OPanel's first cPanel import was refused for staging elsewhere."""
    assert "/var/lib/bpanel/da-import/*" in HELPER
    assert str(da_import.STAGE_BASE).replace("\\", "/").endswith("/var/lib/bpanel/da-import")
    source = Path(cpanel_import.__file__).read_text(encoding="utf-8")
    assert "tempfile" not in source and "stage_dir / \"archive\"" in source


def test_a_packed_fastpanel_account_comes_over_with_its_aliases(importer, folders):
    _tar(folders.fastpanel / "fastpanel-bob.tar.gz", {
        "backup/user.conf": "username=bob\nemail=\n",
        "backup/domains.list": "bob.test\nshop.test\n",
        "domains/bob.test/public_html/index.php": "<?php echo 1;",
        "domains/bob.test/public_html/wp-config.php": ("<?php define('DB_NAME', 'bob_wp'); define('DB_USER', 'bob_wp');"
                                                      " define('DB_PASSWORD', 'fp-pw'); define('DB_HOST', 'localhost');"),
        "domains/shop.test/public_html/index.html": "shop",
        "mysql/bob_wp.sql": "CREATE TABLE t (id int);",
        "backup/bob.test/domain.cert": CERT,
        "backup/bob.test/domain.key": KEY,
        "bpanel/aliases.tsv": "bob.test\tbob.test www.bob.test bob.net shop.test\nshop.test\tshop.test www.shop.test\n",
    })
    result = fastpanel_import.import_fastpanel_backup("fastpanel-bob.tar.gz", replace_own=True)
    summary = result["summary"][0]
    assert sorted(summary["imported_domains"]) == ["bob.test", "shop.test"]
    assert importer.databases == [("bob_wp", "bob_wp", "fp-pw")]
    assert [c[0] for c in importer.certificates] == ["bob.test"]
    with importer.session() as db:
        # www. is served anyway, and shop.test is a website of the same
        # account; only the other name becomes an alias.
        assert [(a.domain, a.website.domain) for a in db.query(WebsiteAlias)] == [("bob.net", "bob.test")]
    assert result["credentials"][0] == "# BPanel FastPanel import credentials"


def test_the_restore_job_hands_each_kind_to_its_importer(monkeypatch):
    calls = []
    for module, name in ((cpanel_import, "import_cpanel_backup"), (fastpanel_import, "import_fastpanel_backup"),
                         (da_import, "import_da_backup")):
        monkeypatch.setattr(module, name, lambda path, force=False, replace_own=False, _n=name: calls.append(
            (_n, path, replace_own)) or {"summary": [{"username": "bob", "imported_domains": ["bob.test"]}],
                                         "credentials": [], "errors": []})
    for kind in ("cpanel", "fastpanel", "directadmin"):
        assert maintenance._restore_directadmin(f"/x/{kind}", kind)["username"] == "bob"
    assert calls == [("import_cpanel_backup", "/x/cpanel", True), ("import_fastpanel_backup", "/x/fastpanel", True),
                     ("import_da_backup", "/x/directadmin", True)]


# --- DirectAdmin import was in the panel before ---------------------------------------------

def test_a_server_that_imported_from_directadmin_keeps_it_once(tmp_path, monkeypatch):
    monkeypatch.setattr(addons, "ADDONS_DIR", tmp_path)
    monkeypatch.setattr(addons, "ADDONS_FILE", tmp_path / "addons.json")
    monkeypatch.setattr(da_import, "DA_BACKUP_DIR", tmp_path / "da")
    monkeypatch.setattr(da_import, "IMPORT_RESULT_FILE", tmp_path / "last-import.json")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(da_import, "SessionLocal", sessionmaker(bind=engine))
    (tmp_path / "da").mkdir()
    assert da_import.was_used() is False, "a fresh server"
    assert addons.adopt_existing(addons.DIRECTADMIN, da_import.was_used()) is False
    assert not addons.is_installed("directadmin")

    with sessionmaker(bind=engine)() as db:
        db.add(AuditLog(user_id=1, action="upload_restore_backups", target="this server",
                        detail="user.admin.carol.tar.zst"))
        db.commit()
    assert da_import.was_used() is True, "a DirectAdmin archive restored from Backups > Restore"
    assert addons.adopt_existing(addons.DIRECTADMIN, True) is True and addons.is_installed("directadmin")
    # The admin removes it: that stands.
    addons.uninstall("directadmin")
    assert addons.adopt_existing(addons.DIRECTADMIN, True) is False and not addons.is_installed("directadmin")
    (tmp_path / "da" / "user.admin.dave.tar.zst").write_bytes(b"x")
    assert da_import.was_used() is True
    main = (PROJECT_ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    assert "addons.adopt_existing(addons.DIRECTADMIN, da_import.was_used())" in main


# --- the helper and the installers ---------------------------------------------------------

def test_the_helper_makes_the_folders_and_takes_each_kind_from_the_drop_folder():
    ensure = HELPER.split("ensure_da_backup_dir() {", 1)[1].split("\n}\n", 1)[0]
    assert 'for folder in "$CPANEL_BACKUP_DIR" "$FASTPANEL_BACKUP_DIR"; do' in ensure
    assert 'CPANEL_BACKUP_DIR="/home/admin/bpanel_backups/cpanel"' in HELPER
    assert 'FASTPANEL_BACKUP_DIR="/home/admin/bpanel_backups/fastpanel"' in HELPER
    assert str(cpanel_import.BACKUP_DIR).replace("\\", "/") == "/home/admin/bpanel_backups/cpanel"
    assert str(fastpanel_import.BACKUP_DIR).replace("\\", "/") == "/home/admin/bpanel_backups/fastpanel"
    take = HELPER.split("backup_inbox_take() {", 1)[1].split("\n}\n", 1)[0]
    assert 'dest_dir="$CPANEL_BACKUP_DIR"' in take and 'dest_dir="$FASTPANEL_BACKUP_DIR"' in take
    assert '|| deny "not a cPanel backup: $name"' in take and '|| deny "not a FastPanel archive: $name"' in take
    for script in ("install.sh", "update.sh"):
        text = (PROJECT_ROOT / "installer" / script).read_text(encoding="utf-8")
        assert "/home/admin/bpanel_backups/cpanel /home/admin/bpanel_backups/fastpanel" in text, script


# --- the pages --------------------------------------------------------------------------------

def test_the_wizard_runs_in_each_pages_mode():
    assert "bpanel: { kinds: ['bpanel'], sources: ['local', 'target', 'remote'] }" in APP
    assert "directadmin: { kinds: ['directadmin'], sources: ['ssh', 'local', 'remote'] }" in APP
    assert "cpanel: { kinds: ['cpanel'], sources: ['ssh', 'local', 'remote'] }" in APP
    assert "fastpanel: { kinds: ['fastpanel'], sources: ['ssh', 'local'] }" in APP
    assert "const restoreUpload = packedHere ? null :" in APP, "nothing to upload from FastPanel"
    assert "kinds: RESTORE_MODES[mode].kinds" in APP, "the list asks only for the page's kinds"
    assert "form.append('mode', restoreMode);" in APP, "an upload says which page it came from"
    assert "if (page === 'backups' && backupTab === 'restore') enterRestoreMode('bpanel');" in APP
    tab = APP.split("  function renderRestoreWizard() {")[1].split("\n  function ")[0]
    assert "{restoreSource === 'ssh' && <form" in tab and "listRestoreSource('ssh')" in tab
    assert "{t('Used for this import only; nothing here is saved.')}" in tab
    page = APP.split("  function renderImportPage(panel) {")[1].split("\n  function ")[0]
    assert "if (!importAddonsInstalled[panel]) return renderAddonMissing(panel);" in page
    assert "if (IMPORT_PAGES[page]) return renderImportPage(IMPORT_PAGES[page]);" in APP
    # The root login is in the page's memory only: no storage, no URL.
    block = APP.split("  const [restoreSsh, setRestoreSsh] = useState(")[1].split("\n")[0]
    assert "localStorage" not in block and "sessionStorage" not in block


def test_the_migration_hub_has_a_tab_per_installed_addon_and_the_dashboard_tiles():
    hub = NAVIGATION.split("{ key: 'migration', title: msg('Migration'), roles: ['admin'], tabs: [")[1].split("] },")[0]
    for page, fact in (("importDirectadmin", "directadminImport"), ("importCpanel", "cpanelImport"),
                       ("importFastpanel", "fastpanelImport")):
        assert f"page: '{page}'" in hub and f"when: (c) => c.{fact}" in hub
        assert f"{fact}: importAddonsInstalled." in APP
    assert "['migration', msg('Migration'), ['da-import', 'cpanel-import', 'fastpanel-import']]" in FEATURES
    for route in ("migration: '/migration'", "importDirectadmin: '/migration/directadmin'",
                  "importCpanel: '/migration/cpanel'", "importFastpanel: '/migration/fastpanel'"):
        assert route in APP
    assert "(page !== 'migration' || addons.loaded)" in APP, "the hub waits for its addons before landing"
