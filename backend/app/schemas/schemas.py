import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


DOMAIN_RE = re.compile(r"^(?!-)([a-zA-Z0-9-]{1,63}\.)+[a-zA-Z]{2,}$")
SUPPORTED_PHP_VERSIONS = {"8.3", "8.4"}
SUPPORTED_APP_TYPES = {"wordpress", "static"}
SUPPORTED_ROLES = {"user", "readonly", "admin", "super_admin"}
SIZE_RE = re.compile(r"^\d{1,6}[KMG]?$")  # e.g. "512M", "1024M"


def _validate_php_version(value: Optional[str]) -> Optional[str]:
    if value is None:
        return value
    if value not in SUPPORTED_PHP_VERSIONS:
        raise ValueError(f"Unsupported PHP version. Allowed: {sorted(SUPPORTED_PHP_VERSIONS)}")
    return value


def _validate_app_type(value: Optional[str]) -> Optional[str]:
    if value is None:
        return value
    if value not in SUPPORTED_APP_TYPES:
        raise ValueError(f"Unsupported app type. Allowed: {sorted(SUPPORTED_APP_TYPES)}")
    return value


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginResponse(BaseModel):
    access_token: Optional[str] = None
    token_type: str = "bearer"
    requires_2fa: bool = False


class TwoFactorStatus(BaseModel):
    enabled: bool


class TwoFactorSetup(BaseModel):
    secret: str
    provisioning_uri: str
    qr_data_url: str


class TwoFactorCode(BaseModel):
    code: str = Field(min_length=6, max_length=12)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    email: EmailStr
    password: str = Field(min_length=12, max_length=72)  # bcrypt 72-byte limit
    role: Literal["user", "readonly", "admin", "super_admin"] = "user"
    website_limit: int = Field(default=5, ge=0, le=1000)
    storage_limit_mb: int = Field(default=1024, ge=0, le=1024 * 1024)


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    role: Optional[Literal["user", "readonly", "admin", "super_admin"]] = None
    is_active: Optional[bool] = None
    website_limit: Optional[int] = Field(default=None, ge=0, le=1000)
    storage_limit_mb: Optional[int] = Field(default=None, ge=0, le=1024 * 1024)


class UserPasswordUpdate(BaseModel):
    password: str = Field(min_length=12, max_length=72)


class UserOut(BaseModel):
    id: int
    username: str
    email: EmailStr
    role: str
    is_active: bool
    website_limit: int
    storage_limit_mb: int
    totp_enabled: bool = False

    class Config:
        from_attributes = True


class AuditLogOut(BaseModel):
    id: int
    user_id: Optional[int] = None
    action: str
    target: str
    detail: str = ""
    created_at: Optional[str] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_row(cls, row) -> "AuditLogOut":
        return cls(
            id=row.id,
            user_id=row.user_id,
            action=row.action,
            target=row.target,
            detail=row.detail or "",
            created_at=row.created_at.isoformat() if row.created_at else None,
        )


class WebsiteCreate(BaseModel):
    domain: str
    owner_id: Optional[int] = None
    php_version: str = "8.3"
    app_type: str = "wordpress"
    install_wordpress: bool = True
    title: str = "My WordPress Site"
    admin_user: str = "admin"
    admin_email: Optional[EmailStr] = None
    admin_password: Optional[str] = None

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        value = value.strip().lower()
        if not DOMAIN_RE.match(value):
            raise ValueError("Invalid domain")
        return value

    @field_validator("php_version")
    @classmethod
    def validate_php(cls, value: str) -> str:
        return _validate_php_version(value)

    @field_validator("app_type")
    @classmethod
    def validate_app(cls, value: str) -> str:
        return _validate_app_type(value)

    @field_validator("admin_password")
    @classmethod
    def validate_admin_password(cls, value: Optional[str]) -> Optional[str]:
        if value is None or value == "":
            return value
        if len(value) < 10:
            raise ValueError("admin_password must be at least 10 characters")
        return value


class WebsiteUpdate(BaseModel):
    php_version: Optional[str] = None
    status: Optional[str] = None
    owner_id: Optional[int] = None
    nginx_custom: Optional[str] = None

    @field_validator("php_version")
    @classmethod
    def validate_php(cls, value: Optional[str]) -> Optional[str]:
        return _validate_php_version(value)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        allowed = {"active", "suspended", "pending"}
        if value not in allowed:
            raise ValueError(f"status must be one of {sorted(allowed)}")
        return value


class WebsiteNginxCustom(BaseModel):
    nginx_custom: str = ""


class DatabasePasswordUpdate(BaseModel):
    password: str = Field(min_length=12)


class DatabaseCreate(BaseModel):
    website_id: int
    db_name: Optional[str] = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")

    @field_validator("db_name", mode="before")
    @classmethod
    def validate_db_name(cls, value) -> Optional[str]:
        if value is None or value == "":
            return None
        return str(value).strip().lower()


class CronDelete(BaseModel):
    website_id: int
    index: int


class WebsiteOut(BaseModel):
    id: int
    domain: str
    owner_id: int
    root_path: str
    linux_user: Optional[str] = None
    panel_username: Optional[str] = None
    panel_password: Optional[str] = None
    php_version: str
    app_type: str
    ssl_enabled: bool
    status: str
    nginx_custom: str = ""

    class Config:
        from_attributes = True


class DatabaseOut(BaseModel):
    id: int
    website_id: int
    db_name: str
    db_user: str

    class Config:
        from_attributes = True


class DatabaseCreatedOut(DatabaseOut):
    db_password: str


class ServiceAction(BaseModel):
    name: str
    action: str


class FirewallPortRule(BaseModel):
    port: str = Field(min_length=1, max_length=5)
    protocol: str = "tcp"


class FirewallIpRule(BaseModel):
    ip: str = Field(min_length=3, max_length=64)
    port: Optional[str] = Field(default=None, max_length=5)
    protocol: str = "tcp"


class BackupCreate(BaseModel):
    website_id: int


def _validate_backup_schedule(value: str) -> str:
    fields = (value or "").split()
    field_re = re.compile(r"^(?:\*|\d{1,2})(?:[-/,](?:\*|\d{1,2}))*$")
    if len(fields) != 5 or not all(field_re.fullmatch(field) for field in fields):
        raise ValueError("Invalid cron schedule")
    return " ".join(fields)


class UserBackupCreate(BaseModel):
    user_id: int
    target_id: Optional[int] = None


class UserRestoreBackup(BaseModel):
    backup_file: str


class BackupScheduleCreate(BaseModel):
    user_id: int
    schedule: str = "0 2 * * *"
    target_id: Optional[int] = None
    retention: int = Field(default=7, ge=1, le=365)
    is_active: bool = True

    @field_validator("schedule")
    @classmethod
    def validate_schedule(cls, value: str) -> str:
        return _validate_backup_schedule(value)


class BackupScheduleOut(BaseModel):
    id: int
    user_id: int
    target_id: Optional[int] = None
    schedule: str
    retention: int
    is_active: bool
    last_run_at: Optional[datetime] = None
    last_status: str
    last_message: str = ""

    class Config:
        from_attributes = True


class SftpBackupTargetCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100, pattern=r"^[A-Za-z0-9._ -]+$")
    host: str = Field(min_length=2, max_length=255)
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=128)
    password: Optional[str] = Field(default=None, max_length=4096)
    private_key: Optional[str] = Field(default=None, max_length=20000)
    remote_path: str = Field(default="/backups/bpanel", min_length=1, max_length=500)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9._:-]+", value):
            raise ValueError("Invalid SFTP host")
        return value

    @field_validator("remote_path")
    @classmethod
    def validate_remote_path(cls, value: str) -> str:
        value = value.strip()
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError("Invalid remote path")
        return value.rstrip("/") or "/"


class SftpBackupTargetOut(BaseModel):
    id: int
    name: str
    host: str
    port: int
    username: str
    remote_path: str
    is_active: bool

    class Config:
        from_attributes = True


class SftpBackupRun(BaseModel):
    website_id: int
    target_id: int


class RestoreBackup(BaseModel):
    website_id: int
    backup_file: str


class PhpConfigUpdate(BaseModel):
    php_version: Literal["8.3", "8.4"] = "8.3"
    display_errors: Literal["On", "Off"] = "Off"
    memory_limit: str = "512M"
    upload_max_filesize: str = "1024M"
    post_max_size: str = "1024M"
    max_execution_time: int = Field(default=300, ge=1, le=3600)
    max_input_time: int = Field(default=600, ge=1, le=3600)
    max_input_vars: int = Field(default=10000, ge=100, le=1_000_000)

    @field_validator("memory_limit", "upload_max_filesize", "post_max_size")
    @classmethod
    def validate_size(cls, value: str) -> str:
        value = (value or "").strip()
        if not SIZE_RE.fullmatch(value):
            raise ValueError("must match digits optionally followed by K, M, or G")
        return value


class CronCreate(BaseModel):
    website_id: int
    schedule: str
    command: str


class WpAction(BaseModel):
    website_id: int
    action: str
