// E24-S01 (#776) slice 1: the ticker's staleness for the OI readout (BQ 3, PROPOSED pending the ticket
// amendment): D02 DV-1 / D03 §10.2 — a CMP-239 chip from 5 s without an update (T1), escalated from 15 s
// (T2), in place of the ticket's 2 s. A served `stale: true` (`23` §14.8) counts as T2, as D02 §9 "Which
// stale" reads the server's flag.

export const STALE_T1_MS = 5_000;
export const STALE_T2_MS = 15_000;

export type StaleTier = "fresh" | "t1" | "t2";

export function staleTier(ageMs: number, serverStale: boolean): StaleTier {
  if (serverStale || ageMs >= STALE_T2_MS) return "t2";
  return ageMs >= STALE_T1_MS ? "t1" : "fresh";
}

/** The chip's age in whole seconds: what changes on screen, so a frame publishes only when it moves. */
export const ageSeconds = (ageMs: number): number => Math.floor(Math.max(0, ageMs) / 1000);
