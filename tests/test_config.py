"""Tests for git_sidecar.config."""

import pytest

from git_sidecar.config import (
    SUPPORTED_TRANSPORTS,
    ConfigError,
    SidecarConfig,
    _parse_prefixes,
    _parse_transport,
)


class TestParsePrefixes:
    """Tests for _parse_prefixes."""

    def test_basic(self):
        """Parse comma-separated values."""
        assert _parse_prefixes("task/,dependabot/") == ["task/", "dependabot/"]

    def test_whitespace(self):
        """Strip whitespace around prefixes."""
        assert _parse_prefixes(" task/ , dep/ ") == ["task/", "dep/"]

    def test_empty_segments(self):
        """Skip empty segments from trailing commas."""
        assert _parse_prefixes("task/,,dep/,") == ["task/", "dep/"]

    def test_single(self):
        """Single prefix without comma."""
        assert _parse_prefixes("feat/") == ["feat/"]

    def test_empty_string(self):
        """Empty string returns empty list."""
        assert _parse_prefixes("") == []


class TestParseTransport:
    """Tests for _parse_transport."""

    @pytest.mark.parametrize("transport", SUPPORTED_TRANSPORTS)
    def test_supported(self, transport):
        """Every supported transport passes through unchanged."""
        assert _parse_transport(transport) == transport

    def test_whitespace(self):
        """Strip whitespace around the transport name."""
        assert _parse_transport("  sse  ") == "sse"

    def test_unsupported(self):
        """An unknown transport is rejected, and the message names it."""
        with pytest.raises(ConfigError) as excinfo:
            _parse_transport("carrier-pigeon")

        assert "carrier-pigeon" in str(excinfo.value)
        assert "sse" in str(excinfo.value)

    def test_stdio_is_not_served(self):
        """The SDK also offers stdio, which the sidecar deliberately does not serve."""
        with pytest.raises(ConfigError):
            _parse_transport("stdio")

    def test_empty(self):
        """An empty value is rejected rather than silently defaulted."""
        with pytest.raises(ConfigError):
            _parse_transport("")


class TestSidecarConfig:
    """Tests for SidecarConfig."""

    def test_defaults(self):
        """Default values are sensible."""
        cfg = SidecarConfig()
        assert cfg.projects_dir == "/projects"
        assert cfg.allowed_branch_prefixes == ["task/", "dependabot/"]
        assert cfg.token_filename == ".git-sidecar-token"
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 8900
        assert cfg.transport == "sse"

    def test_from_env(self, monkeypatch):
        """Load config from environment variables."""
        monkeypatch.setenv("PROJECTS_DIR", "/data/repos")
        monkeypatch.setenv("ALLOWED_BRANCH_PREFIXES", "feat/,fix/,kan-")
        monkeypatch.setenv("SIDECAR_TOKEN_FILENAME", ".my-token")
        monkeypatch.setenv("SIDECAR_HOST", "127.0.0.1")
        monkeypatch.setenv("SIDECAR_PORT", "9000")
        monkeypatch.setenv("SIDECAR_TRANSPORT", "streamable-http")

        cfg = SidecarConfig.from_env()

        assert cfg.projects_dir == "/data/repos"
        assert cfg.allowed_branch_prefixes == ["feat/", "fix/", "kan-"]
        assert cfg.token_filename == ".my-token"
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 9000
        assert cfg.transport == "streamable-http"

    def test_from_env_defaults(self, monkeypatch):
        """Unset env vars fall back to defaults."""
        for key in [
            "PROJECTS_DIR",
            "ALLOWED_BRANCH_PREFIXES",
            "SIDECAR_TOKEN_FILENAME",
            "SIDECAR_HOST",
            "SIDECAR_PORT",
            "SIDECAR_TRANSPORT",
        ]:
            monkeypatch.delenv(key, raising=False)

        cfg = SidecarConfig.from_env()
        default = SidecarConfig()

        assert cfg.projects_dir == default.projects_dir
        assert cfg.allowed_branch_prefixes == default.allowed_branch_prefixes
        assert cfg.token_filename == default.token_filename
        assert cfg.transport == default.transport

    def test_from_env_rejects_an_unsupported_transport(self, monkeypatch):
        """A bad SIDECAR_TRANSPORT stops the server at startup, not mid-serve."""
        monkeypatch.setenv("SIDECAR_TRANSPORT", "websocket")

        with pytest.raises(ConfigError):
            SidecarConfig.from_env()

    def test_frozen(self):
        """Config is immutable."""
        cfg = SidecarConfig()
        try:
            cfg.port = 1234  # type: ignore[misc]
            raise AssertionError("Should have raised")
        except AttributeError:
            pass
