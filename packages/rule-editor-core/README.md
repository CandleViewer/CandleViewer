# @candleviewer/rule-editor-core

Framework-free core of the rule form editor (E36-T01, #1063): the layer between the server's
canonical rule IR and what the form edits. Pure TypeScript: no React, no DOM, no global `fetch`,
no clock and no Node APIs in `src/` (lint and dependency-cruiser enforce it). The server is the
only authority on validation, compilation, canonical form and hashing (E35); this package maps,
caches and anchors, and never computes those semantics itself.

Types come from `@candleviewer/protocol` (generated, imported with `import type` only, C-4.16).
The one other workspace edge is `@candleviewer/rule-graph`, through its entry point only.

## Exports

### Parser limits (SR-E36-13)

The limits of the E36 threat model §5.1
(`docs/security/threat-models/e36-rule-form-editor.md`), checked in its order, each before the step
it protects. Every number equals the server's, so the client never sends a body the server refuses
and a stored rule always reopens. A refusal is a value (`{ ok: false, refusal }`) naming its
`reason`, its `limit` and what was `measured`; nothing here throws, on hostile input or on a body
with no JSON text. Members are read as own properties only.

| Export                        | What it does                                                                                                                                                                                                                                                                                                                    |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `RULE_LIMITS`                 | The frozen §5.1 numbers, plus the one `ir_version` the client maps.                                                                                                                                                                                                                                                             |
| `checkImportSelection(sizes)` | An import selection: at most 100 files, then at most 20,000,000 bytes summed, before any file is read; a size that is not a non-negative safe integer is refused as `import_size`.                                                                                                                                              |
| `parseRuleJson(text, kind)`   | 2,000,000 UTF-8 bytes, then 65 levels (`"ir"`) or 66 (`"bundle"`) by a string-aware scan, then `JSON.parse`, then 20,000 values.                                                                                                                                                                                                |
| `encodeRequestBody(body)`     | The encoded body of a save, validate or compile, refused past 2,000,000 bytes before it is sent; a body with no JSON text (cyclic, `BigInt`) is refused as `unencodable`.                                                                                                                                                       |
| `checkRuleShape(ir)`          | `ir_version` 1 only (any other is refused by name and never mapped), 10 actions, 32 children per boolean node, 1,000 condition nodes; over 200 the rule is not `editable`.                                                                                                                                                      |
| `utf8ByteLength(text)`        | The UTF-8 length of a string without encoding it.                                                                                                                                                                                                                                                                               |
| `jsonDepthExceeds(text, n)`   | The linear pre-parse depth scan, as the server's `json_depth_exceeds`. It counts containers, so a 65-level `ir` whose innermost container holds a value passes it and is refused by the server's `check_bounds` (`rules/compiler/common.py`, depth of a value past 64): the client is at most one level looser, never stricter. |
| `countValues(doc, limit)`     | The value count as the server's `check_bounds`, stopping past `limit`.                                                                                                                                                                                                                                                          |

### Form model

`FormModel` is SCR-081's five sections (`scope`, `trigger`, `conditionGroups`, `actions`,
`options`), the `presentation` block (`graph_layout`, `editor`: outside the hash, carried
untouched), the `opaqueRegions` the form cannot represent (each with its RFC 6901 `irPointer`, the
`rawNode` as loaded, a `plainLanguageSummary` and the server's `reason`), the loaded IR as `base`
`formReasons`, the whole-rule verdict of `@candleviewer/rule-graph`'s `isFormRepresentable` (`[]`
when every node fits; one subset, never mirrored here), and `readOnly` (a §5.1 refusal, or
`null`). Cards in place or D02-G2's whole-rule banner is E36-S03's choice. Rows keep their IR `node_id` as their id. A row naming
an identifier the vocabulary lacks lists it in `unknownIdentifiers` and is re-emitted unchanged.
Types only; the IR adapter (`irToForm`, `formToIr`) builds and writes it.

### JSON pointers

`encodePointer`, `parsePointer`, `getAt`, `hasAt`, `setAt` and `cloneJson`: RFC 6901 pointers over
IR documents. `setAt` writes in place into the structural clone the caller owns, keeping member
order; members are read as own properties and written as data, so `__proto__` is never a
prototype. A pointer that is malformed or does not resolve throws a `PointerError` with a `code`.

## Scripts

`pnpm --filter @candleviewer/rule-editor-core lint | typecheck | test | test:cov | test:perf`.
Coverage floor: 90 % lines, 75 % branches (the ticket's, above the 80 % frontend floor).
