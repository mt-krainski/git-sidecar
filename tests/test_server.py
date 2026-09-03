"""Tests for git_sidecar.server."""

import asyncio

import pytest

from git_sidecar.config import SidecarConfig
from git_sidecar.server import create_server


@pytest.fixture()
def config(tmp_path):
    """SidecarConfig pointing at a temp projects directory."""
    return SidecarConfig(projects_dir=str(tmp_path))


def _registered_tools(server):
    """Every tool registered with the server."""
    return asyncio.run(server.list_tools())


def test_create_server_registers_every_tool(config, expected_tools):
    """Every declared tool reaches the server, and nothing else does."""
    server = create_server(config)

    names = {tool.name for tool in _registered_tools(server)}

    assert names == set(expected_tools)


def test_create_server_reads_config_from_env_when_omitted(
    monkeypatch, tmp_path, expected_tools
):
    """A server built without a config takes one from the environment."""
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))

    server = create_server()

    assert {tool.name for tool in _registered_tools(server)} == set(expected_tools)


def test_registered_tools_take_repo_and_token(config):
    """Every tool takes the repo and token arguments the deployment sends."""
    server = create_server(config)

    for tool in _registered_tools(server):
        required = set(tool.input_schema.get("required", []))
        assert {"repo", "token"} <= required, tool.name
