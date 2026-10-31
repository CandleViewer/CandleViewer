---
description: Branch naming, commits, PR size and PR content rules (C-4.x); apply whenever creating branches, commits or PRs.
---
# Branching and PRs

Source: `CONSTITUTION.md` §4, `docs/plan/01-sdlc-and-branching.md`, `.github/PULL_REQUEST_TEMPLATE.md`.

## Branches
- Trunk-based. `main` is protected: no direct pushes, **never force-push `main` or any shared branch** (C-4.1).
- Name: `<type>/<epic-key>-<short-slug>` — lowercase, kebab-case, ASCII, ≤60 chars (C-4.4).
  Types: `feat`, `fix`, `design`, `chore`, `docs`, `test`, `refactor`, `perf`, `spike`, `hotfix`.
  Example: `feat/of-42-footprint-cells`.
- Branch from fresh `main`; live ≤3 working days (C-4.3). Integrate via `git pull --rebase origin main`
  (C-4.12). Force-push *your own* feature branch with `--force-with-lease` only.
- Spikes end in a written finding (ADR or `docs/plan/` note) and are deleted (C-4.5).

## Scope
- One issue ⇄ one branch ⇄ one PR by default; a bundle under an owner delivery-speed directive closes several tickets of one module / epic / chain, each with its own acceptance table and QA record (C-4.6). No drive-by changes (C-4.9) — open a new issue instead.
- Preferred diff ≤400 changed LOC excluding lockfiles/generated/snapshots (C-4.8). Split larger work
  into stacked PRs behind a flag (C-4.13).
- Before starting, check open PRs for overlapping paths (C-4.15): `gh pr list --search "<path>"`.

## Commits
- Conventional Commits, enforced (C-4.10): `feat(oms): add orderLinkId generator`.
- Breaking change: `!` **and** a `BREAKING CHANGE:` footer (C-4.11).
- Never commit secrets, `.env`, recorded fixtures that are not redacted, or generated artefacts edited by hand (C-4.16).

## Pull request
- Title = conventional commit. Body uses the PR template, fully filled; includes `Closes #N` (C-4.7).
- List: acceptance criteria → how each is verified (test name / screenshot / bench output).
- Attach evidence required by the ticket (Storybook link, bench diff, axe report, migration round-trip log).
- All 20 required checks in CONSTITUTION §9 must be green; never disable or skip a check to go green.
- Reviews: 2 independent agent reviews (`code-reviewer`; `security-reviewer` on security paths). The orchestrator merges
  code PRs once green; **design PRs need owner approval** (C-10.1 v1.1.0, `docs/design/README.md`).
- Resolve every review conversation before merge; squash or rebase merge only (no merge commits).
- Run `/ready-check` then `/pr` locally before opening.
