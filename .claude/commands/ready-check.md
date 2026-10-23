---
description: Run the Definition-of-Done checklist (C-11.2) against the current branch and report pass/fail per item.
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git branch:*), Bash(gh issue view:*), Bash(python docs/plan/backlog/_tools/done_gate.py:*), Bash(pnpm:*), Bash(uv run:*), Bash(pytest:*), Bash(ruff:*), Bash(mypy:*), Bash(lint-imports:*), Bash(alembic:*), Bash(gitleaks:*), Read, Grep, Glob
---

# /ready-check

Evaluate the current branch against DoD (C-11.2, `docs/plan/02-definition-of-ready-done.md`). Do not fix anything;
report. Output a table: item | PASS/FAIL/N/A | evidence.

1. **Branch & scope:** name matches C-4.4; derive issue # from branch/commits; `git diff --stat origin/main...HEAD`
   ≤400 changed LOC excl. lockfiles/generated (C-4.8); every changed file is in the ticket write set (C-4.9).
2. **Commits:** conventional commits (C-4.10); breaking changes have `!` + footer (C-4.11); no merge commits.
3. **Acceptance criteria:** for each AC in the issue, name the test that proves it. Missing ⇒ FAIL.
4. **Checks (run only those affected by changed paths; commands and flags are defined only in `AGENTS.md` §4 — read
   them there, do not copy them here):**
   - `services/api/**`: backend lint/format/typecheck/unit-test/import-lint commands, coverage floor per C-9.4
   - migrations: one new revision only; the up/down/up round-trip command
   - statechart: the statechart lint command, the xstate contract suite, `machine_hashes.lock` updated
   - TS packages: the web lint/typecheck/test/size commands
   - chart engine: the chart-engine bench command (≤5% regression, C-9 #16)
   - UI: Storybook story for each touched CMP-*; the a11y test command
   - contracts: the generate command produces no diff
   - always: the secrets-scan command
     If a command does not exist yet (pre-INFRA-001), mark N/A with the reason — never invent one.
5. **Docs:** docs named in the ticket updated; `AGENTS.md` §4 updated if scripts changed; ADR if required.
6. **Safety:** no secrets in diff; no flag gating a safety invariant (C-4.14); every `C-x.y` cited exists in CONSTITUTION.md.
7. **Done-gate (DoD evidence):** run `python docs/plan/backlog/_tools/done_gate.py <KEY> <issue#>` (read-only) and
   report each named gap (design sign-off/Penpot/PNGs, measurements, security verdict, a11y evidence, QA PASS,
   unchecked DoD boxes). Gaps need the evidence or a specific `#1778` owner exception — never a blanket waiver.
   `qa_close.py` runs the same gate and refuses to close on failure.
8. **Feature flags:** multi-PR features behind a flag (C-4.13).

Finish with `READY FOR PR` or `NOT READY` + the ordered fix list.
