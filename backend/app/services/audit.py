from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.entities import AuditLog


def log_action(
    db: Session,
    user_id: Optional[int],
    action: str,
    target: str,
    detail: str = "",
    request: Optional[Request] = None,
) -> None:
    extras = []
    if request is not None:
        # request.client.host is now trustworthy because uvicorn is started
        # with --proxy-headers --forwarded-allow-ips 127.0.0.1, so X-Forwarded-For
        # is only honoured when the peer is the trusted local Nginx.
        ip = request.client.host if request.client else ""
        ua = request.headers.get("user-agent", "")[:200]
        if ip:
            extras.append(f"ip={ip}")
        if ua:
            extras.append(f"ua={ua}")
    if extras:
        if detail:
            detail = f"{detail} | " + " ".join(extras)
        else:
            detail = " ".join(extras)
    db.add(AuditLog(user_id=user_id, action=action, target=target, detail=detail))
    db.commit()
