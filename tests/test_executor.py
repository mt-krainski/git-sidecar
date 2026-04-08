"""Tests for git_sidecar.executor."""

from git_sidecar.executor import ExecResult, run


class TestExecResult:
    """Tests for ExecResult."""

    def test_ok_true(self):
        """Successful result."""
        r = ExecResult(returncode=0, stdout="out", stderr="")
        assert r.ok is True

    def test_ok_false(self):
        """Failed result."""
        r = ExecResult(returncode=1, stdout="", stderr="err")
        assert r.ok is False

    def test_to_dict(self):
        """Serialization includes all fields."""
        r = ExecResult(returncode=0, stdout="hello", stderr="warn")
        d = r.to_dict()
        assert d == {
            "ok": True,
            "returncode": 0,
            "stdout": "hello",
            "stderr": "warn",
        }


class TestRun:
    """Tests for run."""

    def test_simple_command(self):
        """Run echo and capture stdout."""
        result = run(["echo", "hello"])
        assert result.ok
        assert result.stdout.strip() == "hello"

    def test_failing_command(self):
        """Capture non-zero exit code."""
        result = run(["false"])
        assert not result.ok
        assert result.returncode != 0

    def test_cwd(self, tmp_path):
        """Working directory is respected."""
        result = run(["pwd"], cwd=str(tmp_path))
        assert result.ok
        assert tmp_path.name in result.stdout

    def test_timeout(self):
        """Timeout produces a clear error."""
        result = run(["sleep", "10"], timeout=1)
        assert not result.ok
        assert "timed out" in result.stderr

    def test_command_not_found(self):
        """Missing command produces a clear error."""
        result = run(["nonexistent-binary-xyz"])
        assert not result.ok
        assert "not found" in result.stderr

    def test_env_override(self):
        """Custom env vars are passed to the process."""
        result = run(["env"], env={"MY_TEST_VAR": "hello123"})
        assert result.ok
        assert "MY_TEST_VAR=hello123" in result.stdout

    def test_stderr_captured(self):
        """Stderr is captured separately."""
        result = run(["ls", "/nonexistent-path-xyz"])
        assert not result.ok
        assert result.stderr  # ls should complain
