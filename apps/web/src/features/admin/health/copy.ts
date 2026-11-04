/**
 * SCR-143's words (E42-S06): E42-D05 §15's `health.*`, `stops.*` and `hint.*`, D03's `tile.*` and
 * `meta.asof`. Cited strings are verbatim; the rest are §15's PROPOSED ones, owner E42-D05, and the
 * lines this build adds are marked PROPOSED here: the detail view's [BQ-11], and the client's words
 * for a failed read, never the server's `detail` [BQ-14].
 */
import { STOPS as CITED_STOPS } from "../overview/copy";

export const HEALTH_COPY = {
  title: "System health",
  /** PROPOSED: `meta.asof` before the report's first answer. */
  allUtc: "All times UTC",
  reread: "Re-read",
  retry: "Retry",
  /** `health.overall`; no "as of" for the frame held at mount, which has no time [BQ-8]. */
  overall: (word: string, hms: string | undefined, frame: boolean): string => {
    const asOf = hms === undefined ? "" : ` · as of ${hms}`;
    return `Overall: ${word}${asOf}${frame ? " (last health frame)" : ""}`;
  },
  /** D03 `tile.unavailable`, HL-15's overall line. */
  unavailable: (detail: string): string => `Unavailable — ${detail}`,
  /** `health.incidents` as text (its link is SCR-144's part); "+" when the page has more. */
  incidents: (n: number, more: boolean): string => `Incidents (${n}${more ? "+" : ""} open)`,
  /** PROPOSED: the open incidents read did not answer. */
  incidentsUnread: "Incidents: not received",
  reportFailed: (detail: string): string =>
    `Health report unavailable — ${detail}. Showing live states only.`,
  probesNotDeployed: "Health probes aren't deployed yet — showing live frames only",
  notDeployed: "Not built yet",
  notReported: "Not reported yet",
  /** `health.not_received`: a word the newest frame names in a state the client cannot read. */
  notReceived: "— not received",
  probe: "probe",
  unit: "ms",
  unitSpoken: "milliseconds",
  /** D03 `tile.stale` on CMP-239. */
  staleSince: (hms: string): string => `stale since ${hms}`,
  bannerDown: (labels: string): string => `Down: ${labels}. Each tile says what stops working.`,
  announce: (label: string, word: string): string => `Health: ${label} ${word}.`,
  recovered: (label: string): string => `Health: ${label} healthy again.`,
  noHistory: "History isn't recorded yet.",
  /** PROPOSED (CG-20): the drill-down's metrics wait for a read. */
  noMetrics: "Last-hour metrics aren't recorded yet.",
  drill: {
    /** Each link's arrow is drawn beside it, hidden from the accessibility tree. */
    recorder: "Open Recorder & storage",
    /** PROPOSED [BQ-11]: the detail view's way back to the tiles. */
    back: "All components",
    /** PROPOSED [BQ-11]: a `?component=` no tile has; the link's name is never shown. */
    unknown: "No such component.",
    /** PROPOSED: the document title's words for that view (A-1084P1-d04). */
    unknownTitle: "No such component",
    /** PROPOSED [BQ-11]: what the incident list is, said so. */
    filtered: "Its open incidents, from the newest 100 open ones:",
    none: "No open incidents for this component.",
    unread: "Its open incidents can't be read right now.",
    row: (severity: string, title: string, lastSeen: string): string =>
      `${severity} · ${title} · last seen ${lastSeen} UTC`,
    /** `incident.withheld`: a title the server could not clean. */
    withheld: "Details withheld — they couldn't be cleaned of sensitive text.",
  },
  /** D4: the client tile, and the 143-C1 item with no component (CG-18). */
  client: { label: "Chart engine (this session)", none: "No chart open in this window" },
  algo: { label: "Algo engine" },
  /** HL-8, `stops.clock`; "Clock" and the announced "drift" are PROPOSED. */
  clock: {
    label: "Clock",
    ok: (n: string): string => `offset ${n} ms · ok`,
    drift: (n: string): string =>
      `DRIFT — offset ${n} ms — order entry halts until time sync recovers (Bybit 10002).`,
    notMeasured: "not measured (time sync not deployed)",
    word: "drift",
  },
  /** PROPOSED: the build line's uptime, "up 1 d 2 h". */
  up: (d: number, h: number, m: number): string =>
    `up ${d > 0 ? `${d} d ${h} h` : h > 0 ? `${h} h ${m} min` : `${m} min`}`,
  /** PROPOSED [BQ-14]: the client's words for a failed read. */
  failure: {
    timeout: "no answer in 3 s",
    network: "the server could not be reached",
    busy: "the server is busy",
    audit: "the audit log can't record the read",
    unreadable: "the answer could not be read",
    status: (status: number): string => `the server answered ${status}`,
  },
} as const;

/**
 * `stops.<component>:<state>`: S01's cited sentences (D02:715), then §15's proposed ones, for
 * E42-D06's review. A component and state without one shows no line.
 */
export const STOPS: Readonly<Record<string, string>> = {
  ...CITED_STOPS,
  "bybit_public_ws:down": "prices, charts and the order book stop updating.",
  "questdb:down": "new market data isn't stored; charts may show gaps.",
  "parquet_store:down": "older history can't be read.",
  "ingestion:degraded": "market data may arrive late or with gaps.",
  "bars:degraded": "chart bars may lag.",
  "secrets:down": "stored keys can't be used, so no order can be signed.",
  "disk:down": "recording and backups can't write.",
  "postgres:degraded": "saving may be slow.",
  "recorder:degraded": "some symbols may miss history.",
  "oms:down":
    "no new orders from CandleViewer, and stop-losses being placed or changed may not be " +
    "confirmed: check your positions on Bybit.",
};

/** `hint.<component>`, an action in CandleViewer or at Bybit, never a promise; else `default`. */
export const HINTS: Readonly<Record<string, string>> = {
  bybit_private_ws:
    "Check the account's link on Exchange connectivity; reconnects run by themselves.",
  bybit_public_ws: "Check Exchange connectivity; reconnects run by themselves.",
  bybit_rest:
    "Check Exchange connectivity for rate limits or a Bybit outage; manage positions on Bybit if " +
    "you must.",
  disk: "Free space on the server's data disk, or shorten retention in Recorder & storage.",
  clock:
    "Check the server's time sync; order entry resumes once the offset is back under the limit.",
  postgres: "Check the database service on the server, then its runbook.",
  questdb: "Check the database service on the server, then its runbook.",
  parquet_store: "Check the database service on the server, then its runbook.",
  oms: "Check your positions and their stop-losses on Bybit, then the incident's runbook.",
  secrets: "Check that the server's master key is available; the incident's runbook says how.",
  recorder: "Open Recorder & storage to see which symbols stopped.",
  default: "Open the component's incident for its runbook.",
};
