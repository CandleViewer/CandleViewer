---
name: candleviewer-relayroom-check
description: Verify the CandleViewer RelayRoom identity and read the scoped inbox without exposing credentials.
disable-model-invocation: true
---

# CandleViewer RelayRoom check (manual, read-oriented)

Run only when invoked as `/candleviewer-relayroom-check`. It performs no sends, acks, config edits,
token output, or role changes. Read-oriented MCP calls may still refresh server-side presence; this is
not a zero-side-effect check.

1. Read `.claude/relayroom/identity.local.json` in the effective CandleViewer configuration root (or run
   `python scripts/relayroom-main-doctor.py`). Never open or print `.claude/settings.local.json`.
   **If the descriptor is missing or ambiguous, stop and report** — do not assume Atlas / main-orchestrator.
2. Discover the tools exposed by the MCP alias named in the descriptor (`candleviewer-relayroom`).
3. Call `whoami`. Require `project == "candleviewer"`, `part == descriptor.part`, and
   `isMain == descriptor.expectedIsMain`. **Any mismatch → stop; never edit the descriptor to match.**
4. Call `roster` and report the current part's presence (no changes to any agent).
5. Call `inbox` with `{"unreadOnly": true, "limit": 30}` and list subjects/threads only.
6. Report: identity (project/part/persona/machine alias/run id), roster presence, unread count — nothing else.
