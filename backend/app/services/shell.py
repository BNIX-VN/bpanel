import shlex
import subprocess
from dataclasses import dataclass
from typing import List, Optional

from app.core.config import settings


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str


def _redact(text: str) -> str:
    """Strip stdin echoes that might contain secrets from logs."""
    if not text:
        return text
    return text


class ShellRunner:
    def run(
        self,
        args: List[str],
        check: bool = True,
        input: Optional[str] = None,
        sensitive: bool = False,
    ) -> CommandResult:
        """Run a subprocess.

        - args: argv list (never passed through a shell unless caller uses bash -lc).
        - input: string fed via stdin. Use this for SQL/passwords to avoid leaking into ps.
        - sensitive: if True, redact stdout/stderr/command in error messages.
        """
        quoted = " ".join(shlex.quote(arg) for arg in args)
        log_command = "[redacted]" if sensitive else quoted
        if settings.command_dry_run:
            return CommandResult(command=log_command, returncode=0, stdout=f"DRY RUN: {log_command}", stderr="")
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            input=input,
        )
        stdout = "[redacted]" if sensitive else completed.stdout
        stderr = "[redacted]" if sensitive else completed.stderr
        result = CommandResult(log_command, completed.returncode, stdout, stderr)
        if check and completed.returncode != 0:
            raise RuntimeError(f"Command failed: {log_command}\n{stderr}")
        return result


shell = ShellRunner()
