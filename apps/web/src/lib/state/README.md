# src/lib/state

Plain external stores read through `useSyncExternalStore` (ADR-0001, amendment 2026-11-02 — no Zustand,
Jotai or RxJS in `apps/web`). Empty at E02-T04; populated as features land (E10+).

| File             | Role                                                                                   |
| ---------------- | -------------------------------------------------------------------------------------- |
| `chartLocate.ts` | E22-S01 (#714, BQ-213): the tape's click-to-locate request; charts subscribe (E11/E15) |
