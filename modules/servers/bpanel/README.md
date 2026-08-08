# BPanel WHMCS server module

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
| Package ID | `1` |
| App Type | `php` |
| PHP Version | `8.4` |
| Install WordPress | unchecked by default |
| Auto SSL | unchecked by default |

## Mapping

| WHMCS | BPanel |
|---|---|
| Service ID | `external_id = whmcs:{serviceid}` |
| Username | `bp_{serviceid}` |
| Client email | BPanel user email |
| Domain | Primary website domain |
| Product Package ID | BPanel `UserPackage.id` |

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
