"""Terminal service - executes commands as website user.

Commands are executed via bpanel-helper runuser trampoline for per-user
isolation. Only whitelisted commands are allowed for security.
"""

import shlex
from dataclasses import dataclass
from typing import Optional, Set

from app.services import shell

# Whitelist of allowed commands for terminal access
ALLOWED_COMMANDS: Set[str] = {
    "php",
    "composer",
    "artisan",
    "node",
    "npm",
    "npx",
    "yarn",
    "git",
    "phpunit",
    "ls",
    "cat",
    "mkdir",
    "rm",
    "cp",
    "mv",
    "chmod",
    "chown",
    "pwd",
    "echo",
    "cd",
    "touch",
    "grep",
    "find",
    "tar",
    "zip",
    "unzip",
    "curl",
    "wget",
    "diff",
    "head",
    "tail",
    "less",
}

# Maximum output size in bytes (1MB)
MAX_OUTPUT_BYTES = 1024 * 1024

# Default command timeout in seconds
DEFAULT_TIMEOUT = 30

# Maximum timeout for long-running commands
MAX_TIMEOUT = 120


@dataclass
class CommandResult:
    """Result of a terminal command execution."""

    exit_code: int
    stdout: str
    stderr: str


def is_command_allowed(command: str) -> bool:
    """Check if the command's main executable is in the whitelist.

    Args:
        command: Full command string (e.g., "php artisan migrate")

    Returns:
        True if the command is allowed, False otherwise.
    """
    parts = shlex.split(command)
    if not parts:
        return False
    return parts[0] in ALLOWED_COMMANDS


def _truncate_output(output: str, max_bytes: int = MAX_OUTPUT_BYTES) -> str:
    """Truncate output if it exceeds max_bytes."""
    if len(output.encode("utf-8")) <= max_bytes:
        return output
    # Truncate and add notice
    truncated = output.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")
    return truncated + "\n... (output truncated)"


def exec_command(
    linux_user: str,
    command: str,
    cwd: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> CommandResult:
    """Execute a command as the website user.

    Args:
        linux_user: The Linux username for the website.
        command: The command to execute (e.g., "php artisan migrate").
        cwd: Working directory (defaults to user's home).
        timeout: Maximum execution time in seconds.

    Returns:
        CommandResult with exit_code, stdout, and stderr.

    Raises:
        RuntimeError: If the command is not allowed or execution fails.
    """
    # Validate command
    if not is_command_allowed(command):
        return CommandResult(
            exit_code=126,
            stdout="",
            stderr=f"Command not allowed. Allowed commands: {', '.join(sorted(ALLOWED_COMMANDS))}",
        )

    # Build the command
    # We pass the command as a single string to the helper
    # The helper will execute it via: runuser -u {user} -- env HOME=$HOME {command}
    result = shell.privileged(
        "terminal-exec",
        helper_args=[linux_user, command],
        check=False,
    )

    stdout = _truncate_output(result.stdout)
    stderr = _truncate_output(result.stderr)

    return CommandResult(
        exit_code=result.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def exec_batch(
    linux_user: str,
    commands: list[str],
    cwd: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> list[CommandResult]:
    """Execute multiple commands sequentially.

    Args:
        linux_user: The Linux username for the website.
        commands: List of commands to execute.
        cwd: Working directory (defaults to user's home).
        timeout: Maximum execution time per command.

    Returns:
        List of CommandResult for each command.
    """
    results = []
    for cmd in commands:
        result = exec_command(linux_user, cmd, cwd=cwd, timeout=timeout)
        results.append(result)
        # Stop on first failure if non-interactive
        if result.exit_code != 0:
            break
    return results
