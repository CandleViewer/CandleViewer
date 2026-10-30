/**
 * E10-S04 (#306): the system-state copy, reviewed once and reused by every surface that shows it.
 * Each string is verbatim from its design source; nothing here is composed by the client. Add a
 * row only with its source, never retype a sentence in a component.
 *
 * SCR-153 / CMP-092 rows: `docs/design/E17/E17-D02.md` §8 "The drawn issues" (the routing table
 * is §6; the severities are its first-match partition, M-3). Where the design has no string for a
 * row, the row takes the merged spec's nearest string and is marked PROPOSED beside it (coordinator
 * ruling on #306, 2026-10-27); every DEGRADED_COPY string is verbatim, and only the break-glass
 * row's tone and stillWorks pairing are PROPOSED.
 */
import { CLIENT_PROTOCOL } from "../../lib/ws/protocol/frames";

export type DegradedSeverity = "info" | "warning" | "blocking";

export interface DegradedCopy {
  readonly severity: DegradedSeverity;
  readonly message: string;
  /**
   * What still works, as its own sentence. `null` where the design writes the condition as one
   * sentence that already says it (the store-down row).
   */
  readonly stillWorks: string | null;
  /** How the row's entry is said, a property of its class (E17-D02 §11 rows 5 and 16). */
  readonly announce: "assertive" | "polite";
}

/** The CMP-092 rows whose producer the client already reads, keyed by the issue id. */
export const DEGRADED_COPY = {
  /** Routing row 6: `notice` `maintenance.enabled` (`23` §15.9). */
  maintenance: {
    severity: "blocking",
    message: "Maintenance mode — new orders off.",
    stillWorks: "Cancel and close still work.",
    announce: "assertive",
  },
  /** Routing row 6: the `postgres` component `down`, the one the maintenance gate depends on. */
  storeDown: {
    severity: "blocking",
    message: "Database unavailable — new orders off; cancel and close still work.",
    stillWorks: null,
    announce: "assertive",
  },
  /**
   * SR-023: `notice` `auth.break_glass_used` (`23` §15.9), sent after a first `auth_ok` while a
   * break-glass reset is unresolved. The message is the notice's own, verbatim (E42-D03 OV-10;
   * `break_glass_notice.py` `_MESSAGE`), the same for every role. It refuses nothing, so it is
   * never "blocking"; PROPOSED: the warning tone and §8's "Order entry unaffected." beside it
   * (no §6 row routes it). Said assertively once, as OV-10 asks (§11 row 5 would be polite).
   */
  breakGlass: {
    severity: "warning",
    message: "Break-glass recovery was used on this server; the Owner must review it.",
    stillWorks: "Order entry unaffected.",
    announce: "assertive",
  },
  /** Routing row 8: `exchange_state.public_ws` in `connecting` / `disconnected` (matrix row 13). */
  exchangeFeedDown: {
    severity: "warning",
    message: "Exchange feed down — the server is restoring the connection.",
    stillWorks: "Charts and book pause; positions, cancel and close still work.",
    announce: "polite",
  },
  /** Routing row 9: `exchange_state.private_ws` in `connecting` / `resyncing` (matrix row 24), ≤ 10 s. */
  privateReconnect: {
    severity: "warning",
    message: "Position data is being verified — actions temporarily limited.",
    stillWorks: "Market data is live; cancel and close still work, confirmed over REST.",
    announce: "polite",
  },
  /** Routing row 10: the `rule_engine` component `down` (`14` SCR-153). */
  ruleEngineDown: {
    severity: "info",
    message: "Armed rules are not being evaluated — manual orders still work.",
    stillWorks: "Rule actions resume when the engine is back.",
    announce: "polite",
  },
  /** Routing row 10: the `recorder` component `down` (`14` SCR-153). */
  recorderDown: {
    severity: "info",
    message: "Recorder down — no new history is being written.",
    stillWorks: "Charts, orders, positions, cancel and close still work.",
    announce: "polite",
  },
  /** Routing row 10, client-side: SCR-159's GPU page answered "Keep software rendering" (#306 9c). */
  gpuFallback: {
    severity: "info",
    message: "Chart engine in fallback — reduced visuals.",
    stillWorks: "Order entry unaffected.",
    announce: "polite",
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
  /** §9.2 R-902: the heading (E17-D02 §10 D's family); the sentence is D02 f27's. */
  backend_unreachable: {
    heading: "Can't reach the server",
    sentence: "The app started, but the backend does not answer.",
  },
} as const;

/** D02 f27: R-902's checklist, the lines the client can observe (not "Tailnet connected"). */
export const BOOT_CHECKS = {
  network: "Network connected",
  backend: "Backend answers — no reply within 5 s",
  version: "Backend version — unknown until it answers",
} as const;

/** PROPOSED: the checklist glyphs' names (D02 f27: a glyph and a word, never colour alone). */
export const CHECK_GLYPHS = { passed: "Passed", failed: "Failed", unknown: "Unknown" } as const;

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
  /** §9.2 R-902: the wordmark, and board 10's footer line (CMP-207's pre-auth state is G10). */
  wordmark: "CandleViewer",
  buildLine: (version: string): string => `CandleViewer v${version} · environment not known yet`,
} as const;

/**
 * SCR-159's GPU-unavailable page, the desktop app's only (§9.2's fourth row; #306 9c). The heading
 * is §9.2's and board 10's; f28 drew "Charts are running without the GPU". Board 10 draws a shorter
 * body; D02 f28's is used, since it has the crash time and E11-D04 D13's limits.
 */
export const GPU_COPY = {
  /** §9.2 and board 10. */
  heading: "Hardware acceleration is off",
  /** D02 f28, its time as the StatusBar's clock prints it (" UTC" PROPOSED; f28 draws "14:01:58"). */
  sentence: (at: string): string =>
    `The graphics process stopped at ${at} and CandleViewer restarted the charts in software rendering.`,
  /** D02 f28: `degraded-2d`'s limits (E11-D04 D13). */
  limits: [
    "Charts redraw more slowly: candles, lines, axes, the crosshair and drawings stay.",
    "Footprint cells show colour only and the heatmap is off until the GPU is back.",
    "Order entry, positions and the kill switch are not affected.",
  ],
  /** D02 f28 draws "GPU process restarted 1 time this session"; the plural is PROPOSED. */
  restarts: (n: number): string =>
    `GPU process restarted ${n} time${n === 1 ? "" : "s"} this session`,
  /** D02 f28's secondary action (BQ-9.2; Retry now is board 10's). */
  keep: "Keep software rendering",
} as const;

/**
 * SCR-157's banner (`docs/design/E10/E10-D03.md` §9.1, board 10). What will happen is each shell
 * adapter's `caps.reason.autoUpdate`, which §9.1 cites. Not here: What's new and the position line.
 */
export const VERSION_COPY = {
  /** §9.1 and board 10; the StatusBar's reminder after Later too (D02 :230, PROPOSED there). */
  label: "Update available",
  /** PROPOSED: D02 f23's "(this tab runs 1.4.2, the server serves 1.4.3)" (`14` SCR-157 A11y). */
  versions: (desktop: boolean, client: string, server: string): string =>
    `This ${desktop ? "app" : "tab"} runs ${client}, the server serves ${server}.`,
  /** §9.1 and board 10: CMP-001 secondary, for the session. */
  later: "Later",
  /** §9.1 and board 10: the browser's CMP-001 primary. */
  reload: "Reload",
} as const;

/**
 * SCR-157's blocking dialog (E10-D03 §9.1, board 10; the heading is §10.2's PROPOSED name).
 * `stops` and `works` are board 10's lines, which list what §9.1 names.
 */
export const VERSION_DIALOG_COPY = {
  heading: "This version can't trade with the server",
  /**
   * PROPOSED: board 10's row ("Your client v1.4.2 (API 1.3) · the server requires API 1.4 (ws
   * protocol cv.v1)") with what the client knows of each side: a version and a ws protocol. The
   * server's is its free-text build label, printed bare as the banner prints it.
   */
  versions: (client: string, server: string | undefined, protocol: string | null): string =>
    `Your client v${client} (ws protocol ${CLIENT_PROTOCOL}) · the server ` +
    `${server === undefined ? "" : `${server} `}requires ` +
    (protocol === null ? "a ws protocol this client can't read" : `ws protocol ${protocol}`),
  stops: "What stops: new orders, cancel, reduce-only close, flatten, the in-app kill switch",
  works: "Still works: read-only views — charts, positions, the journal",
  /** §9.1: CMP-001 primary, the one dismiss (`Esc` too: E10-D04 §13.2). */
  continue: "Continue read-only",
  /** §1.3, §9.1: the gated set's T2 reason, PROPOSED key `health.protocol_incompatible` (G14). */
  unavailable: "Unavailable until you update.",
  /** §9.1 (D02 :128): the Safety cluster's kill-switch line meanwhile. */
  killSwitchLine: "Kill switch: unknown — incompatible version",
} as const;

/**
 * SCR-156 / CMP-091: the copy lives with the component (`@candleviewer/ui`
 * `GLOBAL_ERROR_FALLBACK_COPY`, E05-S04), each string with its source there.
 */
export { GLOBAL_ERROR_FALLBACK_COPY as CRASH_COPY } from "@candleviewer/ui";
