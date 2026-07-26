"""Read-only git MCP tools."""

import errno
import os
import pathlib
import stat as statmod

from git_sidecar import executor
from git_sidecar.auth import verify_token
from git_sidecar.config import SidecarConfig
from git_sidecar.validation import resolve_output_path, validate_file_args

_config: SidecarConfig | None = None

# Directory under the repository root that git_diff writes into. The name
# follows the .git-sidecar-token convention already present in a repository.
OUTPUT_DIR = ".git-sidecar"

# Written when that directory is created: '*' matches every file in it, the
# .gitignore included, so git reports nothing there and no repository needs an
# ignore entry of its own for the sidecar's output.
OUTPUT_DIR_IGNORE = "*\n"

# Mode requested for files written here — 0o666 as open() itself requests, so
# the deployment's umask governs the result and nothing changes with the switch
# to os.open().
OUTPUT_FILE_MODE = 0o666

# git elides the middle of a long path in --stat output to fit the 80 columns
# it assumes when not writing to a terminal. These widths hold whole paths up
# to 900 characters; longer ones still elide.
STAT_FORMAT = "--stat=1000,900"


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


def _diff_args(
    staged: bool,
    files: list[str] | None,
    ref: str | None,
    *,
    stat: bool = False,
) -> list[str]:
    """Build the git diff arguments for one selection.

    Args:
        staged: If True, diff the index (--cached).
        files: Optional list of files to limit the diff.
        ref: Optional ref to diff against.
        stat: If True, ask git for the stat summary instead of the body.

    Returns:
        Argument list for executor.run.
    """
    args = ["git", "diff"]
    if stat:
        args.append(STAT_FORMAT)
    if staged:
        args.append("--cached")
    if ref:
        args.append(ref)
    if files:
        args.append("--")
        args.extend(files)
    return args


def _open_child_dir(dir_fd: int, name: str) -> int:
    """Open a subdirectory of an open directory, creating it if it is missing.

    Args:
        dir_fd: File descriptor of the directory to look in.
        name: Single path component below it.

    Returns:
        File descriptor for the subdirectory; the caller closes it.

    Raises:
        OSError: If the component is a symlink, or cannot be opened.
    """
    try:
        os.mkdir(name, dir_fd=dir_fd)
    except FileExistsError:
        pass

    return os.open(
        name,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        dir_fd=dir_fd,
    )


def _write_file(dir_fd: int, name: str, body: str) -> None:
    """Write one file in an open directory, refusing anything but a plain file.

    O_NOFOLLOW makes a symlink at this name fail rather than redirect the
    write, and O_NONBLOCK keeps a planted fifo from parking the server on an
    open() that never returns. Two properties cannot be seen from the name at
    all and are checked on the open descriptor: a hardlink is not a link to
    follow but the inode itself, so a name here can alias a file anywhere on
    the volume and truncating it would corrupt that file; and a device or fifo
    is not a file this tool should be writing through.

    Args:
        dir_fd: File descriptor of the directory to write in.
        name: Single path component to write.
        body: Text to write.

    Raises:
        OSError: If the name is a symlink, is not a regular file, has other
            hard links, or cannot be written.
    """
    fd = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
        OUTPUT_FILE_MODE,
        dir_fd=dir_fd,
    )

    with os.fdopen(fd, "w") as handle:
        info = os.fstat(fd)
        if not statmod.S_ISREG(info.st_mode):
            raise OSError(errno.EINVAL, "Not a regular file", name)
        if info.st_nlink > 1:
            raise OSError(errno.EMLINK, "Target has other hard links", name)

        handle.truncate(0)
        handle.write(body)


def _write_output(path: pathlib.Path, base: pathlib.Path, body: str) -> None:
    """Write a diff body into the sidecar output directory.

    Every step is taken relative to an open directory descriptor, and every
    component is opened with O_NOFOLLOW. Once a component is open the
    descriptor is pinned to that inode, so renaming or replacing the name
    afterwards cannot redirect the write, and a symlink anywhere along the way
    fails outright. This is why the path is not re-checked before writing:
    re-checking answers a question about names and then lets go of the answer,
    which is the window that made the first check exploitable.

    Creates the directory on first use, ignoring itself, so the repository
    stays clean without an entry of its own. A directory that already exists is
    left as found: its .gitignore, or its lack of one, belongs to whoever made
    it.

    Args:
        path: Resolved path to write, inside base.
        base: The sidecar output directory.
        body: Diff text to write.

    Raises:
        OSError: If any component is a symlink, if the target is not a plain
            unaliased file, or if the write fails.
    """
    parts = path.relative_to(base).parts

    try:
        os.mkdir(base)
        created = True
    except FileExistsError:
        created = False

    dir_fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if created:
            _write_file(dir_fd, ".gitignore", OUTPUT_DIR_IGNORE)

        for part in parts[:-1]:
            child_fd = _open_child_dir(dir_fd, part)
            os.close(dir_fd)
            dir_fd = child_fd

        _write_file(dir_fd, parts[-1], body)
    finally:
        os.close(dir_fd)


def git_diff(
    repo: str,
    token: str,
    staged: bool = False,
    files: list[str] | None = None,
    ref: str | None = None,
    output: str | None = None,
) -> dict:
    """Show changes between working tree, index, and commits.

    With `output` the diff body goes straight from git into a file instead of
    being returned. Use this for a review-sized diff: git writes the bytes, so
    nothing re-types them, and none of the body enters the caller's context.

    The result carries the path written and a --stat summary of the same
    selection — each changed file with its changed-line counts. The stat is a
    convenience overview from a second git call, not a check on the file: it
    describes the selection as git saw it a moment later, so a tree that
    changes underneath the two calls can make them disagree.

    `output` is a path relative to `<repo>/.git-sidecar/` and must stay inside
    it; '..', an absolute path, and a symlink leading out are all rejected, so
    no tracked file can be overwritten. Missing directories are created — the
    sidecar directory itself on first use, holding a .gitignore of '*' that
    ignores everything there including itself, so git never reports the written
    file and no repository needs an ignore entry for it. Deleting diffs once
    read is the caller's business.

    An existing file at the path is overwritten; a selection with no changes
    writes an empty file rather than leaving an older diff in place.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.
        staged: If True, show staged changes (--cached).
        files: Optional list of files to limit the diff.
        ref: Optional ref to diff against (e.g. "HEAD~1").
        output: Optional path, relative to `<repo>/.git-sidecar/`, to write the
            diff to instead of returning it.

    Returns:
        ExecResult dict with diff output. With `output`, an ExecResult dict
        without stdout, carrying "path" (absolute path of the file written) and
        "stat" (git's --stat summary of the same selection) instead.

    Raises:
        ValidationError: If a file argument escapes the repository, or the
            output path escapes the sidecar directory.
    """
    if files:
        validate_file_args(files)

    config = _get_config()
    repo_path = verify_token(config, repo, token)

    output_base = repo_path / OUTPUT_DIR
    output_path = (
        resolve_output_path(output_base, output) if output is not None else None
    )

    result = executor.run(_diff_args(staged, files, ref), cwd=str(repo_path))
    if output_path is None or not result.ok:
        return result.to_dict()

    stat_result = executor.run(
        _diff_args(staged, files, ref, stat=True), cwd=str(repo_path)
    )
    if not stat_result.ok:
        return stat_result.to_dict()

    try:
        _write_output(output_path, output_base, result.stdout)
    except OSError as exc:
        return {
            "ok": False,
            "returncode": 1,
            "stdout": "",
            "stderr": f"Diff could not be written to {output_path}: {exc}",
        }

    return {
        "ok": result.ok,
        "returncode": result.returncode,
        "stderr": result.stderr,
        "path": str(output_path),
        "stat": stat_result.stdout,
    }


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
