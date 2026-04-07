"""Safe subprocess executor — no shell=True, ever."""

import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class ExecResult:
    """Result of a subprocess execution."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        """Whether the command succeeded."""
        return self.returncode == 0

    def to_dict(self) -> dict:
        """Serialize for MCP response."""
        return {
            "ok": self.ok,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def run(
    args: list[str],
    *,
    cwd: str | None = None,
    timeout: int = 60,
    env: dict[str, str] | None = None,
) -> ExecResult:
    """Run a command safely with an argument list.

    Args:
        args: Command and arguments as a list (never a string).
        cwd: Working directory for the command.
        timeout: Maximum seconds before the process is killed.
        env: Optional environment variable overrides (merged with current env).

    Returns:
        ExecResult with returncode, stdout, and stderr.
    """
    import os

    run_env = None
    if env:
        run_env = {**os.environ, **env}

    try:
        proc = subprocess.run(  # noqa: S603
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=run_env,
        )
    except subprocess.TimeoutExpired:
        return ExecResult(
            returncode=-1,
            stdout="",
            stderr=f"Command timed out after {timeout}s",
        )
    except FileNotFoundError:
        return ExecResult(
            returncode=-1,
            stdout="",
            stderr=f"Command not found: {args[0]}",
        )

    return ExecResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )
