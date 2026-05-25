from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


DEFAULT_SECRET_KEY = "change-this-secret-key"


class Settings(BaseSettings):
    app_name: str = "BPanel"
    app_env: str = "development"
    secret_key: str = DEFAULT_SECRET_KEY
    access_token_expire_minutes: int = 120  # was 720; shorter window if a token is stolen
    database_url: str = "sqlite:///./bpanel.db"
    command_dry_run: bool = True
    allowed_origins: str = Field(default="")
    sites_root: str = "/home/bpanel-sites"
    backup_root: str = "/var/backups/bpanel"
    nginx_sites_available: str = "/etc/nginx/conf.d"
    default_php_version: str = "8.3"
    ssl_email: str = ""
    redis_url: str = "redis://localhost:6379/0"
    filebrowser_port: int = 8088
    panel_url: str = ""
    panel_domain: str = ""
    panel_port: int = 2222
    panel_ssl_cert: str = ""
    panel_ssl_key: str = ""
    frontend_dist: str = "/opt/bpanel/frontend/dist"
    totp_issuer: str = "BPanel"

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, value: str, info):
        app_env = (info.data.get("app_env") or "development").lower()
        if app_env == "production" and (value == DEFAULT_SECRET_KEY or len(value) < 32):
            raise ValueError("SECRET_KEY must be changed to a strong random value in production")
        return value

    @field_validator("allowed_origins")
    @classmethod
    def validate_allowed_origins(cls, value: str, info):
        app_env = (info.data.get("app_env") or "development").lower()
        normalized = [o.strip() for o in (value or "").split(",") if o.strip()]
        if app_env == "production":
            if "*" in normalized:
                raise ValueError("ALLOWED_ORIGINS cannot be '*' in production with credentials enabled")
            for origin in normalized:
                if not origin.startswith(("http://", "https://")):
                    raise ValueError(f"ALLOWED_ORIGINS entry must include scheme: {origin}")
        return value

    @property
    def cors_origins(self) -> list[str]:
        origins = []
        for origin in self.allowed_origins.split(","):
            origin = origin.strip().rstrip("/")
            if not origin or origin == "*":
                continue
            origins.append(origin)
        return origins

    class Config:
        env_file = ".env"


settings = Settings()
