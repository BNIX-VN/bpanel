import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
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
