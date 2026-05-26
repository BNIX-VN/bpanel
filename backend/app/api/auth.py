import base64
import secrets
import time
from collections import defaultdict, deque
from io import BytesIO
from threading import Lock
from typing import Deque, Dict

import pyotp
import qrcode
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.permissions import Role, ensure_role
from app.core.security import create_access_token, hash_password, needs_rehash, verify_password
from app.core.secrets import decrypt, encrypt
from app.models.entities import User
from app.schemas.schemas import LoginResponse, TwoFactorCode, TwoFactorSetup, TwoFactorStatus

router = APIRouter(prefix="/auth", tags=["auth"])


# Cookie names. The session cookie is HttpOnly so JavaScript cannot read it,
# which mitigates token theft via XSS. The CSRF cookie is readable by JS so
# the SPA can echo it in the X-CSRF-Token header for mutating requests
# (double-submit cookie pattern).
SESSION_COOKIE = "bpanel_session"
CSRF_COOKIE = "bpanel_csrf"
CSRF_HEADER = "X-CSRF-Token"


# In-process sliding window rate limiter for /auth/login.
# We key counters BOTH by client IP and by submitted username so an attacker
# rotating IPs cannot bypass the per-account lockout, and a noisy client IP
# cannot drown out other accounts. For a single-process deployment this is
# enough; for multi-worker switch to Redis (which is already in the stack).
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


def _username_key(username: str) -> str:
    name = (username or "").strip().lower()
    return f"user:{name}" if name else "user:_unknown"


def _is_secure_request(request: Request) -> bool:
    """Decide whether to set the Secure cookie flag.

    True when the inbound request was HTTPS. The panel can also be served
    directly over http://IP:2222 during first install, so production mode alone
    must not force Secure cookies.
    """
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    if forwarded_proto == "https":
        return True
    if request.url.scheme == "https":
        return True
    return False


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


def _issue_login_session(response: Response, request: Request, user: User) -> str:
    token_extra = {"role": user.role, "tv": user.token_version or 0}
    token = create_access_token(user.username, token_extra)
    _set_session_cookies(response, request, token)
    return token


def _get_totp_secret(user: User) -> str:
    return decrypt(user.totp_secret or "")


def _verify_totp(user: User, code: str) -> bool:
    secret = _get_totp_secret(user)
    code = (code or "").replace(" ", "").strip()
    if not secret or not code:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def _qr_data_url(uri: str) -> str:
    image = qrcode.make(uri)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


@router.post("/login", response_model=LoginResponse)
def login(
    request: Request,
    response: Response,
    form: OAuth2PasswordRequestForm = Depends(),
    otp: str = Form(default=""),
    db: Session = Depends(get_db),
):
    ip_key = _client_key(request)
    user_key = _username_key(form.username)
    _enforce_rate_limit(ip_key)
    _enforce_rate_limit(user_key)

    user = db.query(User).filter(User.username == form.username).first()
    if user and user.is_active:
        password_ok = verify_password(form.password, user.hashed_password)
    else:
        verify_password(form.password, _DUMMY_HASH)
        password_ok = False

    if not user or not user.is_active or not password_ok:
        _record_failure(ip_key)
        _record_failure(user_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if user.totp_enabled:
        if not otp:
            return LoginResponse(requires_2fa=True)
        if not _verify_totp(user, otp):
            _record_failure(ip_key)
            _record_failure(user_key)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication code",
            )

    _record_success(ip_key)
    _record_success(user_key)
    if needs_rehash(user.hashed_password):
        try:
            user.hashed_password = hash_password(form.password)
            db.commit()
        except Exception:  # pragma: no cover
            db.rollback()
    token = _issue_login_session(response, request, user)

    # Bearer token still returned for backward compatibility with CLI tools or
    # mobile clients that cannot set cookies. Browser clients should ignore it
    # and rely on the HttpOnly cookie set above.
    return LoginResponse(access_token=token)


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


@router.post("/impersonate/{user_id}", response_model=LoginResponse)
def impersonate_user(
    user_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_role(current_user.role, Role.admin)
    target_user = db.query(User).filter(User.id == user_id).first()
    if target_user is None or not target_user.is_active:
        raise HTTPException(status_code=404, detail="User not found or inactive")
    token = _issue_login_session(response, request, target_user)
    return LoginResponse(access_token=token)


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


@router.get("/2fa/status", response_model=TwoFactorStatus)
def two_factor_status(current_user: User = Depends(get_current_user)):
    return TwoFactorStatus(enabled=bool(current_user.totp_enabled))


@router.post("/2fa/setup", response_model=TwoFactorSetup)
def setup_two_factor(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.totp_enabled:
        raise HTTPException(status_code=400, detail="Two-factor authentication is already enabled")
    secret = pyotp.random_base32()
    current_user.totp_secret = encrypt(secret)
    db.commit()
    account_name = current_user.email or current_user.username
    uri = pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=settings.totp_issuer)
    return TwoFactorSetup(secret=secret, provisioning_uri=uri, qr_data_url=_qr_data_url(uri))


@router.post("/2fa/enable", response_model=TwoFactorStatus)
def enable_two_factor(
    payload: TwoFactorCode,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.totp_secret:
        raise HTTPException(status_code=400, detail="Set up two-factor authentication first")
    if not _verify_totp(current_user, payload.code):
        raise HTTPException(status_code=400, detail="Invalid authentication code")
    if not current_user.totp_enabled:
        current_user.totp_enabled = True
        current_user.token_version = (current_user.token_version or 0) + 1
        db.commit()
        db.refresh(current_user)
    _issue_login_session(response, request, current_user)
    return TwoFactorStatus(enabled=True)


@router.post("/2fa/disable", response_model=TwoFactorStatus)
def disable_two_factor(
    payload: TwoFactorCode,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.totp_enabled and not _verify_totp(current_user, payload.code):
        raise HTTPException(status_code=400, detail="Invalid authentication code")
    current_user.totp_enabled = False
    current_user.totp_secret = None
    current_user.token_version = (current_user.token_version or 0) + 1
    db.commit()
    db.refresh(current_user)
    _issue_login_session(response, request, current_user)
    return TwoFactorStatus(enabled=False)
