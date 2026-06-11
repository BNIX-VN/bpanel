import os
import sys

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("COMMAND_DRY_RUN", "true")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ""))

from app.core import security  # noqa: E402


class FakeCrypt:
    def crypt(self, password, salt):
        return salt if password == "root-password" else "$y$wrong"


def test_shadow_hash_password_verification(monkeypatch):
    monkeypatch.setattr(security, "unix_crypt", FakeCrypt())
    root_hash = "$y$j9T$abcdefghijklmnop"

    assert security.verify_password("root-password", root_hash)
    assert not security.verify_password("wrong-password", root_hash)
    assert not security.needs_rehash(root_hash)


def test_unknown_hash_is_rejected():
    assert not security.verify_password("password", "$unknown$hash")
    assert not security.needs_rehash("$unknown$hash")
