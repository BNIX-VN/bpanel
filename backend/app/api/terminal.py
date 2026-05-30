"""Terminal API endpoints."""

import json

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.permissions import Role, ensure_role, is_admin_role
from app.core.security import ALGORITHM
from app.models.entities import RevokedToken, User, Website
from app.services import terminal

router = APIRouter(prefix="/terminal", tags=["terminal"])


def _origin_allowed(websocket: WebSocket) -> bool:
    origin = (websocket.headers.get("origin") or "").rstrip("/")
    if not origin:
        return True
    allowed = {item.rstrip("/") for item in settings.cors_origins}
    if settings.panel_url:
        allowed.add(settings.panel_url.rstrip("/"))
    return not allowed or origin in allowed


def _current_user_from_session_cookie(websocket: WebSocket, db: Session) -> User | None:
    token = websocket.cookies.get("bpanel_session")
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        username = payload.get("sub")
        token_version = int(payload.get("tv", 0))
        jti = payload.get("jti")
        if not username:
            return None
    except (JWTError, ValueError):
        return None
    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.is_active:
        return None
    if (user.token_version or 0) != token_version:
        return None
    if jti and db.query(RevokedToken.id).filter(RevokedToken.jti == jti).first():
        return None
    return user


async def get_user_website(
    website_id: int,
    db: Session,
    current_user: User,
) -> Website:
    """Get website and verify ownership."""
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    # Check ownership or admin role
    if website.owner_id != current_user.id:
        ensure_role(current_user.role, Role.admin)
    return website


class TerminalExecRequest(BaseModel):
    """Request model for terminal command execution."""

    command: str


class TerminalExecResponse(BaseModel):
    """Response model for terminal command execution."""

    exit_code: int
    stdout: str
    stderr: str


@router.post("/exec/{website_id}", response_model=TerminalExecResponse)
async def exec_command(
    website_id: int,
    request: TerminalExecRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Execute a single command as the website user.

    This endpoint is suitable for non-interactive commands like:
    - php artisan migrate
    - composer install
    - npm run build
    """
    website = await get_user_website(website_id, db, current_user)

    result = terminal.exec_command(
        website.linux_user,
        request.command,
        cwd=website.root_path,
    )

    return TerminalExecResponse(
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
    )


@router.get("/allowed-commands")
async def list_allowed_commands(
    current_user: User = Depends(get_current_user),
):
    """List all allowed commands for terminal access."""
    return {"commands": sorted(terminal.ALLOWED_COMMANDS)}


@router.websocket("/ws/{website_id}")
async def terminal_websocket(
    websocket: WebSocket,
    website_id: int,
    db: Session = Depends(get_db),
):
    """WebSocket endpoint for interactive terminal sessions.

    Auth is handled via cookies (bpanel_session and bpanel_csrf) passed
    automatically by the browser.

    Messages:
    - Client -> Server: {"type": "input", "data": "command\n"}
    - Client -> Server: {"type": "resize", "cols": 80, "rows": 24}
    - Client -> Server: {"type": "ping"}
    - Server -> Client: {"type": "output", "data": "output text"}
    - Server -> Client: {"type": "exit", "code": 0}
    - Server -> Client: {"type": "pong"}
    """
    if not _origin_allowed(websocket):
        await websocket.close(code=4003, reason="Origin not allowed")
        return

    current_user = _current_user_from_session_cookie(websocket, db)
    if not current_user:
        await websocket.close(code=4001, reason="No session cookie")
        return

    # Get website
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        await websocket.close(code=4004, reason="Website not found")
        return

    # Check ownership
    if website.owner_id != current_user.id and not is_admin_role(current_user.role):
        await websocket.close(code=4003, reason="Access denied")
        return

    if not website.linux_user:
        await websocket.close(code=4004, reason="Website runtime user is missing")
        return

    await websocket.accept()
    cwd = website.root_path
    await websocket.send_json({"type": "cwd", "data": cwd})

    try:
        while True:
            message = await websocket.receive_text()

            try:
                msg = json.loads(message)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "data": "Invalid JSON message"
                })
                continue

            msg_type = msg.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg_type == "input":
                command = (msg.get("data", "") or "").strip()
                if not command:
                    await websocket.send_json({"type": "exit", "code": 0})
                    continue
                if command in {"clear", "cls"}:
                    await websocket.send_json({"type": "clear"})
                    await websocket.send_json({"type": "exit", "code": 0})
                    continue

                try:
                    argv = terminal.split_command(command)
                except ValueError as exc:
                    await websocket.send_json({"type": "output", "data": f"{exc}\r\n"})
                    await websocket.send_json({"type": "exit", "code": 2})
                    continue

                if argv[0] == "cd":
                    if len(argv) > 2:
                        await websocket.send_json({"type": "output", "data": "usage: cd [path]\r\n"})
                        await websocket.send_json({"type": "exit", "code": 2})
                        continue
                    try:
                        cwd = terminal.resolve_cwd(website.root_path, cwd, argv[1] if len(argv) == 2 else "")
                    except ValueError as exc:
                        await websocket.send_json({"type": "output", "data": f"{exc}\r\n"})
                        await websocket.send_json({"type": "exit", "code": 1})
                        continue
                    await websocket.send_json({"type": "cwd", "data": cwd})
                    await websocket.send_json({"type": "exit", "code": 0})
                    continue

                result = terminal.exec_command(
                    website.linux_user,
                    command,
                    cwd=cwd,
                )
                await websocket.send_json({
                    "type": "output",
                    "data": result.stdout + result.stderr,
                })
                await websocket.send_json({
                    "type": "exit",
                    "code": result.exit_code,
                })
            elif msg_type == "resize":
                # Terminal resize - can be used for PTY support in future
                pass
            else:
                await websocket.send_json({
                    "type": "error",
                    "data": f"Unknown message type: {msg_type}"
                })

    except WebSocketDisconnect:
        pass  # Client disconnected
    except Exception as e:
        try:
            await websocket.send_json({
                "type": "error",
                "data": f"Server error: {str(e)}"
            })
        except Exception:
            pass  # WebSocket already closed
