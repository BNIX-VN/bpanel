"""Full-user backup archives: which ones BPanel agrees to restore."""

import json
import tarfile

from app.services import backup


def _manifest_archive(tmp_path, manifest: dict, name: str = "user-x-20260901.tar.gz"):
    archive = tmp_path / name
    path = tmp_path / backup.BACKUP_MANIFEST
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(path, arcname=backup.BACKUP_MANIFEST)
    return archive


def test_describe_accepts_an_opanel_user_backup(tmp_path, monkeypatch):
    archive = _manifest_archive(tmp_path, {
        "kind": "opanel_user",
        "user": {"username": "shop"},
        "websites": [{"domain": "shop.vn"}, {"domain": "blog.vn"}],
    })
    monkeypatch.setattr(backup, "user_backup_path", lambda name: archive)

    described = backup.describe_user_backup(archive.name)

    assert described["valid"] is True
    assert described["source"] == "opanel"
    assert described["websites"] == 2
    assert described["error"] == ""


def test_describe_marks_a_bpanel_backup_as_its_own(tmp_path, monkeypatch):
    archive = _manifest_archive(tmp_path, {
        "kind": "bpanel_user",
        "user": {"username": "shop"},
        "websites": [],
    })
    monkeypatch.setattr(backup, "user_backup_path", lambda name: archive)

    described = backup.describe_user_backup(archive.name)

    assert described["valid"] is True
    assert described["source"] == "bpanel"


def test_describe_rejects_an_unknown_kind(tmp_path, monkeypatch):
    archive = _manifest_archive(tmp_path, {"kind": "cpanel_user"})
    monkeypatch.setattr(backup, "user_backup_path", lambda name: archive)

    described = backup.describe_user_backup(archive.name)

    assert described["valid"] is False
    assert "opanel" in described["error"]


def test_restore_refuses_a_non_user_archive(tmp_path, monkeypatch):
    archive = _manifest_archive(tmp_path, {"kind": "website"})
    monkeypatch.setattr(backup, "user_backup_path", lambda name: archive)

    try:
        backup.restore_user_backup(archive.name, db=None)
    except ValueError as exc:
        assert "opanel" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("restore_user_backup accepted a non-user archive")


def test_per_site_restore_stages_into_a_panel_dir_not_the_site_root(tmp_path, monkeypatch):
    """restore_backup must extract into the panel-owned staging area and hand
    the tree to the site user via the helper - never extract as the panel
    account straight into the (customer-owned) site root, which the customer
    could race (TOCTOU)."""
    import io
    from pathlib import Path
    from types import SimpleNamespace
    from app.services import site_users

    monkeypatch.setattr(backup.settings, "backup_root", str(tmp_path / "backups"))
    monkeypatch.setattr(site_users, "IMPORT_STAGE_BASE", tmp_path / "stage")
    domain = "shop.vn"
    bdir = tmp_path / "backups" / domain
    bdir.mkdir(parents=True)
    archive = bdir / "b.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        blob = b"<?php echo 1;"
        info = tarfile.TarInfo("site/public_html/index.php")
        info.size = len(blob)
        tar.addfile(info, io.BytesIO(blob))

    captured = {}

    def fake_import(root_path, linux_user, staged):
        captured["root_path"] = root_path
        captured["linux_user"] = linux_user
        captured["staged"] = staged
        captured["files"] = sorted(p.name for p in Path(staged).rglob("*.php"))

    monkeypatch.setattr(site_users, "import_site_files", fake_import)
    site_root = tmp_path / "home" / "khach" / domain
    website = SimpleNamespace(domain=domain, root_path=str(site_root), linux_user="khach")

    backup.restore_backup(website, str(archive))

    assert captured["linux_user"] == "khach"
    assert captured["root_path"] == str(Path(site_root).resolve())
    # Extraction landed in the panel-owned staging area, with the site/ prefix
    # stripped, and never in the real site root.
    assert str(site_users.IMPORT_STAGE_BASE) in captured["staged"]
    assert captured["files"] == ["index.php"]
    assert not any(site_root.rglob("*.php"))
