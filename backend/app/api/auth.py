import secrets
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Deque, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, needs_rehash, verify_password
from app.models.entities import User
from app.schemas.schemas import Token

router = APIRouter(prefix="/auth", tags=["auth"])


# Cookie names. The session cookie is HttpOnly so JavaScript cannot read it,
# which mitigates token theft via XSS. The CSRF cookie is readable by JS so
# the SPA can echo it in the X-CSRF-Token header for mutating requests
# (double-submit cookie pattern).
SESSION_COOKIE = "bpanel_session"
CSRF_COOKIE = "bpanel_csrf"
CSRF_HEADER = "X-CSRF-Token"


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
    return request.client.host if request.client else "unknown"


def _is_secure_request(request: Request) -> bool:
    """Decide whether to set the Secure cookie flag.

    True when the inbound request was HTTPS, or when running in production
    (the panel is always served behind nginx with a real TLS certificate).
    """
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    if forwarded_proto == "https":
        return True
    if request.url.scheme == "https":
        return True
    return settings.app_env.lower() == "production"


def _set_session_cookies(response: Response, request: Request, token: str) -> str:
    csrf_token = secrets.token_urlsafe(32)
    secure = _is_secure_request(request)
    max_age = settings.access_token_expire_minutes * 60
    # HttpOnly session cookie: never visible to JS.
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    # CSRF cookie: readable by JS so the SPA can mirror it in a header.
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )
    return csrf_token


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


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
    response: Response,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    key = _client_key(request)
    _enforce_rate_limit(key)

    user = db.query(User).filter(User.username == form.username).first()
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
    if needs_rehash(user.hashed_password):
        try:
            user.hashed_password = hash_password(form.password)
            db.commit()
        except Exception:  # pragma: no cover
            db.rollback()
    token_extra = {"role": user.role, "tv": user.token_version or 0}
    token = create_access_token(user.username, token_extra)

    _set_session_cookies(response, request, token)

    # Bearer token still returned for backward compatibility with CLI tools or
    # mobile clients that cannot set cookies. Browser clients should ignore it
    # and rely on the HttpOnly cookie set above.
    return Token(access_token=token)


@router.post("/logout")
def logout(
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Invalidate the session by clearing cookies AND bumping token_version.

    Bumping token_version forces all other devices/tabs holding a JWT for this
    user to be re-authenticated, which is the closest we get to true logout
    without a Redis blacklist.
    """
    current_user.token_version = (current_user.token_version or 0) + 1
    db.commit()
    _clear_session_cookies(response)
    return {"ok": True}


@router.get("/csrf")
def get_csrf(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
):
    """Return (and refresh) the CSRF cookie for the current session.

    The SPA calls this on bootstrap when the cookie is missing, e.g. after a
    page reload that pre-dates this code change.
    """
    secure = _is_secure_request(request)
    csrf_token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )
    return {"csrf_token": csrf_token}
