/**
 * E10-S04 (#306): the system-state copy, reviewed once and reused by every surface that shows it.
 * Each string is verbatim from its design source; nothing here is composed by the client. Add a
 * row only with its source, never retype a sentence in a component.
 *
 * SCR-153 / CMP-092 rows: `docs/design/E17/E17-D02.md` §8 "The drawn issues" (the routing table
 * is §6; the severities are its first-match partition, M-3). Where the design has no string for a
 * row, the row takes the merged spec's nearest string and is marked PROPOSED beside it (coordinator
 * ruling on #306, 2026-10-27); every DEGRADED_COPY row is verbatim, so none is PROPOSED.
 */

export type DegradedSeverity = "info" | "warning" | "blocking";

export interface DegradedCopy {
  readonly severity: DegradedSeverity;
  readonly message: string;
  /**
   * What still works, as its own sentence. `null` where the design writes the condition as one
   * sentence that already says it (the store-down row).
   */
  readonly stillWorks: string | null;
}

/** The CMP-092 rows whose producer the client already reads, keyed by the issue id. */
export const DEGRADED_COPY = {
  /** Routing row 6: `notice` `maintenance.enabled` (`23` §15.9). */
  maintenance: {
    severity: "blocking",
    message: "Maintenance mode — new orders off.",
    stillWorks: "Cancel and close still work.",
  },
  /** Routing row 6: the `postgres` component `down`, the one the maintenance gate depends on. */
  storeDown: {
    severity: "blocking",
    message: "Database unavailable — new orders off; cancel and close still work.",
    stillWorks: null,
  },
  /** Routing row 8: `exchange_state.public_ws` in `connecting` / `disconnected` (matrix row 13). */
  exchangeFeedDown: {
    severity: "warning",
    message: "Exchange feed down — the server is restoring the connection.",
    stillWorks: "Charts and book pause; positions, cancel and close still work.",
  },
  /** Routing row 9: `exchange_state.private_ws` in `connecting` / `resyncing` (matrix row 24), ≤ 10 s. */
  privateReconnect: {
    severity: "warning",
    message: "Position data is being verified — actions temporarily limited.",
    stillWorks: "Market data is live; cancel and close still work, confirmed over REST.",
  },
  /** Routing row 10: the `rule_engine` component `down` (`14` SCR-153). */
  ruleEngineDown: {
    severity: "info",
    message: "Armed rules are not being evaluated — manual orders still work.",
    stillWorks: "Rule actions resume when the engine is back.",
  },
  /** Routing row 10: the `recorder` component `down` (`14` SCR-153). */
  recorderDown: {
    severity: "info",
    message: "Recorder down — no new history is being written.",
    stillWorks: "Charts, orders, positions, cancel and close still work.",
  },
} as const satisfies Readonly<Record<string, DegradedCopy>>;

export type DegradedIssueId = keyof typeof DEGRADED_COPY;

/**
 * SCR-156 / CMP-091. "D03" = `docs/design/E10/E10-D03.md`; "board" = its board 10 export
 * `docs/design/E10/img/E10-D03-10-system-states.png`, frames `SCR-156/panel-level` and
 * `SCR-156/route-level` (board-only strings, read off the export at full size).
 */
export const CRASH_COPY = {
  panel: {
    /** D03:328, :371 (PROPOSED there, §10.2); E10-D04-names.json `shell.scr156.fallback`. */
    heading: "This panel stopped working",
    /**
     * Board `SCR-156/panel-level`, verbatim. Unconditional there and in D03:328 ("the surviving
     * workspace keeps running"); D03:328's "only where true" is the positions / native-stops sentence.
     */
    body: "The surviving workspace is unaffected. Copy diagnostics and report it, or reload the panel.",
    /** D03:328. */
    reload: "Reload panel",
    /** PROPOSED: `docs/design/E04/E04-D01.md`:189, "This panel keeps crashing — reload disabled." */
    repeatedHeading: "This panel keeps crashing — reload disabled.",
  },
  route: {
    /**
     * Board `SCR-156/route-level`, verbatim. D03:328 calls this the shipped placeholder that E10-S04
     * replaces, yet the board draws the same words, so the board's string is kept.
     */
    heading: "Something went wrong",
    /**
     * PROPOSED: board `SCR-156/route-level` reads "Reload the page or the app, or start in safe mode
     * without saved layouts."; the safe-mode clause is cut until safe mode exists.
     */
    body: "Reload the page or the app.",
    /** D03:328. */
    reload: "Reload page",
    /** PROPOSED: E04-D01:189's string, for a page. */
    repeatedHeading: "This page keeps crashing — reload disabled.",
  },
  /** PROPOSED: E04-D01:189-190 asks for the reason in plain text; D03:328 gives the threshold. */
  repeatedReason: "It crashed three times in two minutes. Reload the app to start again.",
  /** D03:328. */
  reloadApp: "Reload app",
  /** D03:328. */
  copyDiagnostics: "Copy diagnostics",
  /** Board `SCR-156/panel-level`: "error id 7f3a-2c · 14:02:05 UTC" (the timestamp is not shown yet). */
  errorId: "error id",
  /** PROPOSED (both): no drawn string for the copy result. */
  copied: "Diagnostics copied.",
  copyFailed: "Couldn't copy the diagnostics.",
} as const;
