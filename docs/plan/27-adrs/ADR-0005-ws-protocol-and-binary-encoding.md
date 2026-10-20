# ADR-0005 — WS protocol: snapshot + delta with binary market-data frames

- Status: **decided** (amended 2026-10-06, 2026-10-20; Amendment 2 is **accepted (interim)**, conditional on E17-Q03, #568)
- Date: 2026-09-14
- Deciders: Architect, Backend lead, Frontend lead, Chart-engine lead
- Consulted: `docs/research/22-architecture-options.md` §4, `docs/research/06-bybit-api.md` §14, digest 10 open question #6
- Related: `docs/plan/23-ws-protocol.md`, `docs/plan/26-chart-engine-design.md` §9, ADR-0004

## Context and problem statement

The browser needs book top-N, footprint cells, heatmap columns (one per 100 ms), bars, trades, CVD/OI/funding series and OMS state, continuously, for several symbols and several chart panes at once, within a ≤ 250 ms tick-to-pixel budget of which only ~20 ms belongs to fan-out. JSON over WebSocket is the obvious starting point and is easy to debug, but the heatmap alone is 512 floats every 100 ms per symbol, and a footprint window is thousands of numeric cells — exactly the payload shapes where JSON parsing dominates the frontend frame budget.

## Decision drivers

- Chart engine decodes in a worker and wants **typed arrays it can hand to the GPU without a copy**.
- Backend must not re-serialise per client: one encode, many sends.
- Protocol must be client-agnostic (planning brief P1) and versioned.
- Recovery must be deterministic without checksums, mirroring Bybit's own model.
- Debuggability matters: an engineer must be able to read the control plane in DevTools.

## Considered options

1. **Hybrid: JSON control frames + custom binary market-data frames**, snapshot+delta with per-topic sequence numbers.
2. **JSON everywhere.**
3. **MessagePack everywhere.**
4. **Protobuf everywhere** (schema-first, codegen for Python and TS).

## Decision outcome

**Chosen: option 1.**

- **Control plane (JSON)**: `hello`, `welcome`, `subscribe`, `unsubscribe`, `ack`, `error`, `resync_required`, `ping`/`pong`, OMS commands and OMS state updates. Human-readable in DevTools, low volume.
- **Data plane (binary)**: book, footprint, heatmap, bars, trades, profile. Little-endian, fixed 24-byte header `{magic u16, version u8, kind u8, flags u16, topicId u16, seq u64, payloadLen u32, count u32}` followed by struct-of-arrays payloads whose column layouts are declared in `23-ws-protocol.md`. Prices are int32 ticks relative to a per-topic `priceOrigin`; times are int64 microseconds.
- **MessagePack** is used for mid-tier structured payloads that are neither tiny control messages nor columnar arrays (e.g. a profile period descriptor with heterogeneous fields).
- **Snapshot + delta**: every topic has one sequence domain. A `snapshot` frame carries the state and the seq it is consistent with; `delta` frames carry monotonically increasing seqs. A gap, an overflow, or any doubt produces a `resync_required` control frame followed by a fresh snapshot. **No checksums**, matching Bybit's own philosophy.
- **Capability negotiation**: `hello` declares `binary: true|false`. A client that declares `binary: false` receives JSON for everything — so the protocol remains fully usable from `wscat` and from any future client that has not implemented the decoders.
- **Versioning**: `proto` integer in `hello`/`welcome`. The server supports the current and previous version; a mismatch closes with a typed code and an explanatory reason.
- **Compression**: `permessage-deflate` is **off** for the data plane (the payloads are already dense numerics and deflate would add per-frame CPU on both ends) and on for the control plane only if measured to help.

### Consequences

Positive:

- The worker decodes a frame into `Float32Array`/`Int32Array` views over the received buffer with no parse and no copy, then transfers it to the render worker — this is what keeps the ≤ 4 ms p95 decode budget achievable.
- One encode per topic serves all subscribers, so client count does not multiply backend CPU.
- The JSON control plane keeps the system debuggable and keeps the contract legible in `23-ws-protocol.md`.

Negative / risks:

- Two encodings to maintain and test. Mitigated by generating both the Python encoder and the TS decoder from a single schema declaration in `packages/protocol`, with a round-trip property test.
- Binary framing is unforgiving of drift. Mitigated by the `version` byte, a CI check that regenerates `packages/protocol` and fails on a diff, and fuzz tests feeding malformed frames to the decoder.

### Why not the alternatives

- **JSON everywhere**: simplest, but measurement in comparable systems puts `JSON.parse` of a 512-float heatmap column plus a footprint window well into the frame budget, and it triples bandwidth. It remains available as the negotiated fallback, which captures most of its debuggability benefit at no architectural cost.
- **MessagePack everywhere**: better than JSON, but it still produces JS arrays of numbers rather than typed arrays, so the copy into GPU-ready buffers remains. Adopted for the mid-tier only.
- **Protobuf everywhere**: strong schema and codegen, but varint encoding of dense numeric columns is both slower to decode and larger than a fixed-width struct-of-arrays layout for our shapes, and research found the Python/TS codegen DX unresearched. Rejected for the data plane; the schema-first discipline is recovered by generating our own codecs.

## Validation

- Spike S5: measure binary vs JSON on a real heatmap + footprint workload. Gate: ≥ 40 % bandwidth reduction and ≥ 30 % decode-time reduction, else the data plane stays JSON and this ADR is amended.
- Contract tests: every frame kind round-trips Python encode → TS decode → re-encode, byte-identical.
- Fuzz tests: malformed frames, truncated payloads, out-of-order and duplicate sequences, NaN/Infinity values.
- Benchmark B7 in `26-chart-engine-design.md` §13 enforces the decode budget in CI.

## Amendment 1 — 2026-10-06: Spike S5 / E17-K01 validation result — gate NOT MET as specified

_Amendment 2 (below) says what shipped and replaces whatever differs from it here._

Evidence: `docs/plan/notes/e17-binary-vs-json.md`; harness and committed artefact `tests/perf/ws/`
(`run_all.py`, `results.json`). 4-pane reference workspace (§16.3), 60 s, seed 17001, headless Chromium
153 on an i7-8550U laptop, median of 5 runs. Workload is modelled on a documented-shape corpus, not a
live capture. **Owner ratification pending.**

| Gate criterion                                  | Result                                                                        | Verdict  |
| ----------------------------------------------- | ----------------------------------------------------------------------------- | -------- |
| Decode time >= 30 % lower than JSON             | -82.3 % (workspace CPU 0.76 -> 0.13 ms/s; footprint -88 %, book delta -17 %)  | PASS     |
| Bandwidth >= 40 % lower, JSON deflated per §3.5 | binary 50.4 KiB/s raw vs JSON 23.7 KiB/s deflated: binary is **112 % larger** | **FAIL** |
| Bandwidth >= 40 % lower, both uncompressed      | 50.4 vs 153.6 KiB/s: -67.2 %                                                  | PASS     |

The verdict turns on compression: with `permessage-deflate` context takeover the workspace (dominated by the redundant 400-cell
footprint) compresses ~6.5x in JSON and ~21x in binary; without takeover the binary advantage is only -29 %.
Everything is far inside the §16.3 envelope (350 KiB/s; footprint decode p99 0.35 ms JSON vs 1.0 ms
target), and `@msgpack/msgpack` structured payloads decode ~2x **slower** than `JSON.parse`, which confirms
the rejection of MessagePack-everywhere. Server-side, a scalar struct-packing encoder (97-103 µs for
footprint/heatmap) is slower than orjson on the whole structured frame (68 / 34 µs); the encode-CPU
benefit of binary exists only with a vectorised or native codec.

**Amended decision (proposed, pending owner ratification).**

1. The **data plane stays JSON** (`cv.v1.json`, deflate on, the negotiated fallback) for the first
   release. This overrides "Data plane (binary)" above for every kind except those in point 2.
2. The binary codec (E17-T02) is **re-scoped to footprint (kind 5), heatmap column (kind 6) and book
   snapshot (kind 1)** — the kinds where decode is 66-88 % cheaper — as an opt-in `binary: true`
   capability. It ships only if the owner accepts per-connection deflate-with-takeover (or a
   delta-footprint) for it; otherwise it is deferred until E17-Q03 measures a real budget miss.
   Book delta, trades and bars (decode 11-17 % better, bars 23 % worse) stay JSON.
3. The **schema-first codec generation** discipline is unchanged; MessagePack remains mid-tier only
   (low volume), never on hot kinds.
4. Not discharged: §3.4's prose record sizes (bars 69 B, footprint cell 33 B) disagree with its field
   lists (65 B, 29 B) and must be reconciled by E17-T02 before any codec is written.

## Amendment 2 — 2026-10-20: as built (E17-T07)

Approval: approved by the orchestrator under owner delegation, 2026-10-20; owner may revoke. The
ruling will be recorded on the E17-T07 ticket (#572) when the PR opens. It stands on one condition: E17-Q03 (#568) measures the as-shipped arm (point 2) against the §16.3
budgets, and the numbers meet them. If one misses, the owner chooses between structured-by-default
(the per-subscription `options.encoding`, a policy default and not a wire change) and a change of
the budget. The body of this ADR and Amendment 1 are left as written; this section is what a reader
uses where they differ.

**1. The gate was not met as specified.** Amendment 1's verdict stands for the arms E17-K01
measured: decode PASS (-82.3 %), bandwidth against deflated JSON FAIL (binary 112 % larger),
bandwidth uncompressed PASS (-67.2 %). The verdict is decided by deflate with context takeover,
not by the encoding, and every arm is far inside the §16.3 envelope (raw JSON 154 KiB/s against a
350 KiB/s target). So no arm was unfit. Amendment 1 itself was never ratified by name, and what
shipped is not what it proposed.

**2. What shipped, against what Amendment 1 proposed.**

| Amendment 1 proposed                                             | As built                                                                                                                                                                                                                                                                            |
| ---------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The data plane stays JSON (`cv.v1.json`, deflate on)             | The web client offers `cv.v1.json` only (`apps/web/src/lib/ws/protocol/frames.ts`). On it a subscription whose family has a binary form defaults to binary (`ws/topics.py`), sent as `e: "b64"`: a base64 CVWB body inside the JSON envelope, deflated. K01 never measured this arm |
| Binary re-scoped to footprint, heatmap and book snapshot, opt-in | All six body kinds ship, on by default per subscription. `hello.encodings` and `hello.capabilities` are advisory: the server reads neither, and `options.encoding` decides                                                                                                          |
| Book delta, trades and bars stay JSON                            | They are binary by default; `bars` has a structured fallback for what kind 4 cannot hold (23 §3.4)                                                                                                                                                                                  |
| MessagePack mid-tier only                                        | `cv.v1.msgpack` is served and preferred by the server as the envelope codec for every frame, with deflate withdrawn for it, decoded under the SR-185 bounds. The web client does not offer it (#2886)                                                                               |

**3. Decision.** The hybrid stands: a readable control plane (§13) and fixed-layout binary bodies
(§3.4) inside a self-describing envelope. What changed is which envelope codec carries the bodies
(the shipped web path is the JSON envelope), which side defaults to binary (the server, per
subscription) and where the negotiation happens (`options.encoding`, not `hello`). The deflate
configuration is part of the wire contract in practice (23 §3.5): "binary is smaller" holds only
with deflate on for `cv.v1.json` and off for `cv.v1.msgpack`.

**4. The layout text of the ADR's body is stale; `23-ws-protocol.md` §3.4 and
`packages/protocol/cvwb-layout.json` govern.**

| The ADR says                                                                          | As built                                                                                                                                                                                                                                               |
| ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| A header of `magic u16, version u8, kind u8, flags u16, topicId, seq, payloadLen`     | A 24-byte header: `magic u32` ("CVWB"), `format_version`, `body_kind`, `flags` (estimated, coalesced, replay, partial), `price_scale`, `qty_scale`, 3 reserved, `record_count u32`, `ts_base_ms u64`. The sequence number lives on the envelope (§3.3) |
| Prices as int32 ticks from a `priceOrigin`, times as int64 microseconds               | Scaled `i64` (decimal exponents, per frame for bars) and per-record `u32` millisecond offsets from `ts_base_ms`                                                                                                                                        |
| Struct-of-arrays payloads                                                             | Fixed-stride records; a struct-of-arrays decode output is deferred (#2067)                                                                                                                                                                             |
| Records of 69 B (bars) and 33 B (footprint cell) against field lists of 65 B and 29 B | Bars are 85 B and footprint cells 33 B, each ending in 4 reserved zero bytes; the footprint group prefix is 28 B. Bars and footprint are `format_version` 2, which carries `(generation, index)` (#2014, #2529). Decoders ignore reserved bytes        |
| Control frames `subscribe`, `unsubscribe`, `ack`, `error`, `resync_required`          | `sub`, `sub_ok`, `unsub`, `unsub_ok`, `err`, `resync`, `snap`, `d`, `ctl`, `ctl_ok`, `revoked`, `permission_change`, `bye`, `ping`, `pong` (§3.1)                                                                                                      |
| Versioning by an integer `proto` the server supports with the previous one            | `protocol: "cv.v1"` and the `cv.v1.*` subprotocol; a breaking change is `cv.v2`, served in parallel for one release (§2.3, C-6.3)                                                                                                                      |

**5. What the implementation taught.** (a) The envelope codec and the body encoding are two axes,
and K01 measured three of the four combinations. (b) Fixed strides forced two `format_version`
bumps before the freeze; after it each is a `cv.v2`. The only free growth is a later bit of a
record's `flags` byte that 23 §3.4 calls reserved: naming a reserved byte or a header flag bit
changes the layout the golden pins, so it is a `cv.v2` change too. (c) One layout declaration generating both codecs turned K01's 69/65 and 33/29 B
disagreements into generation failures, and `wire-contract.v1.golden.json` extends that discipline
to the whole contract. (d) Decoder bounds checked against the real buffer (SR-128), a seed corpus
with a nightly fuzz run (SR-155) and the MessagePack decoder's bounds (SR-185) are why the freeze is
also a security control. (e) Struct-of-arrays decode (#2067) and MessagePack in the web client
(#2886) stay open on purpose.
