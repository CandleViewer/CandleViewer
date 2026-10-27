/**
 * E10-S04 (#306) slice 6: the repeated-crash guard and the one crash-recording path for the CMP-091
 * boundaries. Three crashes of one boundary within two minutes stop its reload (`docs/design/E10/E10-D03.md`
 * §9.4, E05-D02 CMP-091; the threshold is PROPOSED there). The ticket's "three within one minute" yields
 * to the spec (coordinator ruling on #306, 2026-10-27). The window is inclusive — a third crash exactly
 * 2:00 after the first trips it (PROPOSED: the spec does not say).
 */
import { buildDiagnostics, reportCrash } from "../../shell/crash/reportCrash";

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
  /** CMP-091's "Technical detail": this crash's lines of the redacted diagnostics (SR-177), if any. */
  readonly details?: string | undefined;
}

/**
 * The redacted log lines carrying `correlationId`; never the error itself. Only each entry's first
 * line is kept, so a newline inside a message cannot pass for another log line.
 */
function crashDetails(correlationId: string): string | undefined {
  try {
    const lines = buildDiagnostics()
      .recentLogLines.map((l) => l.split(/\r\n|[\n\r\u2028\u2029]/, 1)[0] ?? "")
      .filter((l) => l.includes(correlationId));
    return lines.length === 0 ? undefined : lines.join("\n");
  } catch {
    return undefined;
  }
}

/** Copy diagnostics: the redacted payload, assembled at click time (SR-177); rejects without a clipboard. */
export function copyCrashDiagnostics(): Promise<void> {
  const clipboard = (navigator as Partial<Navigator>).clipboard;
  if (clipboard === undefined) return Promise.reject(new Error("clipboard unavailable"));
  return clipboard.writeText(JSON.stringify(buildDiagnostics(), null, 2));
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
    const correlationId = reportCrash(error, level, boundaryId);
    return {
      correlationId,
      repeated: activeGuard.record(boundaryId),
      details: crashDetails(correlationId),
    };
  } catch {
    return { correlationId: "unavailable", repeated: false };
  }
}
