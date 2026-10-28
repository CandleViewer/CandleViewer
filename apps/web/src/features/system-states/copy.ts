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
 * SCR-159 (`docs/design/E10/E10-D03.md` §9.2 and board 10). Where §9.2 cites an E10-D02 string
 * without restating it ("the three checks", the sentence of a variant), E10-D02's frame is the
 * source, as D03 changes none of D02's strings. PROPOSED marks a string composed here.
 */
export const OFFLINE_COPY = {
  /** §9.2: "You're offline" (E17-D02 §10 D) and "Reconnects automatically.". */
  offline: { heading: "You're offline", sentence: "Reconnects automatically." },
  /** §9.2: the heading (`14` SCR-159 A11y); the sentence is `14` SCR-159 Type's (D02 f26). */
  tailnet_unreachable: {
    heading: "Not connected to the tailnet",
    sentence: "Can't reach the backend — check that Tailscale is connected.",
  },
} as const;

/** D02 f26: the three checks §9.2 cites for tailnet-unreachable. */
export const TAILNET_CHECKS = [
  "Open Tailscale and check this computer shows Connected.",
  "Check the backend machine is online in Tailscale.",
  "Try again.",
] as const;

export const SCR159_COPY = {
  /** §9.2 and board 10 (E17-D02 §10 A's approximate "~4 s"). */
  retryIn: (s: number): string => `Retrying in ~${s} s`,
  /** Board 10. */
  retryNow: "Retry now",
  /** §9.2: SCR-157's fallback block (CMP-068, SR-086). */
  fallback: "Fallback: the server console command",
  command: "candleviewer kill",
  /** PROPOSED: the CMP-033 name on the block (D03 gives the block, not its button's name). */
  copyCommand: "Copy the server console command",
  /** D02 f25 / f26 A11y (`14` SCR-159 checklist 5): the recovery, said once, politely. */
  recovered: "Connected again — data is live.",
} as const;

/**
 * SCR-156 / CMP-091: the copy lives with the component (`@candleviewer/ui`
 * `GLOBAL_ERROR_FALLBACK_COPY`, E05-S04), each string with its source there.
 */
export { GLOBAL_ERROR_FALLBACK_COPY as CRASH_COPY } from "@candleviewer/ui";
