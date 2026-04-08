"""Tests for git_sidecar.tools.github."""

import json
from unittest.mock import call, patch

import pytest

from git_sidecar.config import SidecarConfig
from git_sidecar.executor import ExecResult
from git_sidecar.tools import github

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok(stdout: str = "", stderr: str = "") -> ExecResult:
    """Return a successful ExecResult."""
    return ExecResult(returncode=0, stdout=stdout, stderr=stderr)


def _fail(stderr: str = "", stdout: str = "") -> ExecResult:
    """Return a failed ExecResult."""
    return ExecResult(returncode=1, stdout=stdout, stderr=stderr)


@pytest.fixture(autouse=True)
def reset_config():
    """Reset the module-level _config between tests."""
    github._config = None
    yield
    github._config = None


@pytest.fixture()
def config(tmp_path):
    """Return a SidecarConfig pointing at tmp_path."""
    return SidecarConfig(projects_dir=str(tmp_path))


@pytest.fixture()
def repo_path(tmp_path):
    """Create a fake repo directory with a token file."""
    repo = tmp_path / "my-org" / "my-repo"
    repo.mkdir(parents=True)
    (repo / ".git-sidecar-token").write_text("secret")
    return repo


@pytest.fixture()
def initialized(config):
    """Initialize the github module and return the config."""
    github.init(config)
    return config


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SSH_URL = "git@github.com:acme/srv.git"
REPO_SPEC = "acme/srv"

CHECKS_OUTPUT_WITH_FAILURES = (
    "CI/build\tfail\t1m30s\thttps://github.com/acme/srv/actions/runs/111/jobs/222\n"
    "CI/lint\tpass\t30s\thttps://github.com/acme/srv/actions/runs/333/jobs/444\n"
    "CI/test\tfail\t2m\thttps://github.com/acme/srv/actions/runs/111/jobs/555\n"
)

CHECKS_OUTPUT_ALL_PASS = (
    "CI/build\tpass\t1m\thttps://github.com/acme/srv/actions/runs/888/jobs/1\n"
)


# ---------------------------------------------------------------------------
# _get_github_repo
# ---------------------------------------------------------------------------


class TestGetGithubRepo:
    """Tests for _get_github_repo URL parsing."""

    def test_ssh_url(self):
        """Parse SSH remote URL with .git suffix."""
        with patch("git_sidecar.tools.github.executor.run") as mock_run:
            mock_run.return_value = _ok("git@github.com:acme/my-service.git\n")
            owner, repo = github._get_github_repo("/some/path")
        assert owner == "acme"
        assert repo == "my-service"

    def test_ssh_url_no_dot_git(self):
        """Parse SSH remote URL without .git suffix."""
        with patch("git_sidecar.tools.github.executor.run") as mock_run:
            mock_run.return_value = _ok("git@github.com:acme/my-service\n")
            owner, repo = github._get_github_repo("/some/path")
        assert owner == "acme"
        assert repo == "my-service"

    def test_https_url(self):
        """Parse HTTPS remote URL with .git suffix."""
        with patch("git_sidecar.tools.github.executor.run") as mock_run:
            mock_run.return_value = _ok("https://github.com/acme/my-service.git\n")
            owner, repo = github._get_github_repo("/some/path")
        assert owner == "acme"
        assert repo == "my-service"

    def test_https_url_no_dot_git(self):
        """Parse HTTPS remote URL without .git suffix."""
        with patch("git_sidecar.tools.github.executor.run") as mock_run:
            mock_run.return_value = _ok("https://github.com/acme/my-service\n")
            owner, repo = github._get_github_repo("/some/path")
        assert owner == "acme"
        assert repo == "my-service"

    def test_no_origin_raises(self):
        """Raise ValueError when origin remote is not configured."""
        with patch("git_sidecar.tools.github.executor.run") as mock_run:
            mock_run.return_value = _fail("error: No such remote 'origin'")
            with pytest.raises(ValueError, match="No origin remote configured"):
                github._get_github_repo("/some/path")

    def test_unparseable_url_raises(self):
        """Raise ValueError when URL cannot be parsed."""
        with patch("git_sidecar.tools.github.executor.run") as mock_run:
            mock_run.return_value = _ok("not-a-valid-url\n")
            with pytest.raises(ValueError, match="Cannot parse GitHub owner/repo"):
                github._get_github_repo("/some/path")

    def test_run_called_with_correct_args(self, tmp_path):
        """Verify correct git command is used to get remote URL."""
        with patch("git_sidecar.tools.github.executor.run") as mock_run:
            mock_run.return_value = _ok("git@github.com:org/repo.git")
            github._get_github_repo("/my/repo")
        mock_run.assert_called_once_with(
            ["git", "remote", "get-url", "origin"], cwd="/my/repo"
        )


# ---------------------------------------------------------------------------
# Module initialization
# ---------------------------------------------------------------------------


class TestInit:
    """Tests for module init and _get_config."""

    def test_not_initialized_raises(self):
        """Raise RuntimeError when config is not initialized."""
        with pytest.raises(RuntimeError, match="not initialized"):
            github._get_config()

    def test_init_sets_config(self, config):
        """Init stores the config for later retrieval."""
        github.init(config)
        assert github._get_config() is config


# ---------------------------------------------------------------------------
# gh_pr_create
# ---------------------------------------------------------------------------


class TestGhPrCreate:
    """Tests for gh_pr_create."""

    def test_builds_correct_command(self, initialized, config, repo_path):
        """Verify the gh pr create command is constructed correctly."""
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [
                _ok(SSH_URL),
                _ok("https://github.com/acme/srv/pull/42\n"),
            ]
            result = github.gh_pr_create(
                "my-org/my-repo", "secret", "main", "My Title", "My body"
            )

        assert result["ok"] is True
        assert result["stdout"] == "https://github.com/acme/srv/pull/42\n"

        calls = mock_run.call_args_list
        assert calls[1] == call(
            [
                "gh",
                "pr",
                "create",
                "--base",
                "main",
                "--title",
                "My Title",
                "--body",
                "My body",
                "--repo",
                REPO_SPEC,
            ],
            cwd=str(repo_path),
        )

    def test_propagates_failure(self, initialized, config, repo_path):
        """Return error dict when gh command fails."""
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [_ok(SSH_URL), _fail("gh: error")]
            result = github.gh_pr_create("r", "t", "main", "T", "B")
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# gh_pr_view
# ---------------------------------------------------------------------------


class TestGhPrView:
    """Tests for gh_pr_view."""

    def test_default_fields(self, initialized, repo_path):
        """Use default fields when none specified."""
        pr_data = {"number": 42, "title": "Test PR"}
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [_ok(SSH_URL), _ok(json.dumps(pr_data))]
            result = github.gh_pr_view("r", "t", "42")

        assert result == pr_data
        cmd = mock_run.call_args_list[1][0][0]
        assert "--json" in cmd
        assert github.DEFAULT_PR_FIELDS in cmd

    def test_custom_fields(self, initialized, repo_path):
        """Use custom fields when specified."""
        pr_data = {"number": 42}
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [_ok(SSH_URL), _ok(json.dumps(pr_data))]
            result = github.gh_pr_view("r", "t", "42", fields="number")

        cmd = mock_run.call_args_list[1][0][0]
        assert "number" in cmd
        assert result == pr_data

    def test_failure_returns_exec_dict(self, initialized, repo_path):
        """Return ExecResult dict when gh command fails."""
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [_ok(SSH_URL), _fail("not found")]
            result = github.gh_pr_view("r", "t", "99")
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# gh_pr_list
# ---------------------------------------------------------------------------


class TestGhPrList:
    """Tests for gh_pr_list."""

    def test_lists_prs(self, initialized, repo_path):
        """Return list of PRs wrapped in a dict."""
        prs = [{"number": 1, "title": "PR1"}]
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [_ok(SSH_URL), _ok(json.dumps(prs))]
            result = github.gh_pr_list("r", "t")

        assert result == {"prs": prs}
        cmd = mock_run.call_args_list[1][0][0]
        assert "--head" not in cmd

    def test_with_head_filter(self, initialized, repo_path):
        """Add --head flag when head branch is specified."""
        prs = [{"number": 2}]
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [_ok(SSH_URL), _ok(json.dumps(prs))]
            result = github.gh_pr_list("r", "t", head="feature/x")

        cmd = mock_run.call_args_list[1][0][0]
        assert "--head" in cmd
        assert "feature/x" in cmd
        assert result == {"prs": prs}

    def test_failure_returns_exec_dict(self, initialized, repo_path):
        """Return ExecResult dict when gh command fails."""
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [_ok(SSH_URL), _fail("error")]
            result = github.gh_pr_list("r", "t")
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# gh_pr_fetch
# ---------------------------------------------------------------------------


class TestGhPrFetch:
    """Tests for gh_pr_fetch."""

    def test_combines_three_api_calls(self, initialized, repo_path):
        """Return combined dict with inline_comments, reviews, conversation."""
        inline = [{"id": 1}]
        reviews = [{"id": 2}]
        conversation = [{"id": 3}]

        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [
                _ok(SSH_URL),
                _ok(json.dumps(inline)),
                _ok(json.dumps(reviews)),
                _ok(json.dumps(conversation)),
            ]
            result = github.gh_pr_fetch("r", "t", 42)

        assert result == {
            "inline_comments": inline,
            "reviews": reviews,
            "conversation": conversation,
        }

    def test_api_paths_are_correct(self, initialized, repo_path):
        """Verify the three GitHub API paths are correct."""
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [
                _ok(SSH_URL),
                _ok("[]"),
                _ok("[]"),
                _ok("[]"),
            ]
            github.gh_pr_fetch("r", "t", 7)

        calls = mock_run.call_args_list
        assert f"repos/{REPO_SPEC}/pulls/7/comments" in calls[1][0][0]
        assert f"repos/{REPO_SPEC}/pulls/7/reviews" in calls[2][0][0]
        assert f"repos/{REPO_SPEC}/issues/7/comments" in calls[3][0][0]

    def test_inline_failure_returns_error_dict(self, initialized, repo_path):
        """Return error dict when inline comments API call fails."""
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [_ok(SSH_URL), _fail("api error")]
            result = github.gh_pr_fetch("r", "t", 42)
        assert result["ok"] is False
        assert "inline_comments" in result["error"]

    def test_reviews_failure_returns_error_dict(self, initialized, repo_path):
        """Return error dict when reviews API call fails."""
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [
                _ok(SSH_URL),
                _ok("[]"),
                _fail("api error"),
            ]
            result = github.gh_pr_fetch("r", "t", 42)
        assert result["ok"] is False
        assert "reviews" in result["error"]


# ---------------------------------------------------------------------------
# gh_pr_reply
# ---------------------------------------------------------------------------


class TestGhPrReply:
    """Tests for gh_pr_reply."""

    def test_top_level_comment(self, initialized, repo_path):
        """Post top-level comment via issues endpoint when no comment_id."""
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [_ok(SSH_URL), _ok("{}")]
            github.gh_pr_reply("r", "t", 42, "Hello!")

        cmd = mock_run.call_args_list[1][0][0]
        assert "gh" in cmd
        assert "api" in cmd
        assert f"repos/{REPO_SPEC}/issues/42/comments" in cmd
        assert "body=Hello!" in cmd
        assert "replies" not in " ".join(cmd)

    def test_inline_reply(self, initialized, repo_path):
        """Post inline reply via pulls/comments/{id}/replies endpoint."""
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [_ok(SSH_URL), _ok("{}")]
            github.gh_pr_reply("r", "t", 42, "LGTM", comment_id=99)

        cmd = mock_run.call_args_list[1][0][0]
        assert f"repos/{REPO_SPEC}/pulls/42/comments/99/replies" in cmd
        assert "body=LGTM" in cmd


# ---------------------------------------------------------------------------
# _extract_failed_run_ids
# ---------------------------------------------------------------------------


class TestExtractFailedRunIds:
    """Tests for _extract_failed_run_ids helper."""

    def test_extracts_unique_ids(self):
        """Deduplicate run IDs across multiple failed jobs."""
        run_ids = github._extract_failed_run_ids(CHECKS_OUTPUT_WITH_FAILURES)
        assert run_ids == ["111"]

    def test_no_failures(self):
        """Return empty list when no failures present."""
        run_ids = github._extract_failed_run_ids(CHECKS_OUTPUT_ALL_PASS)
        assert run_ids == []

    def test_empty_input(self):
        """Return empty list for empty string input."""
        assert github._extract_failed_run_ids("") == []


# ---------------------------------------------------------------------------
# gh_pr_checks
# ---------------------------------------------------------------------------


class TestGhPrChecks:
    """Tests for gh_pr_checks."""

    def test_no_failures_no_log_fetch(self, initialized, repo_path):
        """Skip log fetch when all checks pass."""
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [_ok(SSH_URL), _ok(CHECKS_OUTPUT_ALL_PASS)]
            result = github.gh_pr_checks("r", "t", 1)

        assert result["ok"] is True
        assert mock_run.call_count == 2

    def test_failures_trigger_log_fetch(self, initialized, repo_path):
        """Fetch failed run logs when checks have failures."""
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [
                _ok(SSH_URL),
                ExecResult(returncode=1, stdout=CHECKS_OUTPUT_WITH_FAILURES, stderr=""),
                _ok("=== failed logs ==="),
            ]
            result = github.gh_pr_checks("r", "t", 5)

        assert result["ok"] is True
        assert "--- Failed logs for run 111 ---" in result["output"]
        assert "=== failed logs ===" in result["output"]
        assert mock_run.call_count == 3

    def test_command_error_returns_exec_dict(self, initialized, repo_path):
        """Return ExecResult dict when gh command itself errors."""
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [_ok(SSH_URL), _fail("gh: not found")]
            result = github.gh_pr_checks("r", "t", 1)
        assert result["ok"] is False

    def test_correct_command_built(self, initialized, repo_path):
        """Build gh pr checks command with correct repo spec and PR number."""
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [_ok(SSH_URL), _ok("")]
            github.gh_pr_checks("r", "t", 7)

        cmd = mock_run.call_args_list[1][0][0]
        assert cmd == ["gh", "pr", "checks", "7", "--repo", REPO_SPEC]


# ---------------------------------------------------------------------------
# gh_pr_close
# ---------------------------------------------------------------------------


class TestGhPrClose:
    """Tests for gh_pr_close."""

    def test_basic_close(self, initialized, repo_path):
        """Return closed dict without optional flags."""
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [_ok(SSH_URL), _ok("")]
            result = github.gh_pr_close("r", "t", 42)

        assert result == {"pr": 42, "repo": REPO_SPEC, "closed": True}
        cmd = mock_run.call_args_list[1][0][0]
        assert "42" in cmd
        assert "--comment" not in cmd
        assert "--delete-branch" not in cmd

    def test_with_comment(self, initialized, repo_path):
        """Include --comment flag when comment is provided."""
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [_ok(SSH_URL), _ok("")]
            github.gh_pr_close("r", "t", 42, comment="Closing this.")

        cmd = mock_run.call_args_list[1][0][0]
        assert "--comment" in cmd
        assert "Closing this." in cmd

    def test_with_delete_branch(self, initialized, repo_path):
        """Include --delete-branch flag when requested."""
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [_ok(SSH_URL), _ok("")]
            github.gh_pr_close("r", "t", 42, delete_branch=True)

        cmd = mock_run.call_args_list[1][0][0]
        assert "--delete-branch" in cmd

    def test_failure_returns_exec_dict(self, initialized, repo_path):
        """Return ExecResult dict when gh command fails."""
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [_ok(SSH_URL), _fail("error")]
            result = github.gh_pr_close("r", "t", 42)
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# gh_run_view
# ---------------------------------------------------------------------------


class TestGhRunView:
    """Tests for gh_run_view."""

    def test_basic_view(self, initialized, repo_path):
        """View run without --log-failed flag."""
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [_ok(SSH_URL), _ok("run output")]
            result = github.gh_run_view("r", "t", 123)

        assert result["ok"] is True
        cmd = mock_run.call_args_list[1][0][0]
        assert cmd == ["gh", "run", "view", "123", "--repo", REPO_SPEC]
        assert "--log-failed" not in cmd

    def test_log_failed_flag(self, initialized, repo_path):
        """Include --log-failed when log_failed=True."""
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [_ok(SSH_URL), _ok("logs")]
            github.gh_run_view("r", "t", 123, log_failed=True)

        cmd = mock_run.call_args_list[1][0][0]
        assert "--log-failed" in cmd


# ---------------------------------------------------------------------------
# gh_run_list
# ---------------------------------------------------------------------------


class TestGhRunList:
    """Tests for gh_run_list."""

    def test_basic_list(self, initialized, repo_path):
        """List workflow runs with correct command."""
        with (
            patch("git_sidecar.tools.github.verify_token") as mock_vt,
            patch("git_sidecar.tools.github.executor.run") as mock_run,
        ):
            mock_vt.return_value = repo_path
            mock_run.side_effect = [_ok(SSH_URL), _ok("run1\nrun2\n")]
            result = github.gh_run_list("r", "t")

        assert result["ok"] is True
        cmd = mock_run.call_args_list[1][0][0]
        assert cmd == ["gh", "run", "list", "--repo", REPO_SPEC]
