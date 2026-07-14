"""Git LFS tools for the git-sidecar MCP server."""

from git_sidecar import auth, executor
from git_sidecar.config import SidecarConfig
from git_sidecar.validation import validate_file_args

_config: SidecarConfig | None = None

# LFS object transfers can move large files; give them more headroom
# than the executor's 60s default.
LFS_TIMEOUT = 600


def init(config: SidecarConfig) -> None:
    """Initialize module-level config."""
    global _config  # noqa: PLW0603
    _config = config


def _get_config() -> SidecarConfig:
    """Return the current config or raise if not initialized."""
    if _config is None:
        raise RuntimeError("git_lfs module not initialized — call init(config) first")
    return _config


def git_lfs_track(repo: str, token: str, patterns: list[str]) -> dict:
    """Track file patterns with Git LFS (updates .gitattributes)."""
    validate_file_args(patterns)
    config = _get_config()
    repo_path = auth.verify_token(config, repo, token)
    result = executor.run(["git", "lfs", "track", "--"] + patterns, cwd=str(repo_path))
    return result.to_dict()


def git_lfs_untrack(repo: str, token: str, patterns: list[str]) -> dict:
    """Stop tracking file patterns with Git LFS."""
    validate_file_args(patterns)
    config = _get_config()
    repo_path = auth.verify_token(config, repo, token)
    result = executor.run(
        ["git", "lfs", "untrack", "--"] + patterns, cwd=str(repo_path)
    )
    return result.to_dict()


def git_lfs_ls_files(repo: str, token: str) -> dict:
    """List files tracked by Git LFS at the current checkout."""
    config = _get_config()
    repo_path = auth.verify_token(config, repo, token)
    result = executor.run(["git", "lfs", "ls-files"], cwd=str(repo_path))
    return result.to_dict()


def git_lfs_status(repo: str, token: str) -> dict:
    """Show status of Git LFS files in the working tree."""
    config = _get_config()
    repo_path = auth.verify_token(config, repo, token)
    result = executor.run(["git", "lfs", "status"], cwd=str(repo_path))
    return result.to_dict()


def git_lfs_fetch(repo: str, token: str) -> dict:
    """Download LFS objects from origin without updating the working tree."""
    config = _get_config()
    repo_path = auth.verify_token(config, repo, token)
    result = executor.run(
        ["git", "lfs", "fetch", "origin"], cwd=str(repo_path), timeout=LFS_TIMEOUT
    )
    return result.to_dict()


def git_lfs_pull(repo: str, token: str) -> dict:
    """Download LFS objects from origin and update the working tree."""
    config = _get_config()
    repo_path = auth.verify_token(config, repo, token)
    result = executor.run(
        ["git", "lfs", "pull", "origin"], cwd=str(repo_path), timeout=LFS_TIMEOUT
    )
    return result.to_dict()
