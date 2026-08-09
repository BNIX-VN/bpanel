# BPanel WHMCS server module

Compatible with WHMCS on PHP 8.1+.

## Install

Copy this directory to WHMCS:

```text
modules/servers/bpanel/
```

## BPanel token

In BPanel admin API, create provisioning token with scopes:

```text
provisioning:read,provisioning:write
```

## WHMCS server config

Go to **System Settings → Servers → Add New Server**.

| Field | Value |
|---|---|
| Module | BPanel Hosting |
| Hostname | panel domain or IP |
| IP Address | optional |
| Assigned IP Addresses | empty |
| NS fields | empty |
| Type | BPanel Hosting |
| Username | empty |
| Password | BPanel API token, if not using Access Hash |
| Access Hash | BPanel API token |
| Secure | checked if HTTPS |
| Port | BPanel port, usually `2222` |

## Product config

Go to **System Settings → Products/Services → Module Settings**.

| Option | Example |
|---|---|
| Package | select a BPanel package |
| App Type | `php` |
| PHP Version | `8.4` |
| Install WordPress | unchecked by default |
| Auto SSL | unchecked by default |

Disable **Require Domain** on the WHMCS product if customers should be able to order without entering a domain.
If **Install WordPress** or **Auto SSL** is enabled, a domain is still required.
Provisioning generates a unique internal BPanel email alias per service. Customers log in with the BPanel username.

## Mapping

| WHMCS | BPanel |
|---|---|
| Service ID | `external_id = whmcs:{serviceid}` |
| Username | `bp_{serviceid}` |
| Email | generated internal alias per service |
| Domain | Primary website domain, optional |
| Product Package | BPanel `UserPackage.id` |

## Supported actions

- CreateAccount
- SuspendAccount
- UnsuspendAccount
- TerminateAccount
- ChangePassword
- ChangePackage
- UsageUpdate
- LoginLink
- ClientArea
- TestConnection
