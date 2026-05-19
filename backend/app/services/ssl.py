from app.core.config import settings
from app.services.shell import CommandResult, shell


def issue_ssl(domain: str) -> CommandResult:
    args = ["certbot", "--nginx", "-d", domain, "--non-interactive", "--agree-tos", "--redirect"]
    if settings.ssl_email:
        args.extend(["--email", settings.ssl_email])
    else:
        args.append("--register-unsafely-without-email")
    return shell.run(args, check=False)


def renew_all():
    return shell.run(["certbot", "renew", "--quiet"], check=False)
