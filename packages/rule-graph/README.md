# @candleviewer/rule-graph

The rule editor's model of a rule (E37-T01): pure, synchronous TypeScript with no React, DOM,
network or Node API. It turns the rule IR into the editor's graph and back, types the ports, finds
what the server's compile would refuse, and mirrors the server's canonical form and hash, so the
editor answers at once. The server stays the authority: `POST /rules/{ruleId}/compile` validates
and compiles the rule and returns the `ir_hash` that is stored.

## What it exports

- `toGraph(ir, layout?)` and `toIr(graph, layout?)`: the IR to a `GraphModel` (`envelope`, `nodes`,
  `edges`) and back, as `rules/compiler/graph.py` builds them. A shared node is one node with an
  edge per use. Positions, collapsed nodes and comments travel in a `GraphLayout`, stored as
  `graph_layout` and never hashed; `nodesNeedingLayout` is the hook for auto-layout (E37-T02).
- `canonicalise(ir)`, `hash(ir)` and `compareWithServer(clientHash, serverHash)`: the server's
  canonical bytes and their sha256 (`rules/ir/canonical.py`), for display only (see below).
- `PORT_TYPES`, `PORT_COMPAT`, `canConnect`, `NODE_PORTS`, `portsOf` and `portTypeOfMetric`: the
  typed ports, with one compatibility table for every connect path and a sentence per refused pair.
- `findCycles`, `findOrphans`, `findDanglingPorts` and `isFormRepresentable`: the graph analysis,
  naming the node ids at fault.
- `RuleGraphError` and its stable codes, `RULE_GRAPH_ERROR_CODES` (`24-internal-schemas.md` §11.4).
- `RuleIr`, from `@candleviewer/protocol/rule-ir`: generated from the published schema, never
  written by hand.

## The client mirror

- Hash what you send, and never re-hash what you load. Compile returns a decimal `const` as its text
  (`1E-7`), which re-hashes as text, and save hashes the `version` it is sent but stores its own.
- A disagreement shows as "server differs": `compareWithServer` answers `match` or `mismatch` and
  never picks a winner. The client never stores its hash or sends it as authority.
- It mirrors what the server-written vectors pin
  (`packages/fixtures/golden/rule-ir/hash_vectors.json`) and refuses the rest as `SCHEMA_VIOLATION`
  (a UUID without hyphens, a number of 1e21 or more), never guessing. Enums, ranges and patterns are
  the server validator's (E35).

## Tests

- Unit, under coverage: each adapter branch, the vectors' canonical bytes and hashes, the ports and
  the analysis.
- Property (`test/property.test.ts`): 10 000 documents per run from a seeded port of the server's
  generator (`test/support/generate.ts`) through `toGraph` then `toIr`. The seed is printed, and
  `CV_RULE_GRAPH_SEED` replays a run.
- Perf (`test/adapter.perf.test.ts`, the `perf` project, no coverage): `toGraph`, `toIr` and
  `canonicalise` on a 200-node graph take at most 20 ms each.
- Contract (`services/api/tests/contract/test_rule_graph_hash_contract.py`): the compile route
  answers each vector's `ir_hash`.

The commands are listed in `AGENTS.md` §4.
