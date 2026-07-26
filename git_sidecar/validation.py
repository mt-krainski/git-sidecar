"""Input validation for branch names, paths, and arguments."""

import pathlib


class ValidationError(Exception):
    """Raised when input validation fails."""


PROTECTED_BRANCHES = frozenset({"main", "master"})


def validate_branch_prefix(
    branch: str,
    allowed_prefixes: list[str],
) -> None:
    """Ensure a branch name starts with one of the allowed prefixes.

    Args:
        branch: Branch name to validate.
        allowed_prefixes: List of allowed prefix strings.

    Raises:
        ValidationError: If the branch doesn't match any prefix.
    """
    if not branch:
        raise ValidationError("Branch name cannot be empty")

    for prefix in allowed_prefixes:
        if branch.startswith(prefix):
            return

    prefixes_str = ", ".join(allowed_prefixes)
    raise ValidationError(
        f"Branch '{branch}' does not match any allowed prefix: {prefixes_str}"
    )


def validate_push_branch(
    branch: str,
    allowed_prefixes: list[str],
) -> None:
    """Validate a branch is safe to push.

    Blocks main/master and enforces prefix rules.

    Args:
        branch: Branch name to validate.
        allowed_prefixes: List of allowed prefix strings.

    Raises:
        ValidationError: If the branch is protected or doesn't match prefixes.
    """
    if not branch:
        raise ValidationError("Branch name cannot be empty")

    if branch in PROTECTED_BRANCHES:
        raise ValidationError(f"Cannot push to protected branch: {branch}")

    validate_branch_prefix(branch, allowed_prefixes)


def validate_checkout_target(
    target: str,
    allowed_prefixes: list[str],
    *,
    create: bool = False,
) -> None:
    """Validate a checkout target.

    Checking out main/master is allowed (read-only).
    Creating new branches requires allowed prefixes.

    Args:
        target: Branch name or ref to check out.
        allowed_prefixes: List of allowed prefix strings.
        create: Whether this is creating a new branch (-b flag).

    Raises:
        ValidationError: If the target is not allowed.
    """
    if not target:
        raise ValidationError("Checkout target cannot be empty")

    if target in PROTECTED_BRANCHES:
        return

    if create:
        validate_branch_prefix(target, allowed_prefixes)
        return

    validate_branch_prefix(target, allowed_prefixes)


def validate_no_force_flags(args: list[str]) -> None:
    """Reject any force-push flags in an argument list.

    Args:
        args: List of command arguments.

    Raises:
        ValidationError: If force flags are found.
    """
    force_flags = {"--force", "-f", "--force-with-lease"}
    found = force_flags & set(args)
    if found:
        raise ValidationError(f"Force flags are not allowed: {', '.join(found)}")


def validate_file_args(files: list[str]) -> None:
    """Ensure file arguments don't escape the repository.

    Args:
        files: List of file paths (relative to repo root).

    Raises:
        ValidationError: If any path tries to escape with '..'.
    """
    for f in files:
        if ".." in f.split("/"):
            raise ValidationError(f"Path traversal not allowed: {f}")


def resolve_output_path(base: pathlib.Path, output: str) -> pathlib.Path:
    """Resolve a path a tool will write to and confine it to one directory.

    Confinement is decided on the resolved path, component-wise: symlinks are
    followed first, so neither '..', an absolute path, nor a symlink — at any
    component, base itself included — can name a path outside base. A
    string-prefix comparison would be weaker: it admits a sibling whose name
    merely starts with base's, such as "packages-backup" beside "packages".

    This answers what a path names now, which is all a check can answer. It is
    not a licence to write: anything can change between this call and the open,
    so the write must defend itself (see git_read._write_output).

    Args:
        base: Absolute, already-resolved directory the output must stay inside.
            It need not exist yet.
        output: Path relative to base, naming a file below it.

    Returns:
        Resolved absolute path inside base.

    Raises:
        ValidationError: If output is empty, holds a null byte, is absolute,
            cannot be resolved, escapes base, or names base itself.
    """
    if not output:
        raise ValidationError("Output path cannot be empty")

    if "\0" in output:
        raise ValidationError(f"Output path contains a null byte: {output!r}")

    if pathlib.Path(output).is_absolute():
        raise ValidationError(f"Output path must be relative to {base.name}/: {output}")

    try:
        resolved = (base / output).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        message = f"Output path cannot be resolved: {output} ({exc})"
        raise ValidationError(message) from exc

    if not resolved.is_relative_to(base):
        raise ValidationError(f"Output path escapes {base.name}/: {output}")

    if resolved == base:
        raise ValidationError(
            f"Output path must name a file inside {base.name}/: {output}"
        )

    return resolved
