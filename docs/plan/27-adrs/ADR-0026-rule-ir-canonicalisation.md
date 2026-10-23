# ADR-0026 — Rule IR canonicalisation and round-trip fuzz strategy

- Status: **proposed** (owner approval pending)
- Date: 2026-10-03
- Deciders: Owner (`@basiltt`) — owner approval pending.
- Numbering note: the ticket text says "ADR-0016 / ADR-0025"; both are taken, so this is the next free
  number, 0026 (delivery adaptations).
- Amended: 2026-10-23, §5 (the editor's display-only hash mirror, E37-T01).
- Related: E35-K01 (this spike), E35-T01 (consumer), ADR-0007, `24-internal-schemas.md` §11.4,
  `21-database-schema.md` §3.4, `docs/plan/spikes/E35-K01.md`.

## Context

`ir_hash` is the rule content hash: dedupe key (`UNIQUE (rule_id, ir_hash)`), arming-audit evidence and the
production round-trip check (US-RULE-006). Three questions were open: number normalisation, `node_id`
renumbering vs `rule_events.node_ref`, and what the fuzz generator must cover.

## Decision

1. **Strategy 2: JCS-style JSON with `Decimal` as canonical strings**, sha256 (`sha256_hex`) over UTF-8 bytes.
   - Parse with `parse_float=Decimal` (never `float`); integers are rendered through the same decimal rule,
     so `1000`, `1e3` and `1.0E3` agree.
   - Number rule: every JSON number becomes a string in plain notation, no exponent, no trailing fractional
     zeros, no `+`; `-0` becomes `0` (`format(d.normalize(), "f")`, zero special-cased).
     Examples: `1.50 -> "1.5"`, `1e3 -> "1000"`, `10E-1 -> "1"`.
   - Object keys sorted (code point order), no insignificant whitespace, `ensure_ascii=False`, UTF-8.
   - Arrays keep order (order of `children`/`actions` is semantic).
2. **Hashing happens in application code before insert and the hash is stored.** Postgres `jsonb` reorders
   keys and normalises numbers, so the hash must never be recomputed from the jsonb round-trip.
3. **node_ref: keep author-assigned `node_id`s in the stored IR and in `rule_events.node_ref`; renumber only
   inside the hashed view.** DFS renumbering as a _stored_ id is unsafe (spike test: inserting one node
   shifts later ids, so version N's `n3` is a different node in N+1). Renumbering in the hashed view makes
   isomorphic documents with different author ids hash equal, which is desired. `{"ref": id}` pointers are
   rewritten with the same mapping. DFS visits keys in sorted order so dict ordering cannot change ids.
   Editor behaviour for historical events: highlight `node_ref` against the version the event ran under
   (events carry `rule_version_id`). When viewing a newer version, a node is highlighted only if the same
   `node_id` still exists there; otherwise the UI shows "node no longer in this version" and never
   highlights a different node. Author ids are immutable once assigned and never reused after deletion.
4. **Presentation boundary (excluded from hash):** `presentation` (incl. `graph_layout` x/y, `editor`),
   `comment`, `collapsed`, stripped at any depth by key name. Everything else, including `name`, is hashed.
5. **Authoritative server-side only** (amended 2026-10-23 for E37-T01, by the 2026-10-22 ruling): the server
   computes the `ir_hash` that is stored, audited and compared. The TS editor's mirror (`packages/rule-graph`)
   computes the same canonical form and hash for display only: it never stores that hash or sends it as
   authority, and a disagreement with the server's shows as "server differs", never resolved client-side.
6. **Fuzz strategy (E35-T01):** Hypothesis `recursive` grammar `all_of|any_of` over compare leaves
   (prototype: max 4 children; production uses schema limits: 32 boolean children, 8 arithmetic operands,
   10 actions), numbers from ints and 6-place decimals, random author ids, random layout. Properties:
   (a) shuffled key order/indent keeps the hash, (b) presentation edits keep the hash, (c) canonical bytes
   are idempotent, (d) mutation check: dropping `sort_keys` is caught and shrinks to a ~330-byte document in
   ~40 s. The >=10 000 documents/run NFR = `max_examples=10000` spread over properties; the mutation test
   keeps it from being a tautology.
7. **Mismatch telemetry** (`rule_roundtrip_mismatch_total`): `rule_id`, `rule_version_id`, both `ir_hash`es,
   editor direction, first differing JSON pointer, `severity=high`. The diff is downloadable as plain text.

## Considered options (100-node doc, 1000 iterations, workstation Python 3.13)

| Strategy                             | p50    | p99     | Decimal fidelity                                                   | Readability / diff    | Verdict                                          |
| ------------------------------------ | ------ | ------- | ------------------------------------------------------------------ | --------------------- | ------------------------------------------------ |
| 1. JCS, Decimal -> double            | 9.4 ms | 26.9 ms | **lossy** (0.1000000000000000055511151231257827 collides with 0.1) | good                  | rejected: collisions break audit non-repudiation |
| 2. JCS, Decimal -> string            | 4.7 ms | 14.4 ms | exact                                                              | good (text)           | **chosen**                                       |
| 3. canonical CBOR of decimal strings | 6.5 ms | 16.6 ms | exact                                                              | binary, needs tooling | rejected: no benefit, hard to diff/support       |

All are far inside the <=500 ms compile and <=300 ms validate budgets. The prototype uses sorted
`json.dumps`; E35-T01 should add an RFC 8785 conformance test for key order and string escaping (decimal
strings sidestep JCS number serialisation entirely).

## Consequences

- Stable under re-serialisation, so saving an unchanged rule never creates a spurious version.
- Prices are strings inside the _hashed_ view only; stored IR keeps whatever the schema defines.
- Any change to this algorithm changes every hash: E35-T01 must add an `ir_hash_version` and upcaster.
- Residual risk: author-id immutability is an editor invariant E36/E37 must enforce.

## Validation

Prototype and tests: `docs/plan/spikes/E35-K01-harness/` (9 tests pass; throwaway). The 20-document corpus in
`corpus.py` is to be promoted to `tests/fixtures/rule_ir/` by E35-T01.
