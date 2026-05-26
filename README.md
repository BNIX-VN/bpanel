# BPanel

Lightweight server management panel for Ubuntu 24.04. BPanel helps you spin up
WordPress sites, manage databases, SSL, backups, services, and a UFW firewall
from a single web UI.

- WordPress one-click installer (PHP 8.3 / 8.4) with WP-CLI
- Static sites with editable per-site Nginx blocks
- One isolated, locked Linux user per new website; source lives in `/home/<site-user>/<domain>/public`
- Admin-created websites also get a matching panel user with the same site username
- MariaDB database creation and management with phpMyAdmin SSO (60s tokens)
- Let's Encrypt SSL via certbot
- Native BPanel file manager with upload, edit, archive, and extract support
- Backups: archive site files + SQL, scheduled full-user backups, restore, upload, download
- SFTP backup targets for off-server backup copies
- UFW firewall manager (allow port, allow/block IP, delete rules)
- PHP-FPM config editor per version
- Cron job manager with whitelisted WP-CLI commands
- Role-based access: super_admin / admin / user / readonly
- Google Authenticator compatible 2FA

## Tech stack

- Backend: FastAPI, SQLAlchemy, SQLite (default), Pydantic v2
- Frontend: React 18, Vite, lucide-react
- Server: Nginx, systemd, MariaDB, Redis, PHP-FPM, certbot

## System requirements

- Ubuntu 24.04 LTS (clean install recommended)
- Root access
- Optional: a domain pointing to the server's public IP (for SSL on the panel)
- 1 vCPU / 1 GB RAM minimum, 2 vCPU / 2 GB RAM recommended

## Install from GitHub

Run as root on a fresh Ubuntu 24.04 server:

```bash
apt-get update && apt-get install -y git
git clone https://github.com/BNIX-VN/bpanel.git /opt/bpanel-source
cd /opt/bpanel-source
chmod +x installer/install.sh installer/update.sh
sudo bash installer/install.sh
```

The installer will:

1. Install Nginx, MariaDB, Redis, PHP 8.3/8.4, Node.js 22, certbot, phpMyAdmin,
   WP-CLI, UFW.
2. Copy source to `/opt/bpanel`, build the frontend, set up the Python venv.
3. Create the systemd service `bpanel-api`.
4. Configure phpMyAdmin SSO.
5. Start the panel directly on port `2222` without relying on Nginx for login.
6. Issue Let's Encrypt SSL for the panel domain (optional).
7. Print the admin login at the end. Save it.

You will be prompted for:

- Panel domain/URL (optional; blank uses `http://SERVER_IP:2222`)
- Whether to enable Let's Encrypt SSL for the panel domain
- An email for SSL registration

After install, open the URL printed at the end of the installer. If no panel
domain was entered, use `http://SERVER_IP:2222`. The admin password is shown
once — store it in a password manager.

## SSH maintenance menu

Run as root:

```bash
bpanel
```

The menu can set the panel URL/port, install SSL for the panel URL, fix runtime
permissions, show status, and change the `admin` password.

## Update an existing install

After pushing changes to GitHub:

```bash
cd /opt/bpanel-source
sudo bash installer/update.sh
```

The script pulls latest from GitHub, syncs source to `/opt/bpanel`, rebuilds the
frontend, refreshes the direct panel service, and reloads Nginx for customer
vhosts. Old `dist` and Vite caches are
purged so the new bundle hash propagates to browsers.

If the browser still shows the old UI, do a hard refresh (Ctrl + Shift + R) or
open in incognito.

## Project layout

```
bpanel/
├─ backend/                    FastAPI application
│  ├─ alembic/                 SQL schema migrations (Alembic)
│  │  └─ versions/             Migration scripts
│  ├─ alembic.ini              Alembic config
│  ├─ app/
│  │  ├─ api/                  HTTP routes
│  │  ├─ core/                 config, db, security, permissions, secrets
│  │  ├─ models/               SQLAlchemy entities
│  │  ├─ schemas/              Pydantic v2 schemas
│  │  ├─ services/             nginx, mariadb, wp, firewall, backup, etc.
│  │  ├─ templates/nginx/      Jinja2 vhost templates
│  │  ├─ main.py
│  │  └─ seed.py               Seeds the first admin user
│  ├─ tests/                   pytest smoke tests for validators
│  └─ requirements.txt
├─ frontend/                   React + Vite SPA
│  └─ src/
├─ installer/
│  ├─ files/                   bpanel-helper.sh + sudoers rule
│  ├─ install.sh               Full first-time install
│  ├─ migrate-security.sh      One-shot migration to non-root + helper mode
│  └─ update.sh                Pull from GitHub and redeploy
└─ README.md
```

## Database migrations

Schema changes are managed by [Alembic](https://alembic.sqlalchemy.org/).
Migrations live in `backend/alembic/versions/`. The backend automatically
runs `alembic upgrade head` on startup and `installer/update.sh` runs it
explicitly before restarting the API.

To author a new migration locally:

```bash
cd backend
.venv/bin/alembic revision --autogenerate -m "describe change"
# Inspect the generated file in alembic/versions/, then commit it.
```

Existing servers that pre-date Alembic adoption are detected at startup
(tables exist but `alembic_version` does not) and are stamped to revision
`0001_initial` so no DDL is replayed on already-correct schemas.

## Roles

| Role          | Capabilities                                        |
|---------------|-----------------------------------------------------|
| `super_admin` | Full control including stack reinstall              |
| `admin`       | Manage all sites, users, services, firewall, PHP    |
| `user`        | Manage only sites assigned to them                  |
| `readonly`    | View-only access                                    |

## Configuration

`/opt/bpanel/backend/.env` is generated by the installer and contains:

```ini
APP_ENV=production
SECRET_KEY=<random-32-bytes>
COMMAND_DRY_RUN=false
DATABASE_URL=sqlite:////opt/bpanel/backend/bpanel.db
ALLOWED_ORIGINS=https://panel.example.com
SITES_ROOT=/home/bpanel-sites  # legacy/imported sites; new sites use /home/<site-user>/<domain>
BACKUP_ROOT=/var/backups/bpanel
SSL_EMAIL=admin@example.com
PANEL_URL=http://SERVER_IP:2222
PANEL_DOMAIN=
PANEL_PORT=2222
PANEL_SSL_CERT=
PANEL_SSL_KEY=
FRONTEND_DIST=/opt/bpanel/frontend/dist
```

The backend refuses to start in production with `COMMAND_DRY_RUN=true` or
`ALLOWED_ORIGINS=*`. SECRET_KEY must be at least 32 chars in production.

## Service commands

```bash
# API logs
journalctl -u bpanel-api -f

# Restart the API after backend changes
systemctl restart bpanel-api

# Reload Nginx after vhost edits
nginx -t && systemctl reload nginx

# Service status
systemctl status bpanel-api nginx mariadb php8.3-fpm
```

## Security model

The panel daemon does **not** run as root. The installer creates a system user
`bpanel` and a single root-owned helper script that does all privileged work.

```
bpanel-api  (uvicorn, user=bpanel, hardened systemd unit)
   │
   │  sudo -n /usr/local/sbin/bpanel-helper <subcommand> ...
   ▼
bpanel-helper  (root, runs only whitelisted operations)
```

What the helper allows:

- `systemctl start/stop/restart/reload <whitelisted service>`
- `nginx -t`, `nginx reload`
- `certbot --nginx ...` for a single validated domain
- create/delete per-site Linux users and PHP-FPM pools (`bp_*` users only)
- `ufw status/enable/disable/allow/deny/delete`
- fix ownership/ACLs for managed site paths under `/home/<site-user>/<domain>` or legacy `/home/bpanel-sites`
- `rm -rf <managed site path>`
- WP-CLI and crontab management as the isolated site user

Anything else is rejected. The helper validates domains, ports, IPs, and
filesystem paths before invoking the real binary.

The installer also creates a local MariaDB `bpanel` account used by the API to
create per-site databases and users for WordPress installs.

Additional hardening on the systemd unit:

- `ProtectHome=read-only`
- `PrivateTmp`, `PrivateDevices`, `ProtectKernelModules`, `ProtectKernelLogs`
- `MemoryDenyWriteExecute`, `LockPersonality`
- `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK`
- Privileged operations stay constrained by the root-owned helper and sudoers

`NoNewPrivileges`, `ProtectSystem=strict`, `RestrictSUIDSGID`, broad syscall
deny-lists, and capability bounding must not block the helper: `bpanel-api`
intentionally uses `sudo -n /usr/local/sbin/bpanel-helper` for the narrowly
whitelisted root operations.

If the API itself were ever compromised, the attacker would be limited to:
- writing into `/etc/nginx/conf.d/`, managed site paths under `/home`, and `/var/backups/bpanel/`
- running the helper subcommands above (no arbitrary code execution as root)

There is no path back to root via the API process.

## Security notes

- Login is rate-limited (8 attempts / minute, lockout after 20 fails).
- Google Authenticator compatible TOTP 2FA can be enabled per account.
- Constant-time login path: bcrypt is verified even when the user does not
  exist, to avoid username enumeration via timing.
- DB and WordPress passwords are passed via stdin / `--prompt`, never as
  command-line args, so they don't appear in `ps`.
- DB passwords are encrypted at rest (Fernet, key derived from SECRET_KEY).
- Custom Nginx blocks are validated: braces must balance, dangerous directives
  (`server {`, `http {`, `events {`, `include`, `load_module`, `user`, `lua_*`,
  `proxy_pass`, `alias`, `*_log`, `ssl_*`) are rejected, max 16 KB.
- File manager rejects symlinks anywhere in the path. Website owners can manage
  their own deploy sources, including PHP, `.htaccess`, `.env`, and
  `wp-config.php`, with quota and ownership checks enforced by BPanel.
- Path traversal is blocked at every layer that touches the filesystem.
- Auth uses HttpOnly cookies (`bpanel_session`) plus a CSRF token cookie
  (`bpanel_csrf`) echoed in the `X-CSRF-Token` header. The JWT is never
  exposed to JavaScript, mitigating token theft via XSS.
- Strict `Content-Security-Policy` (`script-src 'self'`, `frame-ancestors 'none'`).
- `token_version` on the User row invalidates previously issued JWTs on
  password change, role change, account disable, or explicit logout.

## License

MIT — see LICENSE.
