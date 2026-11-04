# E24-C2 Charter: the cascade must not misstate or lose what happened

- Ticket: E24-Q01 (#771) · Format: session-based, **one** 90-minute session · Status: **not yet run** (ready to run)
- Plan: `docs/qa/e24-derivatives-test-plan.md` (cases CS-nn, BB-005-nn, BB-006-nn, CV-nn, NG-16; sections 5 and 6). Cites `03` §11.2, §9 (backpressure).
- Mission: make a liquidation cascade make the panel misstate what happened, lose a print it should have kept, tell a screen-reader user too much or too little, or grow without bound.
- Not this charter's: the measured budgets and the AC8 load (1 000 prints in 1 s, 500 prints/s for 10 s, at most 2 ms of script per frame). Those are E24-Q03's. This session judges **what the user is told and what survives**; it records the node count and the frame feel, not a timing.
- Status of the surface: the liquidation socket, the handler and the cascade fixture are in #5273 (open); the feed and bars are E24-S05 and E24-S06 (open). The session waits for them and for a seeded stack; the closing slice of #771 adds the run record. If there is no browser or screen reader at run time, the in-process precedent and the plan's Q-10 apply.

## Areas

- The feed under `FX-CASCADE` at its recorded rate: 250 ms buckets, the burst-rate counter, "lower bound" counts, the DOM node count, pause and resume with the "N new" count and the bounded buffer.
- The bars and the heatmap during and after the burst: every print in exactly one bucket, across a bar boundary and 00:00 UTC; the sum of notional against the recorded prints.
- A cascade on a **partial** history (the recorder started 2 hours ago): the chip, the boundary marker and the burst counter together.
- Announcements: at most one summary per 5 000 ms, none per print, none starving the countdown's at 300 000 and 60 000 ms (one polite `role="status"` node per sub-pane).
- Reconnect and a slow consumer (`slow_consumer`, close `4429`): resubscribe with the snapshot (last 100), what the pane shows for the span it missed.
- The `min_notional_usd` filter changed during the burst; the stale ticker during the burst (per sub-pane shading only).

## Oracles (defined before probing)

- O2.1 A **dropped print**: the sum of notional in the shown buckets differs from the recorded prints for the replayed span, per side. P1 (CS-02, BB-006-02).
- O2.2 A **count read as exact**: a burst rate or a bucket count presented without the lower-bound statement. P1 (BB-005-02).
- O2.3 A **lull that is really a gap**: after a reconnect or a slow-consumer close, the missed span shown as quiet rather than unknown. P1 (SM-1, CS-07).
- O2.4 **Unbounded growth**: a DOM node per print, a feed buffer that grows with the burst, a burst state that lingers, node count or script time not returning to the pre-burst level. P2 (CS-01, CS-06, CS-08); P1 if frames are dropped or the page stalls.
- O2.5 **Announcement flood or silence**: more than one summary per 5 000 ms, one per print, or the countdown's two announcements lost during the cascade. P2 (a11y, Q04's) (CS-04, CS-05).
- O2.6 The **partial-history chip or the boundary marker hidden or moved** by the burst, so the recorded window's start is mistaken for the cascade's. P1 (CS-03).
- O2.7 A **server-side filter that is really client-side**: raising `min_notional_usd` mid-burst does not reduce frames, or the filter is not stated in the pane. P2 (CS-09).
- O-ALL.1 An uncaught page error or a console error (every charter).
- Each finding names the layer and the signal that would have caught it (`deriv_fanout_dropped_total` is the metric for a dropped frame; the plan's section 0.5); "none" is an observability finding.

## Seed ideas

Replay the burst at the recorded rate, then at 2x and 5x; start the burst 3 minutes before a settlement; pause the feed for the whole burst and resume; throttle the link until `slow_consumer`; run the burst over a UTC midnight; run it with zones enabled and with the heatmap mode; resize to 360 px during the burst; set and clear a minimum notional three times in 10 seconds; stop the ticker mid-burst.

## Keyboard-only segment (`03` §12)

During the burst: reach Pause, Resume and the "N new" control, the table, and the chip, with focus visible and no focus loss when buckets arrive.

## Seeded stack and fixtures

As charter 1: tier B of `docs/qa/e49-exploratory-harness.md` §2, corpus fixtures behind the egress guard, Demo only, no secrets. Fixtures and toggles: FX-CASCADE (**not on `main`**: `ws/allLiquidation_BTCUSDT_burst.jsonl` and `ws/docs-all-liquidation.jsonl` on #5273 at `9bf4ec8c2bd5a2ca067c5a77726f63f0f2c0d0dd`), FX-RECORDER-GAP, FT-FEED-PAUSE, FT-SOCKET-DROP, FT-CLOCK-OFFSET. Until #5273 merges there is no cascade to replay, so this charter cannot start.

## Automated neighbours

E24-Q03 (AC8 load, fan-out amplification, read p95), E24-Q02 (the partial-history chip), E24-X02 (NG-14, NG-15 caps), the E08 chaos suite for the reconnect path (`03` §9).

## Debrief

Mission · areas actually probed · oracles used · findings (reproduction, layer, severity, signal) · each finding a defect ticket or a recorded non-issue with its reason · areas not reached · keyboard-only dead ends · time spent.

- Run 1: **not yet run.**
