/**
 * E10-S04 (#306): the system-state copy, reviewed once and reused by every surface that shows it.
 * Each string is verbatim from its design source; nothing here is composed by the client. Add a
 * row only with its source, never retype a sentence in a component.
 *
 * SCR-153 / CMP-092 rows: `docs/design/E17/E17-D02.md` §8 "The drawn issues" (the routing table
 * is §6; the severities are its first-match partition, M-3).
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
