"""One unreadable directory must not cost the operator the whole user backup.

160.236.192.167, 2026-10-24: the scheduled backup of "admin" failed with

    [Errno 13] Permission denied:
    '/home/admin/vodien.vn/backups/rapls-m16-callback-profiler'

a plugin's 0700 directory, made by site PHP running as the site user.
tarfile.add() walks a tree itself and aborts on the first entry it cannot
open; the walk now records what it skipped, as OPanel's does.
"""
import inspect
import os
import tarfile

from app.services import backup


def _tree(tmp_path):
    root = tmp_path / "site"
    (root / "public_html").mkdir(parents=True)
    (root / "public_html" / "index.php").write_text("x", encoding="utf-8")
    locked = root / "backups" / "rapls-m16-callback-profiler"
    locked.mkdir(parents=True)
    (locked / "samples.jsonl").write_text("{}", encoding="utf-8")
    return root, locked


def test_an_unreadable_directory_is_recorded_not_fatal(tmp_path, monkeypatch):
    root, locked = _tree(tmp_path)
    real_iterdir = backup.Path.iterdir

    def gated(self):
        if os.path.abspath(str(self)) == os.path.abspath(str(locked)):
            raise PermissionError(13, "Permission denied", str(locked))
        return real_iterdir(self)

    monkeypatch.setattr(backup.Path, "iterdir", gated)
    skipped = []
    with tarfile.open(tmp_path / "out.tar.gz", "w:gz") as tar:
        backup._add_tree(tar, root, "sites/vodien.vn/site", skipped)

    assert [item["path"] for item in skipped] == [str(locked)]
    with tarfile.open(tmp_path / "out.tar.gz") as tar:
        names = tar.getnames()
    assert "sites/vodien.vn/site/public_html/index.php" in names
    assert "sites/vodien.vn/site/backups/rapls-m16-callback-profiler" in names
    assert not any(name.endswith("samples.jsonl") for name in names)


def test_a_symlinked_directory_is_stored_not_walked(tmp_path):
    root, _ = _tree(tmp_path)
    try:
        (root / "public_html" / "loop").symlink_to(root, target_is_directory=True)
    except OSError:  # pragma: no cover - no symlinks on this machine
        return
    skipped = []
    with tarfile.open(tmp_path / "out.tar.gz", "w:gz") as tar:
        backup._add_tree(tar, root, "sites/s/site", skipped)
    with tarfile.open(tmp_path / "out.tar.gz") as tar:
        names = tar.getnames()
    assert "sites/s/site/public_html/loop" in names
    assert not any("loop/public_html" in name for name in names)


def test_the_user_backup_walks_sites_with_the_recording_walk():
    source = inspect.getsource(backup.create_user_backup)
    assert '_add_tree(tar, root, f"sites/{website.domain}/site", skipped)' in source
    assert "tar.add(root," not in source
    assert "BACKUP_SKIPPED" in source


def test_the_message_names_a_few_and_counts_the_rest():
    skipped = [{"path": f"/home/a/s/f{i}", "reason": "denied"} for i in range(5)]
    message = backup.describe_skipped(skipped)
    assert message.startswith("5 unreadable file(s) were skipped (/home/a/s/f0, /home/a/s/f1, /home/a/s/f2, and 2 more)")
    assert backup.describe_skipped([]) == ""
