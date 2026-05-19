import time
from collections import defaultdict, deque
from threading import Lock
from typing import Deque, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token, hash_password, needs_rehash, verify_password
from app.models.entities import User
from app.schemas.schemas import Token

router = APIRouter(prefix="/auth", tags=["auth"])


# In-process sliding window rate limiter for /auth/login.
# For a single-process deployment this is enough; for multi-worker switch to Redis.
_LOGIN_WINDOW_SECONDS = 60
_LOGIN_MAX_ATTEMPTS = 8
_LOGIN_LOCKOUT_SECONDS = 15 * 60
_LOGIN_LOCKOUT_THRESHOLD = 20
_login_attempts: Dict[str, Deque[float]] = defaultdict(deque)
_login_lockouts: Dict[str, float] = {}
_login_lock = Lock()

# Pre-computed dummy bcrypt hash for constant-time fail path.
_DUMMY_HASH = hash_password("not-a-real-password-bpanel-dummy")


def _client_key(request: Request) -> str:
    """Return the client identifier for rate-limit bookkeeping.

    With uvicorn started using --proxy-headers --forwarded-allow-ips 127.0.0.1,
    request.client.host is set from the proxy's X-Forwarded-For value but ONLY
    when the immediate peer is the trusted proxy (Nginx on loopback). Spoofed
    X-Forwarded-For from arbitrary clients is therefore ignored.
    """
    return request.client.host if request.client else "unknown"


def _enforce_rate_limit(key: str) -> None:
    now = time.monotonic()
    with _login_lock:
        locked_until = _login_lockouts.get(key)
        if locked_until and locked_until > now:
            retry_after = int(locked_until - now)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many login attempts. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )
        if locked_until and locked_until <= now:
            _login_lockouts.pop(key, None)
        attempts = _login_attempts[key]
        cutoff = now - _LOGIN_WINDOW_SECONDS
        while attempts and attempts[0] < cutoff:
            attempts.popleft()
        if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many login attempts. Slow down.",
                headers={"Retry-After": str(_LOGIN_WINDOW_SECONDS)},
            )


def _record_failure(key: str) -> None:
    now = time.monotonic()
    with _login_lock:
        attempts = _login_attempts[key]
        attempts.append(now)
        cutoff = now - _LOGIN_WINDOW_SECONDS
        while attempts and attempts[0] < cutoff:
            attempts.popleft()
        if len(attempts) >= _LOGIN_LOCKOUT_THRESHOLD:
            _login_lockouts[key] = now + _LOGIN_LOCKOUT_SECONDS


def _record_success(key: str) -> None:
    with _login_lock:
        _login_attempts.pop(key, None)
        _login_lockouts.pop(key, None)


@router.post("/login", response_model=Token)
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    key = _client_key(request)
    _enforce_rate_limit(key)

    user = db.query(User).filter(User.username == form.username).first()
    # Always run a bcrypt verify so timing is similar regardless of user existence.
    if user and user.is_active:
        password_ok = verify_password(form.password, user.hashed_password)
    else:
        verify_password(form.password, _DUMMY_HASH)
        password_ok = False

    if not user or not user.is_active or not password_ok:
        _record_failure(key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    _record_success(key)
    # Transparent password hash upgrade.
    if needs_rehash(user.hashed_password):
        try:
            user.hashed_password = hash_password(form.password)
            db.commit()
        except Exception:
            db.rollback()
    token_extra = {"role": user.role, "tv": user.token_version or 0}
    token = create_access_token(user.username, token_extra)
    return Token(access_token=token)
