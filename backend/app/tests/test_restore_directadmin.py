"""DirectAdmin archives in the Restore tab, and the admin's SFTP drop folder
(operator, 2026-10-06: "Làm theo opanel" and "Login admin như DA").

What must hold: a DirectAdmin archive is told from a panel one by its name and
goes through the DirectAdmin importer; this server's list reads the DA folder
and /home/admin/backups as well as users/; a file still arriving in the drop
folder is not offered; a key cannot name anything outside those folders; an
existing account is overwritten with its own sites, but another account's site
stops the import; the generated passwords reach only the admin who ran it.
"""
import io
import os
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import UploadFile

from app.api import maintenance
from app.models.entities import Base, User, Website
from app.services import da_import, restore_sources

PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP = (PROJECT_ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
HELPER = (PROJECT_ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")


@pytest.fixture
def folders(monkeypatch, tmp_path):
    monkeypatch.setattr(restore_sources.settings, "backup_root", str(tmp_path / "bpanel"))
    monkeypatch.setattr(restore_sources.settings, "command_dry_run", False)
    da = tmp_path / "da"
    inbox = tmp_path / "inbox"
    for folder in (tmp_path / "bpanel" / "users" / "restore", da, inbox):
        folder.mkdir(parents=True)
    monkeypatch.setattr(da_import, "DA_BACKUP_DIR", da)
    monkeypatch.setattr(restore_sources, "INBOX_DIR", inbox)

    def make(folder: Path, name: str, age: float = 3600, data: bytes = b"x" * 10) -> Path:
        path = folder / name
        path.write_bytes(data)
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
        return path

    return SimpleNamespace(root=tmp_path, users=tmp_path / "bpanel" / "users", da=da, inbox=inbox, make=make)


# --- what an archive is ------------------------------------------------------------

def test_a_directadmin_archive_is_told_from_a_panel_one_by_its_name():
    kind = restore_sources.archive_kind
    assert kind("user-bob-20261006020000.tar.gz") == "bpanel"
    assert kind("bob.test-20261006.tar.gz") == "bpanel"
    for name in ("user.admin.bob.tar.zst", "user.admin.bob.tar.gz", "reseller.admin.shop.tar.gz",
                 "anything.tar.zst", "x.tar.bz2", "x.tar.xz", "x.tar", "x.tgz"):
        assert kind(name) == "directadmin", name
    for name in ("notes.txt", "x.zip", "x.gz", ""):
        assert kind(name) is None, name
    assert restore_sources.account_of("directadmin", "user.admin.Bob.tar.zst") == "bob"
    # The panel's own admin is taken, so DirectAdmin's becomes another name.
    assert restore_sources.account_of("directadmin", "admin.root.admin.tar.zst").startswith("da_admin_")


# --- this server ----------------------------------------------------------------------

def test_this_servers_list_has_the_da_folder_and_the_drop_folder(folders):
    (folders.users / "bob").mkdir()
    folders.make(folders.users / "bob", "user-bob-20261005020000.tar.gz", age=7200)
    folders.make(folders.da, "user.admin.carol.tar.zst", age=5000)
    folders.make(folders.da, "readme.txt")
    folders.make(folders.inbox, "user.admin.dave.tar.gz", age=4000)
    folders.make(folders.inbox, "user-erin-20261001020000.tar.gz", age=3000)
    folders.make(folders.inbox, "user.admin.big.tar.zst.filepart", age=4000)
    folders.make(folders.inbox, "user.admin.fresh.tar.zst", age=5)
    folders.make(folders.inbox, ".hidden.tar.gz", age=4000)
    rows = restore_sources.list_local()
    assert [(row["key"], row["kind"], row["where"], row["username"]) for row in rows] == [
        ("@inbox/user-erin-20261001020000.tar.gz", "bpanel", "inbox", "erin"),
        ("@inbox/user.admin.dave.tar.gz", "directadmin", "inbox", "dave"),
        ("@da/user.admin.carol.tar.zst", "directadmin", "da", "carol"),
        ("bob/user-bob-20261005020000.tar.gz", "bpanel", "panel", "bob"),
    ], "newest first; half-uploaded, fresh and hidden files are not offered"


def test_a_local_key_names_only_those_folders(folders):
    da = folders.make(folders.da, "user.admin.carol.tar.zst")
    inbox = folders.make(folders.inbox, "user.admin.dave.tar.gz")
    assert restore_sources.local_archive("@da/user.admin.carol.tar.zst") == (da, "directadmin", "da")
    assert restore_sources.local_archive("@inbox/user.admin.dave.tar.gz") == (inbox, "directadmin", "inbox")
    (folders.root / "outside.tar.zst").write_bytes(b"x")
    for bad in ("@da/../outside.tar.zst", "@inbox/../outside.tar.zst", "@da/readme.txt", "@inbox/x.zip",
                "@da", "@da/a/b.tar.zst", "@inbox/missing.tar.gz", "@other/x.tar.gz", "@inbox/x\n.tar.gz"):
        with pytest.raises(restore_sources.RestoreSourceError):
            restore_sources.local_archive(bad)


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_a_link_in_the_drop_folder_is_neither_listed_nor_taken(folders):
    target = folders.make(folders.root, "secret.tar.gz")
    (folders.inbox / "user-x-1.tar.gz").symlink_to(target)
    assert restore_sources.list_inbox() == []
    with pytest.raises(restore_sources.RestoreSourceError):
        restore_sources.local_archive("@inbox/user-x-1.tar.gz")


def test_a_drop_folder_archive_is_moved_before_it_is_restored(folders, monkeypatch):
    folders.make(folders.inbox, "user.admin.dave.tar.zst")
    taken = []

    def take(name, kind):
        taken.append((name, kind))
        return str(folders.da / name)

    monkeypatch.setattr(restore_sources, "take_from_inbox", take)
    path, is_copy = restore_sources.fetch({"kind": "local"}, "@inbox/user.admin.dave.tar.zst", 10, db=None)
    assert taken == [("user.admin.dave.tar.zst", "directadmin")]
    assert (path, is_copy) == (str(folders.da / "user.admin.dave.tar.zst"), False), \
        "moved, not copied: it is kept like an upload"


def test_the_helper_takes_a_plain_settled_file_and_hands_it_over_after_the_move():
    take = HELPER.split("backup_inbox_take() {", 1)[1].split("\n}\n", 1)[0]
    checks = ['[[ -f "$src" && ! -L "$src" ]]', 'stat -c %h -- "$src")" == "1"', "(( age >= 60 ))",
              'mv -T -n -- "$src" "$dest"', '[[ ! -e "$src" && -f "$dest" && ! -L "$dest" ]]',
              'chown -h -- "$owner" "$dest"']
    positions = [take.index(check) for check in checks]
    assert positions == sorted(positions), "checked, moved, checked again, and only then given away"
    assert 'install -d -m 2770 -o "$owner" -g bpanel "$BACKUP_INBOX"' in HELPER
    assert 'BACKUP_INBOX="/home/admin/backups"' in HELPER
    assert restore_sources.INBOX_DIR == Path("/home/admin/backups")


def test_the_drop_folder_is_made_on_install_and_on_update():
    for script in ("install.sh", "update.sh"):
        text = (PROJECT_ROOT / "installer" / script).read_text(encoding="utf-8")
        assert 'install -d -o "$inbox_owner" -g bpanel -m 2770 /home/admin/backups' in text, script


# --- another server ----------------------------------------------------------------------

class _Ftp:
    def mlsd(self, folder, facts=None):
        return iter([("user.admin.bob.tar.zst", {"type": "file", "size": "123", "modify": "20261005020000"}),
                     ("user-carol-Mon.tar.gz", {"type": "file", "size": "45", "modify": "20261004020000"}),
                     ("notes.txt", {"type": "file", "size": "1"})])


def test_another_server_lists_directadmin_archives_too():
    rows = restore_sources._ftp_list(_Ftp(), "/backup")
    assert [(row["key"], row["kind"], row["username"]) for row in rows] == [
        ("/backup/user.admin.bob.tar.zst", "directadmin", "bob"),
        ("/backup/user-carol-Mon.tar.gz", "bpanel", "carol"),
    ]
    remote = {"kind": "remote", "protocol": "ftp", "path": "/backup"}
    assert restore_sources.check_key(remote, "/backup/user.admin.bob.tar.zst") == "user.admin.bob.tar.zst"
    assert restore_sources.key_kind(remote, "/backup/user.admin.bob.tar.zst") == "directadmin"
    with pytest.raises(restore_sources.RestoreSourceError):
        restore_sources.check_key(remote, "/backup/notes.txt")


def test_a_directadmin_download_lands_in_the_da_folder_whole_or_not_at_all(folders):
    def pull(destination):
        Path(destination).write_bytes(b"archive")

    path = restore_sources._stage_da(pull, "user.admin.bob.tar.zst")
    assert path == str(folders.da / "user.admin.bob.tar.zst")
    again = restore_sources._stage_da(pull, "user.admin.bob.tar.zst")
    assert again != path and again.endswith(".tar.zst"), "never over an archive already there"

    def broken(destination):
        Path(destination).write_bytes(b"half")
        raise OSError("connection reset")

    with pytest.raises(OSError):
        restore_sources._stage_da(broken, "user.admin.carol.tar.zst")
    assert sorted(p.name for p in folders.da.iterdir()) == sorted([Path(path).name, Path(again).name])
    for bad in ("../x.tar.zst", "user-bob-1.tar.gz", ".hidden.tar.zst"):
        with pytest.raises(ValueError):
            restore_sources._stage_da(pull, bad)


# --- upload and delete ----------------------------------------------------------------------

def test_an_uploaded_directadmin_archive_goes_to_the_da_folder(folders, monkeypatch):
    monkeypatch.setattr(maintenance, "log_action", lambda *a, **k: None)
    monkeypatch.setattr(da_import, "ensure_backup_dir", lambda: None)
    result = maintenance.restore_upload(
        request=None, files=[UploadFile(file=io.BytesIO(b"zstd bytes"), filename="user.admin.bob.tar.zst")],
        source='{"kind": "local"}', db=None, current_user=SimpleNamespace(id=1, role="admin"))
    assert result == {"uploaded": ["user.admin.bob.tar.zst"]}
    assert (folders.da / "user.admin.bob.tar.zst").read_bytes() == b"zstd bytes"
    with pytest.raises(HTTPException) as caught:
        maintenance.restore_upload(
            request=None, files=[UploadFile(file=io.BytesIO(b"x"), filename="photo.zip")],
            source='{"kind": "local"}', db=None, current_user=SimpleNamespace(id=1, role="admin"))
    assert caught.value.status_code == 400


def test_only_what_was_brought_here_can_be_deleted_from_the_tab(folders):
    (folders.users / "bob").mkdir()
    own = folders.make(folders.users / "bob", "user-bob-1.tar.gz")
    upload = folders.make(folders.users / "restore", "user-bob-2.tar.gz")
    da = folders.make(folders.da, "user.admin.carol.tar.zst")
    inbox = folders.make(folders.inbox, "user.admin.dave.tar.gz")
    for key, path in (("restore/user-bob-2.tar.gz", upload), ("@da/user.admin.carol.tar.zst", da),
                      ("@inbox/user.admin.dave.tar.gz", inbox)):
        restore_sources.delete_local(key)
        assert not path.exists(), key
    with pytest.raises(restore_sources.RestoreSourceError, match="Backup user"):
        restore_sources.delete_local("bob/user-bob-1.tar.gz")
    assert own.exists()


# --- the restore job ----------------------------------------------------------------------

def _queue(results):
    return maintenance._queue_backup_job(SimpleNamespace(id=7, role="admin"), "user_restore", "Restore queued",
                                         results=results)


def test_a_directadmin_archive_goes_through_the_importer_and_its_passwords_stay_with_who_ran_it(folders, monkeypatch):
    archive = folders.make(folders.da, "user.admin.bob.tar.zst")
    calls = []

    def importer(path, force=False, replace_own=False):
        calls.append((Path(path).name, force, replace_own))
        return {"summary": [{"username": "bob", "imported_domains": ["bob.test"]}],
                "credentials": ["bob panel password: s3cret-generated"], "errors": []}

    monkeypatch.setattr(da_import, "import_da_backup", importer)
    monkeypatch.setattr(maintenance.backup, "restore_user_backup",
                        lambda path, db: pytest.fail("a DirectAdmin archive reached the panel restore"))
    monkeypatch.setattr(maintenance, "SessionLocal", lambda: SimpleNamespace(rollback=lambda: None, close=lambda: None,
                                                                             get=lambda *a: None))
    monkeypatch.setattr(maintenance, "log_action", lambda *a, **k: None)
    job = _queue([{"name": archive.name, "username": "bob", "kind": "directadmin", "status": "queued", "detail": ""}])
    maintenance._run_restore_job(job["job_id"], 7, {"kind": "local"},
                                 [{"key": f"@da/{archive.name}", "size": 10, "username": "bob"}])
    assert calls == [("user.admin.bob.tar.zst", False, True)], "overwrite its own account, nothing more"
    stored = maintenance._get_backup_job(job["job_id"])
    mine = maintenance._public_backup_job(stored, 7)
    assert mine["status"] == "done" and mine["results"][0]["status"] == "done"
    assert "Imported 1 domain(s): bob.test" in mine["results"][0]["detail"]
    assert mine["results"][0]["credentials"] == ["bob panel password: s3cret-generated"]
    for viewer in (8, None):
        assert "s3cret" not in repr(maintenance._public_backup_job(stored, viewer)), viewer
    assert archive.exists(), "an archive that was already here stays"


def test_a_directadmin_import_that_imported_nothing_is_a_failure(monkeypatch):
    monkeypatch.setattr(da_import, "import_da_backup", lambda path, force=False, replace_own=False: {
        "summary": [{"username": "bob", "imported_domains": [], "warnings": ["x"]}],
        "credentials": [], "errors": ["Already exists: website 'bob.test', owned by another account. Nothing was changed."]})
    with pytest.raises(RuntimeError, match="owned by another account"):
        maintenance._restore_directadmin("/x/user.admin.bob.tar.zst")


# --- overwrite only what is the account's own --------------------------------------------------

@pytest.fixture
def db(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(da_import, "SessionLocal", session_factory)
    monkeypatch.setattr(da_import, "STAGE_BASE", tmp_path / "stage")
    monkeypatch.setattr(da_import, "DA_BACKUP_DIR", tmp_path / "da")
    (tmp_path / "da").mkdir()
    return session_factory


def _da_archive(folder: Path, username: str, domain: str) -> Path:
    path = folder / f"user.admin.{username}.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        for name, body in (("backup/user.conf", f"username={username}\n"), ("backup/domains.list", f"{domain}\n")):
            data = body.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def _account(session, username: str, domain: str | None = None) -> User:
    user = User(username=username, email=f"{username}@x.test", hashed_password="x", role="end_user")
    session.add(user)
    session.flush()
    if domain:
        session.add(Website(domain=domain, owner_id=user.id, root_path=f"/home/{username}/{domain}",
                            linux_user=username, php_version="8.3", app_type="php"))
    session.commit()
    return user


class _Proceeded(Exception):
    pass


def test_replace_own_overwrites_the_account_and_its_own_site(db, monkeypatch, tmp_path):
    with db() as session:
        _account(session, "bob", "bob.test")
    deleted = []
    monkeypatch.setattr(da_import, "_delete_existing_domain", lambda s, domain: deleted.append(domain))

    def stop(s, username):
        deleted.append(username)
        raise _Proceeded

    monkeypatch.setattr(da_import, "_delete_existing_user", stop)
    archive = _da_archive(tmp_path / "da", "bob", "bob.test")
    with pytest.raises(_Proceeded):
        da_import.import_da_backup(str(archive), replace_own=True)
    assert deleted == ["bob.test", "bob"]


def test_replace_own_stops_at_a_site_of_another_account(db, monkeypatch, tmp_path):
    with db() as session:
        _account(session, "bob")
        _account(session, "alice", "bob.test")
    monkeypatch.setattr(da_import, "_delete_existing_domain",
                        lambda s, domain: pytest.fail(f"deleted {domain}, which is alice's"))
    archive = _da_archive(tmp_path / "da", "bob", "bob.test")
    result = da_import.import_da_backup(str(archive), replace_own=True)
    assert result["errors"] == ["Already exists: website 'bob.test', owned by another account. Nothing was changed."]


def test_without_either_flag_an_existing_account_still_stops_the_import(db, monkeypatch, tmp_path):
    with db() as session:
        _account(session, "bob", "bob.test")
    monkeypatch.setattr(da_import, "_delete_existing_user", lambda s, u: pytest.fail("deleted a live account"))
    result = da_import.import_da_backup(str(_da_archive(tmp_path / "da", "bob", "bob.test")))
    assert "panel user 'bob'" in result["errors"][0] and "Re-run with force" in result["errors"][0]


# --- the page --------------------------------------------------------------------------------

def test_the_da_import_tab_is_folded_into_restore():
    assert "activeBackupTab === 'da-import'" not in APP
    assert "['da-import', 'DA Import', ArchiveRestore]" not in APP
    tab = APP.split("  function renderRestoreWizard() {")[1].split("\n  function ")[0]
    assert ".tar.zst" in tab, "Upload backups takes DirectAdmin archives"
    assert "restore-kind" in tab, "each row says which kind it is"
    assert "/home/admin/backups" in tab, "This server says where the SFTP folder is"
