from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings


# Plain bcrypt. To prevent the 72-byte silent truncation problem (see
# security audit #8) we:
#   1. Cap password length at 72 bytes in the Pydantic schemas (bcrypt 72-byte
#      limit), so users can never set a password whose meaningful prefix is
#      truncated.
#   2. Set ``truncate_error=True`` so passlib raises rather than silently
#      truncating if anything bypasses the schema.
#
# We tried bcrypt_sha256 (which pre-hashes with SHA-256 to bypass the limit)
# but the passlib<->bcrypt 4.x compatibility issue makes that path unreliable
# in production. Plain bcrypt with the input length cap is the simplest fix.
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__truncate_error=True,
)
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(password, hashed_password)
    except ValueError:
        # truncate_error=True raises ValueError when the password is too long.
        return False


def needs_rehash(hashed_password: str) -> bool:
    return pwd_context.needs_update(hashed_password)


def create_access_token(subject: str, extra: Optional[Dict[str, Any]] = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload: Dict[str, Any] = {"sub": subject, "exp": expire}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)
