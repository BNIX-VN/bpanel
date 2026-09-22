"""Passkeys, and why they do not replace the authenticator app.

WebAuthn binds a credential to a Relying Party ID, which is a hostname, and a
browser will not so much as admit a credential exists to any other name.
app/serve.py answers on every hostname on the machine that has a certificate,
so the panel derives the RP ID from the request and stores it on the
credential: one account, one passkey per name it signs in through.

That binding is exactly why TOTP stays live beside it. A passkey registered for
panel.example.com is not offered when the same customer reaches the panel by
its IP, and a second factor that can strand somebody on the wrong hostname is
not a security feature. The login offers the passkey first and falls through.

What the tests below actually guard is the trust boundary: the RP ID and the
origin are derived on the server, the challenge is one the server issued and
can only be spent once, and a counter that goes backwards is a cloned key.
"""

import ast
import time
from pathlib import Path

import pytest

from app.services import passkeys

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AUTH_API = PROJECT_ROOT / "backend" / "app" / "api" / "auth.py"


# --- what a hostname may be -------------------------------------------------

@pytest.mark.parametrize("host,expected", [
    ("panel.example.com:2222", "panel.example.com"),
    ("panel.example.com", "panel.example.com"),
    ("PANEL.Example.COM.", "panel.example.com"),
    ("localhost:5173", "localhost"),
])
def test_a_domain_becomes_the_relying_party_id(host, expected):
    assert passkeys.rp_id_for_host(host) == expected


@pytest.mark.parametrize("host", ["163.61.72.88:2222", "10.0.0.1", "[::1]:2222", "nodots", "", "   "])
def test_an_address_is_not_a_relying_party_id(host):
    """WebAuthn requires a domain.

    Reaching the panel by IP has to answer "passkeys are not available here"
    rather than produce a failure the customer cannot interpret.
    """
    assert passkeys.rp_id_for_host(host) == ""
    assert passkeys.supported(host) is False


def test_the_origin_keeps_the_port():
    """The browser reports the origin with its port; a mismatch fails the check."""
    assert passkeys.origin_for_request("https", "panel.example.com:2222") == "https://panel.example.com:2222"


# --- what is derived rather than accepted -----------------------------------

def test_the_relying_party_id_never_comes_from_the_request_body():
    """It is half of what a signature is checked against.

    A caller who could name the RP ID could choose which credential their
    assertion appears to satisfy.
    """
    src = (PROJECT_ROOT / "backend" / "app" / "services" / "passkeys.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef,)):
            continue
        if node.name not in {"verify_registration", "verify_authentication"}:
            continue
        body = ast.unparse(node)
        assert "rp_id = rp_id_for_host(host)" in body, (
            f"{node.name} must derive the RP ID from the request host"
        )
        assert "expected_origin=origin_for_request(" in body


def test_a_passkey_for_another_hostname_is_refused(monkeypatch):
    class _Stored:
        rp_id = "other.example.com"
        public_key = passkeys.b64(b"x")
        sign_count = 0

    with pytest.raises(ValueError, match="different hostname"):
        passkeys.verify_authentication(
            credential_json="{}",
            challenge=b"c",
            stored=_Stored(),
            scheme="https",
            host="panel.example.com:2222",
        )


# --- the challenge ----------------------------------------------------------

def test_a_challenge_is_random_and_long_enough():
    seen = {passkeys.new_challenge() for _ in range(50)}
    assert len(seen) == 50
    assert all(len(c) >= 32 for c in seen)


def test_challenges_are_scoped_to_the_hostname_and_the_subject():
    a = passkeys.challenge_key("auth", "7", "panel.example.com")
    b = passkeys.challenge_key("auth", "7", "other.example.com")
    c = passkeys.challenge_key("auth", "8", "panel.example.com")
    assert a != b != c and a != c


def test_a_challenge_is_spent_when_it_is_read():
    """Read-and-delete. One that can be spent twice is not a nonce."""
    from app.api import auth as auth_api

    key = passkeys.challenge_key("auth", "test-user", "panel.example.com")
    auth_api._challenge_store(key, b"a-challenge-value-32-bytes-long!!")
    assert auth_api._challenge_take(key) == b"a-challenge-value-32-bytes-long!!"
    assert auth_api._challenge_take(key) is None, "a challenge was accepted twice"


def test_a_challenge_expires():
    from app.api import auth as auth_api

    key = passkeys.challenge_key("reg", "expiring", "panel.example.com")
    monkey_ttl = passkeys.CHALLENGE_TTL_SECONDS
    assert monkey_ttl <= 600, "a challenge that lives for ten minutes is a replay window"


# --- the counter ------------------------------------------------------------

def test_the_source_of_truth_for_the_counter_rule_is_written_down():
    """A counter that goes backwards means the credential was cloned.

    An authenticator that does not count reports 0 forever, which the spec
    allows and which must not be mistaken for a clone - the rule has to say
    both halves.
    """
    src = (PROJECT_ROOT / "backend" / "app" / "services" / "passkeys.py").read_text(encoding="utf-8")
    body = src.split("def verify_authentication(", 1)[1].split("\ndef ", 1)[0]
    assert "went backwards" in body
    assert "new_count and" in body, (
        "an authenticator reporting 0 every time is legal and must still work"
    )


# --- the fallback, which is the point --------------------------------------

def test_login_offers_the_passkey_first_and_keeps_the_app_available():
    src = AUTH_API.read_text(encoding="utf-8")
    body = src.split("def login(", 1)[1].split("\n@router", 1)[0]
    assert "requires_passkey=True" in body
    assert "requires_2fa=bool(user.totp_enabled)" in body, (
        "the passkey challenge must also say whether an authenticator app is "
        "available, or a customer on the wrong hostname has no way in"
    )


def test_a_second_factor_that_cannot_be_checked_is_refused_not_ignored():
    """Sending an otp or a passkey to an account with neither must fail."""
    src = AUTH_API.read_text(encoding="utf-8")
    body = src.split("def login(", 1)[1].split("\n@router", 1)[0]
    assert "no second factor configured" in body


def test_a_failed_passkey_counts_against_the_rate_limit():
    """Otherwise it is an unlimited oracle next to a limited one."""
    src = AUTH_API.read_text(encoding="utf-8")
    body = src.split("if passkey and site_passkeys:", 1)[1].split("elif site_passkeys", 1)[0]
    assert body.count("_record_failure(ip_key, apply_lockout=True)") >= 2, (
        "both the expired-challenge and rejected-assertion paths have to record "
        "a failure"
    )


# --- lifecycle --------------------------------------------------------------

def test_deleting_a_user_takes_their_passkeys():
    """A row pointing at a freed user id is a way in for whoever inherits it."""
    src = (PROJECT_ROOT / "backend" / "app" / "services" / "teardown.py").read_text(encoding="utf-8")
    assert "purge_owner_passkeys" in src
    assert '"passkeys": purge_owner_passkeys(db, owner_id)' in src


def test_registering_a_passkey_needs_the_same_step_up_as_setting_up_totp():
    src = AUTH_API.read_text(encoding="utf-8")
    body = src.split("def passkey_register_options(", 1)[1].split("\n@router", 1)[0]
    assert "require_sensitive_action_step_up" in body
