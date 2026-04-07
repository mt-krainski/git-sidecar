"""Tests for git_sidecar.tools.git_write."""

import pathlib
from unittest.mock import patch

import pytest

from git_sidecar.config import SidecarConfig
from git_sidecar.executor import ExecResult
from git_sidecar.tools import git_write
from git_sidecar.validation import ValidationError

PREFIXES = ["task/", "feat/"]

CONFIG = SidecarConfig(
    projects_dir="/projects",
    allowed_branch_prefixes=PREFIXES,
)

REPO_PATH = pathlib.Path("/projects/my-org/my-repo")

OK_RESULT = ExecResult(returncode=0, stdout="ok", stderr="")
FAIL_RESULT = ExecResult(returncode=1, stdout="", stderr="error")


@pytest.fixture(autouse=True)
def setup_config():
    """Initialize git_write with test config before each test."""
    git_write.init(CONFIG)


def make_run_result(returncode=0, stdout="", stderr=""):
    """Build an ExecResult for testing."""
    return ExecResult(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture()
def mock_verify():
    """Patch auth.verify_token to return REPO_PATH."""
    with patch(
        "git_sidecar.tools.git_write.auth.verify_token", return_value=REPO_PATH
    ) as m:
        yield m


@pytest.fixture()
def mock_run():
    """Patch executor.run to return OK_RESULT by default."""
    with patch("git_sidecar.tools.git_write.executor.run", return_value=OK_RESULT) as m:
        yield m


class TestGitAdd:
    """Tests for git_add."""

    def test_stages_files(self, mock_verify, mock_run):
        """Calls git add with file list."""
        result = git_write.git_add("my-org/my-repo", "token", ["src/foo.py"])
        assert result["ok"] is True
        mock_run.assert_called_once_with(
            ["git", "add", "--", "src/foo.py"], cwd=str(REPO_PATH)
        )

    def test_blocks_path_traversal(self, mock_verify):
        """Rejects .. in file paths."""
        with pytest.raises(ValidationError, match="traversal"):
            git_write.git_add("my-org/my-repo", "token", ["../../etc/passwd"])

    def test_multiple_files(self, mock_verify, mock_run):
        """Passes all files to git add."""
        git_write.git_add("my-org/my-repo", "token", ["a.py", "b.py"])
        mock_run.assert_called_once_with(
            ["git", "add", "--", "a.py", "b.py"], cwd=str(REPO_PATH)
        )


class TestGitRm:
    """Tests for git_rm."""

    def test_removes_file(self, mock_verify, mock_run):
        """Calls git rm with file list."""
        result = git_write.git_rm("my-org/my-repo", "token", ["old.py"])
        assert result["ok"] is True
        mock_run.assert_called_once_with(
            ["git", "rm", "--", "old.py"], cwd=str(REPO_PATH)
        )

    def test_blocks_path_traversal(self, mock_verify):
        """Rejects .. in file paths."""
        with pytest.raises(ValidationError, match="traversal"):
            git_write.git_rm("my-org/my-repo", "token", ["../outside.py"])


class TestGitCommit:
    """Tests for git_commit."""

    def _make_commit_run(self, user_name="Agent", user_email="agent@example.com"):
        """Return a side_effect list simulating a successful commit sequence."""
        name_result = make_run_result(0, user_name)
        email_result = make_run_result(0, user_email)
        staged_result = make_run_result(1)  # returncode 1 = has staged changes
        commit_result = make_run_result(0, "1 file changed")
        return [name_result, email_result, staged_result, commit_result]

    def test_successful_commit(self, mock_verify):
        """Commits with author env vars set from git config."""
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            side_effect=self._make_commit_run(),
        ) as mock_run:
            result = git_write.git_commit("my-org/my-repo", "token", "my message")

        assert result["ok"] is True
        # Last call should be the actual commit
        commit_call = mock_run.call_args_list[-1]
        assert commit_call.args[0] == ["git", "commit", "-m", "my message"]
        env = commit_call.kwargs["env"]
        assert env["GIT_AUTHOR_NAME"] == "Agent"
        assert env["GIT_AUTHOR_EMAIL"] == "agent@example.com"
        assert env["GIT_COMMITTER_NAME"] == "Agent"
        assert env["GIT_COMMITTER_EMAIL"] == "agent@example.com"

    def test_fails_if_user_name_not_set(self, mock_verify):
        """Returns error if git config user.name is empty."""
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            side_effect=[make_run_result(1, "")],  # git config user.name fails
        ):
            result = git_write.git_commit("my-org/my-repo", "token", "msg")

        assert result["ok"] is False
        assert "user.name" in result["stderr"]

    def test_fails_if_user_email_not_set(self, mock_verify):
        """Returns error if git config user.email is empty."""
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            side_effect=[
                make_run_result(0, "Agent"),  # user.name ok
                make_run_result(1, ""),  # user.email fails
            ],
        ):
            result = git_write.git_commit("my-org/my-repo", "token", "msg")

        assert result["ok"] is False
        assert "user.email" in result["stderr"]

    def test_fails_if_nothing_staged(self, mock_verify):
        """Returns error if there are no staged changes."""
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            side_effect=[
                make_run_result(0, "Agent"),
                make_run_result(0, "agent@example.com"),
                make_run_result(0),  # returncode 0 = nothing staged
            ],
        ):
            result = git_write.git_commit("my-org/my-repo", "token", "msg")

        assert result["ok"] is False
        assert "nothing staged" in result["stderr"]

    def test_reads_git_config_in_cwd(self, mock_verify):
        """Passes repo path as cwd when reading git config."""
        calls = []

        def capturing_run(args, **kwargs):
            calls.append((args, kwargs))
            if args == ["git", "config", "--get", "user.name"]:
                return make_run_result(0, "Agent")
            if args == ["git", "config", "--get", "user.email"]:
                return make_run_result(0, "agent@example.com")
            if args == ["git", "diff", "--cached", "--quiet"]:
                return make_run_result(1)
            return make_run_result(0, "committed")

        with patch(
            "git_sidecar.tools.git_write.executor.run", side_effect=capturing_run
        ):
            git_write.git_commit("my-org/my-repo", "token", "msg")

        for _, kwargs in calls:
            assert kwargs["cwd"] == str(REPO_PATH)


class TestGitRestore:
    """Tests for git_restore."""

    def test_restore_files(self, mock_verify, mock_run):
        """Calls git restore with files."""
        git_write.git_restore("my-org/my-repo", "token", ["src/foo.py"])
        mock_run.assert_called_once_with(
            ["git", "restore", "--", "src/foo.py"], cwd=str(REPO_PATH)
        )

    def test_restore_staged(self, mock_verify, mock_run):
        """Includes --staged when staged=True."""
        git_write.git_restore("my-org/my-repo", "token", ["src/foo.py"], staged=True)
        mock_run.assert_called_once_with(
            ["git", "restore", "--staged", "--", "src/foo.py"], cwd=str(REPO_PATH)
        )

    def test_blocks_path_traversal(self, mock_verify):
        """Rejects .. in file paths."""
        with pytest.raises(ValidationError, match="traversal"):
            git_write.git_restore("my-org/my-repo", "token", ["../../secret"])


class TestGitStash:
    """Tests for git_stash."""

    def test_push(self, mock_verify, mock_run):
        """Default push action calls git stash push."""
        git_write.git_stash("my-org/my-repo", "token")
        mock_run.assert_called_once_with(["git", "stash", "push"], cwd=str(REPO_PATH))

    def test_push_with_message(self, mock_verify, mock_run):
        """Push with message adds -m flag."""
        git_write.git_stash("my-org/my-repo", "token", action="push", message="wip")
        mock_run.assert_called_once_with(
            ["git", "stash", "push", "-m", "wip"], cwd=str(REPO_PATH)
        )

    def test_pop(self, mock_verify, mock_run):
        """Pop action calls git stash pop."""
        git_write.git_stash("my-org/my-repo", "token", action="pop")
        mock_run.assert_called_once_with(["git", "stash", "pop"], cwd=str(REPO_PATH))

    def test_pop_with_index(self, mock_verify, mock_run):
        """Pop with index appends stash ref."""
        git_write.git_stash("my-org/my-repo", "token", action="pop", index=2)
        mock_run.assert_called_once_with(
            ["git", "stash", "pop", "stash@{2}"], cwd=str(REPO_PATH)
        )

    def test_drop(self, mock_verify, mock_run):
        """Drop action calls git stash drop."""
        git_write.git_stash("my-org/my-repo", "token", action="drop", index=0)
        mock_run.assert_called_once_with(
            ["git", "stash", "drop", "stash@{0}"], cwd=str(REPO_PATH)
        )

    def test_show(self, mock_verify, mock_run):
        """Show action is allowed."""
        git_write.git_stash("my-org/my-repo", "token", action="show")
        mock_run.assert_called_once_with(["git", "stash", "show"], cwd=str(REPO_PATH))

    def test_invalid_action(self, mock_verify):
        """Invalid action raises ValidationError."""
        with pytest.raises(ValidationError, match="Invalid stash action"):
            git_write.git_stash("my-org/my-repo", "token", action="delete")

    def test_all_valid_actions(self, mock_verify, mock_run):
        """All declared valid actions are accepted."""
        for action in git_write.ALLOWED_STASH_ACTIONS:
            git_write.git_stash("my-org/my-repo", "token", action=action)


class TestGitFetch:
    """Tests for git_fetch."""

    def test_fetch(self, mock_verify, mock_run):
        """Calls git fetch origin."""
        result = git_write.git_fetch("my-org/my-repo", "token")
        assert result["ok"] is True
        mock_run.assert_called_once_with(["git", "fetch", "origin"], cwd=str(REPO_PATH))


class TestGitPull:
    """Tests for git_pull."""

    def test_pull(self, mock_verify, mock_run):
        """Calls git pull."""
        result = git_write.git_pull("my-org/my-repo", "token")
        assert result["ok"] is True
        mock_run.assert_called_once_with(["git", "pull"], cwd=str(REPO_PATH))


class TestGitMerge:
    """Tests for git_merge."""

    def test_merge(self, mock_verify, mock_run):
        """Calls git merge with branch name."""
        git_write.git_merge("my-org/my-repo", "token", "task/feature")
        mock_run.assert_called_once_with(
            ["git", "merge", "task/feature"], cwd=str(REPO_PATH)
        )


class TestGitWorktree:
    """Tests for git_worktree."""

    def test_list(self, mock_verify, mock_run):
        """List action calls git worktree list."""
        git_write.git_worktree("my-org/my-repo", "token")
        mock_run.assert_called_once_with(
            ["git", "worktree", "list"], cwd=str(REPO_PATH)
        )

    def test_remove(self, mock_verify, mock_run):
        """Remove action calls git worktree remove with path."""
        wt_path = "/worktrees/my-wt"
        git_write.git_worktree("my-org/my-repo", "token", action="remove", path=wt_path)
        mock_run.assert_called_once_with(
            ["git", "worktree", "remove", wt_path], cwd=str(REPO_PATH)
        )

    def test_add_blocked(self, mock_verify):
        """Add action is blocked."""
        with pytest.raises(ValidationError, match="Adding worktrees is not permitted"):
            git_write.git_worktree("my-org/my-repo", "token", action="add")

    def test_invalid_action(self, mock_verify):
        """Arbitrary invalid action is blocked."""
        with pytest.raises(ValidationError, match="Invalid worktree action"):
            git_write.git_worktree("my-org/my-repo", "token", action="prune")


class TestGitCheckout:
    """Tests for git_checkout."""

    def test_checkout_main(self, mock_verify, mock_run):
        """Checking out main is allowed."""
        git_write.git_checkout("my-org/my-repo", "token", "main")
        mock_run.assert_called_once_with(
            ["git", "checkout", "main"], cwd=str(REPO_PATH)
        )

    def test_checkout_master(self, mock_verify, mock_run):
        """Checking out master is allowed."""
        git_write.git_checkout("my-org/my-repo", "token", "master")
        mock_run.assert_called_once_with(
            ["git", "checkout", "master"], cwd=str(REPO_PATH)
        )

    def test_checkout_valid_prefix(self, mock_verify, mock_run):
        """Checking out a branch with valid prefix is allowed."""
        git_write.git_checkout("my-org/my-repo", "token", "task/my-feature")
        mock_run.assert_called_once_with(
            ["git", "checkout", "task/my-feature"], cwd=str(REPO_PATH)
        )

    def test_checkout_invalid_prefix(self, mock_verify):
        """Checking out a branch with invalid prefix is blocked."""
        with pytest.raises(ValidationError):
            git_write.git_checkout("my-org/my-repo", "token", "release/1.0")

    def test_create_valid_branch(self, mock_verify, mock_run):
        """Creating a branch with valid prefix uses -b flag."""
        git_write.git_checkout("my-org/my-repo", "token", "task/new", create=True)
        mock_run.assert_called_once_with(
            ["git", "checkout", "-b", "task/new"], cwd=str(REPO_PATH)
        )

    def test_create_invalid_prefix(self, mock_verify):
        """Creating a branch with invalid prefix is blocked."""
        with pytest.raises(ValidationError):
            git_write.git_checkout(
                "my-org/my-repo", "token", "hotfix/urgent", create=True
            )


class TestGitPush:
    """Tests for git_push."""

    def test_push_valid_branch(self, mock_verify):
        """Pushes current branch to origin."""
        branch_result = make_run_result(0, "task/my-feature\n")
        push_result = make_run_result(0, "pushed")
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            side_effect=[branch_result, push_result],
        ) as mock_run:
            result = git_write.git_push("my-org/my-repo", "token")

        assert result["ok"] is True
        push_call = mock_run.call_args_list[-1]
        assert push_call.args[0] == ["git", "push", "-u", "origin", "task/my-feature"]

    def test_push_blocks_main(self, mock_verify):
        """Blocks push when current branch is main."""
        branch_result = make_run_result(0, "main\n")
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            return_value=branch_result,
        ):
            with pytest.raises(ValidationError, match="protected"):
                git_write.git_push("my-org/my-repo", "token")

    def test_push_blocks_master(self, mock_verify):
        """Blocks push when current branch is master."""
        branch_result = make_run_result(0, "master\n")
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            return_value=branch_result,
        ):
            with pytest.raises(ValidationError, match="protected"):
                git_write.git_push("my-org/my-repo", "token")

    def test_push_blocks_invalid_prefix(self, mock_verify):
        """Blocks push when branch doesn't match allowed prefixes."""
        branch_result = make_run_result(0, "release/1.0\n")
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            return_value=branch_result,
        ):
            with pytest.raises(ValidationError, match="does not match"):
                git_write.git_push("my-org/my-repo", "token")

    def test_push_no_force_flags(self, mock_verify):
        """git_push never passes force flags to executor."""
        branch_result = make_run_result(0, "task/safe\n")
        push_result = make_run_result(0, "pushed")
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            side_effect=[branch_result, push_result],
        ) as mock_run:
            git_write.git_push("my-org/my-repo", "token")

        push_call = mock_run.call_args_list[-1]
        push_args = push_call.args[0]
        assert "--force" not in push_args
        assert "-f" not in push_args
        assert "--force-with-lease" not in push_args

    def test_push_returns_error_if_rev_parse_fails(self, mock_verify):
        """Returns executor error if branch detection fails."""
        fail_result = make_run_result(128, "", "not a git repo")
        with patch(
            "git_sidecar.tools.git_write.executor.run",
            return_value=fail_result,
        ):
            result = git_write.git_push("my-org/my-repo", "token")

        assert result["ok"] is False
