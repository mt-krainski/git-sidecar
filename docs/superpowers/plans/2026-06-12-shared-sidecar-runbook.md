# Shared-Sidecar Deployment Runbook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the host-specific notes in `tmp-docs/` into a polished, generalized deployment runbook (`docs/runbooks/`) documenting *one* hardened way to run git-sidecar — a single shared sidecar serving multiple mutually-isolated agent users — and link it from the README as an answer to the "security polish isn't here yet" warning.

**Architecture:** One new runbook markdown file merges the two tmp-docs (agent-user provisioning + shared sidecar) into a single narrative with three parts: provision agent users, run the sidecar, connect MCP clients. Provisioning is documented as transparent step-by-step commands only — the `provision-agent-user.sh` script is deliberately NOT carried over (owner's choice: the steps are straightforward and they prefer seeing what happens). The README gains a "Deployment models" section and the warning block gains a pointer. The runbook opens with explicit framing that this is one deployment model among several, not a prescription. Finally, `tmp-docs/` is deleted.

**Tech Stack:** Markdown docs, git. No code changes to the sidecar itself. Verification = link checks, `pre-commit`.

**Important context for the implementer:**

- This is a **documentation-only** change. No Python code, no tests to write. TDD does not apply; verification steps are syntax/link/hook checks instead.
- The source material lives in `tmp-docs/` (untracked): `2026-06-12-provision-rootless-agent-user.md`, `2026-06-12-shared-git-sidecar.md`, `provision-agent-user.sh`. You do NOT need to read them — the output file's full content is inlined below. The content below has already been generalized: host-specific names (`matt`, `claude-yolo`, `claude-gravital`), references to a companion doc that doesn't exist in this repo (`2026-05-10-rootless-docker-setup.md`), legacy `agents`-group migration notes, and a personal Claude Code `settings.json` blob have all been removed or genericized. The `provision-agent-user.sh` script is intentionally NOT ported — provisioning is documented as explicit shell steps only.
- Work on branch `task/shared-sidecar-runbook` (the `task/` prefix matches the sidecar's own `ALLOWED_BRANCH_PREFIXES`, so the branch can be pushed through the sidecar's MCP tools if desired).
- Pre-commit hooks (`trailing-whitespace`, `end-of-file-fixer`, gitleaks) run on commit. If a commit fails because a hook auto-fixed whitespace, run `git add -u` and re-run the same commit command.

---

### Task 1: Branch setup

**Files:** none (git only)

- [ ] **Step 1: Create the working branch**

```bash
cd /home/claude-yolo/Projects/git-sidecar
git checkout -b task/shared-sidecar-runbook
```

Expected: `Switched to a new branch 'task/shared-sidecar-runbook'`

---

### Task 2: The runbook

**Files:**
- Create: `docs/runbooks/shared-sidecar-isolated-agents.md`

- [ ] **Step 1: Write the runbook**

Create `docs/runbooks/shared-sidecar-isolated-agents.md` with exactly this content:

````markdown
# Runbook: one shared sidecar, many isolated agents

> **This is one deployment model, not the only one.** git-sidecar doesn't prescribe how
> you run it. The [README quick start](../../README.md#quick-start) is the simplest model —
> one sidecar on one user's Docker daemon, serving one agent. Another valid model is one
> sidecar *per* agent (own credential volumes, own `gh auth login` each), which buys
> per-agent GitHub identities at the cost of managing N credential sets. This runbook
> documents a third: **several sandboxed agents on one host, mutually isolated, sharing
> one GitHub identity through a single sidecar.** Treat it as a worked example of a
> defensible configuration, not a prescription.

## The model

A single git-sidecar container runs on the administrator's **rootful** Docker daemon. It
mounts every agent's `Projects` directory and runs as a dedicated service uid
(`gitsidecar`, 3000). Because it is one container, it holds **one** SSH key and one `gh`
credential set in named volumes — you authenticate once.

Three kinds of principals on the host:

| Principal                            | Privileges                                                              | Role                                                            |
| ------------------------------------ | ----------------------------------------------------------------------- | --------------------------------------------------------------- |
| Administrator                        | a sudoer; owns the rootful Docker daemon                                | provisions agent users, runs the sidecar                        |
| Agent users (`agent-01`, `agent-02`) | no sudo, no `docker` group, own rootless Docker daemon, private `700` home | run the AI agents; hold **no** credentials                      |
| `gitsidecar` (uid 3000)              | system account, `nologin`                                               | owns the sidecar's credential volumes and the files it writes   |

Why agents stay isolated from each other even though one container can reach them all:

- **File writes.** The container is added to each agent's own primary group at run time
  (`--group-add`), and each agent's `Projects` is `2770` setgid with a default ACL (set up
  during provisioning). The sidecar and the owning agent can both read/write that agent's
  repos — but no *other* agent is in that group, and every home is `700`.
- **Requests.** All agents reach the same endpoint (`127.0.0.1:8900`), but every operation
  requires the per-repo `.git-sidecar-token`, which lives inside that agent's `700` home.
  An agent can't read another agent's token, so it can't drive the sidecar against another
  agent's repo. (The sidecar verifies tokens with a timing-safe compare and resolves repo
  paths relative to `/projects`, so `<agent>/<repo>` addressing works natively.)
- **Credentials.** The sidecar runs on the rootful daemon, which the agents (rootless, not
  in the `docker` group) cannot reach — an agent can't `docker exec` into the sidecar to
  steal the shared credentials.

Tradeoffs you're accepting:

- All agents push under **one** GitHub identity.
- A compromise of the sidecar process itself reaches every mounted `Projects` tree.

If either is unacceptable, run one sidecar per agent instead.

## Host prerequisites

- Docker Engine (rootful) for the sidecar, plus the rootless pieces for the agents:
  `docker-ce-rootless-extras` (provides `dockerd-rootless-setuptool.sh` and
  `rootlesskit`), `uidmap`, and `slirp4netns`.
- The `acl` package (`setfacl`), for default ACLs on the agents' `Projects` directories.
- A sudoer account — the administrator. Everything below runs from it unless marked
  otherwise.

## Part 1 — provision an agent user

Each agent user gets:

- **No `docker` group membership** — no root-equivalent access to the system daemon.
- **Its own rootless `dockerd`** at `unix:///run/user/<uid>/docker.sock`, for running the
  agent's own sandbox containers.
- **A private home** (`chmod 700`, own primary group) — no other non-root user can read it.
- **No passwordless sudo** — anything needing real root stays with the administrator.
- **A "sidecar-ready" `Projects` directory** — setgid to the user's own group with a
  default ACL, so the sidecar (joined to that group at run time) can collaborate on the
  repos while other agents cannot.

A deliberate non-choice: there is **no shared "agents" group**. A shared group is
symmetric — every member reaches every other member's setgid files — which is exactly the
cross-agent access this model avoids. Per-user groups give the sidecar an *asymmetric*
reach: it joins every agent's group; no agent joins any other's.

### Step by step

Run the steps once per new user (`agent-01`, `agent-02`, …); `useradd` auto-allocates each
user the next free subuid/subgid block, so ranges never collide.

All steps run as the administrator. Set the target username once at the top of your shell
session; step 1 captures its uid into `$UIDN`. Every block below assumes both are set:

```bash
export NEWUSER=agent-01            # the only thing you change per user
```

#### 1. Create the user with a private home + own group

```bash
sudo useradd --create-home --user-group --shell /bin/bash "$NEWUSER"
export UIDN=$(id -u "$NEWUSER")              # capture the uid for the steps below
sudo chmod 700 "/home/$NEWUSER"              # private; no group/other access
sudo chown "$NEWUSER:$NEWUSER" "/home/$NEWUSER"
```

`--user-group` gives the user its own primary group (so it is *not* in any shared group).
`useradd` also auto-allocates a subordinate uid/gid range — verify:

```bash
grep "^$NEWUSER:" /etc/subuid /etc/subgid    # expect <user>:<start>:65536
```

If for some reason it's missing, add the next free 65536 block explicitly:

```bash
start=$(awk -F: '{e=$2+$3; if(e>m)m=e} END{print (m<100000?100000:m)}' /etc/subuid)
sudo usermod --add-subuids ${start}-$((start+65535)) "$NEWUSER"
sudo usermod --add-subgids ${start}-$((start+65535)) "$NEWUSER"
```

#### 2. Prepare a "sidecar-ready" Projects directory

The shared sidecar needs to read/write this user's repos while *other* agents cannot. Set
the user's `Projects` dir setgid to its **own** group, with a default ACL so files stay
group-writable regardless of umask:

```bash
sudo -u "$NEWUSER" mkdir -p "/home/$NEWUSER/Projects"
sudo chown "$NEWUSER:$NEWUSER" "/home/$NEWUSER/Projects"
sudo chmod 2770 "/home/$NEWUSER/Projects"          # setgid: files inherit the user's own group
sudo setfacl -m   g::rwX "/home/$NEWUSER/Projects"  # group can write existing entries
sudo setfacl -d -m g::rwX "/home/$NEWUSER/Projects" # ...and anything created later
```

At sidecar start time, the container is added to this group (`--group-add $(id -g
"$NEWUSER")`) so it can collaborate on the repos. No other agent is in the user's group,
and the `700` home blocks everyone else at the top — so this opens access to the sidecar
*only*.

#### 3. Enable linger (persistent user systemd manager + dockerd)

```bash
sudo loginctl enable-linger "$NEWUSER"
# Wait for the user manager to come up. Use `sudo test`: /run/user/$UIDN is mode 700 owned
# by the new user, so an unprivileged shell can't stat the bus socket and a bare
# `[ -S ... ]` would loop forever even once it exists.
while ! sudo test -S "/run/user/$UIDN/bus"; do sleep 0.5; done
```

#### 4. Install rootless docker *as the user*

If `machinectl` is not installed, enter the user's systemd session via env vars. (A bare
`sudo -iu "$NEWUSER"` will **not** work — it lacks `XDG_RUNTIME_DIR` and the dbus address.)

```bash
sudo -u "$NEWUSER" \
  XDG_RUNTIME_DIR="/run/user/$UIDN" \
  DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$UIDN/bus" \
  PATH=/usr/bin:/bin:/usr/sbin:/sbin \
  dockerd-rootless-setuptool.sh install
```

No `--force` is needed: a brand-new user isn't in the `docker` group, so the rootful
socket is already unreachable and the setuptool won't abort.

#### 5. Persist `DOCKER_HOST` for the user

```bash
sudo -u "$NEWUSER" tee -a "/home/$NEWUSER/.bashrc" >/dev/null <<'EOF'

# Rootless Docker
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DOCKER_HOST="unix://${XDG_RUNTIME_DIR}/docker.sock"
EOF

sudo -u "$NEWUSER" mkdir -p "/home/$NEWUSER/.config/environment.d"
sudo -u "$NEWUSER" tee "/home/$NEWUSER/.config/environment.d/10-docker.conf" >/dev/null <<EOF
DOCKER_HOST=unix:///run/user/$UIDN/docker.sock
EOF
```

#### 6. Verify

```bash
run() { sudo -u "$NEWUSER" XDG_RUNTIME_DIR="/run/user/$UIDN" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$UIDN/bus" "$@"; }

id "$NEWUSER"                                # groups = own group only; no 'docker'
run systemctl --user is-active docker        # active
run env DOCKER_HOST="unix:///run/user/$UIDN/docker.sock" docker run --rm hello-world
run env DOCKER_HOST=unix:///var/run/docker.sock docker ps   # -> permission denied (good)
ls -ld "/home/$NEWUSER"                       # drwx------ <user> <user>
```

The proof of containment: a container's `root` maps to the host user's uid, bind-mounting
host paths the user can't read (e.g. `/etc/shadow`) yields "Permission denied" inside the
container, and the system `/var/run/docker.sock` is refused.

### Operating as an agent user

`useradd` leaves the account password-locked. To operate as the user, either:

- `sudo -u "$NEWUSER" -i` for a quick shell (note: not a full systemd session — use the
  env-var form from step 4 for `systemctl --user`/docker), or
- set a password (`sudo passwd "$NEWUSER"`) / install an SSH key in `/home/$NEWUSER/.ssh`
  for direct login.

## Part 2 — run the shared sidecar

### One-time setup

```bash
# 1. Dedicated service user that owns the single credential set (uid 3000, no login).
sudo useradd --system --uid 3000 --user-group --shell /usr/sbin/nologin gitsidecar

# 2. Build the image aligned to that uid (so the gh/ssh volumes are owned by 3000 and
#    files written into /projects land with a sensible owner).
sudo docker build \
  --build-arg UID=3000 --build-arg GID=3000 \
  -t git-sidecar:shared /path/to/git-sidecar

# 3. Start it (see the single command below), then authenticate gh ONCE.
#    Choose SSH as the protocol; it generates + uploads a dedicated key into the volumes.
sudo docker exec -it git-sidecar gh auth login
```

### Start it — the single command

Edit the `AGENTS` list; that's the only thing that changes. Re-running this command
restarts the sidecar with the current agent set (it removes and recreates the container),
so it doubles as "add/remove an agent."

```bash
AGENTS=(agent-01 agent-02)   # users this sidecar serves (each provisioned via Part 1)

# Build the per-agent flags into an array (one --group-add + -v pair per agent):
args=()
for u in "${AGENTS[@]}"; do
  args+=( --group-add "$(id -g "$u")" -v "/home/$u/Projects:/projects/$u" )
done

sudo docker rm -f git-sidecar 2>/dev/null
sudo docker run -d --name git-sidecar --restart unless-stopped \
  -p 127.0.0.1:8900:8900 \
  --user 3000:3000 \
  "${args[@]}" \
  -v "$HOME/.gitconfig:/home/sidecar/.gitconfig:ro" \
  -v sidecar-ssh:/home/sidecar/.ssh \
  -v gh-config:/home/sidecar/.config/gh \
  -e ALLOWED_BRANCH_PREFIXES=task/,dependabot/ \
  git-sidecar:shared
```

The loop puts one `--group-add <gid> -v /home/<u>/Projects:/projects/<u>` pair per agent
into `args` — e.g. for `agent-01`: `--group-add 1004 -v /home/agent-01/Projects:/projects/agent-01`.

> **Build the array; don't inline a `$(for …)` substitution.** If a newline lands
> mid-substitution when you paste an inlined one-liner, the shell splits the argument
> list, runs the usernames as commands (`agent-01: command not found`), and launches the
> container with empty `/home//Projects:/projects/` mounts. The array form above is
> immune to that — every line is a complete statement.

### Per-repo authorization (once per repo)

Each repo an agent should reach needs a token file readable by that agent. As the agent
user, drop it in the repo root with the bundled CLI (see the
[README](../../README.md#authentication) for installing `git-sidecar-token`):

```bash
# as the agent user, inside the repo:
git-sidecar-token ~/Projects/<repo>     # writes ~/Projects/<repo>/.git-sidecar-token
```

The agent then addresses that repo to the MCP server as `<agent>/<repo>` (e.g.
`agent-01/my-repo`) and passes the token with each call.

### Adding an agent later

1. Provision the user (Part 1 — gives it a `700` home and a sidecar-ready `Projects`).
2. Add its name to `AGENTS` and re-run the single start command above.

No second `gh auth login` — the credential volumes are unchanged.

## Part 3 — connect an agent's MCP client

Any MCP client that speaks SSE works. With Claude Code, register the sidecar at user scope
(available in every project), **as the agent user**:

```bash
claude mcp add --transport sse -s user git-sidecar http://127.0.0.1:8900/sse
```

The agent addresses repos as `<agent>/<repo>` (e.g. `agent-01/my-repo`), authenticating
with the per-repo `.git-sidecar-token` from its own `Projects` tree.

If the agent's MCP client is itself a container, replace `-p 127.0.0.1:8900:8900` in the
start command with a shared docker network (`docker network create git-sidecar-net`;
`--network git-sidecar-net` on both containers) so it can reach the sidecar by name.

## Verify the deployment

```bash
sudo docker ps --filter name=git-sidecar           # Up, published on 127.0.0.1:8900
sudo docker logs git-sidecar | tail                # serving on 0.0.0.0:8900
curl -fsS http://127.0.0.1:8900/sse -m 1 || true   # endpoint reachable (SSE stream)

# Ownership proof: a file the sidecar writes into an agent's repo is group-owned by that
# agent and group-writable, so the agent can edit it; other agents are not in the group.
sudo docker exec git-sidecar sh -c 'touch /projects/agent-01/.sidecar-probe; ls -l /projects/agent-01/.sidecar-probe'
ls -l /home/agent-01/Projects/.sidecar-probe       # -rw-rw---- gitsidecar agent-01
sudo rm /home/agent-01/Projects/.sidecar-probe
```

## Notes & caveats

- **`gitconfig`:** the mounted `~/.gitconfig` is the administrator's; it sets the commit
  identity for *all* agents. Point it at a bot identity if you don't want commits
  attributed to your personal account.
- **`--group-add $(id -g <user>)` assumes the user has its own primary group** (true for
  users provisioned via Part 1). If an agent user's primary group is shared with other
  accounts, the sidecar joins that shared group and the isolation argument above no
  longer holds — give such users their own group first.
- **The sidecar is on the rootful daemon**, which the agents (rootless, not in the
  `docker` group) cannot reach — that's what stops an agent from `docker exec`-ing into
  the sidecar to steal the shared credentials. Don't weaken this by adding agent users to
  the `docker` group.
- **Rootless Docker limits for the agent users** (intentional): no privileged ports
  `<1024` by default, no `--net=host`, no `--privileged`, and image storage lives in
  `~/.local/share/docker` (counts against the user's home/disk).

### Troubleshooting: credential volumes owned by a different uid

If a previous sidecar ran as a different uid, the existing `sidecar-ssh` / `gh-config`
volumes are owned by that old uid and the new `gitsidecar` (3000) can't read them. The
tell: inside the container, `.ssh` shows the old numeric owner. Re-own them once to keep
the existing SSH key + gh login (no re-auth):

```bash
SUID=$(sudo docker exec git-sidecar id -u sidecar)   # 3000
SGID=$(sudo docker exec git-sidecar id -g sidecar)
sudo docker exec -u 0 git-sidecar sh -c "
  chown -R $SUID:$SGID /home/sidecar/.ssh /home/sidecar/.config/gh
  chmod 700 /home/sidecar/.ssh
  find /home/sidecar/.ssh -type f -exec chmod 600 {} +
  find /home/sidecar/.ssh -name '*.pub' -exec chmod 644 {} +
"
sudo docker restart git-sidecar
sudo docker exec -u "$SUID" git-sidecar gh auth status   # confirm still logged in
```

To start clean instead: `sudo docker volume rm sidecar-ssh gh-config`, then run the
`gh auth login` from the one-time setup.
````

- [ ] **Step 2: Verify internal links resolve**

```bash
test -f README.md && echo README-LINK-OK
grep -c '^## ' docs/runbooks/shared-sidecar-isolated-agents.md
```

Expected: `README-LINK-OK` and a section count of `7` (The model, Host prerequisites, Part 1, Part 2, Part 3, Verify the deployment, Notes & caveats).

Also confirm the README anchors referenced by the runbook exist:

```bash
grep -n '^## Quick start\|^## Authentication' README.md
```

Expected: both headings found.

- [ ] **Step 3: Commit**

```bash
git add docs/runbooks/shared-sidecar-isolated-agents.md
git commit -m "docs: add shared-sidecar multi-agent deployment runbook"
```

---

### Task 3: README updates

**Files:**
- Modify: `README.md` (warning block at line 4; new section after "Security model", before "Development")

> Note: the warning's "that polish isn't here yet" sentence stays as-is — this is a security boundary and we don't want to over-promise. The runbook is mentioned only as an example.

- [ ] **Step 1: Mention the runbook in the warning (as an example, keeping the caveat)**

In `README.md`, replace this exact text (inside the warning block on line 4):

```
The design is meant to be hardenable (rootless Docker, dedicated unprivileged user, no Docker socket access for the agent), but that polish isn't here yet. Don't point this at credentials you can't afford to lose.
```

with:

```
The design is meant to be hardenable (rootless Docker, dedicated unprivileged user, no Docker socket access for the agent), but that polish isn't here yet. For one example of how those pieces can fit together, see [the deployment runbook](docs/runbooks/shared-sidecar-isolated-agents.md). Don't point this at credentials you can't afford to lose.
```

- [ ] **Step 2: Add a "Deployment models" section**

In `README.md`, insert a new section between the end of the "Security model" section (after the line `- Branch names must match configured prefixes`) and the `## Development` heading:

```markdown
## Deployment models

The quick start above is the simplest setup: one sidecar on one user's Docker daemon, serving one agent. It is not the only way to run git-sidecar — how much isolation you get depends on how you deploy it.

For one example of a hardened multi-agent setup — one shared sidecar serving several mutually-isolated agent users, with rootless Docker, private homes, and per-user group-scoped file access — see [docs/runbooks/shared-sidecar-isolated-agents.md](docs/runbooks/shared-sidecar-isolated-agents.md). Treat runbooks as worked examples, not prescriptions or guarantees.
```

The result around the insertion point must read:

```markdown
- Branch names must match configured prefixes

## Deployment models

The quick start above is the simplest setup: one sidecar on one user's Docker daemon, serving one agent. It is not the only way to run git-sidecar — how much isolation you get depends on how you deploy it.

For one example of a hardened multi-agent setup — one shared sidecar serving several mutually-isolated agent users, with rootless Docker, private homes, and per-user group-scoped file access — see [docs/runbooks/shared-sidecar-isolated-agents.md](docs/runbooks/shared-sidecar-isolated-agents.md). Treat runbooks as worked examples, not prescriptions or guarantees.

## Development
```

- [ ] **Step 3: Verify the links**

```bash
grep -c 'docs/runbooks/shared-sidecar-isolated-agents.md' README.md
test -f docs/runbooks/shared-sidecar-isolated-agents.md && echo TARGET-OK
```

Expected: `2` (warning + new section) and `TARGET-OK`.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: link the deployment runbook from the README"
```

---

### Task 4: Remove tmp-docs

**Files:**
- Delete: `tmp-docs/` (3 untracked files — the two markdown docs are carried into `docs/runbooks/`; `provision-agent-user.sh` is deliberately dropped, owner's choice)

> ⚠️ `tmp-docs/` is **untracked**, so this deletion is not recoverable from git history. Task 2 must be committed first; do not run this task until it is.

- [ ] **Step 1: Confirm the replacement is committed**

```bash
git log --oneline -3
git ls-files docs/runbooks/
```

Expected: the `docs:` commits from Tasks 2–3 are present, and `git ls-files` lists `docs/runbooks/shared-sidecar-isolated-agents.md`.

- [ ] **Step 2: Delete the directory**

```bash
rm -r tmp-docs
git status --short
```

Expected: `tmp-docs/` gone from `git status` output (it was untracked, so no commit is needed).

---

### Task 5: Final verification

**Files:** none

- [ ] **Step 1: Run all pre-commit hooks over the repo**

```bash
uv run pre-commit run --all-files
```

Expected: all hooks pass. If `trailing-whitespace` or `end-of-file-fixer` modified the new docs, re-add and amend the relevant commit:

```bash
git add -u
git commit --amend --no-edit
uv run pre-commit run --all-files   # must pass clean now
```

- [ ] **Step 2: Review the branch**

```bash
git log --oneline main..HEAD
git diff main --stat
```

Expected: 2 commits; changes confined to `README.md` and `docs/runbooks/` (plus this plan file if committed).
