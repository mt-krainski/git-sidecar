"""Tests for git_sidecar.tools.git_lfs."""

import pathlib
from unittest.mock import patch

import pytest

from git_sidecar.config import SidecarConfig
from git_sidecar.executor import ExecResult
from git_sidecar.tools import git_lfs
from git_sidecar.validation import ValidationError

CONFIG = SidecarConfig(
    projects_dir="/projects",
    allowed_branch_prefixes=["task/", "feat/"],
)

REPO_PATH = pathlib.Path("/projects/my-org/my-repo")

OK_RESULT = ExecResult(returncode=0, stdout="ok", stderr="")


@pytest.fixture(autouse=True)
def setup_config():
    """Initialize git_lfs with test config before each test."""
    git_lfs.init(CONFIG)


@pytest.fixture()
def mock_verify():
    """Patch auth.verify_token to return REPO_PATH."""
    with patch(
        "git_sidecar.tools.git_lfs.auth.verify_token", return_value=REPO_PATH
    ) as m:
        yield m


@pytest.fixture()
def mock_run():
    """Patch executor.run to return OK_RESULT by default."""
    with patch("git_sidecar.tools.git_lfs.executor.run", return_value=OK_RESULT) as m:
        yield m


class TestGitLfsTrack:
    """Tests for git_lfs_track."""

    def test_tracks_patterns(self, mock_verify, mock_run):
        """Calls git lfs track with patterns."""
        result = git_lfs.git_lfs_track("my-org/my-repo", "token", ["*.psd", "*.bin"])
        assert result["ok"] is True
        mock_run.assert_called_once_with(
            ["git", "lfs", "track", "--", "*.psd", "*.bin"], cwd=str(REPO_PATH)
        )

    def test_blocks_path_traversal(self, mock_verify):
        """Rejects .. in patterns."""
        with pytest.raises(ValidationError, match="traversal"):
            git_lfs.git_lfs_track("my-org/my-repo", "token", ["../outside/*.bin"])


class TestGitLfsUntrack:
    """Tests for git_lfs_untrack."""

    def test_untracks_patterns(self, mock_verify, mock_run):
        """Calls git lfs untrack with patterns."""
        result = git_lfs.git_lfs_untrack("my-org/my-repo", "token", ["*.psd"])
        assert result["ok"] is True
        mock_run.assert_called_once_with(
            ["git", "lfs", "untrack", "--", "*.psd"], cwd=str(REPO_PATH)
        )

    def test_blocks_path_traversal(self, mock_verify):
        """Rejects .. in patterns."""
        with pytest.raises(ValidationError, match="traversal"):
            git_lfs.git_lfs_untrack("my-org/my-repo", "token", ["../*.bin"])


class TestGitLfsLsFiles:
    """Tests for git_lfs_ls_files."""

    def test_lists_files(self, mock_verify, mock_run):
        """Calls git lfs ls-files."""
        result = git_lfs.git_lfs_ls_files("my-org/my-repo", "token")
        assert result["ok"] is True
        mock_run.assert_called_once_with(["git", "lfs", "ls-files"], cwd=str(REPO_PATH))


class TestGitLfsStatus:
    """Tests for git_lfs_status."""

    def test_shows_status(self, mock_verify, mock_run):
        """Calls git lfs status."""
        result = git_lfs.git_lfs_status("my-org/my-repo", "token")
        assert result["ok"] is True
        mock_run.assert_called_once_with(["git", "lfs", "status"], cwd=str(REPO_PATH))


class TestGitLfsFetch:
    """Tests for git_lfs_fetch."""

    def test_fetches_with_long_timeout(self, mock_verify, mock_run):
        """Calls git lfs fetch origin with the LFS transfer timeout."""
        result = git_lfs.git_lfs_fetch("my-org/my-repo", "token")
        assert result["ok"] is True
        mock_run.assert_called_once_with(
            ["git", "lfs", "fetch", "origin"],
            cwd=str(REPO_PATH),
            timeout=git_lfs.LFS_TIMEOUT,
        )


class TestGitLfsPull:
    """Tests for git_lfs_pull."""

    def test_pulls_with_long_timeout(self, mock_verify, mock_run):
        """Calls git lfs pull origin with the LFS transfer timeout."""
        result = git_lfs.git_lfs_pull("my-org/my-repo", "token")
        assert result["ok"] is True
        mock_run.assert_called_once_with(
            ["git", "lfs", "pull", "origin"],
            cwd=str(REPO_PATH),
            timeout=git_lfs.LFS_TIMEOUT,
        )
