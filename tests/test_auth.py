"""Tests for git_sidecar.auth."""

import pytest

from git_sidecar.auth import AuthError, resolve_repo_path, verify_token
from git_sidecar.config import SidecarConfig


@pytest.fixture()
def projects_dir(tmp_path):
    """Create a temporary projects directory with a sample repo."""
    repo = tmp_path / "my-org" / "my-repo"
    repo.mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def config(projects_dir):
    """Config pointing at the temp projects dir."""
    return SidecarConfig(projects_dir=str(projects_dir))


class TestResolveRepoPath:
    """Tests for resolve_repo_path."""

    def test_valid_repo(self, config, projects_dir):
        """Resolve a valid repo path."""
        result = resolve_repo_path(config, "my-org/my-repo")
        assert result == (projects_dir / "my-org" / "my-repo").resolve()

    def test_path_traversal_blocked(self, config):
        """Block ../ escape attempts."""
        with pytest.raises(AuthError, match="escapes"):
            resolve_repo_path(config, "../../etc")

    def test_nonexistent_repo(self, config):
        """Reject repos that don't exist on disk."""
        with pytest.raises(AuthError, match="not found"):
            resolve_repo_path(config, "no-such/repo")


class TestVerifyToken:
    """Tests for verify_token."""

    def test_valid_token(self, config, projects_dir):
        """Matching tokens pass verification."""
        repo = projects_dir / "my-org" / "my-repo"
        (repo / ".git-sidecar-token").write_text("secret-abc-123\n")

        result = verify_token(config, "my-org/my-repo", "secret-abc-123")
        assert result == repo.resolve()

    def test_whitespace_stripped(self, config, projects_dir):
        """Tokens are stripped before comparison."""
        repo = projects_dir / "my-org" / "my-repo"
        (repo / ".git-sidecar-token").write_text("  secret  \n")

        result = verify_token(config, "my-org/my-repo", "secret")
        assert result == repo.resolve()

    def test_wrong_token(self, config, projects_dir):
        """Mismatched tokens are rejected."""
        repo = projects_dir / "my-org" / "my-repo"
        (repo / ".git-sidecar-token").write_text("real-token")

        with pytest.raises(AuthError, match="mismatch"):
            verify_token(config, "my-org/my-repo", "wrong-token")

    def test_missing_token_file(self, config):
        """Reject if token file doesn't exist."""
        with pytest.raises(AuthError, match="Token file not found"):
            verify_token(config, "my-org/my-repo", "anything")

    def test_empty_token_file(self, config, projects_dir):
        """Reject if token file is empty."""
        repo = projects_dir / "my-org" / "my-repo"
        (repo / ".git-sidecar-token").write_text("   \n")

        with pytest.raises(AuthError, match="empty"):
            verify_token(config, "my-org/my-repo", "anything")
