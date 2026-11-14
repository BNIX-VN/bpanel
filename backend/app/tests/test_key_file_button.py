"""A private key can be chosen as a file, a PuTTY .ppk included (operator,
2026-11-14, cPanel import: "Làm chỗ import file đi")."""
from pathlib import Path

from app.services import restore_sources

APP = (Path(__file__).resolve().parents[3] / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")


def test_the_migration_login_and_an_sftp_destination_take_a_key_file():
    assert "function keyFileButton(onLoad" in APP
    assert "keyFileButton(text => editRestoreSsh({ private_key: text })" in APP
    assert "keyFileButton(text => setNewSftpTarget(prev => ({ ...prev, private_key: text })))" in APP
    button = APP.split("function keyFileButton(")[1].split("\n  }\n")[0]
    # id_rsa has no extension: the picker must not filter by one.
    assert "accept=" not in button and "file.text()" in button


def test_an_unreadable_key_says_what_is_taken():
    assert ".ppk" in restore_sources.PRIVATE_KEY_UNREADABLE
    source = Path(restore_sources.__file__).read_text(encoding="utf-8")
    assert "except ppk.PpkError as exc:\n" in source, "a .ppk's own reason reaches the page"
