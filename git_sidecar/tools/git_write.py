"""Git write tools for the git-sidecar MCP server."""

from git_sidecar import auth, executor
from git_sidecar.config import SidecarConfig
from git_sidecar.validation import (
    ValidationError,
    validate_checkout_target,
    validate_file_args,
    validate_push_branch,
)

_config: SidecarConfig | None = None

ALLOWED_STASH_ACTIONS = frozenset({"push", "pop", "apply", "drop", "show"})
ALLOWED_WORKTREE_ACTIONS = frozenset({"add", "list", "remove"})


def init(config: SidecarConfig) -> None:
    """Initialize module-level config."""
    global _config  # noqa: PLW0603
    _config = config


def _get_config() -> SidecarConfig:
    """Return the current config or raise if not initialized."""
    if _config is None:
        raise RuntimeError("git_write module not initialized — call init(config) first")
    return _config


def git_add(repo: str, token: str, files: list[str]) -> dict:
    """Stage files for commit."""
    validate_file_args(files)
    config = _get_config()
    repo_path = auth.verify_token(config, repo, token)
    result = executor.run(["git", "add", "--"] + files, cwd=str(repo_path))
    return result.to_dict()


def git_rm(repo: str, token: str, files: list[str]) -> dict:
    """Remove files from tracking."""
    validate_file_args(files)
    config = _get_config()
    repo_path = auth.verify_token(config, repo, token)
    result = executor.run(["git", "rm", "--"] + files, cwd=str(repo_path))
    return result.to_dict()


def git_commit(repo: str, token: str, message: str) -> dict:
    """Create a commit. Author/committer from git config."""
    config = _get_config()
    repo_path = auth.verify_token(config, repo, token)
    cwd = str(repo_path)

    # Read user.name from git config
    name_result = executor.run(["git", "config", "--get", "user.name"], cwd=cwd)
    user_name = name_result.stdout.strip() if name_result.ok else None
    if not user_name:
        return {
            "ok": False,
            "returncode": 1,
            "stdout": "",
            "stderr": "git config user.name is not set",
        }

    # Read user.email from git config
    email_result = executor.run(["git", "config", "--get", "user.email"], cwd=cwd)
    user_email = email_result.stdout.strip() if email_result.ok else None
    if not user_email:
        return {
            "ok": False,
            "returncode": 1,
            "stdout": "",
            "stderr": "git config user.email is not set",
        }

    # Check there are staged changes (returncode 1 means there ARE changes)
    staged_result = executor.run(["git", "diff", "--cached", "--quiet"], cwd=cwd)
    if staged_result.returncode == 0:
        return {
            "ok": False,
            "returncode": 1,
            "stdout": "",
            "stderr": "nothing staged; stage changes with git add",
        }

    env = {
        "GIT_AUTHOR_NAME": user_name,
        "GIT_AUTHOR_EMAIL": user_email,
        "GIT_COMMITTER_NAME": user_name,
        "GIT_COMMITTER_EMAIL": user_email,
    }

    result = executor.run(["git", "commit", "-m", message], cwd=cwd, env=env)
    return result.to_dict()


def git_restore(repo: str, token: str, files: list[str], staged: bool = False) -> dict:
    """Restore files. staged=True to unstage."""
    validate_file_args(files)
    config = _get_config()
    repo_path = auth.verify_token(config, repo, token)
    args = ["git", "restore"]
    if staged:
        args.append("--staged")
    args += ["--"] + files
    result = executor.run(args, cwd=str(repo_path))
    return result.to_dict()


def git_stash(
    repo: str,
    token: str,
    action: str = "push",
    message: str | None = None,
    index: int | None = None,
) -> dict:
    """Manage stashes. action: push, pop, apply, drop, show."""
    if action not in ALLOWED_STASH_ACTIONS:
        allowed = ", ".join(sorted(ALLOWED_STASH_ACTIONS))
        raise ValidationError(f"Invalid stash action '{action}'. Allowed: {allowed}")

    config = _get_config()
    repo_path = auth.verify_token(config, repo, token)
    args = ["git", "stash", action]

    if action == "push" and message is not None:
        args += ["-m", message]

    if action in {"pop", "apply", "drop", "show"} and index is not None:
        args.append(f"stash@{{{index}}}")

    result = executor.run(args, cwd=str(repo_path))
    return result.to_dict()


def git_fetch(repo: str, token: str) -> dict:
    """Fetch from origin."""
    config = _get_config()
    repo_path = auth.verify_token(config, repo, token)
    result = executor.run(["git", "fetch", "origin"], cwd=str(repo_path))
    return result.to_dict()


def git_pull(repo: str, token: str) -> dict:
    """Pull from origin."""
    config = _get_config()
    repo_path = auth.verify_token(config, repo, token)
    result = executor.run(["git", "pull"], cwd=str(repo_path))
    return result.to_dict()


def git_merge(repo: str, token: str, branch: str) -> dict:
    """Merge a branch into current."""
    config = _get_config()
    repo_path = auth.verify_token(config, repo, token)
    result = executor.run(["git", "merge", branch], cwd=str(repo_path))
    return result.to_dict()


def git_worktree(
    repo: str,
    token: str,
    action: str = "list",
    path: str | None = None,
    branch: str | None = None,
) -> dict:
    """Manage worktrees. action: add, list, remove."""
    if action not in ALLOWED_WORKTREE_ACTIONS:
        allowed = ", ".join(sorted(ALLOWED_WORKTREE_ACTIONS))
        raise ValidationError(
            f"Invalid worktree action '{action}'. Allowed: {allowed}"
        )

    config = _get_config()
    repo_path = auth.verify_token(config, repo, token)
    args = ["git", "worktree", action]

    if action == "add" and path is not None:
        args.append(path)
        if branch is not None:
            args.extend(["-b", branch])

    if action == "remove" and path is not None:
        args.append(path)

    result = executor.run(args, cwd=str(repo_path))
    return result.to_dict()


def git_checkout(repo: str, token: str, target: str, create: bool = False) -> dict:
    """Check out a branch. create=True for -b flag."""
    config = _get_config()
    validate_checkout_target(target, config.allowed_branch_prefixes, create=create)
    repo_path = auth.verify_token(config, repo, token)
    args = ["git", "checkout"]
    if create:
        args.append("-b")
    args.append(target)
    result = executor.run(args, cwd=str(repo_path))
    return result.to_dict()


def git_push(repo: str, token: str) -> dict:
    """Push current branch to origin."""
    config = _get_config()
    repo_path = auth.verify_token(config, repo, token)
    cwd = str(repo_path)

    # Get current branch
    branch_result = executor.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
    if not branch_result.ok:
        return branch_result.to_dict()

    branch = branch_result.stdout.strip()

    # Validate branch is safe to push
    validate_push_branch(branch, config.allowed_branch_prefixes)

    result = executor.run(["git", "push", "-u", "origin", branch], cwd=cwd)
    return result.to_dict()
