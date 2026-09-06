"""Git write tools for the git-sidecar MCP server."""

import pathlib
import shutil

from git_sidecar import auth, executor
from git_sidecar.config import SidecarConfig
from git_sidecar.tools.git_lfs import LFS_TIMEOUT
from git_sidecar.validation import (
    ValidationError,
    validate_checkout_target,
    validate_file_args,
    validate_push_branch,
    validate_remote_name,
)

_config: SidecarConfig | None = None

ALLOWED_STASH_ACTIONS = frozenset({"push", "pop", "apply", "drop", "show"})
ALLOWED_WORKTREE_ACTIONS = frozenset({"add", "list", "remove"})

DEFAULT_FETCH_REMOTE = "origin"

WORKTREE_TOKEN_MODE = 0o660


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


def _configured_remotes(cwd: str) -> frozenset[str]:
    """Return the names of the remotes configured in a repository.

    `git remote` prints one name per line, and git rejects a remote name
    containing whitespace, so the lines are the names — no parsing, and no
    dependence on the URL column that `git remote -v` would add. A failed
    command yields no names, so an unreadable repository refuses every remote
    rather than admitting one.

    Args:
        cwd: Path to the repository.

    Returns:
        The configured remote names.
    """
    result = executor.run(["git", "remote"], cwd=cwd)
    return frozenset(result.stdout.splitlines())


def git_fetch(repo: str, token: str, remote: str | None = None) -> dict:
    """Fetch from a remote the repository already has configured.

    Defaults to origin. Any other remote must be one configured in that
    repository: git takes a URL wherever it takes a remote name, so an
    unchecked value would fetch from any host the sidecar can reach.
    """
    config = _get_config()
    repo_path = auth.verify_token(config, repo, token)
    cwd = str(repo_path)

    if remote is None:
        target = DEFAULT_FETCH_REMOTE
    else:
        validate_remote_name(remote, _configured_remotes(cwd))
        target = remote

    # `--` so a remote named like an option — which git permits, and which the
    # configured-set rule therefore admits — is resolved as a name instead of
    # parsed as the flag it resembles. Without it, a remote called
    # `--upload-pack=…` makes a fetch run that command.
    result = executor.run(["git", "fetch", "--", target], cwd=cwd)
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


def _copy_token_file(
    config: SidecarConfig, repo_path: pathlib.Path, worktree_path: pathlib.Path
) -> None:
    """Copy the repository's token file into a new worktree.

    The token file is gitignored, so a fresh worktree has none and the first
    sidecar call against it fails authorization. Mode 0o660 keeps it readable
    by the sidecar and the agent, who are different users sharing a group.

    Args:
        config: Server configuration, which names the token file.
        repo_path: Path to the main repository.
        worktree_path: Directory of the newly created worktree.

    Raises:
        OSError: If the token file cannot be copied.
    """
    destination = worktree_path / config.token_filename
    shutil.copyfile(repo_path / config.token_filename, destination)
    destination.chmod(WORKTREE_TOKEN_MODE)


def _worktree_add_args(
    worktree_path: pathlib.Path, branch: str | None, create_branch: bool
) -> list[str]:
    """Build the arguments that follow `git worktree add`.

    Args:
        worktree_path: Resolved absolute location of the new worktree.
        branch: Branch for the new worktree, or None to let git name one.
        create_branch: If True, create branch; if False, attach the existing
            branch of that name.

    Returns:
        Arguments to append after `git worktree add`.
    """
    if branch is None:
        return [str(worktree_path)]

    if create_branch:
        return ["-b", branch, str(worktree_path)]

    # `--` so a branch named like an option is looked up as a name instead of
    # parsed as the flag it resembles. Without it, `--detach` in this slot
    # silently produces a detached worktree instead of failing. The two
    # branches above need no separator: `-b` consumes its own value, and a
    # resolved path is absolute, so neither can lead with a dash.
    return ["--", str(worktree_path), branch]


def git_worktree(
    repo: str,
    token: str,
    action: str = "list",
    path: str | None = None,
    branch: str | None = None,
    create_branch: bool = True,
) -> dict:
    """Manage worktrees. action: add, list, remove.

    A new worktree gets a copy of the repository's token file, which is
    gitignored and so never travels with `git worktree add`.

    An added worktree is usable only where the tree is mounted at the same
    absolute path for every user of the repository: git records absolute paths
    in both of a worktree's pointer files, so a user who sees the tree under a
    different prefix gets "not a git repository", and the main clone reports
    the worktree as prunable.

    Args:
        repo: Path to the repository from the projects directory down
            (e.g. "my-org/my-repo").
        token: Agent authentication token.
        action: One of add, list, remove.
        path: Location of the worktree, given the same way as repo — the path
            from the projects directory down — or an absolute path inside that
            directory. Used by add and remove.
        branch: Branch for the new worktree. Used by add.
        create_branch: If True, add creates branch; if False, it attaches an
            existing branch of that name. Ignored when branch is None.

    Returns:
        ExecResult dict with the output of git worktree. When add succeeds and
        the token copy then fails, a dict this function wrote instead: "ok"
        false and a stderr git never produced, for a worktree that exists on
        disk all the same.

    Raises:
        ValidationError: If action is not one of add, list, remove, or an
            added worktree would sit inside the repository it comes from.
        AuthError: If path falls outside the projects directory.
    """
    if action not in ALLOWED_WORKTREE_ACTIONS:
        allowed = ", ".join(sorted(ALLOWED_WORKTREE_ACTIONS))
        raise ValidationError(f"Invalid worktree action '{action}'. Allowed: {allowed}")

    config = _get_config()
    repo_path = auth.verify_token(config, repo, token)
    worktree_path = (
        auth.resolve_under_projects(config, path) if path is not None else None
    )
    args = ["git", "worktree", action]

    if action == "add" and worktree_path is not None:
        if worktree_path.is_relative_to(repo_path):
            raise ValidationError(
                f"Worktree path is inside the repository it belongs to: {path!r}"
            )
        args.extend(_worktree_add_args(worktree_path, branch, create_branch))

    if action == "remove" and worktree_path is not None:
        args.append(str(worktree_path))

    result = executor.run(args, cwd=str(repo_path))

    if action == "add" and worktree_path is not None and result.ok:
        try:
            _copy_token_file(config, repo_path, worktree_path)
        except OSError as exc:
            return {
                "ok": False,
                "returncode": 1,
                "stdout": result.stdout,
                "stderr": (
                    f"worktree added at {worktree_path} but its token file "
                    f"could not be provisioned: {exc}"
                ),
            }

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

    # git push uploads LFS objects only via repo-local hooks, which may be
    # absent — push them explicitly first when the checkout tracks any.
    lfs_files = executor.run(["git", "lfs", "ls-files", "--name-only"], cwd=cwd)
    if lfs_files.ok and lfs_files.stdout.strip():
        lfs_result = executor.run(
            ["git", "lfs", "push", "origin", branch], cwd=cwd, timeout=LFS_TIMEOUT
        )
        if not lfs_result.ok:
            return lfs_result.to_dict()

    result = executor.run(["git", "push", "-u", "origin", branch], cwd=cwd)
    return result.to_dict()
