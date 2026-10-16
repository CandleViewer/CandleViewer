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
- `src/generated/index.ts` — barrel re-exporting both surfaces as `rest` and
  `ws` namespaces.
- All of `src/generated/` is marked `linguist-generated` in `.gitattributes`;
  `pnpm generate` regenerates it and records every file's sha256 in
  `.cache/generated-manifest.json`, which is git-ignored and never committed
  (#2743: every contract PR conflicted on a committed manifest).
  `scripts/check-generated-guard.mjs` fails if a file lacks its header or
  matches neither what the last `pnpm generate` recorded nor its copy at HEAD
  (a hand edit since then; the record does not move with git, so HEAD's copy
  covers what a pull, rebase or checkout wrote); with no recorded manifest it
  checks the headers only. A committed hand edit fails CI's
  `gen / gen-freshness` check, which regenerates and diffs.
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
  `update-manifest.mjs` (records `.cache/generated-manifest.json`), then
  `check-generated-guard.mjs`.
- `pnpm --filter @candleviewer/protocol generate:check` — the local staleness
  check: re-extracts the WS schema and diffs it against the committed
  `docs/plan/ws-schema.json`, then runs the generated-file guard. `pnpm verify`
  runs the guard first, before anything regenerates. CI's
  `tools/ci/check_gen_freshness.py` regenerates and runs `git diff --exit-code`,
  which catches drift or a hand edit in the TS output itself (`AGENTS.md` §4).
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
