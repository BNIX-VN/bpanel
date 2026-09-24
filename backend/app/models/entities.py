from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserPackage(Base):
    __tablename__ = "user_packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    slug: Mapped[Optional[str]] = mapped_column(String(100), unique=True, nullable=True, index=True)
    website_limit: Mapped[int] = mapped_column(Integer, default=5)
    storage_limit_mb: Mapped[int] = mapped_column(Integer, default=1024)
    database_limit: Mapped[int] = mapped_column(Integer, default=5)
    alias_limit: Mapped[int] = mapped_column(Integer, default=0)
    backup_retention_days: Mapped[int] = mapped_column(Integer, default=7)
    terminal_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    waf_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    wordpress_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 0 keeps app hosting off for every existing package until an admin raises
    # it, the same way terminal_enabled gates the terminal.
    node_apps_limit: Mapped[int] = mapped_column(Integer, default=0)
    node_app_memory_mb: Mapped[int] = mapped_column(Integer, default=512)
    # Extra SFTP logins a user may create, each pinned to one website.
    #
    # Unlike node_apps_limit next door, this grants no access the customer does
    # not already have: a sub-account reaches one site as the uid that owns it,
    # and the customer reaches all of them through the file manager anyway. It
    # exists so they can delegate a narrower credential than the account
    # password. Defaulting it to 0 did not make anyone safer, it made the
    # feature refuse everybody (0034).
    sftp_accounts_limit: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    users: Mapped[List["User"]] = relationship(back_populates="package")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Not unique: several panel users may share a contact email (resellers).
    email: Mapped[str] = mapped_column(String(255), index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="end_user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    package_id: Mapped[Optional[int]] = mapped_column(ForeignKey("user_packages.id", ondelete="SET NULL"), nullable=True, index=True)
    website_limit: Mapped[int] = mapped_column(Integer, default=5)
    storage_limit_mb: Mapped[int] = mapped_column(Integer, default=1024)
    # Copied from the package when one is assigned, exactly like website_limit
    # and storage_limit_mb above, so that enforcement reads one column and a
    # user without a package still resolves to something. UserPackage has
    # carried terminal_enabled since packages were added but nothing ever read
    # it - the terminal checked website ownership only, so the setting did
    # nothing. New accounts default to off: a shell on the server is not
    # something to hand out implicitly.
    terminal_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Copied from the package like the limits above. See UserPackage for why
    # this is not 0: it delegates access the customer already has rather than
    # granting new access, so an admin narrows it rather than opening it.
    sftp_accounts_limit: Mapped[int] = mapped_column(Integer, default=3)
    # When this account's Linux/SFTP password was last set on its own.
    #
    # NULL is load-bearing: it means the Linux password has never been set
    # independently and is still whatever the panel password was. That was the
    # only possible state before 0033, and it made the panel password reachable
    # by brute force against sshd on port 22. Accounts created since get their
    # own secret; legacy ones are retired from the coupling the first time
    # either password is set.
    sftp_password_set_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Bumped to invalidate previously-issued JWTs (logout-everywhere, role
    # change, password reset by admin, account disable, etc).
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    totp_secret: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    websites: Mapped[List["Website"]] = relationship(back_populates="owner")
    package: Mapped[Optional[UserPackage]] = relationship(back_populates="users")
    apps: Mapped[List["SiteApp"]] = relationship(back_populates="owner")


class Website(Base):
    __tablename__ = "websites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    root_path: Mapped[str] = mapped_column(String(500))
    document_root: Mapped[str] = mapped_column(String(255), default="public_html")
    linux_user: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    php_version: Mapped[str] = mapped_column(String(16), default="8.4")
    app_type: Mapped[str] = mapped_column(String(32), default="wordpress")
    ssl_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    ssl_mode: Mapped[str] = mapped_column(String(16), default="none")
    ssl_cert_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    ssl_key_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    ssl_ca_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    ssl_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # For ssl_mode "cloudflare" this is the Cloudflare zone whose wildcard cert
    # this vhost points at; for "shared" it is the source website's domain.
    ssl_source_domain: Mapped[Optional[str]] = mapped_column(String(253), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    nginx_custom: Mapped[str] = mapped_column(Text, default="")
    nginx_config_mode: Mapped[str] = mapped_column(String(16), default="managed")
    nginx_rewrite_mode: Mapped[str] = mapped_column(String(32), default="none")
    waf_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    waf_default_rules: Mapped[str] = mapped_column(Text, default="")
    waf_custom_rules: Mapped[str] = mapped_column(Text, default="")
    # OWASP CRS is per site and off by default: unlike the other WAF toggles it
    # costs real memory, roughly 325 MB of nginx RSS per site that loads it.
    crs_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    http_flood_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    http_flood_config: Mapped[str] = mapped_column(Text, default="")
    # User-agent substrings to answer with 403, one per line. Text rather than a
    # side table because it is edited and applied as one list, and the lists
    # people import run to a few hundred names.
    blocked_bots: Mapped[str] = mapped_column(Text, default="")
    # Set when app_type is "application": the installed app this domain serves.
    app_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("site_apps.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owner: Mapped[User] = relationship(back_populates="websites")
    app: Mapped[Optional["SiteApp"]] = relationship(back_populates="websites")
    database: Mapped[Optional["DatabaseAccount"]] = relationship(back_populates="website", uselist=False)
    aliases: Mapped[List["WebsiteAlias"]] = relationship(
        back_populates="website",
        cascade="all, delete-orphan",
        order_by="WebsiteAlias.domain",
    )


class SiteApp(Base):
    """An application the panel installs, runs and keeps alive.

    An app belongs to a panel user and is independent of any website: it lives
    in its own directory, gets its own loopback port, and runs under its own
    systemd unit. A website in "application" mode then points at one, and nginx
    proxies the domain to that app's port.
    """

    __tablename__ = "site_apps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64), default="app")
    kind: Mapped[str] = mapped_column(String(16), default="node")
    start_kind: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    start_arg: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    node_major: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    # Container runtimes: image reference, the port the process listens on inside
    # the container, and a CPU share. The published side is always loopback.
    image: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    container_port: Mapped[int] = mapped_column(Integer, default=3000)
    cpu_limit: Mapped[str] = mapped_column(String(8), default="1")
    env: Mapped[str] = mapped_column(Text, default="")
    # Compose runtimes: what the customer pasted, and which service the domain
    # reaches. The file that actually runs is regenerated from these, never
    # stored as the source of truth.
    compose_source: Mapped[str] = mapped_column(Text, default="")
    web_service: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    port: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    memory_limit_mb: Mapped[int] = mapped_column(Integer, default=512)
    autostart: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="stopped")
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owner: Mapped[User] = relationship(back_populates="apps")
    websites: Mapped[List[Website]] = relationship(back_populates="app")

    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_site_apps_owner_name"),)


class WebsiteAlias(Base):
    __tablename__ = "website_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(16), default="alias")
    ssl_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    website: Mapped[Website] = relationship(back_populates="aliases")


class DatabaseAccount(Base):
    __tablename__ = "database_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    website_id: Mapped[Optional[int]] = mapped_column(ForeignKey("websites.id"), nullable=True)
    db_name: Mapped[str] = mapped_column(String(64), unique=True)
    db_user: Mapped[str] = mapped_column(String(64), unique=True)
    db_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owner: Mapped["User"] = relationship()
    website: Mapped[Optional[Website]] = relationship(back_populates="database")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(128))
    target: Mapped[str] = mapped_column(String(255))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    jti: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SftpBackupTarget(Base):
    """Somewhere off this machine to put a backup.

    The table keeps its original name because renaming it would move every
    foreign key for no gain; `kind` is what says whether a row is an SSH
    server or an S3 bucket. The SFTP columns are null on an S3 row and the S3
    columns are null on an SFTP row, which is the price of one table and one
    foreign key from backup_schedules instead of two of each.
    """

    __tablename__ = "sftp_backup_targets"

    KIND_SFTP = "sftp"
    KIND_S3 = "s3"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(8), default=KIND_SFTP)

    # --- S3 and anything that speaks its API (Wasabi, B2, Spaces, R2, MinIO)
    endpoint: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    region: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    bucket: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    access_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    secret_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prefix: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    secure: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- SFTP
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=22)
    username: Mapped[str] = mapped_column(String(128))
    password: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    private_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    remote_path: Mapped[str] = mapped_column(String(500), default="/backups/bpanel")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # TOFU host key pinning so the second SSH connection on cannot be silently
    # MITM'd. Populated on first successful connect (or by an explicit rotate
    # action) and verified on every connect afterwards.
    host_key_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    host_key_fingerprint: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BackupSchedule(Base):
    __tablename__ = "backup_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    user_ids: Mapped[str] = mapped_column(Text, default="")
    all_users: Mapped[bool] = mapped_column(Boolean, default=False)
    target_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sftp_backup_targets.id"), nullable=True)
    schedule: Mapped[str] = mapped_column(String(100), default="0 2 * * *")
    # What gets appended to the stored file name, which decides how many files
    # a schedule keeps at the far end. "none" overwrites one file per account;
    # "day_of_week" rotates through seven; "week_of_month" through five;
    # "full_date" keeps one per day and grows until retention prunes it.
    name_suffix: Mapped[str] = mapped_column(String(16), default="full_date")
    retention: Mapped[int] = mapped_column(Integer, default=7)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(32), default="pending")
    last_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    scopes: Mapped[str] = mapped_column(Text, default="provisioning:read,provisioning:write")
    allowed_ips: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class McpToken(Base):
    """A personal token an AI assistant uses to reach the panel over MCP.

    Deliberately not a row in `api_tokens`. That table serves provisioning:
    it is owned by nobody in particular, carries scopes and an IP allowlist,
    and never expires. An MCP token is the opposite on every count - it acts
    as one named user, it is created by that user, it expires, and its whole
    permission model is "can this write". Sharing one table would mean every
    check on either side having to ask which kind it was looking at.

    The token itself is never stored. `token_hash` is SHA-256 of it, and
    `prefix` keeps the first twelve characters so a person with four tokens
    can tell which one they are revoking.
    """

    __tablename__ = "mcp_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(16))
    # Read-only unless the person ticked "Allow actions". A token that cannot
    # write is not shown the tools that write, so an assistant holding one
    # cannot even discover that they exist.
    can_write: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    # Written at most once a minute: every tool call would otherwise be a
    # database write, and the value is only ever read by a human.
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CloudflareCredential(Base):
    """A Cloudflare API token (Zone.DNS Edit), one per zone, stored encrypted.

    Used for DNS-01 wildcard issuance and kept so certbot can auto-renew the
    wildcard cert unattended. The plaintext token only ever leaves here to be
    handed to the privileged helper on stdin.
    """

    __tablename__ = "cloudflare_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    zone: Mapped[str] = mapped_column(String(253), unique=True, index=True)
    api_token: Mapped[str] = mapped_column(Text)  # Fernet ciphertext
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProvisioningAccount(Base):
    __tablename__ = "provisioning_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    external_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    primary_website_id: Mapped[Optional[int]] = mapped_column(ForeignKey("websites.id"), nullable=True)
    package_id: Mapped[Optional[int]] = mapped_column(ForeignKey("user_packages.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    last_action: Mapped[str] = mapped_column(String(64), default="")
    last_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped[Optional[User]] = relationship()
    primary_website: Mapped[Optional[Website]] = relationship(foreign_keys=[primary_website_id])
    package: Mapped[Optional[UserPackage]] = relationship()


class SftpAccount(Base):
    """An extra SFTP login, pinned to exactly one website.

    A panel user's own Linux account already reaches every site they own. This
    is the credential you hand to someone who should reach one of them: a
    freelancer, a deploy script, an agency.

    It is a real Linux user, because OpenSSH has no virtual ones, and it shares
    the site owner's uid on purpose (`useradd -o -u`). Files it uploads then
    land with exactly the ownership the owner's own upload would produce, so
    PHP-FPM keeps write access and WordPress can still update itself. The
    isolation is the chroot, not the uid - which is why chroot_path is
    root-owned and outside anything the panel account can write.
    """

    __tablename__ = "sftp_accounts"
    __table_args__ = (
        UniqueConstraint("owner_id", "website_id", "label", name="ix_sftp_accounts_owner_label"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Denormalised from the website so the teardown sweep has one column to
    # filter on. Written together with website_id, never inferred from it: a
    # transferred site takes its sub-accounts to the new owner.
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    website_id: Mapped[int] = mapped_column(Integer, index=True)
    # What the user typed. The login name is linux_user, which is generated.
    label: Mapped[str] = mapped_column(String(32))
    linux_user: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    chroot_path: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    password_set_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class WebauthnCredential(Base):
    """A passkey, belonging to one account and one hostname.

    WebAuthn binds a credential to a Relying Party ID, which is a hostname, and
    a browser will not even reveal that a credential exists to any other name.
    app/serve.py answers on every hostname on the machine that has a
    certificate, so an account can hold one of these per name it signs in
    through - hence rp_id as a column rather than a panel setting.

    That is also why TOTP stays available beside it: a passkey registered for
    one name is simply not offered at another, and with no second factor to
    fall through to, that would be a lockout rather than a security feature.
    """

    __tablename__ = "webauthn_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    # base64url of the raw credential id, as the browser reports it.
    credential_id: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    public_key: Mapped[str] = mapped_column(Text)
    # Replay defence: an authenticator that counts must never go backwards. One
    # that does not count reports 0 forever, which the spec allows.
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    rp_id: Mapped[str] = mapped_column(String(253), index=True)
    transports: Mapped[str] = mapped_column(String(128), default="")
    # What the customer called it, so a lost device can be identified.
    name: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
