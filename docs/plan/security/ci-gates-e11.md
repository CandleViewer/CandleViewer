# CI security gates for the chart engine (E11-X02)

> Owner: `@CandleViewer/security`. Ticket: E11-X02 (#392). Threat model:
> `docs/security/threat-models/E11-chart-engine.md` (CE-T01, CE-T02, CE-T11, CE-T20, CE-D01,
> CE-I02, CE-I03, CE-I09, CE-E02 to CE-E05, CE-E08; findings F-07, F-09, F-11, F-15). Programme
> rules: `docs/plan/04-security-program.md` section 12.2 (Semgrep, CI-SEC-006 suppressions). This
> page explains each gate; the rule files are the source of truth for what is matched.

## Running locally

- Lint and graph: `pnpm --filter @candleviewer/chart-engine exec vitest run --project unit test/guards`
  (each rule against an in-memory or temporary violation and its negative, dependency-cruiser
  included) and `pnpm lint`.
- Semgrep fixtures: `python tools/ci/check_semgrep_rule_tests.py`; each rule's fixture is a tree,
  `.semgrep/tests/<rule-id>/packages/chart-engine/src/...`, staged at those paths, with an `ok` file
  outside the rule's paths where the scope is the point.
- Python guards: `pytest scripts/tests/test_check_secrets_hygiene.py
scripts/tests/test_check_prod_bundle_handles.py scripts/tests/test_self_hosted_runner_triggers.py`.

## How these gates run

No new required-check name (C-9.1). ESLint runs in `lint`. The dependency-cruiser rules run in
`unit-engine`: `test/guards/c216-boundary.test.ts` cruises the real `packages/chart-engine/src` with
every `chart-engine-*` rule (plus `packages-not-to-apps` and `not-to-unresolvable`) and fails on any
violation, beside the planted-violation tree that proves each rule bites. The required
`architecture` check runs import-linter only; `pnpm arch` runs depcruise over the whole repo
locally. The Semgrep rules run in `semgrep-bandit` (`_job-security.yml`, every `.semgrep/cv-*.yml`,
the fixture checker first), where `ERROR` blocks and `WARNING` reports (`security_gate.py`); the
fixture check in `python scripts/check_secrets_hygiene.py all`; the bundle guard after the web build
(`_job-js.yml`); the runner test in the governance shards (`governance.yml`,
`tools/ci/governance_shards.py`), which run `scripts/tests`.

## The boundary (CE-E04, CE-T20)

`chart-engine-src-relative-only` is an allowlist: `packages/chart-engine/src` imports only its own
files, type-only imports included (`tsPreCompilationDeps`). A package nobody thought to name fails as
surely as React. `chart-engine-no-app-state` (zustand, jotai, redux, mobx, valtio, rxjs, xstate,
`@tanstack/*`) and `chart-engine-no-io-client` (axios, ky, ofetch, undici, ws, node-fetch,
socket.io-client, `node:http` and the other socket modules) fire beside it so the message says why.
`test/guards/package-deps.test.ts` keeps `package.json` free of runtime dependencies: the engine runs
in a worker inside the trading origin, and a new runtime edge needs an ADR and a C-12.3 review.

## No I/O, and the IndexedDB exception (CE-E04)

ESLint bans `fetch`, `XMLHttpRequest`, `WebSocket`, `EventSource`, `WebTransport`,
`RTCPeerConnection`, `RTCDataChannel`, `BroadcastChannel`, `localStorage`, `sessionStorage`,
`indexedDB`, `caches` and `cookieStore` as globals and through `globalThis` / `self` / `window`, by
name or by a string key (`self["fetch"]`); `sendBeacon` and `navigator.storage` however they are
reached. A computed key that is not a literal (`self[k]`), an alias (`const g = self`) or a cast
(`globalThis as X`) of the global object fails too, since each hides a name from the ban; the worker
entry's one typed alias of its scope (`src/worker/render-worker.ts`) is the exception.
`indexedDB` read off any other object (a structurally typed scope: `scope.indexedDB`,
`scope["indexedDB"]`) fails as well, so a typed worker or page scope is no way round the ban.
`src/text/**` alone drops `indexedDB`, for E11-S11's SDF atlas cache (TM DS1): the database is opened
in `src/text/idb-store.ts` only, and the browser glue (`src/worker/text-platform.ts`) hands it its
scope; the inline host builds that glue on the document's own view (`defaultHostEnv`), never on an
alias of `globalThis`. Network and the other storage stay banned there, and `src/textual/` is not `src/text/`. `noInlineConfig` covers all of
`packages/chart-engine/src/**`, so no `eslint-disable` comment lifts a ban (the repo's
`no-inline-suppression-paths.json` stays the drawing paths, as it must equal the drawings rule's).
Not covered: a DOM-reached beacon such as an image `src` set from the host; the html-sink rule
flags a non-literal `src` / `href` write in the engine instead.

## No dynamic code (CE-E03)

ESLint `no-eval`, `no-new-func` and `no-implied-eval` (a string timer) on `src/**` and `bench/**`,
and no code loader: no `import()` expression, no `importScripts` call, no `Blob` or object URL (the
CSP's `worker-src 'self' blob:` would run one as a worker), and `new Worker` / `new SharedWorker`
only in `src/worker/host.ts`, which loads the bundled same-origin URL.

### cv-engine-shader-source-dynamic

`shaderSource` is called only inside `ProgramCache` (`src/gl/program-cache.ts`), with a
`ProgramSource` field unchanged. A source built by concatenation, a template with a substitution or a
call (`.replace`, `.join`) is GLSL made from data; the shader modules' own literals are ESLint's
(`src/gl/shaders/**`, no `${}`). 0 findings at E11-X02.

## cv-engine-html-sink

F-07, CE-T11. The sinks of `cv-drawings-text-to-html-sink` without its JSX arms, its CSS-string
arms included (`cssText`, `insertRule`, `setAttribute("style", ...)`), plus an inline handler
attribute (`setAttribute("onclick", ...)`), any `setAttribute` whose name is not a literal,
`setAttributeNS`, `Reflect.set` on an element, `outerHTML +=`, every `parseFromString` mode, a
`script` / `iframe` / `object` / `embed` / `base` / `link` / `meta` element, a non-literal `src`,
`href`, `action` or `location` write and the `location.assign|replace` / `window.open` navigations,
over
`packages/chart-engine/src/**` except `src/layers/drawings/**` (the drawings rule's). The DOM mirror
(E11-S13) and the host write `textContent` and single attributes. 0 findings at E11-X02
(`host/motion.ts` and `host/scale-badge.ts` use `textContent`). The handler-property arm
(`el.onclick = "..."`, a template or a concatenation) skips a function value: after E11-S11 PR A
(#5296) its IndexedDB callbacks (`r.onerror = () => reject(new Error("..."))`) matched through the
string inside the arrow; a function is code the bundle shipped, and the fixtures now hold both sides.

## cv-engine-proto-pollution

F-15, CE-E02. `__proto__` reads and writes, `Object.setPrototypeOf`, `Reflect.setPrototypeOf`,
`Object.assign` from anything but an object literal, keyed copies (`t[k] = ...` over `for...in`,
`Object.keys`, `Object.entries`, block- or expression-bodied `forEach`, a key-by-key `reduce`), a
recursive merge (a key walk that calls its own function), a prototype write (`X.prototype.y = v`,
`X.prototype = v`, `x.constructor.prototype`), `Reflect.set`, `Object.defineProperty` with a
non-literal key, `Object.defineProperties`, and a write keyed by a received field
(`t[msg.key] = v`). 0 findings at E11-X02; `hit/ObjectIndex.ts` assigns from a literal it builds.
The rule found the worker runtime's per-store element counts keyed by the received store id
(`inst.elements[msg.store] = n`; `rejectReason` had already checked the id against the closed store
set): the counts are now a `Map`, so no received value keys an object write. Semgrep folds
`for...of` into `for...in`, so an indexed write in a `for...of` reads as a keyed copy too: E11-S11's
shelf packer (`text/shelf-packer.ts`, typed-array writes by its own index order) uses an index loop.

Both this rule and `cv-engine-html-sink` exclude the two pure re-export barrels
`src/scene/index.ts` and `src/viewport/index.ts`: Semgrep 1.181 cannot parse TypeScript 5.0's
`export type * from`, and the gate fails a `PartialParsing` error on a repo rule (CI-SEC-005).
Both files hold only re-exports, so no rule match is lost. Revisit: drop the excludes once the pinned
Semgrep parses `export type *`. A new barrel names its types instead (`src/text/index.ts`,
`export type { … } from`), so it needs no exclude.

## cv-ws-wire-count-alloc-ts over the engine (F-11)

`packages/chart-engine/src/model/**` and `src/worker/**` join the rule's paths (BQ-160): 0 findings
over both at E11-X02. After E11-S11 PR A (#5296) it found the font `cmap` reader
(`worker/text-platform.ts`): format 4's segment count and format 12's group count sized their loops
unchecked; each is now compared with the bytes the table holds first, and a table that claims more
maps nothing. Its fixture moved into a tree so the engine paths are proven.

## cv-engine-typed-array-index-unchecked

CE-T01, CE-T02, CE-D01. A value from a worker message (`msg[...]`, `event.data`, a `DataView`
getter, a `layout` field) that indexes an array with no bound before it: an upper-bound comparison in
an `if` that refuses, `assertFits`, `layoutBytes` or `Math.min`. Paths `src/worker/**` and
`src/model/**` only (BQ-161).

Limits, so nobody reads more into a quiet run than it proves: intra-procedural (a value checked in
`rejectReason` and used in the runtime's handler is not followed); sources are bracket reads off a
receiver literally named `msg`, `message`, `payload`, `raw` or `cmd`, so an alias (`const m = msg`)
and the typed dot access the runtime uses after `rejectReason` (`msg.layout.count`, except through
the `layout` source) are not sources; the `if (... > ...) return` sanitizer accepts any `>`
comparison, a lower bound included, and `Math.min(...)` sanitizes whatever it is given. The
protocol tests (`worker/protocol.test.ts`, the validation scenario) carry the boundary; the rule
catches the obvious regression.

## cv-engine-decoded-nonfinite

CE-T02. Arithmetic or a `Math.*` call on such a value (a float read, for `DataView`) with no
`Number.isFinite`, `finite`, `Number.isInteger` or `Number.isSafeInteger` check first. Same paths
and the same intra-procedural limit.

Sites over `src/` at E11-X02's head (the local scan of this PR):
`cv-engine-typed-array-index-unchecked` 51 findings, `cv-engine-decoded-nonfinite` 4 findings, all in `worker/protocol.ts` (`rejectReason`,
`concatBatches` and the decoders after it). They are reported at `WARNING` (non-blocking) until a
follow-up drives both counts to 0. Fixed in this PR rather than left: `rejectReason`'s input row count
(read once, checked `Number.isSafeInteger`), `concatBatches` (both counts and every column width
checked; a malformed pair stays unmerged and `rejectReason` refuses it by name; `protocol.test.ts`
"concatBatches refuses a malformed layout"), and `worker/runtime.ts`'s `data` handler (the count,
already checked by `layoutBytes`, checked again locally).

## Status of the two taint rules (BQ-162)

Both stay `WARNING` (non-blocking: `security_gate.py` maps it to MEDIUM, under the HIGH block line)
in this PR, because each reports findings over `src/` today (the counts above). Each turns
`ERROR` in a follow-up PR that drives its count to 0 and shows 0 findings over main, owned by `@CandleViewer/security` with
E11-X02's lane, target 2026-11-14 (proposed); until then the threat-model rows that cite them say
"WARNING, non-blocking" in their status.

## Fixture content (CE-I09)

`python scripts/check_secrets_hygiene.py engine-fixtures` (and `all`, which CI runs) reads every text
file under `packages/chart-engine/test/` and `bench/`, matrix results included, and fails naming the
file, the line and the pattern, never the value: an `accountId`, `orderId`, `orderLinkId`, `uid`,
`userId`, `email` or `apiKey` field holding a quoted value or a number of 5+ digits, an e-mail
address (not `example.*`, `.test` or `.invalid`), or the hygiene key shapes. Values starting
`fixture-`, `synthetic-`, `test-` or `DUMMYKEY_` pass (BQ-166). `check_fixtures` skips `/test/`
paths, so it could not be extended. Gitleaks scans the whole tree, the package included.

## Debug surface (CE-E05)

`tools/ci/prod-bundle-forbidden-handles.json` gains `__engine` (any `window.__engine*` global and the
`/__engine-harness` route, by substring) and `runBenchScene` (the `./bench` entry), each with
`threat: CE-E05`, `requirement: E11-X02` (BQ-165). The positive control, a harness build that exposes
them, is E11-Q02's (G-39).

## Diagnostics allowlist (CE-I03)

Not here: `copyDiagnostics()` does not exist until E11-T07 (#523), which owns the allowlist test
(no `accountId`, F-10; `runMode`, F-14). Gap G-38 (BQ-164).

## Self-hosted runners (CE-E08)

`scripts/tests/test_self_hosted_runner_triggers.py`: every job whose `runs-on` names `self-hosted`
(or an expression that could) sits in a workflow with no `pull_request`, `pull_request_target`,
`merge_group` or `workflow_call` trigger, and a `workflow_run` job pins the triggering run to a push.
Fork pull requests need approval before any workflow runs: the repository setting is
`all_external_contributors` (2026-10-31, BQ-167). Runner hardening proper is E03's.

## SCA

The engine has no runtime dependency. Its dev dependencies are pinned by the frozen lockfile and
watched by Dependabot (npm at `/`) and `pnpm audit`; Playwright, pixelmatch and fast-check are not
engine dependencies (G-41). The response SLA is SR-134 (`04-security-program.md`) under C-12.3.

## Requesting an exception

Fix the code if you can. Otherwise add
`// nosemgrep: <rule-id> reason=<token> owner=@<handle> review=YYYY-MM-DD` (CI-SEC-006, at most 180
days) on the line above the finding, tag `security-review`, and list the site here. An ESLint or
dependency-cruiser exception is a change to the rule itself, reviewed by the security CODEOWNER.
