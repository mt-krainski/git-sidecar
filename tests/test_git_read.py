"""Tests for git_sidecar.tools.git_read."""

import pathlib
from unittest.mock import patch

import pytest

from git_sidecar.config import SidecarConfig
from git_sidecar.executor import ExecResult
from git_sidecar.tools import git_read
from git_sidecar.validation import ValidationError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def config(tmp_path):
    """SidecarConfig pointing at a temp projects directory."""
    return SidecarConfig(projects_dir=str(tmp_path))


@pytest.fixture(autouse=True)
def init_module(config):
    """Initialize the git_read module before each test."""
    git_read.init(config)


@pytest.fixture()
def repo_path(tmp_path):
    """Create a fake repository directory and write a token file."""
    repo = tmp_path / "my-org" / "my-repo"
    repo.mkdir(parents=True)
    (repo / ".git-sidecar-token").write_text("test-token")
    return repo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GOOD_RESULT = ExecResult(returncode=0, stdout="output", stderr="")
REPO = "my-org/my-repo"
TOKEN = "test-token"


def _mock_verify(repo_path: pathlib.Path):
    """Return a patcher that makes verify_token return repo_path."""
    return patch(
        "git_sidecar.tools.git_read.verify_token",
        return_value=repo_path,
    )


def _mock_run(result: ExecResult = GOOD_RESULT):
    """Return a patcher that makes executor.run return result."""
    return patch("git_sidecar.tools.git_read.executor.run", return_value=result)


# ---------------------------------------------------------------------------
# git_status
# ---------------------------------------------------------------------------


class TestGitStatus:
    """Tests for git_status."""

    def test_calls_git_status(self, repo_path):
        """Correct git command is issued."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            result = git_read.git_status(REPO, TOKEN)

        mock_run.assert_called_once_with(["git", "status"], cwd=str(repo_path))
        assert result == GOOD_RESULT.to_dict()

    def test_auth_called(self, repo_path):
        """verify_token is called with config, repo, and token."""
        with _mock_verify(repo_path) as mock_verify, _mock_run():
            git_read.git_status(REPO, TOKEN)

        mock_verify.assert_called_once_with(git_read._config, REPO, TOKEN)


# ---------------------------------------------------------------------------
# git_diff
# ---------------------------------------------------------------------------


class TestGitDiff:
    """Tests for git_diff."""

    def test_plain_diff(self, repo_path):
        """Plain diff with no options."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_diff(REPO, TOKEN)

        mock_run.assert_called_once_with(["git", "diff"], cwd=str(repo_path))

    def test_staged_diff(self, repo_path):
        """Staged diff includes --cached."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_diff(REPO, TOKEN, staged=True)

        args = mock_run.call_args[0][0]
        assert "--cached" in args

    def test_diff_with_ref(self, repo_path):
        """Ref is appended to args."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_diff(REPO, TOKEN, ref="HEAD~1")

        args = mock_run.call_args[0][0]
        assert "HEAD~1" in args

    def test_diff_with_files(self, repo_path):
        """Files are appended after separator."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_diff(REPO, TOKEN, files=["src/main.py"])

        args = mock_run.call_args[0][0]
        assert "--" in args
        assert "src/main.py" in args

    def test_path_traversal_in_files_rejected(self, repo_path):
        """Path traversal in files list raises ValidationError."""
        with _mock_verify(repo_path), _mock_run():
            with pytest.raises(ValidationError, match="traversal"):
                git_read.git_diff(REPO, TOKEN, files=["../secret"])


# ---------------------------------------------------------------------------
# git_log
# ---------------------------------------------------------------------------


class TestGitLog:
    """Tests for git_log."""

    def test_default_log(self, repo_path):
        """Default log uses --max-count=20."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_log(REPO, TOKEN)

        args = mock_run.call_args[0][0]
        assert "--max-count=20" in args

    def test_custom_max_count(self, repo_path):
        """Custom max_count is applied."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_log(REPO, TOKEN, max_count=5)

        args = mock_run.call_args[0][0]
        assert "--max-count=5" in args

    def test_oneline(self, repo_path):
        """oneline=True adds --oneline flag."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_log(REPO, TOKEN, oneline=True)

        args = mock_run.call_args[0][0]
        assert "--oneline" in args

    def test_log_with_ref(self, repo_path):
        """Ref is appended when provided."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_log(REPO, TOKEN, ref="main")

        args = mock_run.call_args[0][0]
        assert "main" in args


# ---------------------------------------------------------------------------
# git_show
# ---------------------------------------------------------------------------


class TestGitShow:
    """Tests for git_show."""

    def test_default_ref(self, repo_path):
        """Default ref is HEAD."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_show(REPO, TOKEN)

        args = mock_run.call_args[0][0]
        assert args == ["git", "show", "HEAD"]

    def test_custom_ref(self, repo_path):
        """Custom ref is passed through."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_show(REPO, TOKEN, ref="abc1234")

        args = mock_run.call_args[0][0]
        assert "abc1234" in args


# ---------------------------------------------------------------------------
# git_branch
# ---------------------------------------------------------------------------


class TestGitBranch:
    """Tests for git_branch."""

    def test_local_branches(self, repo_path):
        """Without all=True, --all is not included."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_branch(REPO, TOKEN)

        args = mock_run.call_args[0][0]
        assert "--all" not in args

    def test_all_branches(self, repo_path):
        """all=True includes --all flag."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_branch(REPO, TOKEN, all=True)

        args = mock_run.call_args[0][0]
        assert "--all" in args


# ---------------------------------------------------------------------------
# git_rev_parse
# ---------------------------------------------------------------------------


class TestGitRevParse:
    """Tests for git_rev_parse."""

    def test_default_head(self, repo_path):
        """Default ref resolves HEAD."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_rev_parse(REPO, TOKEN)

        args = mock_run.call_args[0][0]
        assert args == ["git", "rev-parse", "HEAD"]

    def test_custom_ref(self, repo_path):
        """Custom ref is passed through."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_rev_parse(REPO, TOKEN, ref="main")

        args = mock_run.call_args[0][0]
        assert "main" in args


# ---------------------------------------------------------------------------
# git_ls_files
# ---------------------------------------------------------------------------


class TestGitLsFiles:
    """Tests for git_ls_files."""

    def test_ls_files(self, repo_path):
        """Correct command is issued."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_ls_files(REPO, TOKEN)

        mock_run.assert_called_once_with(["git", "ls-files"], cwd=str(repo_path))


# ---------------------------------------------------------------------------
# git_stash_list
# ---------------------------------------------------------------------------


class TestGitStashList:
    """Tests for git_stash_list."""

    def test_stash_list(self, repo_path):
        """Correct command is issued."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_stash_list(REPO, TOKEN)

        mock_run.assert_called_once_with(["git", "stash", "list"], cwd=str(repo_path))


# ---------------------------------------------------------------------------
# git_remote
# ---------------------------------------------------------------------------


class TestGitRemote:
    """Tests for git_remote."""

    def test_remote_verbose(self, repo_path):
        """Uses -v flag for URL output."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_remote(REPO, TOKEN)

        mock_run.assert_called_once_with(["git", "remote", "-v"], cwd=str(repo_path))


# ---------------------------------------------------------------------------
# git_blame
# ---------------------------------------------------------------------------


class TestGitBlame:
    """Tests for git_blame."""

    def test_blame_file(self, repo_path):
        """Correct command with the file argument."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_blame(REPO, TOKEN, file="src/main.py")

        mock_run.assert_called_once_with(
            ["git", "blame", "src/main.py"], cwd=str(repo_path)
        )

    def test_path_traversal_rejected(self, repo_path):
        """Path traversal in file raises ValidationError before auth."""
        with _mock_verify(repo_path), _mock_run():
            with pytest.raises(ValidationError, match="traversal"):
                git_read.git_blame(REPO, TOKEN, file="../etc/passwd")

    def test_validation_before_auth(self):
        """File validation happens before verify_token is called."""
        with (
            patch("git_sidecar.tools.git_read.verify_token") as mock_verify,
            _mock_run(),
        ):
            with pytest.raises(ValidationError):
                git_read.git_blame(REPO, TOKEN, file="../escape")

            mock_verify.assert_not_called()


# ---------------------------------------------------------------------------
# git_tag
# ---------------------------------------------------------------------------


class TestGitTag:
    """Tests for git_tag."""

    def test_tag_list(self, repo_path):
        """Correct command is issued."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_tag(REPO, TOKEN)

        mock_run.assert_called_once_with(["git", "tag"], cwd=str(repo_path))


# ---------------------------------------------------------------------------
# git_config_get
# ---------------------------------------------------------------------------


class TestGitConfigGet:
    """Tests for git_config_get."""

    def test_config_get(self, repo_path):
        """Correct command with key argument."""
        with _mock_verify(repo_path), _mock_run() as mock_run:
            git_read.git_config_get(REPO, TOKEN, key="user.email")

        mock_run.assert_called_once_with(
            ["git", "config", "--get", "user.email"], cwd=str(repo_path)
        )


# ---------------------------------------------------------------------------
# Init / config wiring
# ---------------------------------------------------------------------------


class TestInit:
    """Tests for module-level init."""

    def test_init_sets_config(self):
        """init() stores config for subsequent calls."""
        cfg = SidecarConfig(projects_dir="/tmp")  # noqa: S108
        git_read.init(cfg)
        assert git_read._config is cfg

    def test_uninitialised_raises(self):
        """Calling a tool before init raises RuntimeError."""
        original = git_read._config
        git_read._config = None
        try:
            with pytest.raises(RuntimeError, match="not initialized"):
                git_read.git_status("repo", "token")
        finally:
            git_read._config = original
