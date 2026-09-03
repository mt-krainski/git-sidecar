"""Fixtures shared across the git-sidecar test suite."""

import contextlib
import os
import pathlib
import socket
import subprocess
import sys
import time

import pytest

# Seconds to wait for a freshly spawned server to accept a connection. Generous
# because a cold CI runner pays an interpreter start and an import of the whole
# SDK before it binds.
SERVER_START_TIMEOUT = 30.0

# Where each transport serves, using the SDK's default paths.
TRANSPORT_PATHS = {"sse": "/sse", "streamable-http": "/mcp"}

# The tool surface the deployment depends on, written out rather than imported
# from the server so that dropping a tool from the server's registration lists
# fails a test instead of quietly rewriting the contract.
ALL_TOOLS = frozenset(
    {
        "git_status",
        "git_diff",
        "git_log",
        "git_show",
        "git_branch",
        "git_rev_parse",
        "git_ls_files",
        "git_stash_list",
        "git_remote",
        "git_blame",
        "git_tag",
        "git_config_get",
        "git_add",
        "git_rm",
        "git_commit",
        "git_restore",
        "git_stash",
        "git_fetch",
        "git_pull",
        "git_merge",
        "git_worktree",
        "git_checkout",
        "git_push",
        "git_lfs_track",
        "git_lfs_untrack",
        "git_lfs_ls_files",
        "git_lfs_status",
        "git_lfs_fetch",
        "git_lfs_pull",
        "gh_pr_create",
        "gh_pr_edit",
        "gh_pr_view",
        "gh_pr_list",
        "gh_pr_fetch",
        "gh_pr_reply",
        "gh_pr_checks",
        "gh_pr_close",
        "gh_run_view",
        "gh_run_list",
    }
)


@pytest.fixture(scope="session")
def expected_tools() -> frozenset[str]:
    """The full set of tool names the sidecar must serve."""
    return ALL_TOOLS


def _free_port() -> int:
    """Reserve and release a loopback port, returning its number."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_port(port: int, process: subprocess.Popen, log: pathlib.Path) -> None:
    """Block until the server accepts a connection on port.

    Args:
        port: Loopback port the server was told to bind.
        process: The running server process.
        log: File collecting the server's stdout and stderr.

    Raises:
        RuntimeError: If the process exits before it binds.
        TimeoutError: If it neither binds nor exits within the timeout.
    """
    deadline = time.monotonic() + SERVER_START_TIMEOUT

    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"server exited with code {process.returncode} before binding "
                f"port {port}:\n{log.read_text()}"
            )
        with socket.socket() as sock:
            sock.settimeout(0.25)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)

    raise TimeoutError(
        f"server did not bind port {port} within {SERVER_START_TIMEOUT}s:\n"
        f"{log.read_text()}"
    )


@contextlib.contextmanager
def _running_sidecar(transport: str, projects_dir: pathlib.Path, log: pathlib.Path):
    """Run `python -m git_sidecar` and yield the URL its transport serves."""
    port = _free_port()
    env = {
        **os.environ,
        "PROJECTS_DIR": str(projects_dir),
        "SIDECAR_HOST": "127.0.0.1",
        "SIDECAR_PORT": str(port),
        "SIDECAR_TRANSPORT": transport,
    }

    # Output goes to a file, not a pipe: nothing reads the stream while the
    # test runs, and a full pipe buffer would wedge the server mid-test.
    with log.open("w") as sink:
        process = subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "git_sidecar"],
            env=env,
            stdout=sink,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_for_port(port, process, log)
            yield f"http://127.0.0.1:{port}{TRANSPORT_PATHS[transport]}"
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


@pytest.fixture()
def sidecar_server(tmp_path):
    """Return a factory that starts a sidecar and returns its served URL.

    The factory takes the transport name and, optionally, the projects
    directory to serve. Every server it starts is stopped when the test ends.
    """
    with contextlib.ExitStack() as stack:
        started = 0

        def start(transport: str = "sse", projects_dir: pathlib.Path | None = None):
            nonlocal started
            started += 1
            log = tmp_path / f"sidecar-{started}.log"
            return stack.enter_context(
                _running_sidecar(transport, projects_dir or tmp_path, log)
            )

        yield start
