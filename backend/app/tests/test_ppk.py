"""PuTTY .ppk keys are read (operator, 2026-11-14: a .ppk pasted into cPanel
import was refused as unreadable). The fixtures were made by PuTTYgen 0.81
(putty-tools): each type in format 3 and format 2, without and with the
passphrase "test-pass", and the OpenSSH public key PuTTYgen printed for it.
They are test keys, used for nothing else. Same file in OPanel and BPanel."""
from pathlib import Path

import pytest

from app.services import backup, ppk

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ppk"
KEYS = sorted(path.name for path in FIXTURES.glob("*.ppk"))


def test_every_fixture_is_there():
    assert len(KEYS) == 12


@pytest.mark.parametrize("name", KEYS)
def test_a_putty_key_signs_in_as_the_key_puttygen_made(name):
    kind = name.split("-")[0]
    expected = (FIXTURES / f"{kind}.pub").read_text().split()[1]
    passphrase = "test-pass" if "pass" in name else None
    key = backup._load_private_key((FIXTURES / name).read_text(), passphrase)
    assert key.get_base64() == expected


@pytest.mark.parametrize("name", ["rsa-v3-pass.ppk", "rsa-v2-pass.ppk", "ed25519-v3-pass.ppk"])
def test_a_wrong_or_missing_passphrase_is_named(name):
    text = (FIXTURES / name).read_text()
    with pytest.raises(ppk.PpkError, match="passphrase of this PuTTY key is wrong"):
        backup._load_private_key(text, "not-it")
    with pytest.raises(ppk.PpkError, match="has a passphrase"):
        backup._load_private_key(text, None)


def test_a_changed_key_is_refused_by_its_check():
    lines = (FIXTURES / "ed25519-v3.ppk").read_text().splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith("Private-Lines")) + 1
    lines[at] = ("B" if lines[at][0] != "B" else "C") + lines[at][1:]
    with pytest.raises(ppk.PpkError, match="damaged|changed"):
        ppk.to_openssh("\n".join(lines))


def test_a_cut_off_or_old_file_says_what_is_wrong():
    text = (FIXTURES / "rsa-v3.ppk").read_text()
    with pytest.raises(ppk.PpkError, match="incomplete"):
        ppk.to_openssh(text.split("Private-Lines")[0])
    with pytest.raises(ppk.PpkError, match="format 1"):
        ppk.to_openssh(text.replace("PuTTY-User-Key-File-3", "PuTTY-User-Key-File-1"))


def test_windows_line_endings_and_spaces_around_it_are_fine():
    text = (FIXTURES / "ed25519-v2.ppk").read_text()
    assert ppk.is_ppk("\r\n  " + text)
    key = backup._load_private_key("  " + text.replace("\n", "\r\n") + "\r\n")
    assert key.get_base64() == (FIXTURES / "ed25519.pub").read_text().split()[1]


def test_text_that_is_no_key_asks_for_the_whole_key():
    with pytest.raises(ValueError, match="-----BEGIN"):
        backup._load_private_key("AAAAC3NzaC1lZDI1NTE5AAAAIDUo8btJRLVkqlXt1OIefXvAQ1WetOPFRjxGW5v")
