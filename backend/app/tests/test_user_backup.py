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


def test_site_restore_stages_instead_of_extracting_into_the_site():
    """The panel runs as 'bpanel' and cannot write into a site directory - it
    belongs to the site's Linux user, and bpanel only has group read. The
    per-site restore used to call tar.extractall straight into the site and
    died with PermissionError on public_html/index.php the first time it was
    run for real, on both web servers.

    restore_user_backup had the right pattern all along (stage under the
    panel-owned import area, then let the site-populate helper copy it in as
    root); restore_backup now uses it too.
    """
    import inspect

    from app.services import backup as backup_service

    source = inspect.getsource(backup_service.restore_backup)
    assert "import_site_files" in source, "site restore must go through the helper"
    assert "IMPORT_STAGE_BASE" in source, "site restore must stage under the import area"
    # The direct write into the site root is what broke; it must not come back.
    assert "extractall(path=str(destination)" not in source
