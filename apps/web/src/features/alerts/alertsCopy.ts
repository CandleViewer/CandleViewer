/**
 * Values at fire time are absent from the history and the CSV until CC-2 lands: the delivery row's
 * rendered message stands in for them.
 */
/** SCR-090 copy (E40-D02 handoff, "Copy deck" and C1), as constants: the screen holds no inline strings. */
export const COPY = {
  heading: "Alerts",
  /** E09-D09 §3.2: the `{verb}` of `alerts:write`, filling `rbac.permission`. */
  writeVerb: "change alerts",
  loading: "Loading alerts…",
  empty: "No alerts yet",
  emptyBody:
    "Create an alert to be told when a price, indicator or order-flow condition is met. Alerts notify; they never place orders.",
  filteredEmpty: "No alerts match these filters.",
  clearFilters: "Clear filters",
  tabEmpty: { all: "No alerts yet", fired: "Nothing has fired yet.", snoozed: "Nothing snoozed." },
  errorTitle: "Alerts couldn't load.",
  errorCause: {
    unavailable: "The alerts service is unavailable.",
    other: "No response from the server.",
  },
  retry: "Retry",
  tabs: { all: "All", fired: "Fired", snoozed: "Snoozed" },
  readOnly: "Your role can't change alerts.",
  forbiddenCapability: "see alerts",
  vocabularyDown:
    "Alert conditions can't be described right now: the rule engine isn't available. Your alerts are unchanged.",
  disconnected: "Disconnected — alerts may be out of date",
  resyncing: "Resyncing alerts…",
  estimated: "(estimated)",
  disarmTitle: (metric: string): string => `Alert disarmed: ${metric} data source unavailable`,
  disarmWhy:
    "The data source stopped arriving, so the alert was disarmed instead of firing on missing data. It stays off until you enable it.",
  enableConfirm: "If the source is still unavailable, it will disarm again and tell you.",
  deliveryProblem: "Desktop notification blocked by the OS — enable it in Settings",
  deliveryChip: "Desktop blocked",
  showing: (n: number, total: number): string => `Showing ${n} of ${total} alerts`,
  capped: (shown: number, total: number): string =>
    `Showing the first ${shown} of ${total} — refine the filters to see the rest.`,
  truncated: "Only the newest firings are shown; the export holds the same rows.",
  /** Parser-safe: documented here and shown in the dialog, never as a comment line in the CSV. */
  csvNote: "Values at fire time are not stored; the message text stands in for them.",
  selected: (n: number): string => `${n} selected`,
  bulk: {
    enable: {
      title: (n: number) => `Enable ${n} alerts?`,
      body: "They will fire again when their conditions are met. Any the server disarmed may disarm again.",
      confirm: (n: number) => `Enable ${n}`,
    },
    disable: {
      title: (n: number) => `Disable ${n} alerts?`,
      body: "They stop firing until you enable them. Their history is kept.",
      confirm: (n: number) => `Disable ${n}`,
    },
    delete: {
      title: (n: number) => `Delete ${n} alerts?`,
      body: "This can't be undone. Their past firings stay in Notifications.",
      confirm: (n: number) => `Delete ${n}`,
    },
  },
  bulkDone: { enable: "enabled", disable: "disabled", delete: "deleted" },
  failReason: {
    not_found: "it was deleted",
    forbidden: "Your role can't change alerts.",
    invalid: "the server refused the change",
    unavailable: "the server didn't respond — try again",
  },
  history: {
    title: (name: string): string => `Firing history: ${name}`,
    loading: "Loading firings…",
    empty: "This alert hasn't fired.",
    error: "The firing history couldn't load.",
    export: "Export CSV",
    suppressed: "Suppressed (storm)",
    summary: "Folded into a storm summary",
    summaryLink: "Open Notifications",
    close: "Close",
  },
  actions: {
    snooze: "Snooze",
    wake: "Wake now",
    enable: "Enable",
    disable: "Disable",
    chart: "Show on chart",
    history: "View history",
    delete: "Delete…",
  },
  deleteOne: { title: (name: string): string => `Delete ${name}?`, confirm: "Delete" },
} as const;
