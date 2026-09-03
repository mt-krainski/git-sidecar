"""End-to-end tests: the server boots and serves its tools over a transport.

These run `python -m git_sidecar` as a subprocess and drive it with a real MCP
client. The rest of the suite calls the tool functions directly, so it stays
green even when the server cannot start at all — which is how an SDK upgrade
that removed the server API this package imports reached a deployment.
"""

import asyncio
import json
import os
import subprocess

import pytest
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

TRANSPORTS = ["sse", "streamable-http"]

# Set by CI to the URL of a sidecar running in its built container, which is
# the artifact the deployment actually runs.
CONTAINER_URL = os.environ.get("SIDECAR_CONTAINER_URL")

REPO = "my-org/my-repo"
TOKEN = "test-token"


def _client(url: str, transport: str):
    """Open the client transport that matches the server's."""
    if transport == "sse":
        return sse_client(url)
    return streamable_http_client(url)


async def _session_tools(url: str, transport: str) -> set[str]:
    """Complete a handshake and return the tool names the server advertises."""
    async with _client(url, transport) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return {tool.name for tool in result.tools}


async def _session_call(url: str, transport: str, name: str, arguments: dict):
    """Complete a handshake and call one tool."""
    async with _client(url, transport) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(name, arguments)


@pytest.fixture()
def repo(tmp_path):
    """A real git repository under the projects directory, with a token file."""
    path = tmp_path / "my-org" / "my-repo"
    path.mkdir(parents=True)
    (path / ".git-sidecar-token").write_text(TOKEN)
    subprocess.run(  # noqa: S603
        ["git", "init", "--initial-branch=main", str(path)],  # noqa: S607
        check=True,
        capture_output=True,
    )
    return path


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_server_serves_every_tool(transport, sidecar_server, expected_tools):
    """A server started over each supported transport advertises every tool."""
    url = sidecar_server(transport)

    assert asyncio.run(_session_tools(url, transport)) == set(expected_tools)


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_server_runs_a_tool_over_the_transport(
    transport, sidecar_server, repo, tmp_path
):
    """A tool call round-trips over each transport and reaches real git."""
    url = sidecar_server(transport, tmp_path)

    result = asyncio.run(
        _session_call(url, transport, "git_status", {"repo": REPO, "token": TOKEN})
    )

    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["ok"] is True
    assert "On branch main" in payload["stdout"]


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_server_rejects_a_bad_token_over_the_transport(
    transport, sidecar_server, repo, tmp_path
):
    """Authorization still holds when the call arrives over the wire."""
    url = sidecar_server(transport, tmp_path)

    result = asyncio.run(
        _session_call(url, transport, "git_status", {"repo": REPO, "token": "wrong"})
    )

    assert result.is_error is True
    assert "Token mismatch" in result.content[0].text


@pytest.mark.skipif(
    not CONTAINER_URL, reason="SIDECAR_CONTAINER_URL is unset; no container to test"
)
def test_container_serves_every_tool(expected_tools):
    """The built image serves the full tool surface over its default transport."""
    assert asyncio.run(_session_tools(CONTAINER_URL, "sse")) == set(expected_tools)


@pytest.mark.skipif(
    not CONTAINER_URL, reason="SIDECAR_CONTAINER_URL is unset; no container to test"
)
def test_container_runs_a_tool():
    """The image carries the git the tools shell out to, and can reach a repo.

    The container serves a repository mounted at its projects directory, so this
    covers what an in-process test cannot: the binaries the image installs and
    the dependency set the image resolves for itself.
    """
    result = asyncio.run(
        _session_call(
            CONTAINER_URL, "sse", "git_status", {"repo": REPO, "token": TOKEN}
        )
    )

    assert result.is_error is False
    assert json.loads(result.content[0].text)["ok"] is True
