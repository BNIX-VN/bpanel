"""Addons from a repository of their own, and the backup destinations they
bring (operator, 2026-11-16: a Google Drive backup addon "nằm ở gitlab độc
lập. Cần dùng thì chạy lệnh cài vào"). A stand-in addon, written to a
folder as `bpanel addon install` would leave it, goes the whole way: loaded,
a destination made, signed in, tested, a schedule's archive sent, listed and
fetched back for a restore."""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import addons as addons_api
from app.api import maintenance
from app.core.database import Base
from app.models.entities import SftpBackupTarget, User
from app.schemas.schemas import SftpBackupTargetCreate, SftpBackupTargetUpdate
from app.services import addons, backup_scheduler, destinations, external_addons, restore_sources

ROOT = Path(__file__).resolve().parents[3]

DRIVER = '''
class Driver:
    kind = "fake"
    label = "Fake Drive"
    auth = "oauth_device"
    fields = [{"name": "folder", "label": "Folder", "type": "text", "required": True},
              {"name": "token", "label": "Token", "type": "password", "secret": True}]

    def __init__(self):
        self.files = {}

    def validate(self, fields, config):
        if not fields.get("folder"):
            from app.services.destinations import DestinationError
            raise DestinationError("Name the folder")
        return {**config, "folder": fields["folder"]}

    def summary(self, config):
        return "folder " + config.get("folder", "")

    def connected(self, config):
        return bool(config.get("refresh_token"))

    def connect_start(self, config):
        config["device_code"] = "dev-1"
        return {"verification_url": "https://www.google.com/device", "user_code": "ABCD-EFGH",
                "expires_in": 1800, "interval": 5}

    def connect_poll(self, config):
        config.pop("device_code", None)
        config["refresh_token"] = "secret-refresh-token"
        return "done"

    def test(self, config):
        return "wrote and removed a probe"

    def upload(self, config, local_file, remote_name, on_progress=None):
        with open(local_file, "rb") as handle:
            self.files[remote_name] = handle.read()
        return config["folder"] + "/" + remote_name

    def listing(self, config):
        return [{"key": "id-%d/%s" % (i, name), "name": name, "size": len(data), "modified": "2026-11-16T00:00:00"}
                for i, (name, data) in enumerate(sorted(self.files.items()))]

    def download(self, config, key, destination, on_progress=None):
        with open(destination, "wb") as handle:
            handle.write(self.files[key.split("/", 1)[1]])

    def delete(self, config, key):
        self.files.pop(key.split("/", 1)[1], None)


driver = Driver()


def register(panel):
    panel.register_destination(driver)
'''


@pytest.fixture
def addon(tmp_path, monkeypatch):
    root = tmp_path / "addons"
    (root / "fake" / "fakemod").mkdir(parents=True)
    (root / "fake" / "addon.json").write_text(json.dumps(
        {"id": "fake", "name": "Fake", "version": "1.2.3", "panel_api": 1, "module": "fakemod", "kinds": ["fake"]}))
    (root / "fake" / "fakemod" / "__init__.py").write_text(DRIVER)
    monkeypatch.setattr(external_addons, "ROOT", root)
    monkeypatch.setitem(external_addons.KNOWN, "fake", {"name": "Fake", "project": "bnix/addon-fake",
                                                        "summary": "s", "details": []})
    monkeypatch.setattr(external_addons, "_trusted", lambda path: True)   # no root on a test machine
    monkeypatch.setattr(external_addons, "_loaded", {})
    monkeypatch.setattr(destinations, "_drivers", {})
    monkeypatch.setattr(destinations, "_addon_of", {})
    monkeypatch.setitem(addons.CATALOGUE, "fake", external_addons.catalogue_entries()["fake"])
    installed = {"fake": True}
    monkeypatch.setattr(addons, "is_installed", lambda slug: installed.get(slug, False))
    return SimpleNamespace(root=root, installed=installed)


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(maintenance, "log_action", lambda *a, **k: None)
    monkeypatch.setattr(addons_api, "log_action", lambda *a, **k: None)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(User(id=1, username="admin", email="a@example.test", role="admin", hashed_password="x", is_active=True))
    session.commit()
    yield session
    session.close()


def _make(db, folder="BPanel backups"):
    payload = SftpBackupTargetCreate(name="drive", kind="fake", options={"folder": folder})
    return maintenance.create_sftp_target(payload, request=None, db=db, current_user=db.get(User, 1))


def test_an_installed_addon_is_loaded_and_offers_its_kind(addon):
    assert external_addons.load_installed(addons.is_installed) == ["fake"]
    kinds = destinations.kinds()
    assert [k["kind"] for k in kinds] == ["sftp", "s3", "fake"]
    assert kinds[2]["label"] == "Fake Drive" and kinds[2]["auth"] == "oauth_device"
    addon.installed["fake"] = False
    assert [k["kind"] for k in destinations.kinds()] == ["sftp", "s3"], "an addon removed offers nothing"
    with pytest.raises(destinations.DestinationError):
        destinations.driver_for("fake")


def test_a_destination_of_the_kind_is_made_signed_in_and_tested(addon, db):
    out = _make(db)
    assert (out.kind, out.kind_label, out.summary, out.connected) == ("fake", "Fake Drive", "folder BPanel backups", False)
    assert out.options == {"folder": "BPanel backups"}, "the form's own fields, never a secret one"
    row = db.get(SftpBackupTarget, out.id)
    assert row.config and "BPanel" not in row.config, "kept encrypted"
    prompt = maintenance.connect_destination(out.id, request=None, db=db, current_user=db.get(User, 1))
    assert prompt == {"verification_url": "https://www.google.com/device", "user_code": "ABCD-EFGH",
                      "expires_in": 1800, "interval": 5}
    polled = maintenance.poll_destination_connect(out.id, db=db, current_user=db.get(User, 1))
    assert polled["state"] == "done" and polled["destination"].connected
    assert "secret-refresh-token" not in json.dumps(polled["destination"].model_dump())
    assert destinations.read_config(db.get(SftpBackupTarget, out.id))["refresh_token"] == "secret-refresh-token"
    assert maintenance.test_destination(out.id, db=db, current_user=db.get(User, 1))["message"] == "wrote and removed a probe"
    edited = maintenance.update_sftp_target(out.id, SftpBackupTargetUpdate(name="drive", kind="fake", options={"folder": "Other"}),
                                            request=None, db=db, current_user=db.get(User, 1))
    assert edited.summary == "folder Other" and edited.connected, "editing keeps the sign-in"
    with pytest.raises(HTTPException) as exc:
        _make(db, folder="")
    assert exc.value.status_code in (400, 409)


def test_a_schedule_sends_to_it_and_a_restore_lists_and_fetches_from_it(addon, db, tmp_path, monkeypatch):
    out = _make(db)
    archive = tmp_path / "user-bob-20261116.tar.gz"
    archive.write_bytes(b"archive")
    schedule = SimpleNamespace(target_id=out.id, name_suffix="day_of_week")
    sent = backup_scheduler._upload_if_configured(db, schedule, str(archive))
    assert re.fullmatch(r"drive:BPanel backups/user-bob-[\w-]+\.tar\.gz", sent)

    listed = restore_sources._list_archives({"kind": "target", "target_id": out.id}, db)
    assert listed["location"] == "Fake Drive: folder BPanel backups"
    item = listed["items"][0]
    assert item["key"].startswith("id-0/user-bob-") and item["size"] == 7

    monkeypatch.setattr(restore_sources, "users_dir", lambda: tmp_path / "users")
    monkeypatch.setattr(restore_sources.backup, "user_restore_dir", lambda: str(tmp_path / "users"))
    monkeypatch.setattr(restore_sources.backup, "stage_remote_backup",
                        lambda pull, name: (pull(str(tmp_path / "users" / name)), name)[1])
    source = {"kind": "target", "target_id": out.id}
    name = restore_sources.check_key(source, item["key"])
    path, is_copy = restore_sources.fetch(source, item["key"], item["size"], db)
    assert Path(path).name == name and Path(path).read_bytes() == b"archive" and is_copy


def test_the_addon_is_not_removed_while_its_destinations_are_left(addon, db):
    _make(db)
    with pytest.raises(HTTPException) as exc:
        addons_api.perform_uninstall("fake", db, 1)
    assert exc.value.status_code == 409 and "drive" in exc.value.detail


def test_a_file_the_panel_user_could_write_is_never_loaded(addon, monkeypatch):
    monkeypatch.setattr(external_addons, "_trusted", lambda path: path.name != "__init__.py")
    with pytest.raises(external_addons.AddonError, match="not root's alone"):
        external_addons.load("fake")
    assert "fake" not in destinations._drivers


@pytest.mark.parametrize("mode, uid, trusted", [(0o100644, 0, True), (0o100664, 0, False),
                                                (0o100646, 0, False), (0o100644, 1001, False),
                                                (0o120777, 0, False)])
def test_only_roots_files_writable_by_nobody_else_are_trusted(monkeypatch, tmp_path, mode, uid, trusted):
    path = tmp_path / "x"
    monkeypatch.setattr(Path, "lstat", lambda self: SimpleNamespace(st_mode=mode, st_uid=uid))
    assert external_addons._trusted(path) is trusted


def test_an_addon_for_another_panel_api_or_not_itself_is_refused(addon):
    (addon.root / "fake" / "addon.json").write_text(json.dumps({"id": "fake", "panel_api": 2, "module": "fakemod"}))
    with pytest.raises(external_addons.AddonError, match="panel API 2"):
        external_addons.verify("fake")
    (addon.root / "fake" / "addon.json").write_text(json.dumps({"id": "other", "panel_api": 1, "module": "fakemod"}))
    with pytest.raises(external_addons.AddonError, match="not the fake addon"):
        external_addons.verify("fake")


def test_only_the_panels_own_list_names_an_addon_and_the_shell_knows_the_same():
    ctl = (ROOT / "installer" / "files" / "bpanelctl").read_text(encoding="utf-8")
    body = ctl.split("external_addon_project() {")[1].split("\n}\n")[0]
    in_ctl = dict(re.findall(r'^\s+([a-z0-9-]+)\) echo "([^"]+)" ;;', body, re.M))
    assert in_ctl == {slug: entry["project"] for slug, entry in external_addons.KNOWN.items()}
    fetch = ctl.split("fetch_external_addon() {")[1].split("\n}\n")[0]
    assert "local py=(/usr/bin/python3 -I)" in fetch and ".venv" not in fetch, "root never runs the panel's Python"
    assert 'chown -R root:root "$dest.new"' in fetch and "-type l -delete" in fetch


def test_the_kind_is_a_short_word_and_the_options_plain_values():
    with pytest.raises(ValueError):
        SftpBackupTargetCreate(name="x1", kind="Drive!", options={})
    with pytest.raises(ValueError):
        SftpBackupTargetCreate(name="x1", kind="fake", options={"a": {"nested": 1}})
    assert SftpBackupTargetCreate(name="x1", kind="gdrive", options={"folder": "f"}).kind == "gdrive"
