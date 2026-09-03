# Deployment runbook: one sidecar per agent

A worked example of running git-sidecar with **one container per agent user**, each built and
run with that agent's own uid and gid, and each mounting the agent's `Projects` tree at its own
host path.

The alternative — one shared container serving several agents through group membership — is
[the shared-sidecar runbook](shared-sidecar-isolated-agents.md). Choose per-agent when you want
each agent to hold its own code-host identity, or when agents use git worktrees. Choose shared
when one credential set for all agents is acceptable and you would rather run one container.

Treat this as a worked example, not a prescription or a guarantee.

## What this arrangement buys

**Credential isolation.** Each agent gets its own `gh` and SSH volumes, so one agent's identity
is not another's, and a compromised agent reaches only its own.

**No group or ACL machinery.** The shared arrangement exists to bridge a uid gap: the container
runs as a service uid, the agent owns the files, and the two are joined by a shared group,
setgid directories and a `umask`. Matching the uids removes the gap, so none of that is needed.
The agent's `Projects` tree stays a plain, agent-owned directory.

Nothing needs doing about `safe.directory` either. The image sets it for `/projects/*`, which
this arrangement never mounts, so the setting is simply inert — git's ownership check does not
trip when the uids match. If you arrive here from the shared runbook's aligned-mount remedy,
which tells you to widen that glob, that step does not apply.

**Worktrees work.** git records absolute paths in both of a worktree's pointer files, so a
repository reached at two different absolute paths works for one user and not the other. Mounting
the tree at its own host path means there is only one path, and the question does not arise. See
the worktree section of the shared runbook for what goes wrong otherwise.

## Prerequisites

- An unprivileged agent user with a private home and a `Projects` directory. Part 1 **step 1** of
  the shared runbook provisions the user; a plain `mkdir ~/Projects` as that user is enough here.
  **Skip its step 2** — the setgid mode and default ACLs it applies exist so a separate service
  uid can write into the tree, which is the thing this arrangement removes.
- A git identity for the agent. `/home/$AGENT/.gitconfig` must exist, carrying `user.name` and
  `user.email`, **before** the container starts: if that path is absent, Docker creates a
  root-owned directory there and every commit fails.
- The administrator's rootful Docker daemon. The sidecar runs from the administrator's account so
  its credentials stay outside the agent's reach; the agent is not in the `docker` group and
  cannot `docker exec` into it.
- One free loopback port per agent.

## 1. Build an image for the agent

The image creates its in-container user from build arguments and chowns `/app` and the credential
directories to it, so the uid is baked at build time. Build one image per agent.

```bash
AGENT=agent-01

sudo docker build \
  --build-arg UID="$(id -u "$AGENT")" \
  --build-arg GID="$(id -g "$AGENT")" \
  -t "git-sidecar:$AGENT" /path/to/git-sidecar
```

Expected: `docker images` lists `git-sidecar:$AGENT`.

> Do not substitute `--user` at run time against an image built for a different uid: it would run
> as a uid owning neither `/app` nor the credential directories. `gh` and SSH write their files
> `0600`, and the virtualenv under `/app` has to be writable.

## 2. Start the container on its own port

The container always listens on 8900; give each agent a distinct **host** port.

```bash
AGENT=agent-01
PORT=8900          # 8901, 8902, … for each further agent

sudo docker rm -f "git-sidecar-$AGENT" 2>/dev/null
sudo docker run -d --name "git-sidecar-$AGENT" --restart unless-stopped \
  -p "127.0.0.1:$PORT:8900" \
  -v "/home/$AGENT/Projects:/home/$AGENT/Projects" \
  -e PROJECTS_DIR="/home/$AGENT/Projects" \
  -v "/home/$AGENT/.gitconfig:/home/sidecar/.gitconfig:ro" \
  -v "sidecar-ssh-$AGENT:/home/sidecar/.ssh" \
  -v "gh-config-$AGENT:/home/sidecar/.config/gh" \
  -e ALLOWED_BRANCH_PREFIXES=task/,dependabot/ \
  -e GIT_CONFIG_COUNT=1 \
  -e GIT_CONFIG_KEY_0=core.hooksPath \
  -e GIT_CONFIG_VALUE_0=/dev/null \
  "git-sidecar:$AGENT"
```

Expected: the container is running and `curl -fsS "http://127.0.0.1:$PORT/sse" -m 1` answers.

The mount and `PROJECTS_DIR` must name the same path. That is what makes worktrees work, and it
sets how repositories are addressed: a `repo` argument is the path from `PROJECTS_DIR` down, so
with the mount above, `my-repo` addresses `/home/$AGENT/Projects/my-repo`.

Mounting the agent's own `.gitconfig` keeps commit authorship correct per agent.

The `GIT_CONFIG_*` entries disable git hooks for every git invocation the sidecar makes.
Environment config outranks a repository's own, so an agent cannot reinstate them by writing to a
repository it controls.

## 3. Authenticate the agent's identity, once

```bash
sudo docker exec -it "git-sidecar-$AGENT" gh auth login
```

Choose SSH as the protocol; it generates and uploads a dedicated key into this agent's volumes.

Expected: `sudo docker exec "git-sidecar-$AGENT" gh auth status` reports the intended account.
Each agent authenticates separately — that is the point of the arrangement.

## 4. Authorize each repository

Every tool call verifies a token held in the repository's own root, so each repository the agent
should reach needs one. As the agent user, with the bundled CLI installed (see the
[README](../../README.md#authentication)):

```bash
git-sidecar-token "/home/$AGENT/Projects/<repo>"
```

Expected: `<repo>/.git-sidecar-token` exists and the agent can read it. Without it every call
fails with "Token file not found in repository", including all of the checks below.

A worktree added through `git_worktree` inherits the token automatically — the file is gitignored,
so git would not carry it, and the tool copies it in.

## 5. Register the endpoint with the agent's MCP client

This deployment leaves the server on its default transport, so the transport is `sse` and the
path is `/sse`. As the agent user:

```bash
claude mcp add --transport sse git-sidecar "http://127.0.0.1:$PORT/sse"
```

Expected: the client lists `git-sidecar` as connected.

## 6. Verify

As the agent user, against a repository under its `Projects` tree:

- A read-only call succeeds — `git_status` on a repository, addressed by its path below
  `PROJECTS_DIR`.
- A remote call succeeds — `git_fetch` on a repository with a remote, which exercises the SSH
  credential.
- A code-host call succeeds — viewing a pull request, which exercises the `gh` credential.
- `git_worktree` with `action: add` produces a worktree that needs no repair: its token file is
  present, plain `git` works inside it, and the main clone does not report it `prunable`.

Expected: all four succeed. The last one is the check that distinguishes this arrangement from a
misaligned mount, where the worktree is unusable by one of the two users.

Two things to know about worktrees here. Give `path` as a location inside the mounted tree — an
absolute path outside it creates the worktree in the container's own filesystem, where the host
cannot see it and no `repo` argument addresses it. And `git_worktree` does not validate the
branch name against `ALLOWED_BRANCH_PREFIXES`, so a worktree branch that does not carry an
allowed prefix is created happily and refused later at push.

## Adding or removing an agent

Each agent is independent: build its image, start its container on a free port, authenticate it.
Removing one is `docker rm -f "git-sidecar-$AGENT"`, plus `docker volume rm "sidecar-ssh-$AGENT"
"gh-config-$AGENT"` to destroy its credentials and revoking whatever the code host issued.

Adding an agent does not disturb the others — unlike the shared arrangement, where the single
container is recreated with a new agent list.

## Trade-offs

- One image, container and port per agent, rather than one of each in total.
- One code-host identity per agent, each authenticated separately.
- The image is built per host, since it carries a uid. It is not portable between hosts whose
  agent uids differ.
