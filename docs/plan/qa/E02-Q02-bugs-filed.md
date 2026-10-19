# E02-Q02 — Bugs and documentation defects filed

Filed from the two exploratory charter sessions (see the session notes in
this directory). Severity per `docs/plan/03-testing-strategy.md` §11.3.
Each item below should be opened as its own GitHub issue by QA triage; the
reproduction steps are written so that can happen without re-running the
charter.

## BUG-1 (P2) — `pnpm verify` flakes on `@candleviewer/web#test:cov` on a cold, uncached run

Filed: [#1535](https://github.com/CandleViewer/CandleViewer/issues/1535)

**Session:** 1. **Area:** `apps/web` coverage task under Turborepo.

**Repro:**

1. Fresh clone/worktree from `origin/main`, `pnpm install` (cold).
2. `pnpm verify` (full run, cold Turbo cache — no prior `pnpm verify` or
   `pnpm --filter @candleviewer/web test:cov` run in this checkout).
3. Observe `@candleviewer/web#test:cov` throw:
   `Error: ENOENT: no such file or directory, open
'<repo>/apps/web/coverage/.tmp/coverage-0.json'`, failing the whole
   `pnpm verify` run (32/33 other tasks green).
4. Re-run `pnpm --filter @candleviewer/web run test:cov` alone (or re-run
   `pnpm verify` again) — it passes.

**Impact:** a new joiner's very first `pnpm verify` (the README's documented
"reach a green gate" step) can fail on a transient, reproducible-on-first-run
error that looks like a real bug but is a task-ordering/stale-directory
artifact of `apps/web`'s `coverage/.tmp/` output directory under Turbo's
parallel scheduling. Erodes first-hour trust exactly as this ticket's Context
section warns about (R10 key-person: the author's warm cache never hits
this).

**Suggested fix direction:** ensure `apps/web`'s `test:cov` script (or a
`pretest:cov` hook) creates/clears `coverage/.tmp/` before `vitest run
--coverage` writes to it, rather than assuming Vitest creates the directory
race-free under Turbo's concurrent task graph; alternatively pin
`vitest`'s coverage `all`/`clean` options so the directory is guaranteed to
exist before the first write.

## BUG-2 (P2) — `services/api` unit gate: hypothesis deadline flake in `test_never_drop_property.py`

Filed: [#1536](https://github.com/CandleViewer/CandleViewer/issues/1536)

**Session:** 1. **Area:** `services/api/tests/unit/bus/test_never_drop_property.py`.

**Repro:**

1. From `services/api/`, cold: `uv run pytest -m "not integration" --cov=.
--cov-fail-under=85`.
2. Observe `test_never_drop_stream_is_prefix_preserving_under_any_stall_pattern`
   fail with `hypothesis.errors.FlakyFailure` wrapping a
   `DeadlineExceeded` (`253.35ms` vs the default `200ms` deadline on the
   first pass; `16.31ms` on Hypothesis's own shrink re-run of the same
   example) — Hypothesis reports this as "Unreliable test timings!" rather
   than a functional failure.
3. Re-run the same file/test alone — passes.

**Impact:** same class of first-hour trust erosion as BUG-1, specifically on
a machine/run that is momentarily slower than the author's (cold JIT, other
worktree's pytest workers competing for CPU in this session, disk I/O
contention, etc.) — plausible on any new joiner's first run before their
machine's caches are warm.

**Suggested fix direction:** either raise or disable the `@settings(deadline=
...)` for this specific property test (its assertions are about
prefix-preservation, not timing) or mark it `deadline=None` per Hypothesis's
own suggested remediation in the failure message — this is the correct,
minimal fix and does not weaken the property under test.

## BUG-3 (P2) — README's `make up` port-conflict Troubleshooting list is incomplete and one entry is wrong

Filed: [#1537](https://github.com/CandleViewer/CandleViewer/issues/1537)

**Session:** 2 (static). **Area:** `/README.md` Troubleshooting section vs.
`infra/compose/docker-compose.yml`.

**Repro:** compare `README.md`'s line "will hang if `5432`, `8000`,
`8812`/`9009`, `9090` or `3000` are already bound by another local service"
against the compose file's actual `ports:` mappings:
`postgres 127.0.0.1:5432`, `questdb 127.0.0.1:8812/9009/9000`,
`api 127.0.0.1:8000`, `prometheus 127.0.0.1:9090`,
`grafana 127.0.0.1:3001:3000` (host `3001`, not `3000`), plus
`minio 127.0.0.1:9002/9003` (cold profile).

**Impact:** a joiner debugging a Grafana port conflict per the doc would
check/free host port `3000`, which is not the port docker-compose actually
binds (it's `3001`); the doc also omits `9000` (QuestDB's HTTP console).

**Suggested fix direction:** update the Troubleshooting line to list actual
host-side ports: `5432, 8000, 8812, 9009, 9000, 9090, 3001` (core+obs
profiles) `and 9002/9003 if using --profile cold`.

## BUG-4 (P1) — Compose image digests are well-formed placeholders, not real resolved digests

Filed: [#1538](https://github.com/CandleViewer/CandleViewer/issues/1538)

**Session:** 2 (static). **Area:** `infra/compose/docker-compose.yml`.

**Repro:** read the file's own header comment (lines 3–11): it discloses
that because the E02-T08 author's environment also had no Docker, the
`sha256:` digests for `postgres`, `questdb`, `prometheus`, `grafana`, and
`minio` are syntactically valid placeholders, not digests resolved via
`docker pull && docker inspect`. Confirmed the digests are still present in
this checkout (`grep image: infra/compose/docker-compose.yml` — 5 image
lines, all still carrying the placeholder note's described shape).

**Impact:** `docker compose up` / `make up` will fail to pull any image on
the **first real run on any machine**, anywhere, until each digest is
re-resolved against a real registry pull — this is the true, currently-
unverified blocker behind Session 2's inability to dynamically confirm AC1
("all six services reach healthy"). Tracked already as residual **R4** in
the E02-X01/E02-X02 threat model per the file's own comment, but as of this
charter it has not yet been closed, and no session (author's or this one's)
has actually driven `make up` to a healthy stack end-to-end.

**Suggested fix direction:** on the first machine in the fleet with Docker
available, run `docker pull <image>:<tag> && docker inspect --format
'{{index .RepoDigests 0}}' <image>:<tag>` for each of the 5 pinned images
and replace the placeholder digests in place; re-run
`infra/scripts/lint_compose.py` to confirm shape compliance; then execute
this ticket's Session 2 dynamically to close AC1/AC3 for real.

## NOTE-1 (P3, tracking only) — `/mnt/c` vs WSL-filesystem AC2 needs an empirical run

**Session:** 1. **Area:** environment/tooling, not code.

Session 1 verified the `/mnt/c` warning is **present and correctly worded**
in `README.md`'s Troubleshooting section (satisfying AC2's "the warning is
verified to be present" branch), but could not empirically confirm the
underlying claim (dramatic slowdown / stale-file errors under `docker
compose` on `/mnt/c`) because no WSL Ubuntu distro was available on the
non-author machine used for this charter. Not a bug — recorded so a future
WSL-equipped charter run can close this specific empirical gap before E02's
overall QA sign-off, per this ticket's own Coverage-assessment guidance.
