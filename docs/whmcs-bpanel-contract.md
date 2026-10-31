# WHMCS ↔ BPanel Provisioning API Contract

**Version**: 1.0.0  
**Base path**: `/api/provisioning/v1` (router prefix `/provisioning/v1` mounted under `/api`)  
**Auth**: Bearer API token (not a user session)  
**Content-Type**: `application/json`

## Architecture

| System | Responsibility |
|--------|---------------|
| WHMCS | Billing, orders, invoices, service status, client management |
| BPanel | Hosting accounts, websites, databases, SSL, quotas, runtime, SSO |

WHMCS never touches the BPanel database directly — everything goes through this
provisioning API. The bundled WHMCS server module lives in
`modules/servers/bpanel/`.

## Response format

BPanel returns the **raw data object (or array) directly. There is NO
`{success, data, error}` envelope.** `GET /plans` returns a JSON array; every
account endpoint returns a JSON object.

Error responses use FastAPI's default shape with a 4xx/5xx status:

```json
{ "detail": "Human-readable error message" }
```

A `422` (request-body validation) returns `detail` as an **array** of
field-error objects instead of a string. The WHMCS module reads `detail`
(falling back to the raw body) for the message.

> This is the biggest difference from a panel that wraps responses in an
> envelope — do not expect `success`/`data`/`error` keys here.

## Auth

Tokens are stored in the `api_tokens` table (SHA-256 hash only; the raw value is
shown once at creation). A provisioning token:

- is sent as `Authorization: Bearer <token>` (the module takes it from the
  server **Access Hash**, falling back to **Password**);
- carries a comma-separated `scopes` string — `provisioning:read` and/or
  `provisioning:write`;
- **never expires** (there is no expiry on provisioning tokens);
- may carry an optional comma-separated IP allowlist (enforced → `403` when set
  and the caller's IP is not listed);
- has a `bp_` prefix on its raw value.

**Scope rules to note:**

- `provisioning:read` → `GET /plans`, `GET /accounts/{id}`, `GET …/usage`.
  `TestConnection` calls `/plans`, so it needs **read**.
- `provisioning:write` → create, suspend, unsuspend, terminate, password,
  package, **and login**. The SSO "Login to BPanel" link therefore needs
  **write**; a read-only token silently falls back to the plain panel URL.

Give the WHMCS server's token **both** scopes.

### Issuing a token

Token management endpoints are **admin-only and authenticated by a panel admin
session cookie** (not a Bearer token), kept apart from the WHMCS surface:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/provisioning/v1/tokens` | list tokens (no secrets) |
| POST | `/api/provisioning/v1/tokens` | create a token; returns the raw value once |
| DELETE | `/api/provisioning/v1/tokens/{id}` | revoke a token |

## external_id

Every account is keyed by `external_id = "whmcs:{serviceid}"`. The API treats it
as an opaque idempotency/lookup key. For display, `whmcs:` is stripped and the
`service_label` renders as e.g. `Starter #7`.

## Endpoints

| # | Method + path | Scope | Notes |
|---|---------------|-------|-------|
| 1 | `GET /plans` | read | global packages only (`owner_id IS NULL`) |
| 2 | `POST /accounts` | write | create, idempotent, **HTTP 200** |
| 3 | `GET /accounts/{external_id}` | read | account status |
| 4 | `POST /accounts/{external_id}/login` | write | one-time SSO link |
| 5 | `POST /accounts/{external_id}/suspend` | write | |
| 6 | `POST /accounts/{external_id}/unsuspend` | write | |
| 7 | `DELETE /accounts/{external_id}` | write | full teardown |
| 8 | `PATCH /accounts/{external_id}/password` | write | may rotate SFTP password |
| 9 | `PATCH /accounts/{external_id}/package` | write | change plan (quota only) |
| 10 | `GET /accounts/{external_id}/usage` | read | disk + counts |

### `GET /plans`

Lists the administrator's **global** packages only (`owner_id IS NULL`);
reseller-owned packages are intentionally excluded. Plan object keys: `id`,
`name`, `slug`, `website_limit`, `storage_limit_mb`, `database_limit`,
`alias_limit`, `backup_retention_days`, `terminal_enabled`, `waf_enabled`,
`wordpress_enabled`. The WHMCS Package option is a free-text box; typing the id
of a reseller-owned package yields `404 Package not found`.

### `POST /accounts`

Create a hosting account. **Idempotent** by `external_id` (an existing,
non-terminated account is returned as-is). Returns **HTTP 200**.

```json
{
  "external_id": "whmcs:123",
  "username": "bp123_ab12cd34",
  "password": "secure-password-here",
  "package_id": 1,
  "php_version": "8.4",
  "app_type": "php",
  "domain": "example.com"
}
```

| Field | Required | Default | Notes |
|-------|----------|---------|-------|
| `external_id` | yes | — | Idempotency key |
| `username` | yes | — | `^[a-z_][a-z0-9_-]{2,31}$`, 3–32, not reserved |
| `password` | yes | — | 12–72 chars |
| `package_id` | yes | — | global package id, ≥ 1 |
| `php_version` | no | `"8.4"` | one of 5.6, 7.4, 8.0–8.5 |
| `app_type` | no | `"php"` | `php`, `wordpress`, `static` |
| `domain` | no | — | primary domain, validated/lowercased |
| `email` | no | — | **ignored** — set server-side (see below) |
| `install_wordpress` | no | `false` | API accepts it; the WHMCS module never sends it |
| `enable_ssl` | no | `false` | API accepts it; the WHMCS module never sends it |

> **A WHMCS order only creates the account and attaches its domain.** The module
> never sends `install_wordpress` or `enable_ssl`, and there is no product option
> for them — WordPress and SSL are left for the customer to set up in the panel.
> The API still accepts both fields for other clients.
>
> `email` is **always derived server-side** as an internal alias per account;
> the client-sent `email` is ignored. Customers log in with the username.
>
> With **no domain**, only the panel user is created and `app_type` is forced to
> `php` until a website is added later.

Response = account object (see GET). The module reads `username` and stores the
generated username/password back on the WHMCS service for the welcome email.

### `GET /accounts/{external_id}`

Account object keys: `external_id`, `username`, `email`, `domain`, `package_id`,
`package_name`, `service_label`, `status`, `panel_url`, `created_at`
(`created_at` is a naive UTC `isoformat()` — no `Z`). **Disk/usage is not here**
— use `/usage`.

### `GET /accounts/{external_id}/usage`

Keys: `external_id`, `storage_used_bytes`, `storage_limit_bytes`,
`storage_percent`, `website_count`, `database_count`. The client area calls this
to show disk usage and website/database counts.

### `POST /accounts/{external_id}/login`

One-time SSO link, **expires in 300 seconds** (single-use). Response includes
`login_url` (read this), a legacy `url` alias, `path`, and `expires_in: 300`.
If `login_url` is absent/empty the module falls back to the plain panel URL.

### suspend / unsuspend

`suspend` takes optional `{"reason": "..."}`; returns `{"ok": true, "status":
"suspended"}`. `unsuspend` takes no body; returns `{"ok": true, "status":
"active"}`.

### `DELETE /accounts/{external_id}`

Full teardown: every website's database and files are removed, then the
Linux/SFTP user and home directory. Accepts an optional `?backup=true` query to
archive first (default **off**); the WHMCS module never sends it, so WHMCS
termination always deletes without an archive. Returns
`{"ok": true, "status": "terminated", "deleted_websites": [...]}`.

### `PATCH …/password`

Request `{"password": "..."}` (12–72). Returns `{"ok": true}`, and when the
account's SFTP password is rotated as part of the change, a **one-time**
`sftp_password` (plus `sftp_password_rotated: true`). That value is readable only
in this response — the module records it on the WHMCS service so it is not lost.

### `PATCH …/package`

Request `{"package_id": N}` (global package). Returns `{"ok": true,
"package_id": N}`. Quota change only — no recreate/restart.

## Account statuses

`pending` (create in progress), `active`, `suspended`, `failed` (a provisioning
step errored), `terminated`. The WHMCS module passes `status` straight through to
the client-area template and does not map it to a WHMCS service status.

## TLS

The module hard-pins `CURLOPT_SSL_VERIFYPEER` / `VERIFYHOST`. A BPanel reachable
only over a self-signed certificate cannot be used as-is — put a valid
certificate on the panel host (the `serversecure` checkbox only switches the
scheme, it does not relax verification).

## WHMCS module

Located at `modules/servers/bpanel/`:

```
bpanel.php        — module functions
hooks.php         — service-label hooks
templates/
  clientarea.tpl  — client area (shows status, package, username, domain,
                    disk usage, website/database counts, created date, SSO button)
README.md
```

Module name / server type: `bpanel`. Display name: `BPanel Hosting`.
Token source: `serveraccesshash` (primary) or `serverpassword` (fallback).

## Security

- Tokens hashed (SHA-256), raw value shown once, revocable; optional per-token IP
  allowlist. Provisioning tokens do not expire.
- Passwords and SSO tokens are redacted from module logs.
- All passwords validated (12–72) before reaching the Linux account.
