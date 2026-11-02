# E49 exploratory harness

- Ticket: E49-Q02 (#1336). Index and rules: `docs/qa/charters/E49-README.md`.
- Code: `apps/web/e2e/exploratory/` (`harness.ts`, `playwright.explore.config.ts`, `run-<n>.explore.ts`).
- Scope: a way to run a charter session that is recorded, repeatable and cannot reach the network. It is
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

**Tier A, browser on stubs (any machine with the workspace installed; what run 1 used).**

```sh
pnpm install --frozen-lockfile
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

**Tier B, the seeded backend (a docker host; not run in PR 1).** `infra/compose` brings up Postgres,
QuestDB and the API; the exchange is the in-process fake trading port
(`services/api/candleviewer/exchange/base/fakes.py`) with recorded fixtures from `packages/fixtures`.
Seed data: synthetic, namespaced `test-` / `fixture-` users and Demo accounts (03 §13). The SPA is served
by `vite preview` with `e2e/vite.real.config.ts`, which proxies `/api/v1` to the API (one origin). No
Demo, testnet or live key is used for exploration; testnet is connectivity smoke only (03 §17, RSK-014).
Charters 1 to 4 and 6 need this tier, plus an injected-fault switch for the 03 §9 scenarios.

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
