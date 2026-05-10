# git-sidecar

> [!WARNING]
> **Work in progress — security is not guaranteed.** Effective isolation depends substantially on your individual host setup: Docker group membership, file ownership and umask, SSH key permissions, and which user accounts can `docker exec` into the running container all materially change what a compromised agent can reach. The design is meant to be hardenable (rootless Docker, dedicated unprivileged user, no Docker socket access for the agent), but that polish isn't here yet. Don't point this at credentials you can't afford to lose.

A containerized MCP server that provides secure, credential-isolated Git and GitHub operations for AI agents running in sandboxed environments.

The sidecar holds SSH keys and GitHub credentials; the agent never sees them. Communication happens via MCP tools over SSE, with each operation scoped to a specific repository and authorized via a shared secret token file.

## Quick start

Build the image, aligning the in-container user with the host user/group that owns the projects directory. This makes files written by the sidecar land on the host with the expected ownership:

```bash
docker build \
  --build-arg UID=$(id -u <agent-user>) \
  --build-arg GID=$(getent group <shared-group> | cut -d: -f3) \
  -t git-sidecar .
```

Run, publishing the SSE endpoint to host loopback so a host-side MCP client can reach it. SSH keys and `gh` credentials live in named volumes so they survive container restarts and stay isolated from host user keys:

```bash
docker run -d \
  --name git-sidecar \
  --restart unless-stopped \
  -p 127.0.0.1:8900:8900 \
  -v /home/<agent-user>/Projects:/projects \
  -v ~/.gitconfig:/home/sidecar/.gitconfig:ro \
  -v sidecar-ssh:/home/sidecar/.ssh \
  -v gh-config:/home/sidecar/.config/gh \
  -e ALLOWED_BRANCH_PREFIXES=task/,dependabot/ \
  git-sidecar
```

The MCP client connects to `http://127.0.0.1:8900/sse`.

If the MCP client also runs in a container, replace `-p 127.0.0.1:8900:8900` with a shared bridge network (`docker network create git-sidecar-net` once, then `--network git-sidecar-net` on both containers).

### First-run setup

Authenticate `gh` once — choose SSH as the protocol and let it generate and upload a dedicated SSH key for you. The key lands in `~/.ssh/` and gh credentials in `~/.config/gh/`, both held by named volumes so they survive restarts:

```bash
docker exec -it git-sidecar gh auth login
```

GitHub host keys are pre-baked into `/etc/ssh/ssh_known_hosts` at image build, so `git fetch`/`push` won't prompt or fail on first use.

## Authentication

Each project that an agent should access needs a `.git-sidecar-token` file in its root directory. The agent must be able to read it — either generate the token as the agent user, or adjust file permissions afterwards so the agent has read access.

Generate with the included CLI tool:

```bash
uv tool install .
git-sidecar-token ~/Projects/my-repo
```

The agent provides this token with every tool call. The sidecar verifies it using timing-safe comparison before executing any operation.

## MCP tools

32 tools across three categories:

**Git read** (12): `git_status`, `git_diff`, `git_log`, `git_show`, `git_branch`, `git_rev_parse`, `git_ls_files`, `git_stash_list`, `git_remote`, `git_blame`, `git_tag`, `git_config_get`

**Git write** (11): `git_add`, `git_rm`, `git_commit`, `git_restore`, `git_stash`, `git_fetch`, `git_pull`, `git_merge`, `git_worktree`, `git_checkout`, `git_push`

**GitHub** (9): `gh_pr_create`, `gh_pr_view`, `gh_pr_list`, `gh_pr_fetch`, `gh_pr_reply`, `gh_pr_checks`, `gh_pr_close`, `gh_run_view`, `gh_run_list`

## Configuration

All configuration is via environment variables:

| Variable                  | Default              | Description                                            |
| ------------------------- | -------------------- | ------------------------------------------------------ |
| `PROJECTS_DIR`            | `/projects`          | Mount point for project directories                    |
| `SIDECAR_HOST`            | `0.0.0.0`            | Server bind address                                    |
| `SIDECAR_PORT`            | `8900`               | Server port                                            |
| `ALLOWED_BRANCH_PREFIXES` | `task/,dependabot/`  | Comma-separated branch prefixes agents can create/push |
| `SIDECAR_TOKEN_FILENAME`  | `.git-sidecar-token` | Name of the per-project token file                     |

## Volume mounts

| Mount                                      | Purpose                                                         |
| ------------------------------------------ | --------------------------------------------------------------- |
| `~/Projects:/projects`                     | Project directories the agent can access                        |
| `~/.gitconfig:/home/sidecar/.gitconfig:ro` | Git user config (name, email, SSH command) — read from host     |
| `sidecar-ssh:/home/sidecar/.ssh`           | Dedicated SSH key + known_hosts, generated and held by sidecar  |
| `gh-config:/home/sidecar/.config/gh`       | Persistent GitHub CLI credentials                               |

Adjust the projects directory to match your setup.

## Security model

- Agent runs in an untrusted container without any credentials
- All Git/GitHub operations are proxied through the sidecar
- No `shell=True` anywhere — all subprocess calls use argument lists
- Protected branches (main/master) cannot be pushed to
- Force-push flags are rejected
- Path traversal is blocked at multiple layers
- Branch names must match configured prefixes

## Development

```bash
./scripts/configure.sh  # install dependencies and pre-commit hooks
uv run pytest            # run tests
uv run ruff check .      # lint
```
