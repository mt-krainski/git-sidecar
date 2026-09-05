"""Authorization via per-project token files."""

import hmac
import pathlib

from git_sidecar.config import SidecarConfig


class AuthError(Exception):
    """Raised when token verification fails."""


def resolve_under_projects(config: SidecarConfig, path: str) -> pathlib.Path:
    """Resolve a path against projects_dir without requiring it to exist.

    The path need not exist. That absence is the reason this is separate from
    resolve_repo_path: a worktree location is resolved before it is created.

    Args:
        config: Server configuration.
        path: Path relative to the projects directory (e.g. "my-org/my-repo"),
            or an absolute path inside it.

    Returns:
        Resolved absolute path.

    Raises:
        AuthError: If the resolved path escapes the projects directory.
    """
    projects = pathlib.Path(config.projects_dir).resolve()
    resolved = (projects / path).resolve()

    if not resolved.is_relative_to(projects):
        raise AuthError(f"Path escapes projects directory: {path}")

    return resolved


def resolve_repo_path(config: SidecarConfig, repo: str) -> pathlib.Path:
    """Resolve a repo identifier to an absolute path under projects_dir.

    Args:
        config: Server configuration.
        repo: Relative path to the repository (e.g. "my-org/my-repo").

    Returns:
        Resolved absolute path.

    Raises:
        AuthError: If the path escapes the projects directory or doesn't exist.
    """
    repo_path = resolve_under_projects(config, repo)

    if not repo_path.is_dir():
        raise AuthError(f"Repository not found: {repo}")

    return repo_path


def verify_token(config: SidecarConfig, repo: str, token: str) -> pathlib.Path:
    """Verify the agent-provided token against the on-disk token file.

    Args:
        config: Server configuration.
        repo: Relative path to the repository.
        token: Token value provided by the agent.

    Returns:
        Resolved absolute path to the repository.

    Raises:
        AuthError: If verification fails for any reason.
    """
    repo_path = resolve_repo_path(config, repo)
    token_file = repo_path / config.token_filename

    if not token_file.is_file():
        raise AuthError(f"Token file not found in repository: {config.token_filename}")

    try:
        disk_token = token_file.read_text().strip()
    except OSError as exc:
        raise AuthError(f"Cannot read token file: {exc}") from exc

    if not disk_token:
        raise AuthError("Token file is empty")

    if not hmac.compare_digest(disk_token, token.strip()):
        raise AuthError("Token mismatch")

    return repo_path
