# BPanel

Lightweight hosting management panel for Ubuntu 24.04. BPanel helps you run
WordPress and PHP websites from a single clean web UI with user
ownership, quotas, backups, SSL, services, and firewall tools built in.

- Dashboard resource monitoring for CPU, RAM, disk, and network throughput
- WordPress one-click installer (PHP 8.3 / 8.4) with WP-CLI
- WordPress and PHP sites with editable full Nginx vhosts
- Panel users map to locked Linux users; website source lives in `/home/<panel-user>/<domain>/public_html`
- Admin quick-login for creating sites as a selected user, plus one-owner assignment per website
- Website count limits and BPanel soft storage quotas per end user
- MariaDB database creation and management with phpMyAdmin SSO (60s tokens)
- Let's Encrypt SSL via certbot
- Native BPanel file manager with upload, edit, archive, and extract support
- Backups: archive site files + SQL, scheduled full-user backups, restore, upload, download
- SFTP backup targets for off-server backup copies
- UFW firewall manager with protected panel/web/mail defaults and user rules below them
- Update controls for apt-based OS packages and BPanel source updates
- Nginx ModSecurity/WAF engine installed by default, with per-site toggles
- PHP-FPM config editor per version
- Cron job manager with whitelisted WP-CLI commands
- Role-based access: Admin / End user
- Google Authenticator compatible 2FA

## Tech stack

- Backend: FastAPI, SQLAlchemy, SQLite (default), Pydantic v2
- Frontend: React 18, Vite, lucide-react
- Server: Nginx, ModSecurity/WAF, systemd, MariaDB, Redis, PHP-FPM, certbot

## Versioning

Current release: `1.00.0009`.

BPanel versions use `xx.yy.zzzz`: `xx` for major/release changes, `yy` for
feature updates in the same release line, and `zzzz` for bugfix builds.

## System requirements

- Ubuntu 24.04 LTS (clean install recommended)
- Root access
- Optional: a domain pointing to the server's public IP (for SSL on the panel)
- 1 vCPU / 1 GB RAM minimum, 2 vCPU / 2 GB RAM recommended

## Install from GitHub

Run as root on a fresh Ubuntu 24.04 server:

```bash
apt-get update;apt-get install -y git;\
git clone https://github.com/BNIX-VN/bpanel.git /opt/bpanel-source;\
cd /opt/bpanel-source;\
chmod +x installer/install.sh installer/update.sh;\
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
7. Print the admin login and save it to `/root/login.txt`.

You will be prompted for:

- Panel hostname (optional; blank uses the server IP)
- Panel port (default `2222`)
- Whether to enable Let's Encrypt SSL for the panel domain
- An email for SSL registration

After install, open the URL printed at the end of the installer. If no panel
domain was entered, use `http://SERVER_IP:2222`. The admin password is shown
at the end and saved to `/root/login.txt`; store it in a password manager.

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
|-- backend/                    FastAPI application
|   |-- alembic/                 SQL schema migrations (Alembic)
|   |   `-- versions/             Migration scripts
|   |-- alembic.ini              Alembic config
|   |-- app/
|   |   |-- api/                  HTTP routes
|   |   |-- core/                 config, db, security, permissions, secrets
|   |   |-- models/               SQLAlchemy entities
|   |   |-- schemas/              Pydantic v2 schemas
|   |   |-- services/             nginx, mariadb, wp, firewall, backup, etc.
|   |   |-- templates/nginx/      Jinja2 vhost templates
|   |   |-- main.py
|   |   `-- seed.py               Seeds the first admin user
|   |-- tests/                   pytest smoke tests for validators
|   `-- requirements.txt
|-- frontend/                   React + Vite SPA
|   `-- src/
|-- installer/
|   |-- files/                   bpanel-helper.sh + sudoers rule
|   |-- install.sh               Full first-time install
|   |-- migrate-security.sh      One-shot migration to non-root + helper mode
|   `-- update.sh                Pull from GitHub and redeploy
`-- README.md
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

| Role | Capabilities |
|------|--------------|
| `admin` | Full control: websites, users, ownership assignment, services, firewall, PHP config, backups, and security settings. |
| `end_user` | Manage only websites assigned to the account, including files, databases, SSL, WordPress tools, cron, and own backups. |

## User and website ownership

- Each panel user also has a locked Linux user with the same normalized username.
- New websites are created under `/home/<panel-user>/<domain>/public_html`.
- If an admin creates a website without impersonating another user, the website
  belongs to the admin account.
- Admins can quick-login as another panel user before creating websites for
  that account.
- Admins can assign a website to exactly one panel user. Moving ownership also
  moves the site path to the new Linux user and rewrites the PHP-FPM/Nginx
  runtime configuration.
- Deleting a panel user permanently deletes all websites, files, databases,
  backup schedule links, cron entries, PHP-FPM pools, and Linux-user data owned
  by that user.

## Quotas

- End users have a website count limit and a storage limit in MB.
- Admin users are not storage-limited.
- Storage usage is calculated from all websites owned by the user.
- BPanel enforces the storage limit before site creation, upload, edit, archive,
  extract, and ownership assignment operations.
- This is an application-level soft quota, not an OS disk quota.

## Configuration

`/opt/bpanel/backend/.env` is generated by the installer and contains:

```ini
APP_ENV=production
SECRET_KEY=<random-32-bytes>
COMMAND_DRY_RUN=false
DATABASE_URL=sqlite:////opt/bpanel/backend/bpanel.db
REDIS_URL=redis://localhost:6379/0
RATE_LIMIT_BACKEND=redis
ALLOWED_ORIGINS=https://panel.example.com
SITES_ROOT=/home/bpanel-sites  # legacy/imported sites; new sites use /home/<panel-user>/<domain>
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
systemctl status bpanel-api nginx mariadb redis-server php8.3-fpm php8.4-fpm
```

## Security model

The panel daemon does **not** run as root. The installer creates a system user
`bpanel` and a single root-owned helper script that does all privileged work.

```
bpanel-api  (uvicorn, user=bpanel, hardened systemd unit)
   |
   |  sudo -n /usr/local/sbin/bpanel-helper <subcommand> ...
   v
bpanel-helper  (root, runs only whitelisted operations)
```

What the helper allows:

- `systemctl start/stop/restart/reload <whitelisted service>`
- `nginx -t`, `nginx reload`
- `certbot --nginx ...` for a single validated domain
- create/delete locked panel Linux users and per-user PHP-FPM pools
- `ufw status/enable/disable/allow/deny/delete`
- fix ownership/ACLs for managed site paths under `/home/<panel-user>/<domain>` or legacy `/home/bpanel-sites`
- `rm -rf <managed site path>`
- WP-CLI and crontab management as the website's Linux user

Anything else is rejected. The helper validates domains, ports, IPs, and
filesystem paths before invoking the real binary.

The installer also creates a local MariaDB `bpanel` account used by the API to
create per-site databases and users for WordPress installs.

Additional hardening on the systemd unit:

- Runs as `bpanel` with only the `www-data` and `bpanel-sites` supplementary groups.
- Uses `PrivateTmp`, `PrivateDevices`, `ProtectKernelTunables`,
  `ProtectKernelModules`, `ProtectKernelLogs`, `ProtectControlGroups`,
  `ProtectClock`, `ProtectHostname`, and `ProtectProc=invisible`.
- Uses `RestrictNamespaces`, `RestrictRealtime`, `LockPersonality`,
  `MemoryDenyWriteExecute`, `SystemCallArchitectures=native`, and
  `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK`.
- Drops ambient capabilities with `CapabilityBoundingSet=~`.

`NoNewPrivileges=false`, `ProtectSystem=false`, `ProtectHome=false`, and
`RestrictSUIDSGID=false` are intentional because the API must invoke the sudo
helper and manage website files under `/home`. Privileged operations stay
constrained by the root-owned helper and sudoers allowlist.

If the API itself were ever compromised, the attacker would be limited to:
- writing into `/etc/nginx/conf.d/`, managed site paths under `/home`, and `/var/backups/bpanel/`
- running the helper subcommands above (no arbitrary code execution as root)

There is no path back to root via the API process.

## Security notes

- Login is rate-limited in Redis (8 attempts / minute, lockout after 20 fails),
  so counters are shared across uvicorn workers.
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
- JWTs include a `jti`; revoked session IDs are stored server-side, and
  `token_version` invalidates previously issued JWTs on password change, role
  change, account disable, 2FA changes, or explicit logout.
- Production installs require `RATE_LIMIT_BACKEND=redis`, reject
  `ALLOWED_ORIGINS=*`, enforce `COMMAND_DRY_RUN=false`, and return generic
  500 responses for unhandled errors.

## License

MIT - see LICENSE.
