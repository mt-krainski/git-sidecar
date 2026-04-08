"""Read-only git MCP tools."""

from git_sidecar import executor
from git_sidecar.auth import verify_token
from git_sidecar.config import SidecarConfig
from git_sidecar.validation import validate_file_args

_config: SidecarConfig | None = None


def init(config: SidecarConfig) -> None:
    """Initialize the module with server configuration.

    Args:
        config: Server configuration instance.
    """
    global _config  # noqa: PLW0603
    _config = config


def _get_config() -> SidecarConfig:
    """Return the current config or raise if not initialized.

    Returns:
        Current SidecarConfig instance.

    Raises:
        RuntimeError: If init() has not been called.
    """
    if _config is None:
        raise RuntimeError("git_read module not initialized — call init(config) first")
    return _config


def git_status(repo: str, token: str) -> dict:
    """Show working tree status.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.

    Returns:
        ExecResult dict with stdout of git status.
    """
    config = _get_config()
    repo_path = verify_token(config, repo, token)
    result = executor.run(["git", "status"], cwd=str(repo_path))
    return result.to_dict()


def git_diff(
    repo: str,
    token: str,
    staged: bool = False,
    files: list[str] | None = None,
    ref: str | None = None,
) -> dict:
    """Show changes between working tree, index, and commits.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.
        staged: If True, show staged changes (--cached).
        files: Optional list of files to limit the diff.
        ref: Optional ref to diff against (e.g. "HEAD~1").

    Returns:
        ExecResult dict with diff output.
    """
    config = _get_config()
    repo_path = verify_token(config, repo, token)

    args = ["git", "diff"]
    if staged:
        args.append("--cached")
    if ref:
        args.append(ref)
    if files:
        validate_file_args(files)
        args.append("--")
        args.extend(files)

    result = executor.run(args, cwd=str(repo_path))
    return result.to_dict()


def git_log(
    repo: str,
    token: str,
    max_count: int = 20,
    oneline: bool = False,
    ref: str | None = None,
) -> dict:
    """Show commit log.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.
        max_count: Maximum number of commits to show.
        oneline: If True, use --oneline format.
        ref: Optional ref to start the log from.

    Returns:
        ExecResult dict with log output.
    """
    config = _get_config()
    repo_path = verify_token(config, repo, token)

    args = ["git", "log", f"--max-count={max_count}"]
    if oneline:
        args.append("--oneline")
    if ref:
        args.append(ref)

    result = executor.run(args, cwd=str(repo_path))
    return result.to_dict()


def git_show(repo: str, token: str, ref: str = "HEAD") -> dict:
    """Show a commit or object.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.
        ref: Commit or object reference (default: HEAD).

    Returns:
        ExecResult dict with the object contents.
    """
    config = _get_config()
    repo_path = verify_token(config, repo, token)
    result = executor.run(["git", "show", ref], cwd=str(repo_path))
    return result.to_dict()


def git_branch(repo: str, token: str, all: bool = False) -> dict:  # noqa: A002
    """List branches.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.
        all: If True, include remote-tracking branches.

    Returns:
        ExecResult dict with branch list output.
    """
    config = _get_config()
    repo_path = verify_token(config, repo, token)

    args = ["git", "branch"]
    if all:
        args.append("--all")

    result = executor.run(args, cwd=str(repo_path))
    return result.to_dict()


def git_rev_parse(repo: str, token: str, ref: str = "HEAD") -> dict:
    """Resolve a ref to a commit hash.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.
        ref: Ref to resolve (default: HEAD).

    Returns:
        ExecResult dict with the resolved commit hash.
    """
    config = _get_config()
    repo_path = verify_token(config, repo, token)
    result = executor.run(["git", "rev-parse", ref], cwd=str(repo_path))
    return result.to_dict()


def git_ls_files(repo: str, token: str) -> dict:
    """List tracked files.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.

    Returns:
        ExecResult dict with tracked file paths.
    """
    config = _get_config()
    repo_path = verify_token(config, repo, token)
    result = executor.run(["git", "ls-files"], cwd=str(repo_path))
    return result.to_dict()


def git_stash_list(repo: str, token: str) -> dict:
    """List stashes.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.

    Returns:
        ExecResult dict with the stash list.
    """
    config = _get_config()
    repo_path = verify_token(config, repo, token)
    result = executor.run(["git", "stash", "list"], cwd=str(repo_path))
    return result.to_dict()


def git_remote(repo: str, token: str) -> dict:
    """Show remotes with URLs.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.

    Returns:
        ExecResult dict with remote names and URLs.
    """
    config = _get_config()
    repo_path = verify_token(config, repo, token)
    result = executor.run(["git", "remote", "-v"], cwd=str(repo_path))
    return result.to_dict()


def git_blame(repo: str, token: str, file: str) -> dict:
    """Show blame for a file.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.
        file: File path relative to repo root.

    Returns:
        ExecResult dict with blame output.
    """
    validate_file_args([file])
    config = _get_config()
    repo_path = verify_token(config, repo, token)
    result = executor.run(["git", "blame", file], cwd=str(repo_path))
    return result.to_dict()


def git_tag(repo: str, token: str) -> dict:
    """List tags.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.

    Returns:
        ExecResult dict with tag list.
    """
    config = _get_config()
    repo_path = verify_token(config, repo, token)
    result = executor.run(["git", "tag"], cwd=str(repo_path))
    return result.to_dict()


def git_config_get(repo: str, token: str, key: str) -> dict:
    """Get a git config value.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.
        key: Config key to retrieve (e.g. "user.email").

    Returns:
        ExecResult dict with the config value.
    """
    config = _get_config()
    repo_path = verify_token(config, repo, token)
    result = executor.run(["git", "config", "--get", key], cwd=str(repo_path))
    return result.to_dict()
