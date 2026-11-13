# E49 exploratory harness

- Ticket: E49-Q02 (#1336). Index and rules: `docs/qa/charters/E49-README.md`.
- Code: `apps/web/e2e/exploratory/` (`harness.ts`, `playwright.explore.config.ts`, `run-<n>.explore.ts`).
- Scope: a way to run a charter session that is recorded, repeatable and cannot reach the network (tier A; tier B
  has its own note below). It is
  not a test suite: no CI job runs it and it never gates a PR.

## §1 What the harness gives a session

| Piece                                       | What it does                                                                                                                                                                                                   |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Egress guard (`@candleviewer/fixtures/e2e`) | Aborts every request and page socket that leaves the loopback interface (sockets opened inside shared or service workers are not seen); the session fails on any hit (C-13.5). The same guard as the PR lane.  |
| Session stubs (`apps/web/e2e/support/`)     | `stubSession` signs in Owner, Manager or Viewer on recorded-shape stubs (22-api-openapi.yaml examples): stub values only, no credential.                                                                       |
| Session log (`log.note`)                    | Append-only JSONL per session: charter, step, route, role, oracle id, result (`ok`, `suspect`, `info`), note. Never fails on an observation.                                                                   |
| Page-error and API-status capture           | Every uncaught page error and console error is a `suspect` note (O-ALL.1; the count is raw, one repeated console line counts per page); every `/api/` answer of 400 or above is an `info` note (path, status). |
| Focus probe (`focused`)                     | The focused element per Tab press, numbered per element, with a visible-focus check: the keyboard-only segment (03 §12).                                                                                       |
| Recording                                   | Playwright video, trace and a final screenshot for every session (`trace`, `video`, `screenshot`: `on`), in the git-ignored `apps/web/test-results/explore/`.                                                  |

The lane is separate by file name: sessions end in `.explore.ts`, which the PR lane (`*.spec.ts`), the
a11y collectors (`*.collect.ts`) and the real-backend lane (`*.real.ts`) never match. The PR lane's
`--list` is identical with and without this directory (PR 1 evidence).

## §2 Seeded-stack recipe

**Tier A, browser on stubs (any machine with the workspace set up; what run 1 used).**

```sh
pnpm i --frozen-lockfile
pnpm exec turbo run build --filter=@candleviewer/web...   # builds the packages the app imports, then dist/
cd apps/web
pnpm exec playwright test -c e2e/exploratory/playwright.explore.config.ts
```

- Build first: `vite preview` serves whatever `dist/` holds, so a stale build gives a stale session. A
  bare `pnpm build` inside `apps/web` fails until `packages/ui` has been built once (its token CSS).
- The preview runs on `127.0.0.1:4174` (`CV_EXPLORE_PORT` to change it), never reusing another server.
- One worker, no retry: a session runs in order and its log is not interleaved.
- Navigate with absolute URLs (`http://127.0.0.1:<port><path>`): a path that starts with `//` is
  otherwise read as a host, which the egress guard then blocks (run 1, E49-R1-07).

**Tier B, a local seeded backend (a docker host with compose v2, uv, pnpm, openssl and curl).**

```sh
tools/qa/explore_stack.sh [--bind 127.0.0.1] [--api-port 8000] [--preview-port 4174] [--skip-build]
```

- It follows the real-backend CI lane (`.github/workflows/e2e-auth-real.yml`): Postgres and QuestDB from
  compose, migrations, the API on the host (testnet, synthetic feed, test clock), and the built SPA behind
  `vite preview` with `e2e/vite.real.config.ts`, which proxies `/api/v1` to the API (one origin).
- It seeds one Owner, one Manager and one Viewer with `services/api/scripts/seed_fixture_user.py`. The
  password and each TOTP seed are made per run into a mode-0700 directory under `$TMPDIR`, are never
  printed, and are removed on exit. The script prints the three usernames, the preview URL and the run
  directory name only.
- Refusals (exit 2, before anything starts): docker, compose, uv, pnpm, openssl or curl missing; a bind
  address (`--bind`, `CV_BIND_HOST` or `CV_METRICS_BIND`) that is not loopback; `CV_ENVIRONMENT` other than `testnet`; any `CV_BYBIT_API_*` variable set; a stack port (5432, 8812, 9009, 9000 or the two chosen ports) already in use;
  a chosen port outside 1 to 65535, or the two chosen ports equal.
  `scripts/tests/test_explore_stack_refusals.py` covers them without docker.
- Ctrl-C (or any exit) stops the API and the preview process groups and runs `docker compose down -v` under a
  per-run compose project name, so it never touches another stack. If the API or the preview exits on its own,
  the script stops and removes everything.
- Network: tier B runs `uv sync --frozen` and `pnpm i --frozen-lockfile` and may pull compose images, so it
  can reach the network; the egress guard is on the Playwright side only and the script adds none.
- Platform: Linux / WSL only (the script and its tests use POSIX process groups and `/proc`).
- Limits: no exchange and no order path, no Demo or live credential, and the exchange is not faked
  either. Only the surfaces C7 (admin and RBAC) and C8 (cross-feature, the built screens) probe are
  reachable; charters 1 to 6 need screens and an exchange fake this tier does not have.
- Recording rule for tier B: pages hold real session values and TOTP codes, so Playwright `trace`,
  `video` and `screenshot` stay off (as in the CI lane) and a tier B session keeps only the session log
  (paths and statuses). A human who screen-records does it at display level with the sign-in done off
  camera. Before anything from a tier B run is attached to the epic, run the repo's artefact secrets
  checker (`security/zap/check_artefact_secrets.py`) over it.
- Tier A recording (§1) is unchanged: it holds stub values only.

## §3 Writing a session

```ts
import { test } from "./harness";
test.describe("C7 …", () => {
  test.use({ charter: "C7" });
  test("probe", async ({ page, log }) => {
    /* drive the page; log.note({ step, route, role, oracle: "O7.1", result, note }) */
  });
});
```

- Notes are neutral and short; no body, token or header is ever logged (only paths and statuses).
- An observation is never an `expect`: the triage of the run record decides what it is.

## §4 From log to run record

1. Collect the logs: `cat apps/web/test-results/explore/*/attachments/session-log-*.jsonl`.
2. Group the `suspect` and `info` notes by oracle; open the trace or video of each group.
3. Each distinct candidate becomes one row of the run record (schema in the README), dispositioned.
4. Security-class candidates leave the log for the private route (SECURITY.md); the record keeps a count.
5. Evidence paths in the record name the session folder; the folder itself is not committed.
