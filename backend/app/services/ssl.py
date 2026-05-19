from app.core.config import settings
from app.services.shell import CommandResult, shell


def issue_ssl(domain: str) -> CommandResult:
    helper_args = [domain]
    fallback = ["certbot", "--nginx", "-d", domain, "--non-interactive", "--agree-tos", "--redirect"]
    if settings.ssl_email:
        helper_args.append(settings.ssl_email)
        fallback.extend(["--email", settings.ssl_email])
    else:
        fallback.append("--register-unsafely-without-email")
    return shell.privileged("certbot-issue", helper_args=helper_args, check=False, fallback=fallback)


def renew_all() -> CommandResult:
    return shell.privileged("certbot-renew", check=False, fallback=["certbot", "renew", "--quiet"])
