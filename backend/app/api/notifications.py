"""The Notifications addon's API.

The server's settings (SMTP, the Telegram bot, thresholds, language) and the
delivery log are an administrator's. Everyone - customers included - has
their own page: which channels, which events, and their Telegram link. Every
route answers 409 while the addon is not installed.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.permissions import Role, ensure_role, is_admin_role
from app.models.entities import NotificationLog, User
from app.services import addons, notifications, notify_messages
from app.services.audit import log_action


def require_notifications() -> None:
    addons.require(addons.NOTIFICATIONS)


router = APIRouter(prefix="/notifications", tags=["notifications"],
                   dependencies=[Depends(require_notifications)])


class SmtpSettings(BaseModel):
    host: str | None = Field(default=None, max_length=255)
    port: int | None = None
    security: str | None = None
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=512)
    clear_password: bool = False
    from_email: str | None = Field(default=None, max_length=255)
    from_name: str | None = Field(default=None, max_length=100)


class TelegramSettings(BaseModel):
    bot_token: str | None = Field(default=None, max_length=128)
    chat_id: str | None = Field(default=None, max_length=40)
    clear_bot_token: bool = False


class Thresholds(BaseModel):
    disk_percent: int | None = None
    ssl_days: int | None = None
    quota_percent: int | None = None


class SettingsUpdate(BaseModel):
    language: str | None = None
    smtp: SmtpSettings | None = None
    telegram: TelegramSettings | None = None
    thresholds: Thresholds | None = None


class MyPrefsUpdate(BaseModel):
    email_enabled: bool | None = None
    telegram_enabled: bool | None = None
    telegram_chat_id: str | None = Field(default=None, max_length=40)
    muted: list[str] | None = None


class TestRequest(BaseModel):
    channel: str = Field(pattern=r"^(email|telegram|telegram_admin)$")


def _events(admin: bool) -> list[dict]:
    return [{"key": key, **notify_messages.EVENTS[key]} for key in notify_messages.events_for(admin)]


@router.get("/settings")
def get_settings(current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    return notifications.public_config()


@router.put("/settings")
def put_settings(payload: SettingsUpdate, request: Request, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    try:
        result = notifications.save_config(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_action(db, current_user.id, "notifications_settings", "notifications", request=request)
    return result


def _me(db: Session, user: User) -> dict:
    config = notifications.load_config()
    pref = notifications.prefs_for(db, user.id)
    db.commit()
    admin_chat = notifications.admin_chat(config) if is_admin_role(user.role) else ""
    return {
        "email": user.email or "",
        "email_enabled": bool(pref.email_enabled),
        "telegram_enabled": bool(pref.telegram_enabled),
        "telegram_linked": bool(pref.telegram_chat_id),
        "telegram_chat_id": pref.telegram_chat_id or "",
        # An administrator with no chat of their own hears in the admin chat.
        "telegram_admin_chat": admin_chat if not pref.telegram_chat_id else "",
        "telegram_link_pending": bool(pref.telegram_link_code and pref.telegram_link_expires_at
                                      and pref.telegram_link_expires_at >= datetime.utcnow()),
        "muted": sorted(notifications.muted(pref)),
        "events": _events(is_admin_role(user.role)),
        "channels": {"email": notifications.smtp_ready(config), "telegram": notifications.telegram_ready(config),
                     "bot_username": config["telegram"].get("bot_username", "")},
    }


@router.get("/me")
def get_my_prefs(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _me(db, current_user)


@router.put("/me")
def put_my_prefs(payload: MyPrefsUpdate, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    pref = notifications.prefs_for(db, current_user.id)
    if payload.email_enabled is not None:
        pref.email_enabled = payload.email_enabled
    if payload.telegram_enabled is not None:
        pref.telegram_enabled = payload.telegram_enabled
    if payload.telegram_chat_id is not None:
        try:
            pref.telegram_chat_id = notifications.valid_chat_id(payload.telegram_chat_id) or None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        pref.telegram_link_code = None
    if payload.muted is not None:
        allowed = set(notify_messages.events_for(is_admin_role(current_user.role)))
        unknown = sorted(set(payload.muted) - allowed)
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown event(s): {', '.join(unknown)}")
        pref.muted_events = ",".join(sorted(set(payload.muted)))
    pref.updated_at = datetime.utcnow()
    db.commit()
    return _me(db, current_user)


@router.post("/me/telegram/link")
def start_telegram_link(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        return notifications.start_telegram_link(db, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/me/telegram/verify")
def verify_telegram_link(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        notifications.collect_telegram_links(db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"Telegram: {exc}") from exc
    return _me(db, current_user)


@router.delete("/me/telegram")
def unlink_telegram(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    pref = notifications.prefs_for(db, current_user.id)
    pref.telegram_chat_id = None
    pref.telegram_link_code = None
    pref.telegram_link_expires_at = None
    db.commit()
    return _me(db, current_user)


@router.post("/test")
def send_test(payload: TestRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Email goes out through the server's SMTP account, whose quota belongs to
    # the administrator, and the admin chat is the administrators'; a customer
    # can test the Telegram chat they linked.
    if payload.channel in ("email", "telegram_admin"):
        ensure_role(current_user.role, Role.admin)
    try:
        target = notifications.send_test(current_user, payload.channel, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - the server's answer is what a test is for
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}"[:500]) from exc
    return {"sent_to": target}


@router.get("/telegram/chats")
def telegram_chats(current_user: User = Depends(get_current_user)):
    """Who recently wrote to the bot: pick the admin chat instead of looking it up."""
    ensure_role(current_user.role, Role.admin)
    try:
        return notifications.recent_chats()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"Telegram: {exc}") from exc


@router.get("/log")
def delivery_log(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    rows = (db.query(NotificationLog, User.username)
            .outerjoin(User, User.id == NotificationLog.user_id)
            .order_by(NotificationLog.id.desc()).limit(100).all())
    return [{"id": row.id, "created_at": row.created_at.isoformat() if row.created_at else "",
             "username": username or "", "event": row.event, "channel": row.channel,
             "status": row.status, "title": row.title, "detail": row.detail} for row, username in rows]
