/**
 * SCR-120's words (E42-S01). Keyed strings are verbatim from the copy decks: E42-D03 §14 (`tile.*`,
 * `cap.*`, `strip.*`, `meta.asof`), E42-D04 §14 (`audit.marker`) and E42-D05 §15 (`stops.*`, the cited
 * sentences only). The tile lines' labels and the client's failure words have no deck key: they are
 * PROPOSED (owner E42-D03), after E42-D02 §6.2's wireframe and E42-D01's tile contents.
 */
export const OVERVIEW_COPY = {
  title: "Overview",
  /** `meta.asof` "All times UTC · as of {hh:mm:ss}" (proposed in the deck). */
  meta: (hms: string): string => `All times UTC · as of ${hms}`,
  /**
   * PROPOSED: a line's own read time when its tile's "as of" is another read's (C-5330-11): E42-D03's
   * `tile.asof` ("as of {hh:mm:ss}") with the "UTC" an absolute time carries (D02:119).
   */
  rowAsOf: (hms: string): string => `as of ${hms} UTC`,
  /** The three bands' `h2`s (§6 Anatomy), drawn in capitals by the style, read as words. */
  bands: ["Right now", "People and access", "Evidence and controls"],
  tiles: {
    trading: "Trading safety",
    health: "Health",
    recorder: "Recorder and storage",
    users: "Users",
    accounts: "Accounts and keys",
    profiles: "Profiles and limits",
    audit: "Audit",
    security: "Security and backups",
    flags: "Flags",
  },
  /** `tile.not_built`'s detail: "Unavailable — not built yet". */
  notBuilt: "not built yet",
  /** PROPOSED: a slice the answer left out, "Unavailable — not received". */
  notReceived: "not received",
  /** PROPOSED: the client's words when a read failed (the server's slice errors are its own). */
  failure: {
    timeout: "no answer within 3 s",
    network: "the server could not be reached",
    status: (status: number | undefined): string => `the server answered ${status ?? "an error"}`,
    unreadable: "the answer could not be read",
  },
  /** Trading safety (`tile.trading_unknown`, `tile.maintenance_off`, `tile.maintenance_on`). */
  trading: {
    live: "Live trading",
    killSwitch: "Kill switch",
    positions: "Open positions",
    maintenance: "Maintenance",
    on: "on",
    off: "off",
    unknown: "unknown",
    maintenanceOff: "off (flags read)",
    /** `tile.maintenance_on` (proposed in the deck): "ON since {hh:mm} UTC → Maintenance". */
    maintenanceOn: (hhmm: string | null): string =>
      hhmm === null ? "ON → Maintenance" : `ON since ${hhmm} UTC → Maintenance`,
  },
  /** PROPOSED row labels, after E42-D02 §6.2 and E42-D01's tile contents. */
  users: {
    total: "Total",
    active: "Active",
    withoutMfa: "Without two-factor",
    invites: "Invites pending",
  },
  accounts: {
    total: "Total",
    enabled: "Enabled",
    expiring: "Keys expiring within 30 days",
    invalid: "Keys rejected by Bybit",
    /** The line's read is not mounted (`getSecuritySummary`, CG-7): `tile.not_built`. */
    withdrawal: "Withdrawal permission",
  },
  recorder: {
    recording: "Symbols recording",
    degraded: "Symbols degraded",
    lag: "Lag p99",
    used: "Disk used",
    free: "Disk free",
    daysUntilFull: "Days until full",
    /** `tile.not_measured`. */
    notMeasured: "not measured",
  },
  health: {
    incidents: "Open incidents",
    /** `tile.not_deployed` (proposed in the deck, after D02:715); one component reads singular. */
    notDeployed: (n: number): string =>
      `${n} ${n === 1 ? "component" : "components"} not deployed — showing live frames only`,
  },
  flags: {
    total: "Total",
    enabled: "Enabled",
    /** PROPOSED, after E42-D02 §10's SCR-145 line: a `fail_closed` list is not the stored state. */
    failClosed: "flag store unreachable — every flag shows its fail-closed value",
  },
  /** E42-D04 §14 `audit.marker`: the overview's audit read is recorded as `admin.audit_read`. */
  auditMarker: "Viewing this log is recorded — Audit log viewed (admin.audit_read)",
  backups: {
    last: "Last backup",
    /** PROPOSED: a catalogue with no run yet. */
    none: "none yet",
  },
  /** The capacity line, `cap.*` (E42-D03 §14); its [Change] and [Record tier] are E42-S02's. */
  cap: {
    recorded: (used: number, cap: number, tier: string, date: string | null): string =>
      `${used} of ${cap} sub-accounts used · ${tier} tier${date === null ? "" : `, recorded ${date}`}`,
    /** D12 (proposed in the deck): over the cap, the copy asserts no single cause. */
    over: (used: number, cap: number, tier: string): string =>
      `${used} sub-accounts in use · ${tier} tier allows ${cap}. Bybit lets accounts keep ` +
      "sub-accounts made before 14 August 2026 — or the recorded tier may be wrong.",
    unrecorded: (used: number): string =>
      `${used} sub-accounts in use · Tier not recorded — record it to see your cap`,
    tierUnavailable: (used: number): string =>
      `${used} sub-accounts in use · cap unavailable right now`,
    usedUnavailable: (tier: string, cap: number): string =>
      `${tier} tier allows ${cap} · sub-accounts in use: unavailable right now`,
    down: "Sub-account capacity unavailable right now",
    /** PROPOSED: a capacity read answered `404` or `501`: its name, then `tile.not_built`. */
    notBuilt: "Sub-account capacity: Unavailable — not built yet",
    tiers: { regular: "Regular", business_kyc: "Business KYC" } as Readonly<Record<string, string>>,
  },
  /** `strip.*` (E42-D03 §14): counts only, as the slices return them; one reads singular. */
  strip: {
    noMfa: (n: number): string =>
      n === 1
        ? "1 active user without two-factor → Users"
        : `${n} active users without two-factor → Users`,
    keyExpiry: (n: number): string =>
      n === 1
        ? "1 key expires within 30 days → Accounts and keys"
        : `${n} keys expire within 30 days → Accounts and keys`,
    keysInvalid: (n: number): string =>
      n === 1
        ? "1 key rejected by Bybit → Accounts and keys"
        : `${n} keys rejected by Bybit → Accounts and keys`,
    tier: "Tier not recorded → Record tier",
  },
} as const;

/**
 * E42-D05 §15 `stops.<component>`, the sentences it cites (D02:715) per component and state: what
 * stops working. A component and state without one shows no line (the proposed ones await
 * E42-D06's review, so they stay out).
 */
export const STOPS: Readonly<Record<string, string>> = {
  "postgres:down": "new orders are off; cancel and close still work.",
  "bybit_private_ws:degraded": "order and position updates may lag; REST reconcile runs.",
  "bybit_rest:down": "no new orders; cancel/stop reserve only.",
  "rule_engine:down": "armed rules are not evaluating",
  "recorder:down": "no new history",
  "disk:warning": "recording stops at 95 %",
  "oms:degraded": "reconciliation pending.",
};
