import json
import os
import secrets
import stat as _stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


TOKEN_TTL_SECONDS = 60
PANEL_LOGIN_TTL_SECONDS = 300
TOKEN_DIR = Path("/tmp/bpanel-phpmyadmin-sso")


def _ensure_token_dir() -> None:
    """Make TOKEN_DIR 0700 and refuse a pre-existing entry we do not fully own.

    The directory lives in the bpanel-api unit's PrivateTmp /tmp, wiped on every
    restart, so a tenant process sharing that namespace could pre-create it -- as
    a directory it owns, or a symlink -- and list token names or redirect writes.
    mkdir(exist_ok=True) accepted whatever was there. Create it fresh; if it
    exists, require a real directory (not a symlink) owned by this process at 0700.
    """
    try:
        os.mkdir(TOKEN_DIR, 0o700)
        return
    except FileExistsError:
        pass
    st = os.lstat(TOKEN_DIR)
    if _stat.S_ISLNK(st.st_mode) or not _stat.S_ISDIR(st.st_mode):
        raise RuntimeError(f"{TOKEN_DIR} is not a directory")
    if st.st_uid != os.geteuid():
        raise RuntimeError(f"{TOKEN_DIR} is not owned by this process")
    if _stat.S_IMODE(st.st_mode) != 0o700:
        os.chmod(TOKEN_DIR, 0o700)


def _token_dir_is_safe() -> bool:
    try:
        st = os.lstat(TOKEN_DIR)
    except FileNotFoundError:
        return False
    return (not _stat.S_ISLNK(st.st_mode) and _stat.S_ISDIR(st.st_mode)
            and st.st_uid == os.geteuid())


def create_phpmyadmin_token(db_user: str, db_password: str, db_name: str) -> str:
    return _create_token({
        "kind": "phpmyadmin",
        "db_user": db_user,
        "db_password": db_password,
        "db_name": db_name,
    }, TOKEN_TTL_SECONDS)


def create_panel_login_token(username: str) -> str:
    return _create_token({"kind": "panel_login", "username": username}, PANEL_LOGIN_TTL_SECONDS)


def _create_token(data: dict, ttl_seconds: int) -> str:
    _ensure_token_dir()
    cleanup_expired_tokens()
    token = secrets.token_urlsafe(32)
    token_path = _token_path(token)
    payload_data = dict(data)
    payload_data["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
    payload = json.dumps(payload_data)
    # Atomic create with mode 0o600 from the start. O_EXCL prevents symlink
    # racing — if a file already exists at that path (collision or attack),
    # we abort.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(str(token_path), flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
    except Exception:
        token_path.unlink(missing_ok=True)
        raise
    return token


def consume_phpmyadmin_token(token: str) -> Optional[dict]:
    data = _consume_token(token)
    if not data or data.get("kind", "phpmyadmin") != "phpmyadmin":
        return None
    return data


def consume_panel_login_token(token: str) -> Optional[dict]:
    data = _consume_token(token)
    if not data or data.get("kind") != "panel_login":
        return None
    return data


def _consume_token(token: str) -> Optional[dict]:
    if not _token_dir_is_safe():
        return None
    cleanup_expired_tokens()
    try:
        token_path = _token_path(token)
    except ValueError:
        return None
    if not token_path.exists():
        return None
    try:
        try:
            data = json.loads(token_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError):
            return None
        if not isinstance(data, dict):
            return None
    finally:
        token_path.unlink(missing_ok=True)
    try:
        expires_at = datetime.fromisoformat(data["expires_at"])
    except (ValueError, KeyError, TypeError):
        return None
    if expires_at < datetime.now(timezone.utc):
        return None
    return data


def cleanup_expired_tokens() -> None:
    if not _token_dir_is_safe():
        return
    now = datetime.now(timezone.utc)
    for token_path in TOKEN_DIR.glob("*.json"):
        try:
            data = json.loads(token_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Invalid token payload")
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
