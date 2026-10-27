/**
 * E10-S04 (#306) slice 6: the repeated-crash guard and the one crash-recording path for the CMP-091
 * boundaries. Three crashes of one boundary within two minutes stop its reload (`docs/design/E10/E10-D03.md`
 * §9.4, E05-D02 CMP-091; the threshold is PROPOSED there). The ticket's "three within one minute" yields
 * to the spec (coordinator ruling on #306, 2026-10-27). The window is inclusive — a third crash exactly
 * 2:00 after the first trips it (PROPOSED: the spec does not say).
 */
import { reportCrash } from "../../shell/crash/reportCrash";

export const REPEAT_LIMIT = 3;
export const REPEAT_WINDOW_MS = 120_000;

export interface CrashGuard {
  /** Records one crash of `boundaryId`; true when it is the third within the window. */
  record(boundaryId: string): boolean;
}

/** `now` is injected; one ring of ≤ REPEAT_LIMIT times per id (the ids are static, so bounded). */
export function createCrashGuard(now: () => number = Date.now): CrashGuard {
  const rings = new Map<string, number[]>();
  return {
    record(boundaryId) {
      const ring = rings.get(boundaryId) ?? [];
      rings.set(boundaryId, ring);
      const t = now();
      ring.push(t);
      if (ring.length > REPEAT_LIMIT) ring.shift();
      const first = ring[0] ?? t;
      return ring.length === REPEAT_LIMIT && t - first <= REPEAT_WINDOW_MS;
    },
  };
}

/** The page's guard, so a route boundary that re-mounts per crash still counts. */
export const defaultCrashGuard: CrashGuard = createCrashGuard();

export interface CrashRecord {
  readonly correlationId: string;
  readonly repeated: boolean;
}

const recorded = new WeakMap<object, CrashRecord>();

/** Reports a crash and counts it; idempotent per error object (StrictMode's double effect is one crash). */
export function recordCrash(
  error: unknown,
  level: "panel" | "route",
  boundaryId: string,
  guard: CrashGuard,
): CrashRecord {
  const key = typeof error === "object" && error !== null ? error : {};
  const crash = recorded.get(key) ?? {
    correlationId: reportCrash(error, level, boundaryId), // never throws
    repeated: guard.record(boundaryId),
  };
  recorded.set(key, crash);
  return crash;
}
