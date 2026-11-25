"""An account restore reads its archive once (36.50.27.11 -> 163.61.73.40,
2026-11-25: 14 sites in a 2.7 GB archive took hours, because every site,
database and mailbox started decompressing the .tar.gz over from the top).

What must hold: what a restore takes out of the unpacked archive is exactly
what it took out member by member; the archive is opened once for all of it;
and anything the old way refused or handled differently - a link out of its
folder, a disk that cannot take the archive, a folder asked for twice - goes
the old way.
"""
import io
import tarfile
from pathlib import Path

import pytest

from app.services import backup


def _archive(path: Path, files: dict, links: dict | None = None) -> Path:
    with tarfile.open(path, "w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for name, target in (links or {}).items():
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            tar.addfile(info)
    return path


FILES = {
    "manifest.json": b"{}",
    "sites/a.test/site/public_html/index.php": b"<?php echo 'a';",
    "sites/a.test/site/public_html/wp-content/uploads/x.bin": bytes(range(256)) * 4,
    "sites/b.test/site/public_html/index.html": b"b",
    "databases/a.test.sql": b"CREATE TABLE t (ip BINARY(16));\nINSERT INTO t VALUES ('\xff\xfe');\n",
    "mail/a.test/info/cur/1": b"From: x\n\nhello",
}


def _tree(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


@pytest.fixture
def unpacked(tmp_path):
    archive = _archive(tmp_path / "user-bob.tar.gz", FILES)
    root = backup._unpack_archive(archive, tmp_path / "stage" / "unpacked")
    assert root is not None
    backup._UNPACKED[str(archive)] = (root, set())
    yield archive
    backup._UNPACKED.pop(str(archive), None)


def test_what_comes_out_is_what_came_out_member_by_member(tmp_path, unpacked):
    archive = unpacked
    old = tmp_path / "old-archive.tar.gz"
    old.write_bytes(archive.read_bytes())
    for prefix in ("sites/a.test/site", "sites/b.test/site", "mail/a.test/info", "sites/none.test/site"):
        backup._safe_extract_prefix(old, prefix, tmp_path / "old" / prefix)
        backup._safe_extract_prefix(archive, prefix, tmp_path / "new" / prefix)
        assert _tree(tmp_path / "new" / prefix) == _tree(tmp_path / "old" / prefix)
    assert _tree(tmp_path / "new" / "sites/a.test/site")["public_html/wp-content/uploads/x.bin"] == bytes(range(256)) * 4
    for member in ("databases/a.test.sql", "databases/missing.sql"):
        a = backup._extract_member_to_file(old, member, tmp_path / "old-sql")
        b = backup._extract_member_to_file(archive, member, tmp_path / "new-sql")
        assert (a and a.read_bytes()) == (b and b.read_bytes())
    assert b"\xff\xfe" in (tmp_path / "new-sql" / "a.test.sql").read_bytes()


def test_the_archive_is_opened_once_for_every_site_database_and_mailbox(tmp_path, unpacked, monkeypatch):
    opened = []
    real_open = tarfile.open
    monkeypatch.setattr(backup.tarfile, "open", lambda *a, **k: opened.append(a[0]) or real_open(*a, **k))
    for prefix in ("sites/a.test/site", "sites/b.test/site", "mail/a.test/info"):
        backup._safe_extract_prefix(unpacked, prefix, tmp_path / "out" / prefix)
    backup._extract_member_to_file(unpacked, "databases/a.test.sql", tmp_path / "sql")
    assert opened == []


def test_a_folder_asked_for_twice_is_read_from_the_archive_again(tmp_path, unpacked):
    backup._safe_extract_prefix(unpacked, "sites/a.test/site", tmp_path / "first")
    backup._safe_extract_prefix(unpacked, "sites/a.test/site", tmp_path / "second")
    assert _tree(tmp_path / "second") == _tree(tmp_path / "first") != {}


def test_a_link_out_of_its_site_unpacks_nothing(tmp_path):
    archive = _archive(tmp_path / "user-bob.tar.gz", FILES,
                       links={"sites/a.test/site/public_html/evil": "../../../b.test/site/public_html/index.html"})
    assert backup._unpack_archive(archive, tmp_path / "unpacked") is None
    assert not (tmp_path / "unpacked").exists()


def test_a_disk_that_cannot_take_it_unpacks_nothing(tmp_path, monkeypatch):
    archive = _archive(tmp_path / "user-bob.tar.gz", FILES)
    monkeypatch.setattr(backup, "UNPACK_DISK_RESERVE", 1 << 62)
    assert backup._unpack_archive(archive, tmp_path / "unpacked") is None
    assert not (tmp_path / "unpacked").exists()


def test_a_stale_entry_reads_the_archive_again(tmp_path):
    archive = _archive(tmp_path / "user-bob.tar.gz", FILES)
    root = backup._unpack_archive(archive, tmp_path / "unpacked")
    backup._UNPACKED[str(archive)] = (root, set())
    import shutil

    shutil.rmtree(root)  # tmp_dir goes at the end of the restore
    backup._safe_extract_prefix(archive, "sites/b.test/site", tmp_path / "out")
    assert _tree(tmp_path / "out") == {"public_html/index.html": b"b"}
    backup._UNPACKED.pop(str(archive), None)
