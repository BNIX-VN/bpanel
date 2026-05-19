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
        forwarded = request.headers.get("x-forwarded-for", "")
        ip = forwarded.split(",", 1)[0].strip() if forwarded else (request.client.host if request.client else "")
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
