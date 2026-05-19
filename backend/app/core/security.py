from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

# Use bcrypt_sha256 to avoid the 72-byte password truncation issue inherent
# to plain bcrypt (longer passwords silently hash to the same value as their
# 72-byte prefix). Old plain-bcrypt hashes still verify and are auto-upgraded
# on next successful login.
pwd_context = CryptContext(
    schemes=["bcrypt_sha256", "bcrypt"],
    default="bcrypt_sha256",
    deprecated=["bcrypt"],
)
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return pwd_context.verify(password, hashed_password)


def needs_rehash(hashed_password: str) -> bool:
    return pwd_context.needs_update(hashed_password)


def create_access_token(subject: str, extra: Optional[Dict[str, Any]] = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload: Dict[str, Any] = {"sub": subject, "exp": expire}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)
