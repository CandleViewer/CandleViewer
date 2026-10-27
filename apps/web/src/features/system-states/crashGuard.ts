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

/**
 * `now` is injected; one ring of ≤ REPEAT_LIMIT times per id. The id set is finite: panel ids are
 * literals at their mount sites, route ids come from the route manifest (through `useMatches`).
 */
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

/** The page's one guard, so a route boundary that re-mounts per crash still counts. */
let activeGuard: CrashGuard = createCrashGuard();

/** Test-only seam: installs a guard (a fake clock, a fresh ring set) for the boundaries. */
export function setCrashGuardForTests(guard: CrashGuard): void {
  activeGuard = guard;
}

export interface CrashRecord {
  readonly correlationId: string;
  readonly repeated: boolean;
}

/**
 * Reports one crash and counts it on the guard. Callers call it once per crash (the panel from
 * `componentDidCatch`, the route once per mount and error). Never throws: a failing reporter still
 * leaves a fallback to render.
 */
export function recordCrash(
  error: unknown,
  level: "panel" | "route",
  boundaryId: string,
): CrashRecord {
  try {
    return {
      correlationId: reportCrash(error, level, boundaryId),
      repeated: activeGuard.record(boundaryId),
    };
  } catch {
    return { correlationId: "unavailable", repeated: false };
  }
}
