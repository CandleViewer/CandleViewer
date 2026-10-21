# @candleviewer/protocol

Generated TS types/decoders from `docs/plan/22-api-openapi.yaml` (REST) and
`docs/plan/23-ws-protocol.md` (WS), plus hand-written runtime binary frame
decoders and sequence/resync helpers.

- `src/generated/rest/` — TS types for every OpenAPI schema/operation, via
  `openapi-typescript`. **Never hand-edit.**
- `src/generated/ws/` — TS types for every WS envelope/message-kind/topic
  payload, via `json-schema-to-typescript` compiling
  `docs/plan/ws-schema.json` (a machine-readable extract of
  `23-ws-protocol.md` §13-15, produced by
  `scripts/extract-ws-schema.mjs`). Also exports `WsTopicPayloadMap`, mapping
  every §6 topic pattern to its payload type. **Never hand-edit.**
- `src/generated/index.ts` — barrel re-exporting the `rest`, `ws`, `policy` and
  `bars` surfaces as namespaces, written by `scripts/generate-barrel.mjs`.
  `src/generated/cvwb/` stays out of it: `src/runtime` imports it directly.
- All of `src/generated/` is marked `linguist-generated` in `.gitattributes`;
  `pnpm generate` regenerates it and records every file's sha256 in
  `.cache/generated-manifest.json`, which is git-ignored and never committed
  (#2743: every contract PR conflicted on a committed manifest).
  `scripts/check-generated-guard.mjs` fails if a file lacks its header or
  matches neither what the last `pnpm generate` recorded nor its copy at HEAD
  (a hand edit since then; the record does not move with git, so HEAD's copy
  covers what a pull, rebase or checkout wrote); with no recorded manifest it
  checks the headers only. A committed hand edit fails the `gen` step of CI's
  `gates` job (lane `gen` in `ci-required`), which regenerates and diffs; so
  does a committed file there that no generator writes (CI-GEN-005).
  `make gen-check` runs that gate locally; `make gen` regenerates.
- `src/runtime/` — sequence-gap classification (`checkSequence`) and binary
  frame decoders for the six §3.4 `body_kind`s (book snapshot/delta, trades,
  bars, footprint, heatmap column) over untrusted WS input; a fuzz target for
  E03's Schemathesis/contract job.

The Python side of this same contract pair (pydantic v2 models under
`services/api/candleviewer/{api,ws}/_generated/`) is generated separately by
`services/api/scripts/generate_protocol_models.py`, wrapping
`datamodel-code-generator` — see that script's docstring.

## Scripts

- `pnpm --filter @candleviewer/protocol generate` — runs, in order:
  `extract-ws-schema.mjs` (markdown → `docs/plan/ws-schema.json`),
  `generate-rest-types.mjs` (OpenAPI → `src/generated/rest/`),
  `generate-ws-types.mjs` (ws-schema.json → `src/generated/ws/`),
  `generate-policy-rules.mjs` (policy tables → `src/generated/policy/`),
  `generate-bar-types.mjs` (bar model schema → `src/generated/bars/`),
  `generate-cvwb-layout.mjs` (`cvwb-layout.json` → `src/generated/cvwb/` and the
  Python twin `services/api/candleviewer/ws/_generated/cvwb_layout.py`),
  `generate-barrel.mjs` (→ `src/generated/index.ts`),
  `update-manifest.mjs` (records `.cache/generated-manifest.json`), then
  `check-generated-guard.mjs`.
- `pnpm --filter @candleviewer/protocol generate:check` — the local staleness
  check: re-extracts the WS schema and diffs it against the committed
  `docs/plan/ws-schema.json`, then runs the generated-file guard. `pnpm verify`
  runs the guard first, before anything regenerates. CI's `gen` step runs
  `tools/ci/check_gen_freshness.py` (`make gen-check`), which regenerates and
  runs `git diff --exit-code`, catching drift or a hand edit in the TS output
  itself (`AGENTS.md` §4).
- `pnpm --filter @candleviewer/protocol build` / `test` / `test:cov`.

## WS schema bundle (E17-T01) - the one rule

**Edit the Markdown (`docs/plan/23-ws-protocol.md`), never the bundle or anything generated.**

- `ws-schemas.json` - deterministic bundle of every fenced `json` schema in sections 13-15,
  keyed by `$id`; produced by `tools/contracts/extract_ws_schemas.py`.
- `generated/ws_constants.py` - frame types, encodings and section 6 topic patterns for the
  backend; produced by `tools/contracts/gen_ws_constants.py`. (TS types: `src/generated/ws/`.)
- `make gen` regenerates all of it; `make contracts` runs the offline gates, including the
  blocking `ws_message_schemas` gate (`tools/contracts/validate_ws_schemas.py --draft 2020-12`:
  meta-validation, `$ref` closure inside the bundle, every section 12 example frame validates).
  CI job `contract` runs `make contracts` and prints the schema and example counts.

## Compatibility: additive or breaking? (`cv.v1` is frozen)

`cv.v1` is frozen (E17-T07, #572). The wire contract is pinned by `wire-contract.v1.golden.json` in
this package and checked on every PR by `make contracts` (`tools/contracts/wire_contract.py`) and by
`services/api/tests/contract/ws/test_ws_wire_contract.py` (CI job `contract`). The document
`docs/plan/23-ws-protocol.md` is the source of truth and the code moves to match it
(`services/api/tests/contract/ws/test_ws_spec_parity.py`). The rules are 23 §2.3 and CONSTITUTION
C-6.3. When in doubt, it is breaking.

### What the golden pins, and what it does not

`wire-contract.v1.golden.json` pins: the 24-byte header and every body kind field by field (offsets,
sizes, reserved bytes, header flag names, `format_version`, length rule, and the heatmap's one column per frame); the envelope (frame types,
members, the members each frame type requires, the member types a frame type adds); every control frame
of §13.1 to §13.6 (required members, the JSON type of each member, whether it admits others); the pinned
enumerations (two of them open); the close codes with the reason-to-code map and each `reconnect`; the
error codes with their scope, `retryable` and close code; the six `welcome.limits`, each as a floor or a
ceiling, at the shipped defaults; the topic names with their payload schema's name; the subprotocols;
and the bounds that were set before the freeze: `from_seq` (an integer of 0 or more), the list options
`metrics`, `status`, `rule_ids` and `symbols`, `ctl.metrics` and `sub_id`.

Limits and bounds are compared by direction. The floors are `max_subscriptions`, `max_topics_per_request`,
`max_inbound_frame_bytes` and `max_symbols_per_connection` (what a client may send): raising one is
additive, lowering one is breaking. The ceilings are `max_outbound_frame_bytes` (the most the server sends
in one frame) and `min_throttle_ms` (the lowest throttle a client may ask for): lowering one is additive,
raising one is breaking. A bound on a request (what the server accepts) may widen, which is additive, and
may not narrow; a promise about what the server sends (`sub_id`'s length, the type of `s`) may narrow,
which is additive, and may not widen.

It does not pin: the other ranges, lengths, item bounds and enumerations of the request options and of
`hello` and `resync` (`hello.capabilities`, `hello.encodings`, `hello.shell`, `resync.reason`); the
enumerations of `common` other than `snapMeta.reason`, `snapMeta.source` and the error codes
(`environment`, which `auth_ok.allowed_environments` uses, `side`, `barType`, `depth`); the code list in
`bye.code`'s schema (the gateway's own close-code set is pinned); the members of `snapMeta`; the `e` and
`sp` clauses of the envelope schema; the members of the §14 and §15 payload schemas (only the schema's
name per topic); or any wording. Those are judged against the rules below in review; no gate fails on them.

The golden changes only by `--extend` (an additive change, shown as a diff in review: the file is not
marked generated) or by a new `wire-contract.v2.golden.json` for `cv.v2`. Never delete it to make a check
pass: restore it from git (`git restore -- packages/protocol/wire-contract.v1.golden.json`). `--write`
creates the first golden and refuses to overwrite one, and a diff that `--extend` refuses is breaking.
A bound, enumeration or limit that `wire_contract.py` declares and the golden lacks is reported as damage;
any other member removed from the golden by hand reads as a promise never made and shows as a deleted line
in the golden's diff. To start pinning something new, name it in `PIN_ADDITIONS` in `wire_contract.py` (a group that
`compare` reads with `.get`: `body_kinds`, `control_frames`, `enums`, `bounds`, `error_codes`, `limits` or `topics`; a
bound, enumeration or limit the tool declares; or a new member of a pinned kind by its path, as
`body_kinds.6.header_record_count` was), run `--extend`, and remove the name in the same change.

### Additive: free, no `cv.v2`

| Change                                                                                               | Why it is safe                                                                                                                       | What you do                                                                                                                                                                                              |
| ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A new topic                                                                                          | a client never receives a topic it did not subscribe to                                                                              | contract first: the §6 row and the payload schema in §13-§15, then the registry row in `ws/topics.py`; the parity test fails until the two agree                                                         |
| A new optional member of a structured payload or of a server-to-client frame                         | clients MUST ignore unknown members (§2.3)                                                                                           | add it as optional to the §13-§15 schema; `make gen`                                                                                                                                                     |
| A new optional member of a client request (a `sub` option, a `ctl` key)                              | old clients never send it; its absence must behave as today                                                                          | the schema, the registry, and a default equal to today's behaviour                                                                                                                                       |
| A new error code, a new `bye` or `revoked` reason                                                    | clients keep unknown reasons as tags; the web client shows an unclassified code as a client bug (a console error and a report toast) | the registry (`x-error-codes-ws` in `22-api-openapi.yaml`), §10.2 with its `Scope` and `retryable`, §10.3 and the web mapping row (`apps/web/src/lib/ws/errorMapping.ts`) in the same change; `make gen` |
| A new `kind` of the `system` topic                                                                   | the web client ignores kinds it does not know (`apps/web/src/lib/ws/state/reducer.ts`)                                               | §15.9 and its schema                                                                                                                                                                                     |
| A new value of an open enum, §2.3 (`snapMeta.reason`, `bye.reason`, `revoked.reason`, `system.kind`) | clients keep the value as a tag, never as a decode check                                                                             | the document and the server's set                                                                                                                                                                        |
| A new optional `welcome.limits` key or `welcome.features` flag                                       | clients read the keys they know                                                                                                      | the §4.2 table and the schema: add the key to the `properties` of `welcome.limits`, which admits no unknown key, and never to its `required`, which is pinned                                            |
| A loosened limit: a floor raised or a ceiling lowered (23 §4.2)                                      | a client sized to the old value still fits                                                                                           | the §4.2 table and §16.2, in the same PR                                                                                                                                                                 |
| A new body kind (id above 6) for a new topic                                                         | only subscribers of that topic receive it                                                                                            | `cvwb-layout.json`; never touch an existing kind                                                                                                                                                         |
| A bit of a record's `flags` byte that §3.4 calls reserved ("0 on send, ignored on receive")          | decoders ignore reserved bits; the golden pins the field, not its bits                                                               | the document, the decoders, the vectors                                                                                                                                                                  |

### Breaking: `cv.v2`, served in parallel for at least one full release

- Any change to the 24-byte header or to an existing body kind: a field, offset, type, record stride,
  `format_version`, length rule or the magic. A fixed stride cannot grow in place: that is what
  `format_version` is for.
- Removing or renaming a member, a topic, a frame type, an error code, a close code or a reason;
  moving a reason to another close code; changing an error's `retryable` or `close_code`.
- Adding a new frame type. The web client treats an unknown `t` as a decode failure
  (`apps/web/src/lib/ws/protocol/codec.ts`), so it is not additive until clients are required to
  ignore it.
- Changing a `required` set in either direction, tightening a type or a range (a nullable becoming
  non-null), changing the values of a closed server-to-client enumeration, or giving an existing
  value a new meaning.
- Tightening a limit: a floor lowered or a ceiling raised, the reverse of the additive row (clients size to
  them). The golden's limits are the shipped defaults: a deployment may lower
  `CV_WS_MAX_INBOUND_FRAME_BYTES` for itself (23 §4.3) and tell its clients, and that does not change the
  contract.
- Naming a header flag bit or a reserved record byte: the golden pins the header and every record field
  by name, offset and size, so it needs `cv.v2` although decoders ignore the bytes.
- A heatmap frame with other than one column (its header's `record_count`, which the golden pins): it needs
  `cv.v2`.
- Changing what consumes a sequence number, what a `snap` resets, or what a resync does (23 §3.3, §7).
- Changing the envelope codec rules: framing, the `e` values, the subprotocol names.

### Making an additive change

1. Edit `docs/plan/23-ws-protocol.md` first, in the first commit of the PR (C-6.1). Schemas live in
   §13-§15.
2. `make gen`, then `make contracts`. The wire-contract check prints `NOTE additive: ...` for what it
   sees; the parity test fails until the document and the code agree.
3. Optionally record the addition so that removing it later is also caught:
   `uv run --project services/api python tools/contracts/wire_contract.py --extend`. It refuses a
   diff that is not purely additive. A new topic needs no golden change: its document row protects
   it.
4. Add the provider and consumer contract tests (C-6.2).

### Making a breaking change

There is no flag that accepts it. Write an ADR; serve `cv.v2.*` next to `cv.v1.*` for at least one
full release; add a deprecation entry to 23 (C-6.3, C-6.4); add `wire-contract.v2.golden.json`; keep
`v1` passing until `cv.v1` is retired by a commit with a `BREAKING CHANGE` footer.
