# E15-D01 — Sync-comprehension stimuli: six configurations, C1–C6

- **Use:** Part 2 of a session, about 10 minutes, before the card sort ([`discussion-guide.md`](discussion-guide.md)).
  This is the facilitator's copy: it holds the answer key, so participants see only the boards (the report's boards 03
  and 04), one configuration at a time. Results go on the scoring sheet below and into [`findings.md`](findings.md) §3.2.
- **Material (ticket Accessibility notes):** text at 16 px or more, greyscale; the letter is the only cue, never colour; a
  panel in no group carries no badge; time limits are relaxed on request.
- **Model under test (SCR-023):** a panel is in one sync group (A, B, C) or none; a change on a shared axis reaches every
  other member of that group and nothing outside it (US-LAY-003 "Sync groups"). Axes are set per group (SCR-023,
  E15-T03); today's contract cannot store C5's per-group difference (report OQ-5).
- **Per configuration, read verbatim:** (1) badges only: "The letter in a panel's corner is its sync group. You change
  the symbol in panel N to the new symbol. Which other panels change?" (2) Reveal the shared axes: "Here is what each
  group shares. Which other panels change?" (3) "And if you change the interval in panel N instead?" Note whether they
  asked what a group shares first (a signal for F2).

### C1 — One group (the control)

```text
+-------------------------+-------------------------+
| 1 Chart BTCUSDT 1h  [A] | 2 Chart BTCUSDT 5m  [A] |
+-------------------------+-------------------------+
| 3 Chart BTCUSDT 1m  [A] | 4 Chart BTCUSDT 15m [A] |
+-------------------------+-------------------------+
```

- Revealed: A shares symbol and crosshair. Set panel 1 to ETHUSDT. Key: symbol **2, 3, 4**; interval **none**.
- Probes whether the letter reads as "these follow each other". Predicted risk: low.

### C2 — Two groups

```text
+-------------------------+-------------------------+
| 1 Chart BTCUSDT 1h  [A] | 2 Chart BTCUSDT 5m  [A] |
+-------------------------+-------------------------+
| 3 Chart ETHUSDT 1h  [B] | 4 Chart ETHUSDT 5m  [B] |
+-------------------------+-------------------------+
```

- Revealed: A and B each share symbol and crosshair. Set panel 1 to SOLUSDT. Key: symbol **2 only**; interval **none**.
- Probes group scope, the ticket's "changed the symbol in one chart and it wrecked my other five". Predicted risk: medium.

### C3 — A panel in no group

```text
+-------------------------+-------------------------+
| 1 Chart BTCUSDT 4h  [A] | 2 Chart BTCUSDT 1h  [A] |
+-------------------------+-------------------------+
| 3 Chart BTCUSDT 15m [A] | 4 Chart ETHUSDT 15m     |
+-------------------------+-------------------------+
```

- Revealed: A shares symbol and crosshair; panel 4 is in no group. Set panel 1 to SOLUSDT. Key: symbol **2, 3**; interval **none**.
- Probes whether a missing badge reads as "independent" or as a hidden default. Predicted risk: low to medium.

### C4 — A group that shares the interval, not the symbol

```text
+-------------------------+-------------------------+
| 1 Chart BTCUSDT 5m  [A] | 2 Chart ETHUSDT 5m  [A] |
+-------------------------+-------------------------+
| 3 Chart SOLUSDT 5m  [A] | 4 Chart XRPUSDT 5m  [A] |
+-------------------------+-------------------------+
```

- Revealed: A shares interval and crosshair, not symbol. Set panel 1 to DOGEUSDT. Key: symbol **none**; interval **2, 3, 4**.
- Probes the badge's silence about axes (F2); competitors' links carry the symbol. Predicted risk: high.

### C5 — Two groups, two meanings (SCR-049's own wireframe pattern)

```text
+-------------------------+-------------------------+
| 1 Chart BTCUSDT 4h  [A] | 2 Chart BTCUSDT 5m  [A] |
+-------------------------+-------------------------+
| 3 Chart ETHUSDT 1h  [B] | 4 Chart SOLUSDT 1h  [B] |
+-------------------------+-------------------------+
```

- Revealed: A shares symbol and crosshair, B interval and crosshair. Set panel 3 to XRPUSDT. Key: symbol **none**; interval **4**.
- Probes one badge shape carrying two meanings side by side. Predicted risk: high.

### C6 — An armed order panel in the group

```text
+-------------------------+-------------------------+
| 1 Chart BTCUSDT 1m  [A] | 2 Chart BTCUSDT 15m [A] |
+-------------------------+-------------------------+
| 3 DOM BTCUSDT       [A] | 4 Positions             |
|   ONE-CLICK ARMED       |                         |
+-------------------------+-------------------------+
```

- Revealed: A shares symbol and crosshair; panel 4 is in no group. Set panel 1 to ETHUSDT. Key: symbol **2, 3**: the armed DOM
  now shows ETHUSDT and, under today's plan, stays armed (E30-S04 has no disarm trigger for it); interval **none**.
- Then ask, verbatim: "Is that what you want? What should happen to the armed DOM?" Probes a silent re-point of an
  armed order panel (F1): a requirement for E15-D06 and E30-S04 whatever the score.

## Scoring sheet (empty until a session runs; per cell: badge-only, revealed, interval as `✓` or `✗`, `?` if asked)

| C   | Key: symbol · interval | P1  | P2  | P3  | P4  | P5  | P6  | Badge-only right (n of N) | Flagged |
| --- | ---------------------- | --- | --- | --- | --- | --- | --- | ------------------------- | ------- |
| C1  | 2, 3, 4 · none         |     |     |     |     |     |     |                           |         |
| C2  | 2 · none               |     |     |     |     |     |     |                           |         |
| C3  | 2, 3 · none            |     |     |     |     |     |     |                           |         |
| C4  | none · 2, 3, 4         |     |     |     |     |     |     |                           |         |
| C5  | none · 4               |     |     |     |     |     |     |                           |         |
| C6  | 2, 3 · none            |     |     |     |     |     |     |                           | always  |

**Flag rule (ticket AC2, pre-registered in the report §3.2).** A configuration whose badge-only symbol answer fewer than
4 of 6 participants get right is flagged and becomes a redesign requirement for E15-D06, worded in the report's table;
with fewer participants the bar is two thirds, rounded up (2 of 3, 3 of 4, 4 of 5). C6 is a requirement whatever its
score. For E15-D02's and E15-D06's own bar, also count per participant how many of the six they got right from the badge.
