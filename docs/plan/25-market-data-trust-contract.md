# 25. Market-data trust contract

> Companion to `docs/plan/27-adrs/ADR-0023-exchange-adapter-boundary.md`. This document is a
> **checklist for consumers**, not a description of producers: it tells a downstream developer, in ten
> minutes, how much to trust a field on an event they did not produce and how it must be rendered. Owner
> file for the trust semantics; the adapter _implementation_ is owned by `24-internal-schemas.md` §14.
> Anything asserted here that has no enforcement (a test, a lint rule, or a schema field) is marked a
> **convention** in §5 — an unenforced assertion is honestly labelled as one, never silently trusted.

Cross-linked from `docs/plan/20-architecture.md` §3, `docs/plan/24-internal-schemas.md` §14 and the E08
epic ticket (issue #35).

## 1. Measured vs derived vs estimated

Every value a consumer receives falls into exactly one of three trust classes. The class is a property of
the **value**, not the event envelope — two fields on the same event can have different classes.

| Class         | Definition                                                                                                                                                                                                                                                            | Examples                                                                                                                                                                                         | UI requirement                                                                                                                                                                                                                                                                                                                                                                                |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Measured**  | Read directly off the exchange wire, or built from measured inputs by a deterministic, lossless transform (unit conversion, µs normalisation). No heuristic, no statistical inference.                                                                                | Trades, bars/klines (`o,h,l,c,v`), book snapshots/deltas, liquidations, funding, open interest.                                                                                                  | Rendered at full confidence; no affordance needed.                                                                                                                                                                                                                                                                                                                                            |
| **Derived**   | A deterministic aggregate or transform over measured inputs — reproducible from the same inputs every time, but not itself a wire field.                                                                                                                              | CVD, imbalance (`24-internal-schemas.md` §4), footprint cell volumes, profile POC/VAH/VAL.                                                                                                       | Rendered at full confidence like measured data **provided every input is measured**; if any input carries `estimated=True` (e.g. book columns produced during `Resyncing`), the derived value inherits `estimated=True` and must be labelled per the estimated row below (`24-internal-schemas.md` §6, "exact (estimated if any source column `estimated=True`)" pattern).                    |
| **Estimated** | A heuristic, threshold-based or statistical inference — a _guess_, however well-calibrated. `confidence: Literal["exact","estimated"]` is mandatory on every metric descriptor for heuristics (`24-internal-schemas.md` §7); heuristics are **always** `"estimated"`. | Iceberg presence/executed volume, stop-run detection, absorption, exhaustion, divergence detectors, market regime (Hurst/ADX/ATR%), liquidity-cluster persistence/pull, queue-position estimate. | **Must** carry the "estimate" affordance defined in `docs/plan/15-component-catalogue.md` in any UI that shows it. Presenting a heuristic as a certainty is a defect (`docs/plan/32-risk-register.md` R9 Advice boundary; research 08/09 recommendation). Predicted/estimated liquidation levels (Coinglass-style) are explicitly **not in v1** — only realized liquidation history is shown. |

**Label text convention (enforcement anchor for the checklist item below):** any value with
`confidence="estimated"` or `estimated=True` is prefixed with the word **"Est."** (or the full word
"Estimated" where space allows) in its UI label, tooltip and any exported/copied representation
(journal entries, screenshots' alt text). This is the required label text convention referenced by the
edge-case scenario in this ticket's acceptance criteria — an unlabelled estimated value is a defect
against the consuming epic, not against E08.

## 2. Confirmed vs unconfirmed

The last bar in any `bars`/`footprint` frame may carry `confirm: false` (wire bit `flags` bit 0,
`24-internal-schemas.md` §2 kline body format; `23-ws-protocol.md` §6.1). Kline "closed" gates strictly on
this flag (`24-internal-schemas.md` §14.3, "Kline" row).

- **A client MUST NOT treat an unconfirmed bar as closed.** This is normative protocol rule C3
  (`23-ws-protocol.md` §3211: "Never treat `confirm: false` bars as closed") and exists specifically to
  prevent the flicker bug where an in-progress bar's OHLC is momentarily rendered, then silently revised —
  a viewer must never see a bar "close" twice.
- **State-merge rule:** for the `bars` stream, a confirmed bar is never replaced by an unconfirmed one; the
  in-progress bar is overwritten many times per second until `confirm: true` arrives, at which point it is
  final (`23-ws-protocol.md` §839 state-merge table).
- **Consumer checklist item:** any code path that reads the _last_ element of a bars/footprint array must
  branch on `confirm` before treating OHLC, volume or footprint aggregates as final — including CVD/imbalance
  derived values keyed to that bar (§1 above: a derived value over an unconfirmed bar is provisional, not
  wrong, but must not be presented as closed).
- **Producer side:** what "confirmed" means per bar family, the 60 s amend window and generation changes
  are stated in `36-bar-semantics-reference.md` §4 and §5; this section stays the consumer rule.

## 3. Fresh vs stale vs desynced

Every market-data stream publishes health as one of three states, always as a plain value a consumer reads
— **never** by querying a statechart interpreter on a hot path (`28-statechart-catalogue.md` §B14 MUSTNOT-01;
the per-delta apply loop is exempt from the statechart rule, health publication is not the interpreter
itself). `FeedHealthEvent` (`24-internal-schemas.md` §2, 1 Hz, `stream_kind, connected, last_msg_age_ms,
latency_p50_ms, latency_p99_ms, msgs_per_s, dropped`) is the transport for the first two states;
`BookDesyncEvent` is the transport for the third, book-specific state.

| State        | Definition                                                                                                                                                                                                         | Who publishes                            | Required consumer rendering                                                                                                                                                                                                                                                                   |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Fresh**    | `connected=true` and `last_msg_age_ms` under the stream's staleness threshold (per-stream-kind threshold; see `book_staleness_ms`, "age of last applied book update", `24-internal-schemas.md` §7, class `exact`). | The adapter, per `stream_kind`, 1 Hz.    | Normal rendering; no badge.                                                                                                                                                                                                                                                                   |
| **Stale**    | `connected=true` but `last_msg_age_ms` (or `book_staleness_ms` for the book) exceeds the threshold — the connection has not dropped but has stopped delivering updates in time.                                    | Same `FeedHealthEvent`.                  | A visible "stale" indicator on the affected widget; values keep their last known state but must not be presented as live-updating.                                                                                                                                                            |
| **Desynced** | Book-specific: any `u` sequence gap, or a crossed book after applying a delta (ADR-0023 D3). Not a graceful degradation of "stale" — it is a hard invalidation.                                                    | `BookDesyncEvent`, recorded and alerted. | The "book resyncing" badge over the DOM/heatmap (`24-internal-schemas.md` §2.2); columns produced while resyncing are rendered at 40% opacity with a hatch pattern and marked `estimated=True`, and are **excluded** from any rule-engine liquidity metric until a fresh snapshot is applied. |

**Consumer checklist item:** a widget that renders book-derived data (DOM ladder, heatmap, liquidity-cluster
metrics) must subscribe to both `FeedHealthEvent` and `BookDesyncEvent` for its symbol and switch rendering
mode on either — a widget that only checks "is the socket connected" and ignores staleness/desync will
render confidently wrong data during a silent stall or an unresolved gap.

## 4. Complete vs gapped

Historical coverage is expressed per `(symbol, stream_kind, tier)` as a set of contiguous covered
intervals plus the storage tier holding them, via `GET /market/data-coverage`
(`docs/plan/22-api-openapi.yaml`). The endpoint exists specifically so the UI can grey out ranges that were
never recorded **before** rendering a historical window, rather than showing a misleading empty chart
(`23-ws-protocol.md` §3286).

- **A consumer must call `/market/data-coverage` before rendering any historical range** it did not just
  receive live, and render gaps as explicitly missing (greyed, with a "no data recorded" affordance) —
  never as a flat line, a zero, or an interpolated value. A hole in coverage is a hole in the data, not a
  quiet interval.
- **Interpolation across a gap is never permitted** for measured data classes (§1) — a gap in trades, bars
  or book history stays a visible gap. This is distinct from the _derived_ smoothing already documented for
  specific metrics (e.g. exponential decay weighting in the liquidation heatmap, `24-internal-schemas.md`
  §6) which operates only within recorded data, not across a coverage hole.
- **Recorder/replay note:** `docs/plan/24-internal-schemas.md` §13 owns the recorder's own retention and
  replay semantics; this document only states the consumer-facing contract — call the coverage endpoint,
  trust its answer, render holes honestly.
- **Bars:** which bar gap and partial markers are served today, and which are not yet, is the
  non-guarantee list of `36-bar-semantics-reference.md` §7.

## 5. Rules for consumers — review checklist

A reviewer (or a downstream epic's own developer, before writing UI code) can walk this list against any
screen or metric that touches market data:

1. **Classify every value you render** as measured, derived or estimated (§1). If you cannot say which in
   one sentence, ask the epic that produces it — do not guess.
2. **Estimated values carry the "Est." label** in every surface they appear on: chart overlay, tooltip,
   journal export, screenshot alt text (§1). An unlabelled estimated value is a defect against the
   consuming epic.
3. **Never treat the last bar/footprint element as closed without checking `confirm`** (§2).
4. **Subscribe to `FeedHealthEvent` and `BookDesyncEvent`**, not just socket-connected state, for any
   book-derived widget; render stale and desynced states per the table in §3 — do not fall back to "last
   known good" silently.
5. **Call `/market/data-coverage` before rendering historical ranges**; render gaps as gaps, never
   interpolated or blank-as-zero (§4).
6. **Price/quantity are `Decimal`; `price_ticks` is derived, never authoritative** — do not round-trip
   through `float` anywhere a comparison or a monetary total depends on the result (ADR-0023 D6).
7. **Every enforceable assertion above is enforced by one of:**

   | Assertion                                                      | Enforcement                                                                                                                                                                |
   | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
   | `confirm: false` never treated as closed                       | `23-ws-protocol.md` contract tests (protocol schema validation) + chart-engine bar-merge unit tests                                                                        |
   | `estimated=True` inherited through derived metrics             | `24-internal-schemas.md` §7 `MetricDescriptor.confidence` schema field; heuristic detectors are schema-typed `Literal["estimated"]`, not a free string                     |
   | Book desync ⇒ invalidate, never patch                          | `28-statechart-catalogue.md` §B14 golden-trace contract tests (`tests/xstate_contract/`)                                                                                   |
   | P3 (no Bybit vocabulary outside the adapter)                   | `E08-X03` lint gate (CI-blocking)                                                                                                                                          |
   | Coverage gaps rendered, not interpolated                       | **convention** — no automated check exists yet; tracked as a gap for the E12/E22/E24 UI test suites to close with an explicit "renders coverage hole" test case per screen |
   | Depth-tier default (200) is capability-driven, not conditional | `E08-X03` lint gate (same mechanism as P3)                                                                                                                                 |

   The one row marked **convention** is honestly labelled as such per this document's opening note — it is
   a rule with no enforcement yet, not a tested guarantee, until a downstream epic adds the missing test.
