# CI security gates for the drawings persistence surface (E14-X03)

> Owner: `@CandleViewer/security`. Ticket: E14-X03 (#549), in slices (the persistence rules, the
> render-path guards, the production-bundle guard, then the nightly DAST profile and the wrap-up
> with the carried gaps). Threat model: `docs/security/threat-models/E14-drawings.md` (DR1, DR5 to
> DR7, DR9, DR10, DR12, DR20, DR21, DR23, DR29, DR30, section 4; DR8, the SDF text layer, has no gate
> here). Programme rules: `docs/plan/04-security-program.md` section 12.2 (Semgrep composition,
> CI-SEC-006 suppressions) and 16.2 (exceptions). This page explains each gate; the rule YAML is the
> source of truth for what is matched.

## Running locally

- Validate: `semgrep --metrics=off --validate --config .semgrep`.
- Prove the exception sites, in a git checkout (Semgrep reads no file of a path-scoped rule's
  subdirectory target outside one, and the pin then fails as having scanned nothing):
  `python tools/ci/check_drawings_exception_sites.py`.
- Prove the fixtures: `python tools/ci/check_semgrep_rule_tests.py`. Every rule needs at least one
  `# ruleid: <id>` line and, since E14-X03, one `# ok: <id>` line: a line a naive rule would flag.
  The checker cannot tell an `ok` line a rule scans from one outside its `paths.include`: place
  yours in scope.
- Fixtures are trees, `.semgrep/tests/<rule-id>/<repo path>/...`, staged at those paths, with a PEP
  695 file where the real file has generics (`api/drawings*.py`): Semgrep parses it another way
  (#3549).
- The render-path guards: `vitest run test/features/drawings-lint-ban.test.ts` (in `apps/web`) and
  `python tools/ci/check_no_inline_suppressions.py`.
- The bundle guard, after a web build:
  `python tools/ci/check_prod_bundle_handles.py --dist apps/web/dist`. The nosniff pin, in
  `services/api`: `pytest tests/drawings/test_drawings_nosniff.py`.

## How these gates run

`_job-security.yml` passes every `.semgrep/cv-*.yml` to `semgrep scan` and runs the fixture checker
in the same job: no new required-check name (C-9.1; the one step added is below); `ERROR` blocks
(`security_gate.py`), so the whole-tree scan keeps `services/api` at zero unsuppressed findings.

**The four exceptions below are pinned by statement, not by count.**
`tools/ci/check_drawings_exception_sites.py` scans `services/api/candleviewer` with the five rules and
`--disable-nosem`, names each finding by its file and the statement it opens (`_PURGE`), and compares
them with `tools/ci/drawings-exception-sites.json`. The `semgrep-bandit` job runs it, so a fifth
unscoped statement, or an annotation moved to another statement of the same file, fails the job (the
pin, with the whole-tree scan's zero-finding gate beside it) until an entry in the list lands,
reviewed under C-10.1: the list is not a C-10.2 path, so it needs no security-team approval (a count
of (file, rule) pairs passed both). A scan that read no file, or left a target unread for a reason
other than configuration, fails too. `scripts/tests/test_e14_security_gates.py` runs the same scan
where `semgrep` is installed (CI's governance shards have none, so that test skips there), checks
the annotations in the source against the list without it, and pins each rule's metadata, scope and
doc section.

Every rule but the first is scoped by glob (`api/drawings*.py`; the batch rule also
`storage/repositories/drawings*.py`): a router moved into a package `api/drawings/`, or a
`drawing_*.py` module, is out of scope until the globs are widened. The render-path guards (PR-2)
follow the persistence rules; the nightly ZAP profile is under DAST below.

## Reviewed exceptions

Four statements are unscoped by design. Each has a comment-only
`nosemgrep: cv-drawings-query-missing-owner-filter reason=<token> owner=@basiltt review=2027-03-25`
on the line above it, with its rationale (CI-SEC-006: review within 180 days, policed by
governance): `_EXISTS_OTHER` (asks whether an id is another owner's; a bool; DR20), `_PURGE`
(retention, no caller; DR35) and `_COUNT_LIVE` (the all-owner rows gauge; DR25) in
`drawings_sqlalchemy.py`, and `_PURGE_LAYOUTS` in `workspaces_sqlalchemy.py` (its correlated
`SELECT ... FROM drawings` looks for live drawings of any owner under a layout it would purge;
E15-T01's spec decision on #402, SR-E14-09).

## cv-drawings-query-missing-owner-filter

- **Protects:** DR1, DR12, DR20, DR21; SR-051, C-12.4. `scope: self` is a data-layer promise.
- **Matches:** a `SELECT`, `UPDATE`, `DELETE` or `INSERT ... SELECT` on `drawings` with no
  `WHERE|AND|ON owner_user_id = :owner` predicate (a `SET owner_user_id = ...` is a transfer, not a
  scope), as text SQL (`text(`, `execute(`, `fetch(` ... or an assignment whose first literal opens
  with the verb; any `r`/`u`/`f`/`b` prefix) or as a Core `select`/`update`/`delete` of the table,
  bare or module-qualified (`drawings`, `m.drawings`, `models.drawings`), with no
  `.where(... owner_user_id == ...)`. Scope: `services/api/candleviewer/**`, not migrations. Fix:
  add `AND owner_user_id = CAST(:owner AS uuid)`, or annotate with a reason.
- **Does not match:** `INSERT ... VALUES` (an upsert too), `drawing_templates`, text built before
  the call (`cv-no-raw-sql-interpolation` owns construction). The predicate is looked for, not
  parsed: one under `OR`/`or_()`, `not_()` or `~`, in a subselect, in a SQL comment, or compared with
  any right-hand side (`== body.owner_user_id`) passes (the repository's unit test covers its
  constants). Not seen: comma joins, a literal that is returned or held in a dict, `MERGE`, anything
  after the first `+` of a `+`-joined statement, a name split after its schema qualifier
  (`"FROM public." "drawings"`, prefixed or not) or quoted (`"public"."drawings"`), a predicate on a
  joined table's `owner_user_id` (`JOIN layouts l ... WHERE l.owner_user_id = :owner` passes), any
  bind named `:owner...` (`:owner_from_body` passes); in Core, `select_from(drawings)`, table
  methods such as `drawings.update()`, a table held in a variable or an attribute (the class-based
  repository's idiom, `self.table = m.drawings`), `sa.table("drawings")` and
  `getattr(m, "drawings")` (Core is unused for drawings today).
- **Deliberate-regression fixture:** the `ruleid` lines of
  `.semgrep/tests/cv-drawings-query-missing-owner-filter/`, with the annotated multi-line statement
  that proves the marker placement the four exceptions use.

## cv-drawings-owner-from-body

- **Protects:** DR1; SR-051, SR-040. The owner is `principal.user_id`; request models are closed.
- **Matches:** the owner taken from request data (`request.query_params`, `path_params`, `headers`,
  `json()`; an attribute or subscript of `body`/`op`/`payload`; a `model_validate` result) as the
  store's first argument, an `owner`/`owner_user_id` keyword or dict key, or an owner-named
  variable; and an `owner`, `owner_id`, `owner_user_id`, `user_id`, `actor_user_id` or `created_by`
  field on a request model. Scope: `api/drawings*.py`. Fix: `str(principal.user_id)`; no owner field
  on a model.
- **Does not match:** `request` alone (`caller(request, ...)` stays clean), request data at a
  non-owner argument, response models (`..Out`, `..Response`, `..Row`). Search mode, not taint mode:
  one rule cannot hold the structural schema arm. Not seen: a handler parameter named `owner`,
  `getattr`, a non-owner-named intermediate, camelCase fields, a hoisted `repo = store()` receiver,
  a `user_id=` keyword or dict key; DR1's 422 test and the repository tests own the rest. **Fixture:**
  `.semgrep/tests/cv-drawings-owner-from-body/`.

## cv-drawings-unbounded-geometry

- **Protects:** DR29, DR30 (DR10); SR-040; section 4. The bounds are `DrawingIn._tool_rules`,
  `POINT_COUNTS` and the caps in `drawings_models.py`; storage validates no geometry or style.
- **Matches:** `DrawingFields(` outside `_fields`; `dataclasses.replace(...)`;
  `model_construct(...)`; `model_copy(update=...)`; `extra="allow"` or `"ignore"`; a dict display
  given to the store's `create`, `update` or `apply_batch`. Scope: `api/drawings*.py`. Fix:
  `_parse(DrawingIn, text)`, then `_fields(body)`.
- **Does not match:** `_ListQuery` (`extra="ignore"`: unknown query parameters are ignored, as
  FastAPI does), `model_copy()` without `update`. A tripwire on the roads round the validator, not a
  proof. Not seen: `__new__`, `Extra.allow`, a v1 `class Config`, a dict held in a variable or built
  by `dict(geometry=...)`, a free-form `dict`/`Any` field on a request model. **Fixture:**
  `.semgrep/tests/cv-drawings-unbounded-geometry/`.

## cv-drawings-batch-unvalidated-ids

- **Protects:** DR12, DR21, DR23; SR-051. Invariant: the owner-scoped snapshot precedes every UPDATE
  or DELETE of existing rows.
- **Matches:** in `storage/repositories/drawings*.py`, `_UPDATE_MANY` or `_SOFT_DELETE_MANY` run
  with no earlier `_SNAPSHOT` in the same function; in `api/drawings*.py`, an `update`,
  `soft_delete` or `create` on any receiver (`store()` or a hoisted `repo`; a dict's `update` too)
  in a loop or comprehension over `ops`/`operations`. Fix: hand the whole batch to
  `store().apply_batch(owner, ops)`.
- **Does not match:** `_INSERT_MANY` (a create touches no existing row; a key collision is refused
  atomically). A structural heuristic: not seen are a snapshot taken in a helper, `enumerate(ops)`,
  `list(ops)`, a loop over `ids` or another name than `ops`/`operations`, a generator inside
  `gather` and an aliased constant. **Fixture:**
  `.semgrep/tests/cv-drawings-batch-unvalidated-ids/`.

## cv-drawings-pixel-geometry

- **Protects:** DR10. A correctness guard: the contract (`22-api-openapi.yaml`, `DrawingPoint`,
  `DrawingGeometry`, `additionalProperties: false`) stores chart space only, a time `t` and a price
  `p`.
- **Matches:** a field, dict key, subscript key or keyword named `x`, `y` or `px` in
  `api/drawings*.py`. Fix: convert pixels to chart coordinates in the client. The TypeScript arm
  follows in the render slice.
- **Does not match:** a comprehension or lambda variable `x` (as in `_parse_t`), a parameter.
  **Fixture:** `.semgrep/tests/cv-drawings-pixel-geometry/`.

## cv-drawings-text-to-html-sink

- **Protects:** DR6 (stored XSS), DR7 (the accessible-name path), DR9 (a style value in CSS);
  SR-E14-01, SR-E14-02, SR-E14-04. A label, a note and a template name are user text and the server
  encodes none of it: safety lives at the sink.
- **Matches:** raw HTML (`dangerouslySetInnerHTML`, `innerHTML`, `outerHTML`, `insertAdjacentHTML`,
  `setHTMLUnsafe`, `parseHTMLUnsafe`), `document.write(ln)`, `createContextualFragment`, `srcdoc`,
  CSS strings (`cssText`, `insertRule`, `setAttribute("style", ...)` with a non-literal), each also
  named by a string key (`el["innerHTML"] = s`, a local constant key included, which `no-unsanitized`
  does not read; `setAttribute("srcdoc" | "style", ...)` too), the raw-HTML keys and a non-literal
  `cssText` also by an `Object.assign` property bag (`Object.assign(el, { innerHTML: s })`), and
  `document.write(ln)` reached through strict TypeScript's `!` or `?.`
  (`frame.contentDocument!.write(s)`), and `href`, `src`, `style`, `aria-label`,
  `aria-description` or `title` built by `+` or a template with a substitution (JSX, `setAttribute`
  with the name in any case or a backtick string, a DOM property, `createElement` props). Scope: the paths of
  `tools/ci/no-inline-suppression-paths.json`. The message points to a React text child,
  `textContent` or `setAttribute(name, raw)`, never to stripping characters (it breaks RTL text and
  emoji).
- **Shell rule:** `cv-shell-dangerously-set-inner-html` bans the raw-HTML sinks under `features`,
  `lib`, `packages/ui/src` and more, but not in the literal drawing paths or the engine layer. This
  rule repeats them for its own paths, so the drawing invariant does not rest on another epic's
  scope; under `features/drawings` both fire.
- **Does not match:** a raw variable (`aria-label={label}`), a literal, a call (`t(...)`), a template
  without a substitution, a `style` object (the CSSOM path), a `data-*` attribute. It is syntactic:
  `aria-label={`${kind} ${label}`}` fires whatever it is built from (use `{label}` or
  `aria-labelledby`); with the scope removed it finds 5 such `aria-label`s in the frontend, none at
  a raw-HTML sink. Not seen: a conditional of templates, `.join`, `DOMParser`, a raw `href` from data,
  deliberate reflection (`Reflect.set(el, "innerHTML", s)`, a property descriptor's `set.call`), a
  `document` reached through an alias or in parentheses, an `Object.assign` bag's URL, name or
  `style` key, a computed key that is no literal, a bag held in a variable or a spread argument, an
  attribute name held in a variable, a string-keyed `setAttribute` of a URL or name, a module-scope
  constant key read inside a function declaration or a class method (inside an arrow or a function
  expression it is seen; a constant imported from another module never is), and `.mts` or `.cts`
  files, which Semgrep does not read (the lint ban covers only its `no-unsanitized` forms there: no
  `createElement` props, string keys or URL, name and CSS arms, and the engine layer has no raw-HTML
  lint). Fixture-proven until E14-S08.
- **Deliberate-regression fixture:** `.semgrep/tests/cv-drawings-text-to-html-sink/` (a `ruleid` per
  sink, form and root; the shell rule alone misses 62 of its 68, every string-key,
  `setHTMLUnsafe`, `style` and attribute-name form among them).

## cv-drawings-pixel-geometry-ts

- **Protects:** DR10, SR-040: the TypeScript arm of `cv-drawings-pixel-geometry`. The store holds
  and persists chart space only, a time `t` and a price `p`.
- **Matches:** in `apps/web/src/features/drawings/store/**`, an object with a key `x`, `y` or `px`
  (shorthand and a destructuring too) and a write `o.x = ...` or `o["px"] = ...`. Fix: convert pixels
  to chart coordinates in the engine first.
- **Does not match:** a read (`e.x`), a name that holds the letters (`max`, `xs`), anything outside
  the store: the engine works in pixels by design. Fixture-proven until E14-T02:
  `.semgrep/tests/cv-drawings-pixel-geometry-ts/`.

## The drawing render-path lint ban

- **Protects:** DR6, SR-E14-01. `apps/web/eslint.config.mjs` sets `no-unsanitized/method` and
  `/property` to error for `src/features/drawings`, `src/drawings` and `src/objecttree` (`.ts`, `.tsx`,
  `.mts` and `.cts`) and `react/no-danger` for their `.ts` and `.tsx`, with
  `linterOptions.noInlineConfig`: an `eslint-disable` or an `/* eslint <rule>: off */` there is inert
  and ESLint warns that it has no effect, which `--max-warnings=0` fails. Elsewhere a directive still
  works. `packages/chart-engine/eslint.config.mjs` sets `noInlineConfig` for `src/layers/drawings`, so
  no comment there lifts C-2.16's DOM ban either.
- **Proof:** `apps/web/test/features/drawings-lint-ban.test.ts` lints a virtual file under each path
  with the app's config, `.mts` and `.cts` probes, and an engine-layer probe with the engine's
  config; `projectService` refuses a virtual file even under the tsconfig `include`, so each is named
  in `allowDefaultProject`. No block in `packages/ui`: no object-tree component
  exists there. When one does, add its path to the list and a block to that config.

## tools/ci/check_no_inline_suppressions.py

- **Protects:** DR6, SR-E14-01: no silent suppression of the guards above; run by `_job-js.yml`'s
  `lint` job.
- **Matches:** in source files under the paths of `tools/ci/no-inline-suppression-paths.json`, a
  comment holding `eslint-disable[-next-line|-line]`, an ESLint config comment such as
  `/* eslint no-console: off */`, `@ts-ignore`, `@ts-expect-error` (as tsc reads them, with no word
  boundary after) or `nosemgrep` or any `nosem...` word that is no reviewed annotation:
  `reason=<token> owner=@CandleViewer/security review=YYYY-MM-DD` in the same comment (the grammar and
  180-day cap of `tools/ci/suppressions.py`, CI-SEC-006, which takes any `@handle`: on these paths
  only the security team may own one, the ticket's Security-engineer review). A marker that opens a
  line inside a block comment counts (ESLint reads `/*`, a newline and `eslint-disable` as a
  directive; tsc reads any run of `/` and `*` before `@ts-...`), and so does each marker of a line.
- **Does not match:** a word in a string, a Markdown file, a directory symlink or `@ts-nocheck`
  (typescript-eslint bans it). An annotated `eslint-disable` in a listed path still fails the lint:
  it is inert, so it warns.
- **Extending:** add a glob to the JSON. Tests keep the lists honest: the Semgrep rule's
  `paths.include` equals it, the ESLint proof lints a file under each `apps/web` entry, and a
  tripwire fails when a `drawing*` directory (camel-cased `drawingTools` too) or `object-tree*` name
  appears under `apps/*/src` or
  `packages/*/src` outside it. Fixture: `scripts/tests/test_check_no_inline_suppressions.py`.

## tools/ci/check_prod_bundle_handles.py

- **Protects:** DR5 (spoofing: a test-only handle in a production bundle), SR-E14-10.
  `__cvEngine.projectForTest` (E14-Q03) projects chart coordinates to pixels for a test; on a
  production page a script could use it to spoof where a drawing sits.
- **Matches:** a script file (`.js`, `.mjs`, `.cjs`) or a page (`.html`, `.htm`) of `apps/web/dist`
  that holds an identifier of `tools/ci/prod-bundle-forbidden-handles.json`, as a substring
  (`__cvEngineDebug` counts as `__cvEngine`). It runs in `_job-js.yml`'s `build` job after the
  Electron-hardening step, which builds `apps/web`, and reads that dist (no second build; a test pins
  the step's place and its `--dist`). A failure names the file, line, column, identifier, DR5 and
  SR-E14-10. A dist with no script file fails, whatever pages it holds, so a missing or half-written
  build never passes. Both of E14-Q03's names are registered already; E14-Q03 adds a positive
  control (an E2E build that exposes the handle).
- **Does not match:** source maps (`sourcesContent` holds the source of a correctly gated handle),
  other file types, a name built at run time. `release.yml`'s `build-sign-installer` has no web-build
  step (it only needs `apps/web/dist` to exist), so the guard sits where that build is made; a release
  is cut from `main`, which passed it.
- **Extending:** add an object to the manifest's `handles` with `identifier` (4 or more characters,
  matched as a substring), `threat` and `requirement`, each non-empty; the guard refuses any other
  entry, and an empty or unreadable manifest.
- **Deliberate-regression fixture:** `scripts/tests/test_check_prod_bundle_handles.py` builds
  synthetic dists: a handle in a `.js`, `.mjs`, `.cjs` or `.htm` file fails, one only in a `.map`
  passes, a clean dist passes, and one with no script file fails.

## test_drawings_nosniff.py

- **Protects:** DR6, SR-E14-01: the stored-XSS abuse cases rest on hostile text being inert JSON, and
  `nosniff` keeps a browser from reading it as HTML. `NoSniff` (#3990) already stamps every answer;
  nothing pinned it on `/drawings*`, and ZAP's passive rule 10021 is Low, under the gate of
  `security/zap/baseline_gate.py`.
- **Matches:** the deployed `create_app(Settings())` answers each of the five `/drawings*` routes,
  unauthenticated (a 401 or a 403), with one `X-Content-Type-Options: nosniff`; and it serves exactly
  those five, so a sixth must be pinned. No product code changed.

## DAST

- **Workflow:** `.github/workflows/dast-drawings-nightly.yml`, `schedule` (03:57 UTC) and
  `workflow_dispatch` only, **never on a pull request**. It calls `_dast-low-priv.yml` (#3991) with
  `role: manager` and a `fixture`: a throwaway stack on the runner (the compose data stores and the
  API on loopback), as `dast-market-nightly` does. "Staging" in the ticket is E17's target, and the
  harness refuses any target but loopback (`mint_sessions.py`): a run against it is the owner's call.
- **Plan:** `.zap/e14-drawings.yaml` imports `22-api-openapi.yaml` cut to `/drawings`,
  `/drawings/batch` and `/drawings/{drawingId}` by `security/zap/nightly_plans.py`, then runs an
  active scan for SQL injection, reflected XSS, command injection, path traversal and template
  injection, at most 8 minutes. Its `defaultThreshold` is `Off`, so only those rules run (the market
  and rules plans keep ZAP's defaults at Medium). Persistent XSS (40014) is listed, as in the admin
  plan, but attacks only the stored sinks that its companions 40016 and 40017 find, and they do not
  run: it tests nothing here. A label's stored-XSS sink is the SPA (DR6), whose gates are
  `cv-drawings-text-to-html-sink` and `test_drawings_nosniff.py`. The ticket's
  `security/zap/e14-drawings.conf` is a baseline-rule file, which cannot hold contexts, users or
  active policies; an automation plan is the form E12, E35 and E42 use.
- **Principals:** a Viewer cannot write drawings (DR38), so the scan role is a synthetic **Manager**,
  with a real TOTP method and no MFA exception. A synthetic Owner (TOTP too) signs in to seed one
  drawing with a fixed client id (`.zap/e14-drawings-seed.json`, a batch `create`) and again after the
  scan. ZAP's `{drawingId}` example names that id and its PUT body is valid for it, so the scan's
  PUT and DELETE can reach the owner check. Whether ZAP 2.17 sends the examples is not shown
  offline, and a batch `update` or `delete` needs the row's live `updated_at`, which no plan knows.
- **The check:** `security/zap/drawings_isolation.py verify` therefore writes to the Owner's row
  itself, as the Manager, before it judges the row. A batch `update` and `delete` carrying the token
  the seed returned must answer the batch 409 (`target_unavailable`, DR21); a PUT of the row's own
  input, its label changed, and a DELETE must answer the foreign 404 (`not_found`, DR20). A 2xx is a
  cross-owner write that succeeded (DR12); any other answer means the probe never reached the owner
  check, and it fails too. The check then requires the Owner's row exactly as seeded (no cross-owner
  write, DR12, DR21) and none of the Owner's rows in the Manager's list, read to its last page (at
  most 20 pages of 500; no cross-owner read, DR20), whatever ZAP raised: the AF `accessControl` job
  is used nowhere in this repo and is unverified in the pinned image, so ZAP's alerts do not judge
  it. The seeded rows stay under `$RUNNER_TEMP/cv`, out of the scan's writable mount, until the
  check has read them; then they join the artefact.
- **The documented refusals** (22-api) raise 90022 on their problem text: the foreign 404
  `not_found` (DR20), the batch 409 `conflict` with `target_unavailable`, `version_conflict` or
  `id_unavailable` (DR21), and `invalid_cursor`, `payload_too_large` and `validation_failed`. An
  `alertFilter` marks that alert "False Positive" on `/drawings*` only when its evidence holds one
  of those codes, never the problem media type alone. Injection and disclosure rules are never
  filtered. Whether 90022's evidence lands on a code is shown by the first run: the log names a
  waived alert, not a baseline entry.
- **Not here:** a body over 64 KiB is no plan literal (`test_drawings_abuse_exhaustion.py` covers the
  cap).
- **Baseline:** `.zap/e14-drawings-baseline.json` (empty at merge). `security/zap/baseline_gate.py`
  fails the job on any High or Medium alert whose `pluginId METHOD path` is not in it (entries need
  `reason`, `owner` and a `review` date). Triage is the SR-134 clock, as for E12: 48 hours, 7 days
  for a Medium.
- **First run:** a workflow must be on the default branch to be dispatched, so the first real run, one
  `workflow_dispatch`, and its baseline triage (a comment on #549) come after merge. Then the
  ticket's regression proof: one dispatch on a scratch branch whose drawings repository drops the
  owner filter from the soft delete (`_SOFT_DELETE`), or from both the read and the update (`_GET`
  and `_UPDATE`: the router reads the row before it updates it, so the update's filter alone is
  never reached), must go red on the check (the Manager's probes answer 2xx); its run is linked
  in a comment on #549 before the branch is deleted. Until then the plan is proven offline:
  `python security/zap/nightly_plans.py --profile drawings --out DIR` and
  `scripts/tests/test_zap_nightly.py`.

## CodeQL

`.github/codeql/codeql-config.yml` is untouched. The `codeql` job runs the action's default query
suite over `javascript-typescript` and `python`, which holds the XSS and `py/sql-injection` queries;
a query pack cannot be scoped to a path, and `security-extended` is repo-wide, left to E43 as for E12.
The ticket's custom taint source (a drawing's `label`, `text` and template name as user input) needs
an anchor for CodeQL's API graph on a runtime value, a `@candleviewer/protocol` decoder or the store
selector (TypeScript types are erased), and none exists until E14-T02 or E14-S08: it can be neither
written nor proven now. It lands with E14-T02, as a models-as-data extension; the deferral is a
comment on #549 (the filing freeze: no new issue).

## SCA

No sanitiser or geometry dependency exists, and E14 adds none: the backend sanitiser is the standard
library (`sanitize_text`, `drawings_models.py`) and the client renders text as text (`pnpm-lock.yaml`
holds no DOMPurify, sanitize-html or xss). The ticket's "SCA allowlist" is the licence allowlist
`tools/ci/licenses-allowlist.json` with C-12.3: a new dependency is pinned, justified, licence-checked
and has a CODEOWNER. A sanitiser library, should one be proposed, is security-critical: it needs an
ADR, a pinned version and an update watch, and the lockfile and licence gates already apply.

## Budget

The ticket asks for under 30 s added to CI. Measured with Semgrep 1.181.0 on the shared 8-vCPU VPS,
under `nice -n 10`:

- **Repo-wide scan:** the five rules over `services/api` (797 files, `--jobs 2`): 0 findings, 0
  errors. Their own matching is 0.74 s (`semgrep --time` at load 5 to 7:
  `cv-drawings-query-missing-owner-filter` 0.63 s over 20 files, slowest `db/models.py` 0.14 s; the
  other four 0.01 to 0.04 s each).
- **Fixture checker,** one `semgrep scan` per rule: 194.8 s wall (191.1 s CPU) for all 57 rules at
  load 6 to 9, and 412.9 s at load 8 to 13. The five new scans take 17.6 s wall at load 6 to 7, and
  took 30.3 and 31.5 s at load 8 to 13 against 34.4 and 36.1 s for five existing tree rules. A new
  rule costs one start-up, no more than an existing one, so the five add about 18 s on a quiet host
  and up to 30 s on a busy one: under the bound, then at it. Not measured on a CI runner.
- **PR-2's two rules** take 2.8 s and 4.4 s in the checker at load 5.6, and read no file in the product
  scan (their directories do not exist yet). With PR-1's five that is about 25 s on a quiet host, under
  the bound, and over it on a busy one.
- **The exception-site pin** (`check_drawings_exception_sites.py`) is one more `semgrep scan` of the
  five rules over `services/api/candleviewer` with `--disable-nosem`: 26 s of CPU and 51 s wall at
  load 17 on the shared VPS, of which the matching is about a second (the rest is Semgrep's start-up
  and the tree walk). It is a step of its own in `semgrep-bandit`, within that job's budget, and the
  part of this gate that goes over the ticket's 30 s when added to the rules above on a busy host.
  Not measured on a CI runner.

## Requesting an exception

Fix the code if you can. Otherwise add
`# nosemgrep: <rule-id> reason=<token> owner=@<handle> review=YYYY-MM-DD` (at most 180 days) on the
line above the finding's first line, with the rationale above it, and tag `security-review`; an
exception of `cv-drawings-query-missing-owner-filter` is also listed in
`tools/ci/drawings-exception-sites.json` (its one `rule` names that rule, the only one with exceptions
today; another rule's exception needs the list to name rules per site), by the constant its statement
assigns, else as `line N`, which moves with any edit above it,
and a High finding or an exception that outlives a release also follows `04-security-program.md`
section 16.2.
