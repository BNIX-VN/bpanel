import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import auth, databases, firewall, maintenance, services, users, websites
from app.core.config import settings
from app.core.database import run_migrations

run_migrations()

logger = logging.getLogger("bpanel")

app = FastAPI(title="BPanel API", version="0.1.0")

# Refuse to start in production with unsafe defaults.
if settings.app_env.lower() == "production":
    if settings.command_dry_run:
        raise RuntimeError(
            "COMMAND_DRY_RUN must be False in production. "
            "Set COMMAND_DRY_RUN=false in the environment."
        )

cors_origins = settings.cors_origins
if not cors_origins and settings.app_env != "production":
    cors_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    logger.exception("Unhandled request error: %s %s", request.method, request.url.path)
    if settings.app_env.lower() == "production":
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "accelerometer=(), autoplay=(), camera=(), display-capture=(), encrypted-media=(), "
        "fullscreen=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), midi=(), "
        "payment=(), usb=()",
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'",
    )
    if settings.app_env.lower() == "production":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(websites.router, prefix="/api")
app.include_router(databases.router, prefix="/api")
app.include_router(firewall.router, prefix="/api")
app.include_router(services.router, prefix="/api")
app.include_router(maintenance.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok", "name": "BPanel"}


frontend_dist = Path(settings.frontend_dist)
assets_dir = frontend_dist / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")


@app.get("/favicon.png", include_in_schema=False)
def favicon():
    path = frontend_dist / "favicon.png"
    if path.exists():
        return FileResponse(path, media_type="image/png")
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/{full_path:path}", include_in_schema=False)
def serve_spa(full_path: str):
    """Serve the built React app directly from FastAPI on the panel port."""
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    index = frontend_dist / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"detail": "Frontend build not found", "path": str(index)}
