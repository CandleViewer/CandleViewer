# RelayRoom client setup — `main-orchestrator` (Atlas) on laptop l01

Nonsecret setup report per the owner's "main-orchestrator Claude Desktop setup" handoff. No token,
connect code, secret-bearing URL or password appears in this file or in any commit.

| Item | Value |
|---|---|
| Date | 2026-10-14 |
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
| `.gitignore` | yes | Adds `.claude/relayroom/` and `.claude/settings.local.json` (narrow entries) |
| `CLAUDE.md` | yes | Appended the marked `CANDLEVIEWER RELAYROOM COORDINATION` block (46 lines, nothing else touched; rollback copy at `C:\tmp\CLAUDE.md.bak-relayroom`) |
| `scripts/relayroom-main-doctor.py` | yes (new) | Redacting validator; allowlisted PASS/FAIL output only |
| `scripts/relayroom-enter-credentials.py` | yes (new) | Masked-TTY, atomic JSON merge of the three env keys; refuses non-TTY |
| `.claude/skills/candleviewer-relayroom-check/SKILL.md` | yes (new) | Manual `/candleviewer-relayroom-check` (read-oriented; stops on identity mismatch) |
| `.claude/relayroom/identity.local.json` | **ignored** | Secret-free private binding descriptor |
| `.claude/relayroom/runs/8236a4ad-….json` | **ignored** | This run's nonsecret record |
| `.claude/settings.local.json` | **ignored** (pre-existing, untracked) | Credentials go here under `env` — **not yet entered** |

Not touched: `~/.claude/settings.json`, `~/.claude.json` user-scope MCP, Windows env vars,
`claude_desktop_config.json`, any other project, any other terminal.

## Completion status

| Step | Status |
|---|---|
| Configuration prepared | **done** — doctor: 18 PASS |
| Credential prerequisite | **owner decision 2026-10-14:** self-hosted, single user, public repo — the existing token is reused; no revocation (recorded verbatim in the session). Credentials entered into the ignored `settings.local.json`; doctor → READY |
| MCP connected | **done** — direct Streamable-HTTP session to the hub (server `relayroom 0.1.0`, 14 tools); in-session `/mcp` reconnect pending |
| Identity verified | **done** — `whoami` → project `candleviewer`, part `main-orchestrator`, `isMain: true`; `roster` shows this part online, `you: true`; `inbox` empty |
| Human round trip | **sent** — progress event `01a13bd2-bbf3-7d42-b007-a09caffd2db8`; thread `01a13bd2-be93-7d19-ad57-085f57ab55be`, message `01a13bd2-bee1-7bfd-890e-eb6e8cb74732`, nonce `fb27e4f2`; **awaiting the owner's `ACK fb27e4f2` in the dashboard**, then ack → reply → close |
| Out-of-scope changes | **none made** |
| Other session's live behaviour | **not inspected** (no unrelated WSL project exists on this machine) |

## Platform deviations (honest)

- **File protection:** `chmod 0600` is not meaningful on NTFS. `.claude/settings.local.json` is
  protected by Windows ACLs of the user profile only. If stronger isolation is wanted, the owner
  should store the token in Windows Credential Manager and have a launcher inject the env var —
  out of scope here.
- **Session wake-up:** plain MCP does not wake an idle session; no background delivery is claimed.
- **Exclusive ownership:** `whoami` proves the binding, not exclusivity. Owner confirmed this
  session is the sole `main-orchestrator` client (2026-10-14). Agents B and C use their own parts.

## To activate (owner, in a NEW terminal at CONFIG_ROOT)

1. In the RelayRoom dashboard: confirm the previously exposed `main-orchestrator` token is revoked
   (targeted; do not delete the agent or revoke every project token); open Connect for the existing
   agent with bypass **off**; read the connect code and the fresh token privately.
2. `python scripts/relayroom-enter-credentials.py` (masked input; nothing echoed).
3. `python scripts/relayroom-main-doctor.py` → must print `READY`.
4. In this Code session: `/mcp` → reconnect `candleviewer-relayroom`.
5. Tell Atlas "RelayRoom credentials entered"; Atlas then runs §8: `whoami` → `roster` → `inbox` →
   progress event → `[SETUP-CHECK]` thread to `human` with a nonce → you reply `ACK <nonce>` in the
   dashboard → Atlas acks, replies, closes the thread, and appends the IDs to this report.

## Rollback

Remove only: the `candleviewer-relayroom` entry in `.mcp.json`, the two `.gitignore` lines, the
marked CLAUDE.md block, the two scripts, the skill directory, and `.claude/relayroom/`. Revoke only
the newly issued token through the dashboard/admin. Nothing else was changed.
