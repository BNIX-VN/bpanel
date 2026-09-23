"""Object storage as a backup destination, and what the stored file is called.

The naming mode is the part that carries a guarantee. A schedule set to
`none` overwrites one file per account; `day_of_week` rotates through seven;
`week_of_month` through five. Those three bound what accumulates in a bucket
without anything having to delete - which is the guarantee you want when the
machine that would do the deleting is the one that might be compromised.
`full_date` keeps one a day and grows until retention prunes it.
"""

from datetime import date, datetime
from pathlib import Path

import pytest

from app.services import backup, backup_s3

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class _Target:
    """Enough of a target row for the functions under test."""

    kind = "s3"
    endpoint = "s3.wasabisys.com"
    region = "us-east-1"
    bucket = "my-backups"
    access_key = "AK"
    secret_key = "ciphertext"
    prefix = "bpanel/nightly"
    secure = True


# --- what the file is called ------------------------------------------------

WEDNESDAY = datetime(2026, 9, 23, 8, 15)  # a Wednesday, in the fourth week


@pytest.mark.parametrize("mode,expected", [
    ("none", "user-alice.tar.gz"),
    ("day_of_week", "user-alice-Wed.tar.gz"),
    ("week_of_month", "user-alice-W4.tar.gz"),
    ("full_date", "user-alice-2026-09-23.tar.gz"),
])
def test_each_mode_names_the_file_its_own_way(mode, expected):
    assert backup_s3.stored_name("user-alice-20260923081500.tar.gz", mode, when=WEDNESDAY) == expected


def test_the_timestamp_the_panel_adds_is_stripped_first():
    """Otherwise every rotating name would still be unique, defeating the point."""
    name = backup_s3.stored_name("user-alice-20260923081500.tar.gz", "day_of_week", when=WEDNESDAY)
    assert "20260923081500" not in name


def test_a_name_with_no_timestamp_still_works():
    assert backup_s3.stored_name("user-alice.tar.gz", "day_of_week", when=WEDNESDAY) == "user-alice-Wed.tar.gz"


def test_an_unknown_mode_falls_back_to_the_safest_one():
    """Keeping one a day loses nothing. Overwriting on a guess could."""
    assert backup_s3.stored_name("user-alice-20260923081500.tar.gz", "sideways", when=WEDNESDAY) \
        == "user-alice-2026-09-23.tar.gz"
    assert backup_s3.stored_name("user-alice-20260923081500.tar.gz", None, when=WEDNESDAY) \
        == "user-alice-2026-09-23.tar.gz"


def test_something_that_is_not_ours_is_left_alone():
    assert backup_s3.stored_name("someone-elses-file.zip", "none") == "someone-elses-file.zip"


def test_a_path_never_survives_into_the_stored_name():
    assert "/" not in backup_s3.stored_name("/tmp/x/user-alice-20260923081500.tar.gz", "none")


@pytest.mark.parametrize("day,week", [(1, 1), (7, 1), (8, 2), (14, 2), (15, 3), (22, 4), (28, 4), (30, 5)])
def test_week_of_month_counts_from_the_first(day, week):
    """Not ISO weeks: the 1st to the 7th is week 1 whatever weekday that is."""
    assert backup_s3.week_of_month(date(2026, 9, day)) == week


def test_week_of_month_never_exceeds_five():
    assert backup_s3.week_of_month(date(2026, 8, 31)) == 5


def test_rotation_reuses_exactly_one_name_per_bucket():
    """Seven weekdays means seven files, and the eighth day reuses the first."""
    names = {backup_s3.stored_name("user-alice-20260101000000.tar.gz", "day_of_week",
                                   when=datetime(2026, 9, 21 + offset))
             for offset in range(8)}
    assert len(names) == 7


# --- where it goes in the bucket -------------------------------------------

@pytest.mark.parametrize("prefix,expected", [
    ("bpanel/nightly", "bpanel/nightly/a.tar.gz"),
    ("/bpanel/", "bpanel/a.tar.gz"),
    ("", "a.tar.gz"),
    (None, "a.tar.gz"),
])
def test_the_prefix_never_produces_a_leading_slash(prefix, expected):
    assert backup_s3.object_key(prefix, "a.tar.gz") == expected


# --- refusing bad input before it reaches the network ----------------------

def test_a_target_with_no_endpoint_says_so():
    target = _Target()
    target.endpoint = ""
    with pytest.raises(backup_s3.S3Error) as exc:
        backup_s3._client(target)
    assert "endpoint" in str(exc.value)


def test_a_scheme_in_the_endpoint_is_stripped(monkeypatch):
    """minio wants host[:port]; `secure` already carries http vs https."""
    seen = {}

    class _Minio:
        def __init__(self, endpoint, **kwargs):
            seen["endpoint"] = endpoint
            seen.update(kwargs)

    monkeypatch.setitem(__import__("sys").modules, "minio",
                        type("M", (), {"Minio": _Minio}))
    monkeypatch.setattr("app.core.secrets.decrypt", lambda value: "plaintext")

    target = _Target()
    target.endpoint = "https://s3.wasabisys.com/"
    backup_s3._client(target)
    assert seen["endpoint"] == "s3.wasabisys.com"
    assert seen["secure"] is True


@pytest.mark.parametrize("key", ["", "/etc/passwd", "../../etc/passwd", "a/../../b"])
def test_download_refuses_a_key_that_climbs(key):
    with pytest.raises(backup_s3.S3Error):
        backup_s3.download(_Target(), key, "/tmp/x")


@pytest.mark.parametrize("key", ["", "/x", "../x"])
def test_remove_refuses_the_same(key):
    with pytest.raises(backup_s3.S3Error):
        backup_s3.remove(_Target(), key)


# --- reading an account out of a file name ---------------------------------

@pytest.mark.parametrize("name,expected", [
    ("user-alice-20260923081500.tar.gz", "alice"),
    ("user-alice-Mon.tar.gz", "alice"),
    ("user-alice-W3.tar.gz", "alice"),
    ("user-alice-2026-09-23.tar.gz", "alice"),
    ("user-alice.tar.gz", "alice"),
    ("user-some-long-name-Fri.tar.gz", "some-long-name"),
    ("website-example.com-20260101000000.tar.gz", ""),
    ("junk", ""),
])
def test_the_account_is_guessed_from_the_name_for_listing_only(name, expected):
    assert backup.username_from_archive_name(name) == expected


# --- staging something fetched from a bucket -------------------------------

def test_staging_refuses_anything_that_is_not_a_backup_name():
    for bad in ("../escape.tar.gz", "sub/dir.tar.gz", "notanarchive.txt", ""):
        with pytest.raises(ValueError):
            backup.stage_remote_backup(lambda destination: None, bad)


def test_staging_refuses_an_empty_download(tmp_path, monkeypatch):
    """A download that produced nothing must not be handed to restore."""
    monkeypatch.setattr(backup, "_user_restore_dir", lambda: tmp_path)
    with pytest.raises(ValueError) as exc:
        backup.stage_remote_backup(lambda destination: Path(destination).write_bytes(b""),
                                   "user-alice-Mon.tar.gz")
    assert "no file" in str(exc.value)


def test_staging_does_not_overwrite_something_already_there(tmp_path, monkeypatch):
    """Two targets can hold a file of the same name."""
    monkeypatch.setattr(backup, "_user_restore_dir", lambda: tmp_path)
    existing = tmp_path / "user-alice-Mon.tar.gz"
    existing.write_bytes(b"the good one")

    staged = backup.stage_remote_backup(
        lambda destination: Path(destination).write_bytes(b"the new one"),
        "user-alice-Mon.tar.gz",
    )
    assert staged != existing.name
    assert existing.read_bytes() == b"the good one"
    assert (tmp_path / staged).read_bytes() == b"the new one"


# --- the schedule carries the mode -----------------------------------------

def test_the_scheduler_names_the_upload_before_sending_it():
    source = (PROJECT_ROOT / "backend" / "app" / "services" / "backup_scheduler.py").read_text(encoding="utf-8")
    body = source[source.index("def _upload_if_configured"):]
    body = body[:body.index("\ndef _decode_user_ids")]
    assert "backup_s3.stored_name" in body
    assert body.index("stored_name") < body.index("backup_s3.upload"), (
        "the name has to be decided before the upload, not after"
    )
    assert "remote_name=remote_name" in body, "and the SFTP path takes it too"


def test_both_kinds_of_target_go_through_the_same_naming():
    source = (PROJECT_ROOT / "backend" / "app" / "services" / "backup_scheduler.py").read_text(encoding="utf-8")
    body = source[source.index("def _upload_if_configured"):]
    body = body[:body.index("\ndef _decode_user_ids")]
    assert body.count("remote_name") >= 2
