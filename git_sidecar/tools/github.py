"""GitHub CLI wrapper tools for the git-sidecar MCP server."""

import json
import re

from git_sidecar import executor
from git_sidecar.auth import verify_token
from git_sidecar.config import SidecarConfig

_config: SidecarConfig | None = None

DEFAULT_PR_FIELDS = "number,title,url,headRefName,state,statusCheckRollup"


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
        raise RuntimeError("github module not initialized — call init(config) first")
    return _config


def _get_github_repo(repo_path: str) -> tuple[str, str]:
    """Extract owner and repo from git remote origin URL.

    Args:
        repo_path: Absolute path to the repository.

    Returns:
        Tuple of (owner, repo) strings.

    Raises:
        ValueError: If origin remote is not configured or URL cannot be parsed.
    """
    result = executor.run(["git", "remote", "get-url", "origin"], cwd=repo_path)
    if not result.ok:
        raise ValueError("No origin remote configured")
    url = result.stdout.strip()

    # SSH: git@github.com:owner/repo.git
    ssh_match = re.match(r"git@[^:]+:([^/]+)/(.+?)(?:\.git)?$", url)
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2)

    # HTTPS: https://github.com/owner/repo.git
    https_match = re.match(r"https?://[^/]+/([^/]+)/(.+?)(?:\.git)?$", url)
    if https_match:
        return https_match.group(1), https_match.group(2)

    raise ValueError(f"Cannot parse GitHub owner/repo from remote URL: {url}")


def gh_pr_create(repo: str, token: str, base: str, title: str, body: str) -> dict:
    """Create a pull request.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.
        base: Base branch for the PR.
        title: PR title.
        body: PR body text.

    Returns:
        ExecResult dict with command output.
    """
    config = _get_config()
    repo_path = verify_token(config, repo, token)
    owner, repo_name = _get_github_repo(str(repo_path))
    repo_spec = f"{owner}/{repo_name}"

    result = executor.run(
        [
            "gh",
            "pr",
            "create",
            "--base",
            base,
            "--title",
            title,
            "--body",
            body,
            "--repo",
            repo_spec,
        ],
        cwd=str(repo_path),
    )
    return result.to_dict()


def gh_pr_view(
    repo: str,
    token: str,
    pr: str,
    fields: str | None = None,
) -> dict:
    """View a PR by number or branch.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.
        pr: PR number or branch name.
        fields: Comma-separated JSON fields to fetch (default: common fields).

    Returns:
        Dict with PR data parsed from gh JSON output, or ExecResult dict on error.
    """
    config = _get_config()
    repo_path = verify_token(config, repo, token)
    owner, repo_name = _get_github_repo(str(repo_path))
    repo_spec = f"{owner}/{repo_name}"

    result = executor.run(
        [
            "gh",
            "pr",
            "view",
            pr,
            "--json",
            fields or DEFAULT_PR_FIELDS,
            "--repo",
            repo_spec,
        ],
        cwd=str(repo_path),
    )
    if not result.ok:
        return result.to_dict()
    return json.loads(result.stdout)


def gh_pr_list(repo: str, token: str, head: str | None = None) -> dict:
    """List pull requests.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.
        head: Optional head branch filter.

    Returns:
        Dict with "prs" key containing list of PR dicts, or ExecResult dict on error.
    """
    config = _get_config()
    repo_path = verify_token(config, repo, token)
    owner, repo_name = _get_github_repo(str(repo_path))
    repo_spec = f"{owner}/{repo_name}"

    cmd = [
        "gh",
        "pr",
        "list",
        "--json",
        "number,title,url,headRefName,state",
        "--repo",
        repo_spec,
    ]
    if head:
        cmd.extend(["--head", head])

    result = executor.run(cmd, cwd=str(repo_path))
    if not result.ok:
        return result.to_dict()
    return {"prs": json.loads(result.stdout)}


def gh_pr_fetch(repo: str, token: str, pr_number: int) -> dict:
    """Fetch PR feedback: inline comments, reviews, conversation.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.
        pr_number: The pull request number.

    Returns:
        Dict with keys "inline_comments", "reviews", "conversation",
        or an error dict if any API call fails.
    """
    config = _get_config()
    repo_path = verify_token(config, repo, token)
    owner, repo_name = _get_github_repo(str(repo_path))
    repo_spec = f"{owner}/{repo_name}"

    def _api_get(path: str) -> tuple[bool, object]:
        res = executor.run(
            ["gh", "api", f"repos/{repo_spec}/{path}"],
            cwd=str(repo_path),
        )
        if not res.ok:
            return False, res.to_dict()
        return True, json.loads(res.stdout)

    ok, inline = _api_get(f"pulls/{pr_number}/comments")
    if not ok:
        return {"ok": False, "error": "inline_comments fetch failed", "detail": inline}

    ok, reviews = _api_get(f"pulls/{pr_number}/reviews")
    if not ok:
        return {"ok": False, "error": "reviews fetch failed", "detail": reviews}

    ok, conversation = _api_get(f"issues/{pr_number}/comments")
    if not ok:
        return {
            "ok": False,
            "error": "conversation fetch failed",
            "detail": conversation,
        }

    return {
        "inline_comments": inline,
        "reviews": reviews,
        "conversation": conversation,
    }


def gh_pr_reply(
    repo: str,
    token: str,
    pr_number: int,
    body: str,
    comment_id: int | None = None,
) -> dict:
    """Reply to a PR.

    Without comment_id, posts a top-level conversation comment.
    With comment_id, replies in an inline review thread.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.
        pr_number: The pull request number.
        body: Comment body text.
        comment_id: ID of the inline comment to reply to (optional).

    Returns:
        ExecResult dict with command output.
    """
    config = _get_config()
    repo_path = verify_token(config, repo, token)
    owner, repo_name = _get_github_repo(str(repo_path))

    if comment_id is not None:
        path = f"repos/{owner}/{repo_name}/pulls/{pr_number}/comments/{comment_id}/replies"
        cmd = [
            "gh",
            "api",
            "-X",
            "POST",
            path,
            "-f",
            f"body={body}",
        ]
    else:
        path = f"repos/{owner}/{repo_name}/issues/{pr_number}/comments"
        cmd = [
            "gh",
            "api",
            "-X",
            "POST",
            path,
            "-f",
            f"body={body}",
        ]

    result = executor.run(cmd, cwd=str(repo_path))
    return result.to_dict()


def _extract_failed_run_ids(checks_output: str) -> list[str]:
    """Extract unique run IDs from failed check lines in gh pr checks output.

    Args:
        checks_output: Stdout from gh pr checks.

    Returns:
        Ordered list of unique run IDs for failed checks.
    """
    run_ids: list[str] = []
    seen: set[str] = set()
    for line in checks_output.splitlines():
        if "fail" not in line.lower() or "/runs/" not in line:
            continue
        match = re.search(r"/runs/(\d+)", line)
        if not match:
            continue
        run_id = match.group(1)
        if run_id in seen:
            continue
        seen.add(run_id)
        run_ids.append(run_id)
    return run_ids


def gh_pr_checks(repo: str, token: str, pr_number: int) -> dict:
    """Show CI check statuses and fetch failed logs.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.
        pr_number: The pull request number.

    Returns:
        Dict with "ok", "output" keys. Output includes failed run logs appended.
    """
    config = _get_config()
    repo_path = verify_token(config, repo, token)
    owner, repo_name = _get_github_repo(str(repo_path))
    repo_spec = f"{owner}/{repo_name}"

    result = executor.run(
        ["gh", "pr", "checks", str(pr_number), "--repo", repo_spec],
        cwd=str(repo_path),
    )

    # gh pr checks returns 1 when any check has failed — this is normal,
    # but only when it produced stdout (the checks table). If stdout is empty
    # and returncode != 0, the command itself errored.
    if not result.ok and not result.stdout:
        return result.to_dict()

    output = result.stdout
    run_ids = _extract_failed_run_ids(result.stdout)
    for run_id in run_ids:
        log_result = executor.run(
            ["gh", "run", "view", run_id, "--log-failed", "--repo", repo_spec],
            cwd=str(repo_path),
        )
        output += f"\n--- Failed logs for run {run_id} ---\n"
        output += log_result.stdout

    return {"ok": True, "output": output}


def gh_pr_close(
    repo: str,
    token: str,
    pr_number: int,
    comment: str | None = None,
    delete_branch: bool = False,
) -> dict:
    """Close a pull request.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.
        pr_number: PR number to close.
        comment: Optional comment to leave when closing.
        delete_branch: Whether to delete the head branch after closing.

    Returns:
        Dict with closure status or ExecResult dict on error.
    """
    config = _get_config()
    repo_path = verify_token(config, repo, token)
    owner, repo_name = _get_github_repo(str(repo_path))
    repo_spec = f"{owner}/{repo_name}"

    cmd = ["gh", "pr", "close", str(pr_number), "--repo", repo_spec]
    if comment:
        cmd.extend(["--comment", comment])
    if delete_branch:
        cmd.append("--delete-branch")

    result = executor.run(cmd, cwd=str(repo_path))
    if not result.ok:
        return result.to_dict()
    return {"pr": pr_number, "repo": repo_spec, "closed": True}


def gh_run_view(
    repo: str,
    token: str,
    run_id: int,
    log_failed: bool = False,
) -> dict:
    """View a workflow run.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.
        run_id: The workflow run ID.
        log_failed: If True, fetch only failed step logs (--log-failed).

    Returns:
        ExecResult dict with run output.
    """
    config = _get_config()
    repo_path = verify_token(config, repo, token)
    owner, repo_name = _get_github_repo(str(repo_path))
    repo_spec = f"{owner}/{repo_name}"

    cmd = ["gh", "run", "view", str(run_id), "--repo", repo_spec]
    if log_failed:
        cmd.append("--log-failed")

    result = executor.run(cmd, cwd=str(repo_path))
    return result.to_dict()


def gh_run_list(repo: str, token: str) -> dict:
    """List workflow runs.

    Args:
        repo: Relative path to the repository.
        token: Agent authentication token.

    Returns:
        ExecResult dict with run list output.
    """
    config = _get_config()
    repo_path = verify_token(config, repo, token)
    owner, repo_name = _get_github_repo(str(repo_path))
    repo_spec = f"{owner}/{repo_name}"

    result = executor.run(
        ["gh", "run", "list", "--repo", repo_spec],
        cwd=str(repo_path),
    )
    return result.to_dict()
