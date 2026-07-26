"""Git write tools for the git-sidecar MCP server."""

import os
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
)

_config: SidecarConfig | None = None

ALLOWED_STASH_ACTIONS = frozenset({"push", "pop", "apply", "drop", "show"})
ALLOWED_WORKTREE_ACTIONS = frozenset({"add", "list", "remove"})

GITDIR_PREFIX = "gitdir: "
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


def _rewrite_gitdir_pointer(worktree_path: pathlib.Path) -> None:
    """Rewrite a new worktree's .git pointer as a path relative to the worktree.

    `git worktree add` records an absolute gitdir, which only resolves in the
    namespace that created it — the sidecar sees the tree under its projects
    mount and the agent sees the same tree under its own home. A relative
    pointer resolves for both, since both see the same directory structure.

    Only this forward pointer is rewritten. The reverse pointer
    (`<main>/.git/worktrees/<name>/gitdir`) is left absolute because git 2.34.1
    cannot read a relative one: it resolves the recorded path against the
    current working directory rather than against the admin directory, so the
    worktree reads as prunable from some directories and not others. Git 2.48
    writes both pointers relative under `worktree.useRelativePaths`; below that
    floor there is no relative form that works.

    That leaves a residual hazard this function cannot fix: the reverse pointer
    is only valid in the namespace that created the worktree, so `git worktree
    list` in the *other* namespace reports the worktree as prunable and `git
    worktree prune` there would delete its admin metadata. In-worktree commands
    (status, ls-files, commit) are unaffected — git does not read the reverse
    pointer from inside a worktree. Closing it needs the two users to see the
    tree at the same absolute path, or git >= 2.48.

    Args:
        worktree_path: Directory of the newly created worktree.

    Raises:
        OSError: If the pointer file cannot be read or written.
        ValueError: If the pointer file is not a gitdir pointer.
    """
    pointer_file = worktree_path / ".git"
    pointer = pointer_file.read_text().strip()

    if not pointer.startswith(GITDIR_PREFIX):
        raise ValueError(f"{pointer_file} is not a gitdir pointer")

    gitdir = pointer.removeprefix(GITDIR_PREFIX).strip()
    relative_gitdir = os.path.relpath(gitdir, worktree_path)
    pointer_file.write_text(f"{GITDIR_PREFIX}{relative_gitdir}\n")


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


def git_worktree(
    repo: str,
    token: str,
    action: str = "list",
    path: str | None = None,
    branch: str | None = None,
) -> dict:
    """Manage worktrees. action: add, list, remove.

    A new worktree is provisioned for shared use: its gitdir pointer is made
    relative so it resolves for the sidecar and the agent alike, and the
    repository's token file is copied in.
    """
    if action not in ALLOWED_WORKTREE_ACTIONS:
        allowed = ", ".join(sorted(ALLOWED_WORKTREE_ACTIONS))
        raise ValidationError(f"Invalid worktree action '{action}'. Allowed: {allowed}")

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

    if action == "add" and path is not None and result.ok:
        worktree_path = repo_path / path
        try:
            _rewrite_gitdir_pointer(worktree_path)
            _copy_token_file(config, repo_path, worktree_path)
        except (OSError, ValueError) as exc:
            return {
                "ok": False,
                "returncode": 1,
                "stdout": result.stdout,
                "stderr": (
                    f"worktree added at {worktree_path} but could not be "
                    f"provisioned for shared use: {exc}"
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
