# RelayRoom client setup — `main-orchestrator` (Atlas) on laptop l01

Nonsecret setup report per the owner's "main-orchestrator Claude Desktop setup" handoff. No token,
connect code, secret-bearing URL or password appears in this file or in any commit.

| Item | Value |
|---|---|
| Date | 2026-10-14 (setup); status and files reconciled 2026-10-16 (PR #2439 review round 1) |
| Runtime (actual) | **Native Windows** Claude Code 2.0.65, Git Bash (MINGW64). Not WSL. Owner chose "proceed on Windows" when the §3.3 mismatch was raised. |
| CONFIG_ROOT = INSTRUCTIONS_ROOT | `C:\Users\basil\Desktop\Projects\FullStackProjects\CandleViewer` (main checkout, branch `main`; worktrees under `%TEMP%` are agent scratch and load this CLAUDE.md) |
| Hub | `https://relay.candleviewer.com` — `/health` → `ok: true, busDegraded: false` (normal TLS, no `-k`) |
| Project | `candleviewer` |
| Registered agent / part | `main-orchestrator` (existing; not created, renamed or duplicated) |
| Persona / role | Atlas / orchestrator |
| MCP alias | `candleviewer-relayroom` (project-scoped `.mcp.json`; no same-name entry at user scope — user scope has only `github`, `penpot`) |
| Machine alias / label | `l01` / `cv-main-desktop-win-l01` |
| Client-instance UUID | `d93a5eee-dc36-43c6-b5b4-98f21e94a7b0` (binding; preserve on resume) |
| Run UUID (this conversation) | `8236a4ad-2682-4f72-9750-ed79a5f129d3` (run8 `8236a4ad`) |
| Suggested session title | `CandleViewer \| Atlas \| main-orchestrator \| l01 \| 8236a4ad` |

The three identifiers above are distinct: **agent** (server-registered part), **client binding**
(this checkout + its private files), **run** (one conversation). They are not interchangeable.

## Files changed (all in CONFIG_ROOT)

| File | Tracked? | Purpose |
|---|---|---|
| `.mcp.json` | yes (new) | Shared template: alias + `${ENV}` placeholders only |
| `.github/CODEOWNERS` | yes | One line: `/.mcp.json` → `@CandleViewer/security @CandleViewer/devsecops` (GOV-001: the new MCP config surface must be code-owned; adds reviewers, removes none) |
| `.gitignore` | yes | Adds `.claude/relayroom/`, `.claude/settings.local.json` and `.claude/.settings.local.*.tmp` (the credential script's temp file) — narrow entries |
| `CLAUDE.md` | yes | **One line** in §10a (toolkit list) pointing to `/candleviewer-relayroom-check` and this report. The coordination rules are **not** in the tracked file; see "Where the coordination rules live" below |
| `.claude/settings.json` | yes | Three `permissions.deny` rules for the RelayRoom secret files (`Read` of `.claude/settings.local.json` and of `.claude/relayroom/**`, and `Bash(cat ./.claude/settings.local.json)`); no `ask` rule, `defaultMode` unchanged |
| `scripts/relayroom-main-doctor.py` | yes (new) | Redacting validator; allowlisted PASS/FAIL output only; exit 0 ready, 1 FAIL, 2 crashed |
| `scripts/relayroom-enter-credentials.py` | yes (new) | Masked-TTY, atomic JSON merge of the three env keys; refuses non-TTY; removes its temp file on every failure path |
| `scripts/tests/test_relayroom_scripts.py` | yes (new) | Unit tests for both scripts; synthetic values in temp directories only |
| `.claude/skills/candleviewer-relayroom-check/SKILL.md` | yes (new) | Manual `/candleviewer-relayroom-check` (read-oriented; stops on identity mismatch) |
| `.claude/relayroom/identity.local.json` | **ignored** | Secret-free private binding descriptor |
| `.claude/relayroom/runs/8236a4ad-….json` | **ignored** | This run's nonsecret record |
| `.claude/settings.local.json` | **ignored** (pre-existing, untracked) | Holds the three credential keys under `env` — **entered**; doctor → READY |

Not touched: `~/.claude/settings.json`, `~/.claude.json` user-scope MCP, Windows env vars,
`claude_desktop_config.json`, any other project, any other terminal.

## Completion status

| Step | Status |
|---|---|
| Configuration prepared | **done** — doctor: 18 PASS before the credentials were entered (the three credential keys were the only pending items, by design) |
| Token decision | **Owner decision 2026-10-15: the existing `main-orchestrator` token is kept** (self-hosted, single user, public repo). No rotation and no revocation. This supersedes the original handoff's "confirm the exposed token is revoked" step, which is therefore no longer an activation step |
| Credentials entered | **done** — the three keys are in the ignored `settings.local.json`; `scripts/relayroom-main-doctor.py` → **READY** (exit 0) |
| MCP connected | **done** — direct Streamable-HTTP session to the hub (server `relayroom 0.1.0`, 14 tools); in-session `/mcp` reconnect pending |
| Identity verified | **done** — `whoami` → project `candleviewer`, part `main-orchestrator`, `isMain: true`; `roster` shows this part online, `you: true`; `inbox` empty |
| Human round trip | **`[SETUP-CHECK]` sent, owner ACK still pending** — progress event `01a13bd2-bbf3-7d42-b007-a09caffd2db8`; thread `01a13bd2-be93-7d19-ad57-085f57ab55be`, message `01a13bd2-bee1-7bfd-890e-eb6e8cb74732`, nonce `fb27e4f2`. Not complete until the owner replies `ACK fb27e4f2` in the dashboard and Atlas then acks, replies and closes the thread |
| Out-of-scope changes | **none made** |
| Other session's live behaviour | **not inspected** (no unrelated WSL project exists on this machine) |

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
  `.claude/settings.local.json` and `.claude/relayroom/**` and `cat` of the settings file. This is a
  guard against accidental reads, not an isolation boundary: a differently written shell command
  can still read the file as the same Windows user.
- **Session wake-up:** plain MCP does not wake an idle session; no background delivery is claimed.
- **Exclusive ownership:** `whoami` proves the binding, not exclusivity. Owner confirmed this
  session is the sole `main-orchestrator` client (2026-10-14). Agents B and C use their own parts.

## Activation steps (owner, in a NEW terminal at CONFIG_ROOT)

Re-use these for another machine or after a token change. Status on this machine: steps 1-3 done,
step 4 pending, step 5 in progress (`[SETUP-CHECK]` sent, owner ACK pending).

1. In the RelayRoom dashboard: open Connect for the existing agent with bypass **off**; read the
   connect code and the agent token privately. (No revocation or rotation is required here: the
   owner kept the existing token, see "Token decision" above.)
2. `python scripts/relayroom-enter-credentials.py` (masked input; nothing echoed).
3. `python scripts/relayroom-main-doctor.py` → must print `READY` (exit 0).
4. In the Code session: `/mcp` → reconnect `candleviewer-relayroom`.
5. Tell Atlas "RelayRoom credentials entered"; Atlas then runs §8: `whoami` → `roster` → `inbox` →
   progress event → `[SETUP-CHECK]` thread to `human` with a nonce → you reply `ACK <nonce>` in the
   dashboard → Atlas acks, replies, closes the thread, and appends the IDs to this report.

## Rollback

Remove only: the `candleviewer-relayroom` entry in `.mcp.json`; the `/.mcp.json` line in
`.github/CODEOWNERS` (together with the file, never alone); the three RelayRoom patterns in
`.gitignore`; the one-line pointer in `CLAUDE.md` §10a; the three RelayRoom `deny` rules in
`.claude/settings.json`; the two scripts and `scripts/tests/test_relayroom_scripts.py`; the skill
directory; and `.claude/relayroom/`. No token was issued by this setup (the existing one was kept),
so rolling back does not touch the dashboard; rotate or revoke the token there only on an owner
decision. Nothing else was changed.
