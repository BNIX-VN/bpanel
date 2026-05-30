"""Terminal API endpoints."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.entities import User, Website
from app.services import terminal

router = APIRouter(prefix="/terminal", tags=["terminal"])


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


async def get_current_user_ws(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
) -> User:
    """Get current user from JWT token (for WebSocket auth)."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"],
        )
        user_id: int = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception
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
        from app.core.permissions import Role, ensure_role
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
    current_user: User = Depends(get_current_user_ws),
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
    current_user: User = Depends(get_current_user_ws),
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
    from jose import jwt
    from app.core.database import SessionLocal

    # Authenticate via cookie
    session_cookie = websocket.cookies.get("bpanel_session")
    if not session_cookie:
        await websocket.close(code=4001, reason="No session cookie")
        return

    try:
        # Use a separate db session for WebSocket
        db_ws = SessionLocal()
        try:
            payload = jwt.decode(
                session_cookie,
                settings.secret_key,
                algorithms=["HS256"],
            )
            user_id = payload.get("sub")
            if not user_id:
                await websocket.close(code=4001, reason="Invalid session")
                return
            current_user = db_ws.query(User).filter(User.id == user_id).first()
            if not current_user:
                await websocket.close(code=4001, reason="User not found")
                return
        finally:
            db_ws.close()
    except JWTError:
        await websocket.close(code=4001, reason="Invalid session")
        return

    # Get website
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        await websocket.close(code=4004, reason="Website not found")
        return

    # Check ownership
    if website.owner_id != current_user.id:
        from app.core.permissions import Role
        if current_user.role != Role.admin:
            await websocket.close(code=4003, reason="Access denied")
            return

    await websocket.accept()

    # Track active sessions for this website
    # In production, this should use Redis or similar for multi-process coordination
    try:
        while True:
            message = await websocket.receive_text()
            import json

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
                command = msg.get("data", "").strip()
                if not command:
                    continue
                result = terminal.exec_command(
                    website.linux_user,
                    command,
                    cwd=website.root_path,
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
