"""Tests for the DirectAdmin backup import service."""

import tarfile

import pytest

from app.services import da_import


def _make_da_backup(tmp_path, name="user.admin.demo.tar", pointers=None):
    """Build a minimal DirectAdmin-shaped account backup."""
    src = tmp_path / f"src-{name}"
    backup = src / "backup"
    backup.mkdir(parents=True)
    (backup / "user.conf").write_text("username=demo\nemail=demo@example.com\n", encoding="utf-8")
    (backup / "domains.list").write_text("example.com\n", encoding="utf-8")
    if pointers is not None:
        (backup / "example.com.pointers").write_text(pointers, encoding="utf-8")

    public = src / "domains" / "example.com" / "public_html"
    public.mkdir(parents=True)
    (public / "index.php").write_text("<?php echo 'hi';", encoding="utf-8")
    (public / "wp-config.php").write_text(
        "<?php define('DB_NAME', 'demo_wp'); define('DB_USER', 'demo_wp');", encoding="utf-8"
    )
    (src / "demo_wp.sql").write_text("CREATE TABLE t (id int);\n", encoding="utf-8")

    archive = tmp_path / name
    with tarfile.open(archive, "w") as handle:
        handle.add(src, arcname=".")
    return archive


class TestSafeExtract:
    def test_extracts_seekable_archive(self, tmp_path):
        archive = _make_da_backup(tmp_path)
        dest = tmp_path / "out"

        da_import._safe_extract_tar(archive, dest)

        assert (dest / "backup" / "user.conf").is_file()
        assert (dest / "domains" / "example.com" / "public_html" / "index.php").is_file()

    def test_extracts_non_seekable_stream(self, tmp_path, monkeypatch):
        """The .tar.zst path pipes through zstd, so the tar stream is read once.

        Regression test: validating members in a separate pass consumed the
        stream and extractall then raised StreamError / wrote nothing.
        """
        archive = _make_da_backup(tmp_path, name="user.admin.demo.tar.zst")
        plain = _make_da_backup(tmp_path, name="plain.tar")
        dest = tmp_path / "out-stream"

        class FakePopen:
            def __init__(self, *args, **kwargs):
                self.stdout = open(plain, "rb")
                self.stderr = None
                self.returncode = 0

            def wait(self):
                return 0

        monkeypatch.setattr(da_import.shutil, "which", lambda name: "/usr/bin/zstdcat")
        monkeypatch.setattr(da_import.subprocess, "Popen", FakePopen)

        da_import._safe_extract_tar(archive, dest)

        assert (dest / "backup" / "domains.list").is_file()
        assert (dest / "domains" / "example.com" / "public_html" / "index.php").is_file()

    def test_rejects_path_escaping_destination(self, tmp_path):
        archive = tmp_path / "evil.tar"
        payload = tmp_path / "payload.txt"
        payload.write_text("x", encoding="utf-8")
        with tarfile.open(archive, "w") as handle:
            handle.add(payload, arcname="../escaped.txt")

        with pytest.raises(RuntimeError, match="Unsafe path"):
            da_import._safe_extract_tar(archive, tmp_path / "out")


class TestUploadName:
    def test_strips_directory_components(self):
        assert da_import.safe_upload_name("backup.tar.gz") == "backup.tar.gz"
        assert da_import.safe_upload_name("/etc/cron.d/../backup.tar.gz") == "backup.tar.gz"
        assert da_import.safe_upload_name("..\\..\\backup.tar.gz") == "backup.tar.gz"

    def test_rejects_traversal_and_bad_types(self):
        for name in ("../../etc/cron.d/evil", "..", "", ".hidden.tar.gz", "shell.php", "notes.txt"):
            with pytest.raises(ValueError):
                da_import.safe_upload_name(name)


class TestResolveBackupPath:
    def test_accepts_paths_inside_backup_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(da_import, "DA_BACKUP_DIR", tmp_path)
        target = tmp_path / "user.demo.tar.gz"
        target.write_text("x", encoding="utf-8")

        assert da_import.resolve_backup_path(str(target)) == target.resolve()
        assert da_import.resolve_backup_path("user.demo.tar.gz") == target.resolve()

    def test_rejects_paths_outside_backup_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(da_import, "DA_BACKUP_DIR", tmp_path / "da")
        (tmp_path / "da").mkdir()

        for value in ("../../etc/passwd", str(tmp_path / "elsewhere.tar.gz"), ""):
            with pytest.raises(ValueError):
                da_import.resolve_backup_path(value)


class TestDomainPointers:
    def test_reads_mode_from_pointer_file(self, tmp_path):
        root = tmp_path / "extracted"
        (root / "backup").mkdir(parents=True)
        (root / "backup" / "example.com.pointers").write_text(
            "alias.com=alias\nold-name.com=redirect\n# comment\n\nexample.com=alias\n",
            encoding="utf-8",
        )

        assert da_import._discover_domain_pointers(root, "example.com") == [
            ("alias.com", "alias"),
            ("old-name.com", "redirect"),
        ]

    def test_bare_domain_lines_default_to_alias(self, tmp_path):
        root = tmp_path / "extracted"
        (root / "domains" / "example.com").mkdir(parents=True)
        (root / "domains" / "example.com" / "domain.pointers").write_text(
            "alias.com\n", encoding="utf-8"
        )

        assert da_import._discover_domain_pointers(root, "example.com") == [("alias.com", "alias")]

    def test_missing_pointer_file_is_empty(self, tmp_path):
        assert da_import._discover_domain_pointers(tmp_path, "example.com") == []


class TestScan:
    def test_scan_reports_domains_databases_and_aliases(self, tmp_path, monkeypatch):
        monkeypatch.setattr(da_import, "DA_BACKUP_DIR", tmp_path)
        monkeypatch.setattr(da_import, "STAGE_BASE", tmp_path / "stage")
        archive = _make_da_backup(tmp_path, name="user.admin.demo.tar", pointers="alias.com=alias\n")

        result = da_import.scan_da_backup(str(archive))

        assert result["errors"] == []
        assert len(result["users"]) == 1
        user = result["users"][0]
        assert user["username"] == "demo"
        domain = user["domains"][0]
        assert domain["domain"] == "example.com"
        assert domain["app_type"] == "wordpress"
        assert domain["db_name"] == "demo_wp"
        assert domain["has_sql_dump"] is True
        assert domain["aliases"] == [{"domain": "alias.com", "mode": "alias"}]

    def test_scan_rejects_path_outside_backup_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(da_import, "DA_BACKUP_DIR", tmp_path / "da")
        (tmp_path / "da").mkdir()
        outside = tmp_path / "outside.tar.gz"
        outside.write_text("x", encoding="utf-8")

        with pytest.raises(ValueError):
            da_import.scan_da_backup(str(outside))
