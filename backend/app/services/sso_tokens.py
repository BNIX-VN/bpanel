import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


TOKEN_TTL_SECONDS = 60
TOKEN_DIR = Path("/tmp/bpanel-phpmyadmin-sso")


def create_phpmyadmin_token(db_user: str, db_password: str, db_name: str) -> str:
    cleanup_expired_tokens()
    token = secrets.token_urlsafe(32)
    TOKEN_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    token_path = _token_path(token)
    token_path.write_text(json.dumps({
        "db_user": db_user,
        "db_password": db_password,
        "db_name": db_name,
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=TOKEN_TTL_SECONDS)).isoformat(),
    }), encoding="utf-8")
    token_path.chmod(0o600)
    return token


def consume_phpmyadmin_token(token: str) -> Optional[dict]:
    cleanup_expired_tokens()
    token_path = _token_path(token)
    if not token_path.exists():
        return None
    try:
        data = json.loads(token_path.read_text(encoding="utf-8"))
    finally:
        token_path.unlink(missing_ok=True)
    expires_at = datetime.fromisoformat(data["expires_at"])
    if expires_at < datetime.now(timezone.utc):
        return None
    return data


def cleanup_expired_tokens() -> None:
    if not TOKEN_DIR.exists():
        return
    now = datetime.now(timezone.utc)
    for token_path in TOKEN_DIR.glob("*.json"):
        try:
            data = json.loads(token_path.read_text(encoding="utf-8"))
            expires_at = datetime.fromisoformat(data["expires_at"])
        except (OSError, ValueError, KeyError):
            token_path.unlink(missing_ok=True)
            continue
        if expires_at < now:
            token_path.unlink(missing_ok=True)


def _token_path(token: str) -> Path:
    if not token.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Invalid token")
    return TOKEN_DIR / f"{token}.json"
