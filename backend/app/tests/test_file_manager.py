import io
import stat
import tarfile

import pytest

from app.models.entities import Website
from app.services import file_manager


def _website(root):
    return Website(domain="example.test", owner_id=1, root_path=str(root), linux_user=None)


def test_tar_validation_allows_more_than_legacy_file_limit(tmp_path):
    archive_path = tmp_path / "many.tar.gz"
    destination = tmp_path / "public_html"
    destination.mkdir()

    with tarfile.open(archive_path, "w:gz") as archive:
        for index in range(10005):
            info = tarfile.TarInfo(f"many/file-{index}.txt")
            info.size = 0
            archive.addfile(info, io.BytesIO())

    with tarfile.open(archive_path, "r:gz") as archive:
        assert file_manager._tar_uncompressed_size(archive, destination, archive_path, allow_executable=True) == 0


def test_extract_tar_reopens_after_validation(tmp_path):
    root = tmp_path / "site"
    public = root / "public_html"
    public.mkdir(parents=True)
    archive_path = public / "site.tar.gz"
    content = b"hello from archive"

    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo("app/index.php")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))

    file_manager.extract_archive(
        _website(root),
        "public_html/site.tar.gz",
        "public_html",
        allow_executable=True,
    )

    assert (public / "app" / "index.php").read_bytes() == content


def test_extract_tar_does_not_overwrite_source_archive(tmp_path):
    root = tmp_path / "site"
    public = root / "public_html"
    public.mkdir(parents=True)
    archive_path = public / "site.tar.gz"

    with tarfile.open(archive_path, "w:gz") as archive:
        payload = b"this would truncate the source archive without the guard"
        info = tarfile.TarInfo("site.tar.gz")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    original = archive_path.read_bytes()

    file_manager.extract_archive(
        _website(root),
        "public_html/site.tar.gz",
        "public_html",
        allow_executable=True,
    )

    assert archive_path.read_bytes() == original
    with tarfile.open(archive_path, "r:gz") as archive:
        assert archive.getnames() == ["site.tar.gz"]


def test_chmod_entry_updates_mode(tmp_path):
    root = tmp_path / "site"
    public = root / "public_html"
    public.mkdir(parents=True)
    target = public / ".env"
    target.write_text("APP_ENV=local\n", encoding="utf-8")

    file_manager.chmod_entry(_website(root), "public_html/.env", "600")

    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert file_manager.list_files(_website(root), "public_html")[0]["mode"] == "600"


def test_copy_entries_copies_files_and_folders(tmp_path):
    root = tmp_path / "site"
    public = root / "public_html"
    public.mkdir(parents=True)
    (public / "index.php").write_text("hello", encoding="utf-8")
    (public / "assets").mkdir()
    (public / "assets" / "app.css").write_text("body{}", encoding="utf-8")
    destination = root / "copies"
    destination.mkdir()

    copied = file_manager.copy_entries(
        _website(root),
        ["public_html/index.php", "public_html/assets"],
        "copies",
        allow_executable=True,
    )

    assert len(copied) == 2
    assert (destination / "index.php").read_text(encoding="utf-8") == "hello"
    assert (destination / "assets" / "app.css").read_text(encoding="utf-8") == "body{}"
    assert (public / "index.php").exists()


def test_move_entries_moves_files_and_folders(tmp_path):
    root = tmp_path / "site"
    public = root / "public_html"
    public.mkdir(parents=True)
    (public / "index.php").write_text("hello", encoding="utf-8")
    (public / "assets").mkdir()
    (public / "assets" / "app.css").write_text("body{}", encoding="utf-8")
    destination = root / "moved"
    destination.mkdir()

    moved = file_manager.move_entries(
        _website(root),
        ["public_html/index.php", "public_html/assets"],
        "moved",
        allow_executable=True,
    )

    assert len(moved) == 2
    assert (destination / "index.php").read_text(encoding="utf-8") == "hello"
    assert (destination / "assets" / "app.css").read_text(encoding="utf-8") == "body{}"
    assert not (public / "index.php").exists()
    assert not (public / "assets").exists()


def test_move_entries_rejects_folder_into_itself(tmp_path):
    root = tmp_path / "site"
    public = root / "public_html"
    nested = public / "assets" / "nested"
    nested.mkdir(parents=True)

    with pytest.raises(ValueError, match="folder into itself"):
        file_manager.move_entries(
            _website(root),
            ["public_html/assets"],
            "public_html/assets/nested",
            allow_executable=True,
        )
