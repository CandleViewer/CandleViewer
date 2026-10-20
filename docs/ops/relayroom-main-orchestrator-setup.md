# RelayRoom client setup — `main-orchestrator` (Atlas) on laptop l01

Nonsecret setup report per the owner's "main-orchestrator Claude Desktop setup" handoff. No token,
connect code, secret-bearing URL or password appears in this file or in any commit.

| Item                            | Value                                                                                                                                                               |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Date                            | 2026-10-14 (setup); status and files reconciled 2026-10-16 (PR #2439 review round 1)                                                                                |
| Runtime (actual)                | **Native Windows** Claude Code 2.0.65, Git Bash (MINGW64). Not WSL. Owner chose "proceed on Windows" when the §3.3 mismatch was raised.                             |
| CONFIG_ROOT = INSTRUCTIONS_ROOT | `C:\Users\basil\Desktop\Projects\FullStackProjects\CandleViewer` (main checkout, branch `main`; worktrees under `%TEMP%` are agent scratch and load this CLAUDE.md) |
| Hub                             | `https://relay.candleviewer.com` — `/health` → `ok: true, busDegraded: false` (normal TLS, no `-k`)                                                                 |
| Project                         | `candleviewer`                                                                                                                                                      |
| Registered agent / part         | `main-orchestrator` (existing; not created, renamed or duplicated)                                                                                                  |
| Persona / role                  | Atlas / orchestrator                                                                                                                                                |
| MCP alias                       | `candleviewer-relayroom` (git-ignored `.mcp.json` from `docs/ops/relayroom-mcp.template.json`; user scope has no same-name entry, only `github`, `penpot`)          |
| Machine alias / label           | `l01` / `cv-main-desktop-win-l01`                                                                                                                                   |
| Client-instance UUID            | `d93a5eee-dc36-43c6-b5b4-98f21e94a7b0` (binding; preserve on resume)                                                                                                |
| Run UUID (this conversation)    | `8236a4ad-2682-4f72-9750-ed79a5f129d3` (run8 `8236a4ad`)                                                                                                            |
| Suggested session title         | `CandleViewer \| Atlas \| main-orchestrator \| l01 \| 8236a4ad`                                                                                                     |

The three identifiers above are distinct: **agent** (server-registered part), **client binding**
(this checkout + its private files), **run** (one conversation). They are not interchangeable.

## Files changed (all in CONFIG_ROOT)

| File                                                   | Tracked?                              | Purpose                                                                                                                                                                                                                                                                                                     |
| ------------------------------------------------------ | ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docs/ops/relayroom-mcp.template.json`                 | yes (new; was root `.mcp.json`)       | Shared template: alias + `${ENV}` placeholders only; copied to a local, git-ignored root `.mcp.json`, which the doctor reads                                                                                                                                                                                |
| `.github/CODEOWNERS`                                   | yes                                   | Two lines: `/docs/ops/relayroom-mcp.template.json` → `@CandleViewer/security @CandleViewer/devsecops` (GOV-001: the new MCP config surface must be code-owned; adds reviewers, removes none); `/docs/ops/relayroom-check-skill.template.md` keeps the owners the old `/.claude/` path gave the skill        |
| `.gitignore`                                           | yes                                   | Adds `.claude/relayroom/`, `.claude/settings.local.json`, `.claude/.settings.local.*.tmp` (the credential script's temp file), `/.mcp.json`, `/.mcp.json.tmp` and `/.claude/skills/candleviewer-relayroom-check/` — narrow entries                                                                          |
| `CLAUDE.md`                                            | yes                                   | **One line** in §10a (toolkit list) pointing to `/candleviewer-relayroom-check` and this report. The coordination rules are **not** in the tracked file; see "Where the coordination rules live" below                                                                                                      |
| `.claude/settings.json`                                | yes                                   | Two `permissions.deny` rules on the secret-bearing file only (`Read(./.claude/settings.local.json)` and `Bash(*settings.local.json*)`); the nonsecret `.claude/relayroom/` identity and run records stay readable because the skill and the worker policy read them; no `ask` rule, `defaultMode` unchanged |
| `scripts/relayroom-main-doctor.py`                     | yes (new)                             | Redacting validator; allowlisted PASS/FAIL output only; exit 0 ready, 1 FAIL, 2 crashed                                                                                                                                                                                                                     |
| `scripts/relayroom-enter-credentials.py`               | yes (new)                             | Masked-TTY, atomic JSON merge of the three env keys; refuses non-TTY; removes its temp file on every failure path                                                                                                                                                                                           |
| `scripts/tests/test_relayroom_scripts.py`              | yes (new)                             | Unit tests for both scripts; synthetic values in temp directories only                                                                                                                                                                                                                                      |
| `docs/ops/relayroom-check-skill.template.md`           | yes (new; was in `.claude/skills/`)   | Template of the manual `/candleviewer-relayroom-check` skill (read-oriented; stops on identity mismatch); installed per machine into the git-ignored `.claude/skills/candleviewer-relayroom-check/`                                                                                                         |
| `.claude/relayroom/identity.local.json`                | **ignored**                           | Secret-free private binding descriptor                                                                                                                                                                                                                                                                      |
| `.claude/relayroom/runs/8236a4ad-….json`               | **ignored**                           | This run's nonsecret record                                                                                                                                                                                                                                                                                 |
| `.mcp.json`                                            | **ignored** (local copy)              | Copied from the MCP template; the doctor reads this live file and requires it to keep the `${…}` placeholders (worker clients use their own private binding, never this template)                                                                                                                           |
| `.claude/skills/candleviewer-relayroom-check/SKILL.md` | **ignored** (installed per machine)   | Local copy of the check skill, installed by the client tooling or by hand from the template (see Activation steps)                                                                                                                                                                                          |
| `.claude/settings.local.json`                          | **ignored** (pre-existing, untracked) | Holds the three credential keys under `env` — **entered**; doctor → READY                                                                                                                                                                                                                                   |

Not touched: `~/.claude/settings.json`, `~/.claude.json` user-scope MCP, Windows env vars,
`claude_desktop_config.json`, any other project, any other terminal.

## Completion status

| Step                           | Status                                                                                                                                                                                                                                                                                                                                              |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Configuration prepared         | **done** — doctor: 18 PASS before the credentials were entered (the three credential keys were the only pending items, by design)                                                                                                                                                                                                                   |
| Token decision                 | **Owner decision 2026-10-15: the existing `main-orchestrator` token is kept** (self-hosted, single user, public repo). No rotation and no revocation. This supersedes the original handoff's "confirm the exposed token is revoked" step, which is therefore no longer an activation step                                                           |
| Credentials entered            | **done** — the three keys are in the ignored `settings.local.json`; `scripts/relayroom-main-doctor.py` → **READY** (exit 0)                                                                                                                                                                                                                         |
| MCP connected                  | **done** — direct Streamable-HTTP session to the hub (server `relayroom 0.1.0`, 14 tools); in-session `/mcp` reconnect pending                                                                                                                                                                                                                      |
| Identity verified              | **done** — `whoami` → project `candleviewer`, part `main-orchestrator`, `isMain: true`; `roster` shows this part online, `you: true`; `inbox` empty                                                                                                                                                                                                 |
| Human round trip               | **`[SETUP-CHECK]` sent, owner ACK still pending** — progress event `01a13bd2-bbf3-7d42-b007-a09caffd2db8`; thread `01a13bd2-be93-7d19-ad57-085f57ab55be`, message `01a13bd2-bee1-7bfd-890e-eb6e8cb74732`, nonce `fb27e4f2`. Not complete until the owner replies `ACK fb27e4f2` in the dashboard and Atlas then acks, replies and closes the thread |
| Out-of-scope changes           | **none made**                                                                                                                                                                                                                                                                                                                                       |
| Other session's live behaviour | **not inspected** (no unrelated WSL project exists on this machine)                                                                                                                                                                                                                                                                                 |

## Where the coordination rules live

The tracked `CLAUDE.md` carries only the one-line pointer in §10a. The RelayRoom collaboration
policy (why RelayRoom exists here, identity and boundaries, orchestrator responsibilities,
messaging behaviour, recovery) lives in **each machine's git-ignored `CLAUDE.local.md`**, alongside
that machine's private `.claude/relayroom/identity.local.json`. The first revision of this PR
appended the policy to `CLAUDE.md` as a marked block; review round 1 moved it out of the tracked
file.

## Platform deviations (honest)

- **File protection:** `chmod 0600` is not meaningful on NTFS. `.claude/settings.local.json` is
  protected by Windows ACLs of the user profile only (the credential script's docstring states the
  same caveat). If stronger isolation is wanted, the owner should store the token in Windows
  Credential Manager and have a launcher inject the env var — out of scope here.
- **Agent reads:** the tracked `.claude/settings.json` denies agent `Read` of
  `.claude/settings.local.json` and any shell command naming `settings.local.json`. This is a
  guard against accidental reads, not an isolation boundary: a differently written shell command
  can still read the file as the same Windows user. The identity and run records under
  `.claude/relayroom/` are nonsecret by design (the doctor checks they carry no token, URL or
  connect code) and stay readable.
- **Session wake-up:** plain MCP does not wake an idle session; no background delivery is claimed.
- **Exclusive ownership:** `whoami` proves the binding, not exclusivity. Owner confirmed this
  session is the sole `main-orchestrator` client (2026-10-14). Agents B and C use their own parts.

## Activation steps (owner, in a NEW terminal at CONFIG_ROOT)

Re-use these for another machine or after a token change. Status on this machine: steps 1-3 done,
step 4 pending, step 5 in progress (`[SETUP-CHECK]` sent, owner ACK pending).

1. In the RelayRoom dashboard: open Connect for the existing agent with bypass **off**; read the
   connect code and the agent token privately. (No revocation or rotation is required here: the
   owner kept the existing token, see "Token decision" above.)
2. `cp docs/ops/relayroom-mcp.template.json .mcp.json` (once; the root file is git-ignored and
   machine-local), then `python scripts/relayroom-enter-credentials.py` (masked input; nothing
   echoed).
   Transition (checkouts that pulled this change over a `.mcp.json` from the tracked era): the pull
   deletes an unmodified root copy and the skill file — re-run this step and the skill `cp`. A plain
   `git pull` / `git pull --rebase` over a hand-edited root copy aborts ("would be overwritten");
   never clear that abort with `git add` or `commit -a` — move the edited file aside instead. With
   `--autostash`, a stash/pop, or an edit that was already committed, git's rename detection moves
   the edit onto `docs/ops/relayroom-mcp.template.json` (a tracked, public file): run
   `git restore --source=HEAD --staged --worktree -- docs/ops/relayroom-mcp.template.json` (this
   also undoes a staged carry), then `cp docs/ops/relayroom-mcp.template.json .mcp.json`, and drop
   any local commit that carries the edit; `git diff origin/main -- docs/ops/relayroom-mcp.template.json`
   must print nothing before you push. The orchestrator's root copy stays placeholder-only (the
   doctor fails on a literal URL); worker clients re-enter their binding with their own tooling.
3. `python scripts/relayroom-main-doctor.py` → must print `READY` (exit 0).
4. In the Code session: `/mcp` → reconnect `candleviewer-relayroom`.
5. Tell Atlas "RelayRoom credentials entered"; Atlas then runs §8: `whoami` → `roster` → `inbox` →
   progress event → `[SETUP-CHECK]` thread to `human` with a nonce → you reply `ACK <nonce>` in the
   dashboard → Atlas acks, replies, closes the thread, and appends the IDs to this report.

The check skill is not tracked: the client tooling installs it per machine. To install it by hand,
from CONFIG_ROOT:

```sh
mkdir -p .claude/skills/candleviewer-relayroom-check && cp docs/ops/relayroom-check-skill.template.md .claude/skills/candleviewer-relayroom-check/SKILL.md
```

## Rollback

Remove only: the `candleviewer-relayroom` entry in your local `.mcp.json` and the templates
`docs/ops/relayroom-mcp.template.json` and `docs/ops/relayroom-check-skill.template.md`; their lines
in `.github/CODEOWNERS` (together with the templates, never alone); the six RelayRoom patterns in
`.gitignore` (four under `.claude/`, plus `/.mcp.json` and `/.mcp.json.tmp`); the one-line pointer
in `CLAUDE.md` §10a; the two RelayRoom `deny` rules in `.claude/settings.json`; the two scripts and
`scripts/tests/test_relayroom_scripts.py`; the local skill directory; and `.claude/relayroom/`. No
token was issued by this setup (the existing one was kept), so rolling back does not touch the
dashboard; rotate or revoke the token there only on an owner decision. Nothing else was changed.
