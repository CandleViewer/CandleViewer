/**
 * The statechart inspector's words (E42-S08). Keyed strings are verbatim from E42-D05 §15
 * (`machine.*`, `admin.*`) and §11's anatomy (its column and control names). The rest have no deck
 * key: each is marked PROPOSED (owner E42-D05) and listed in `14`'s As-built line.
 */
export const INSPECTOR_COPY = {
  /** The page (§5.1). */
  page: {
    /** The `h1` and R-357's page title (BQ-1; board 09's "E42-S08 inspector" is a placeholder). */
    title: "Statechart inspector",
    /** E42-D03's `meta.asof` "All times UTC · as of {hh:mm:ss}"; its first half alone before an answer. */
    utc: "All times UTC",
    asOf: (hms: string): string => `All times UTC · as of ${hms}`,
  },
  /** `machine.current`. */
  current: "current",
  /** The chart's text list (§4.2), the normative non-visual equivalent of the drawing. */
  chart: {
    /** PROPOSED: the list's two headings. */
    states: "States",
    transitions: "Transitions",
    /** PROPOSED: a parallel root's top-level states are its regions, all active together. */
    parallelRoot: "The top-level states run in parallel.",
    /**
     * PROPOSED: the source of the root's own transitions. The library takes the deepest source
     * first, so a root arm applies only where the active state does not handle the event itself.
     */
    anyState: "Any state that doesn't handle it itself",
    /** PROPOSED: a state's markers, each read as "(initial)". */
    initial: "initial",
    final: "final",
    parallel: "parallel",
    /** PROPOSED: the words after the arrow, which is hidden from assistive technology. */
    to: "to",
    on: (event: string): string => `on ${event}`,
    always: "(always)",
    after: (delay: string): string => `after ${delay}`,
    done: (service: string): string => `when ${service} is done`,
    error: (service: string): string => `when ${service} fails`,
    /** PROPOSED: an arm with no target, such as a guard's refusal arm. */
    noChange: "no state change",
    /** PROPOSED: the drawing's region and its image (§4.4; BQ-6). */
    diagramName: (kind: string): string => `State diagram: ${kind}`,
    diagramTitle: (kind: string, states: number): string =>
      `${kind} chart: ${states} states. The list after it gives every state and transition.`,
    /** PROPOSED `machine.too_large`: a chart over the drawing's bounds (§4.3). */
    tooLarge: "This chart is too large to draw here; the list below is complete.",
  },
  /** `machine.latched`. */
  latched: (trips: number): string => `Latched — chain trips: ${trips}`,
  /** `machine.unreadable` and `machine.seal_failed`. */
  unreadable: "Machine snapshots can't be read right now.",
  sealFailed: "A snapshot's seal didn't verify, so its machine isn't listed.",
  /** `admin.ack_not_built`: the acknowledge's T2 reason until its write path exists (BQ-5). */
  ackNotBuilt: "Acknowledging isn't built yet.",
  /** The machine view (§5.2). */
  view: {
    heading: (machine: string, env: string): string => `${machine} · ${env}`,
    /** PROPOSED. */
    back: "Back to machines",
    /** PROPOSED, after E42-D05's `health.reread`. */
    reread: "Re-read",
    /** CMP-027's Retry. */
    retry: "Retry",
    /**
     * §11's [Acknowledge latch…]; its name names the machine, "Acknowledge latch on {machine}…"
     * (the ticket's a11y note), the visible label first (WCAG 2.5.3).
     */
    acknowledge: "Acknowledge latch",
    acknowledgeOn: (machine: string): string => ` on ${machine}`,
    ellipsis: "…",
    /** PROPOSED `machine.not_found`. */
    notFound: "This machine isn't listed. It may have stopped, or it isn't visible to you.",
    /** PROPOSED: a `501` on the machine. */
    notBuilt: "Machine details aren't available on this server.",
    /** PROPOSED: the machine's read failed (a timeout, the network or a `5xx`). */
    failed: "This machine can't be read right now.",
    /** PROPOSED: a failed read of the machine or of its chart read again, polite once (D05 §13). */
    loaded: "The machine loaded.",
    chartLoaded: "The chart loaded.",
    /** PROPOSED `machine.chart_unavailable` and `machine.chart_changed`. */
    chartUnavailable: "The chart can't be read right now.",
    chartChanged: "This chart changed since the machine was read.",
    /** PROPOSED: the timeline's two empty states. */
    eventsUnavailable: "Events can't be read right now.",
    eventsNone: "No events recorded yet.",
  },
  /** The machine's facts: §11's column names. */
  facts: {
    kind: "Kind",
    environment: "Environment",
    state: "State",
    hash: "Hash",
    chainTrips: "Chain trips",
    latched: "Latched",
    deferred: "Deferred",
    updated: "Updated",
  },
  /** §11's words for the hash against `machine_hashes.lock`. */
  matches: "matches the lock",
  differs: "differs",
  /** PROPOSED: a machine whose latch is not set. */
  notLatched: "Not latched",
  /** PROPOSED: the name of "—" where a value is not recorded (`deferred_depth` `null`). */
  notRecorded: "not recorded",
  /** "{hh:mm:ss} UTC" (E42-D03 §1: admin times are UTC). */
  utc: (time: string): string => `${time} UTC`,
  /** The timeline (SI-5): §11's columns, `machine.timeline.*`, and a PROPOSED caption. */
  timeline: {
    caption: "Events, newest first",
    time: "Time",
    event: "Event",
    phase: "Phase",
    fromTo: "From → to",
    faulted: "Faulted",
    phases: { ahead: "ahead", commit: "commit", fault: "fault" },
    faultedWord: "faulted",
    /** PROPOSED: the name of "—" for an event with no states on one side. */
    none: "none",
  },
  /** The list page (§5.1): §11's column and control names, `machine.*`, and PROPOSED lines. */
  list: {
    /** PROPOSED: the counters' `h2` and caption, and the grid's. */
    kindsHeading: "Machines by kind",
    machinesHeading: "Machines",
    /** §11's toggle. */
    latchedOnly: "Latched only",
    /** §11's columns: the counters', and the grid's first (the rest are the facts' words). */
    columns: {
      kind: "Kind",
      environment: "Environment",
      machines: "Machines",
      byState: "By state",
      chainTrips: "Chain trips",
      latched: "Latched",
      droppedReceipts: "Dropped receipts",
      machine: "Machine",
    },
    /** PROPOSED, as SCR-120's: a count the metrics source did not give, after a drawn "—". */
    notReceived: "not received",
    /** `machine.metrics_unavailable`. */
    metricsUnavailable: (detail: string): string => `Metrics unavailable — ${detail}`,
    /** `machine.rowless`; the kind is "{kind} (B{n}) · {ENV}", per kind and environment. */
    rowless: (kind: string, n: number): string =>
      `${kind}: ${n} latched — this kind has no public id yet, so it can't be opened or acknowledged here`,
    /** `machine.latched_effect`. */
    latchedEffect: "A latched machine refuses order-path commands until its latch is acknowledged.",
    /** `machine.empty`. */
    empty: "No machine has a saved snapshot yet.",
    /** PROPOSED `machine.none_latched`. */
    noneLatched: "No machine is latched.",
    /** PROPOSED: no row although kinds run (the kinds without a public id show as counters only). */
    noRows: "No machine to list.",
    noRowsRowless: "The kinds running have no public id yet, so they show only in the counters.",
    /** PROPOSED `machine.more`: `has_more`, until #1135's cursor pager (BQ-9). */
    more: "Showing the first 200 machines. Turn on Latched only to narrow the list.",
    /** PROPOSED: the list's read failed (a timeout, the network or a `5xx`). */
    failed: "The machine list can't be read right now.",
    /** PROPOSED: a failed read of the list read again, polite once (D05 §13 "recovery"). */
    loaded: "The machine list loaded.",
    /**
     * PROPOSED: a filter's result, polite once per filter (D05 §13 "results"); none latched reads
     * `machine.none_latched`.
     */
    listed: (n: number, latchedOnly: boolean): string =>
      `${n} ${latchedOnly ? "latched " : ""}${n === 1 ? "machine" : "machines"} listed.`,
    /** PROPOSED: a `404` or `501` on the list. */
    notBuilt: "The machine list isn't available on this server.",
    /** PROPOSED: the grid's visible hint above it, and its first cells' description. */
    openHint: "Enter opens a machine.",
  },
} as const;
