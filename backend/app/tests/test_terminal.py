"""Tests for terminal service."""

import pytest

from app.services.terminal import (
    ALLOWED_COMMANDS,
    MAX_OUTPUT_BYTES,
    CommandResult,
    _truncate_output,
    exec_batch,
    exec_command,
    is_command_allowed,
)


class TestIsCommandAllowed:
    """Tests for command whitelist validation."""

    def test_allowed_commands(self):
        """All whitelisted commands should be allowed."""
        allowed = [
            "php",
            "composer",
            "node",
            "npm",
            "yarn",
            "git",
            "ls",
            "cat",
            "mkdir",
            "rm",
            "cp",
            "mv",
            "chmod",
            "chown",
            "pwd",
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
        ]
        for cmd in allowed:
            assert is_command_allowed(cmd), f"Command {cmd} should be allowed"

    def test_disallowed_commands(self):
        """Commands not in whitelist should not be allowed.

        Note: is_command_allowed only checks the first word (the executable).
        Full command safety is enforced in bpanel-helper.sh.
        """
        dangerous = [
            "dd if=/dev/zero of=/dev/sda",
            "nc -e /bin/bash",
            "python -c 'import os'",
            "bash -c 'rm -rf /'",
            "sh -c 'cat /etc/passwd'",
            "sudo su",
            "vim",
            "nano",
            "emacs",
            "chroot",
        ]
        for cmd in dangerous:
            assert not is_command_allowed(cmd), f"Command {cmd} should NOT be allowed"

    def test_empty_command(self):
        """Empty command should not be allowed."""
        assert not is_command_allowed("")
        assert not is_command_allowed("   ")

    def test_artisan_command(self):
        """Artisan should be allowed (it's a PHP script executed via php)."""
        assert is_command_allowed("artisan")

    def test_phpunit_command(self):
        """PHPUnit should be allowed."""
        assert is_command_allowed("phpunit")

    def test_whitelist_size(self):
        """Whitelist should contain a reasonable number of commands."""
        assert len(ALLOWED_COMMANDS) >= 20
        assert len(ALLOWED_COMMANDS) <= 50


class TestTruncateOutput:
    """Tests for output truncation."""

    def test_small_output_not_truncated(self):
        """Small output should not be truncated."""
        small = "Hello, World!"
        assert _truncate_output(small) == small

    def test_exact_limit_not_truncated(self):
        """Output at exact limit should not be truncated."""
        exact = "x" * MAX_OUTPUT_BYTES
        assert _truncate_output(exact) == exact

    def test_large_output_truncated(self):
        """Large output should be truncated with notice."""
        large = "x" * (MAX_OUTPUT_BYTES + 1000)
        result = _truncate_output(large)
        assert "..." in result
        assert len(result.encode("utf-8")) <= MAX_OUTPUT_BYTES + 50  # Small buffer for notice


class TestCommandResult:
    """Tests for CommandResult dataclass."""

    def test_command_result_fields(self):
        """CommandResult should have correct fields."""
        result = CommandResult(exit_code=0, stdout="hello", stderr="")
        assert result.exit_code == 0
        assert result.stdout == "hello"
        assert result.stderr == ""

    def test_command_result_with_stderr(self):
        """CommandResult should capture stderr."""
        result = CommandResult(exit_code=1, stdout="", stderr="error message")
        assert result.exit_code == 1
        assert result.stderr == "error message"
