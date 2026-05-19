from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import ALGORITHM
from app.models.entities import User


# auto_error=False because the token may instead be in an HttpOnly cookie.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def _resolve_token(
    bearer: Optional[str],
    cookie_token: Optional[str],
) -> Optional[str]:
    if bearer:
        return bearer
    if cookie_token:
        return cookie_token
    return None


def get_current_user(
    request: Request,
    bearer_token: Optional[str] = Depends(oauth2_scheme),
    session_cookie: Optional[str] = Cookie(default=None, alias="bpanel_session"),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = _resolve_token(bearer_token, session_cookie)
    if not token:
        raise credentials_exception

    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        username: Optional[str] = payload.get("sub")
        token_version = int(payload.get("tv", 0))
        if username is None:
            raise credentials_exception
    except (JWTError, ValueError) as exc:
        raise credentials_exception from exc

    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.is_active:
        raise credentials_exception
    if (user.token_version or 0) != token_version:
        raise credentials_exception

    # When the request was authenticated via cookie (browser flow) we ALSO
    # require a CSRF token on mutating methods. Bearer auth (CLI/SDK) is
    # exempt because it cannot be triggered cross-origin without an explicit
    # Authorization header which browsers will not send automatically.
    if session_cookie and not bearer_token:
        if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            csrf_cookie = request.cookies.get("bpanel_csrf")
            csrf_header = request.headers.get("x-csrf-token")
            if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="CSRF token missing or invalid",
                )

    return user
