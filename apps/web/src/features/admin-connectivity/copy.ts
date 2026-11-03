// Generated once from docs/design/E08/E08-D13-copy.json (keys `d09.W-nn`), byte for byte; the copy test
// compares every entry to the pack, which wins on any conflict. PROPOSED strings stay PROPOSED (E08-D09 §15).
// A `{slot}` is illustrative: a figure is filled only from a served value (`fill`), never typed here.

export const COPY = {
  "W-01": "illustrative values, not a market capture",
  "W-02": "Exchange connectivity",
  "W-03": "All times UTC · as of {14:02:11}",
  "W-04": "as of {14:02:11} · stale since {14:02:11} · Stale {4s}",
  "W-05": "Not connected yet · The backend does not serve this figure yet.",
  "W-06a": "Reserved for stops and cancels · Not connected yet",
  "W-06b": "Reserved for stops and cancels · {30} requests",
  "W-07":
    "Request budgets by endpoint class and account. Headroom excludes the reserve for stops and cancels.",
  "W-08": "Class · Account · Limit · Used now · Window · Headroom",
  "W-09": "{7} of {10} requests per second used, {0} left after the reserve",
  "W-10": "All classes, peak per minute",
  "W-11": "Exchange · Network · Our backend",
  "W-12":
    "Wait. The exchange sets this limit. · Wait for the reconnect, or force a reconnect. · Check the backend. The exchange is not the cause.",
  "W-13": "Within budget",
  "W-14": "Attention: near limit · {82} % of the spendable budget used",
  "W-15":
    "Throttled · {Main}, {order} · Limit {10} requests per second · Retry at {14:32:10} (in {42} s) · code 10006",
  "W-16":
    "On hold — all accounts · Our hold ends at {14:42:05} (in {8m 20s}) · code 10018 · The exchange asked us to slow down across every account.",
  "W-17":
    "Banned by the exchange · All requests from this server are locked out for at least 10 minutes. · Time left: not received",
  "W-18": "Disconnected · Disconnected — last data {00:12} ago",
  "W-19": "Reconnecting… · attempt {3}",
  "W-20": "Connection unstable",
  "W-21": "Clock drift",
  "W-22":
    "Order entry halted · Order entry halted until the server clock is back in sync with the exchange.",
  "W-23":
    "Not measured yet · Clock offset has not been measured yet. · Order entry waits for the first measurement.",
  "W-24": "Degraded",
  "W-25":
    "Error · Our rate-limit counters did not report. · last good {14:01:58} · Usage is unknown until our counters report again.",
  "W-26":
    "Unavailable · We couldn't read the connectivity report. Figures stay unknown until it answers. · Retry",
  "W-27":
    "The exchange refused a request because our clock was out of its window (code 10002). Order entry resumes after a successful measurement.",
  "W-28":
    "Dropping updates · Our backend dropped {12} market-data updates in the last minute. The affected panels resync.",
  "W-29": "In sync · {12} ms {behind}",
  "W-30": "No topics subscribed · The backend holds no market-data subscription right now.",
  "W-31":
    "Cancel, close, flatten and stop placement use the reserved budget once it is connected. · Native stops on the exchange are unaffected.",
  "W-32": "Charts keep showing stored data.",
  "W-33":
    "While the hold lasts, no request from this server reaches the exchange, protective ones included. Native stops on the exchange stay active. The kill switch is a synchronous local check, not a request to the exchange.",
  "W-34":
    "Don't retry in a loop: it extends the limit. · Don't raise the budget: it can't raise the exchange's limit. · Don't force a reconnect: it can't end the hold. · Check this server's outbound setup.",
  "W-35": "Re-measure now · Measuring…",
  "W-36": "All requests are on hold.",
  "W-36b": "A measurement just ran. Try again in {20} s.",
  "W-37":
    "Bar boundaries and request signatures depend on this clock. Past 2 s, the exchange can refuse orders, so order entry is halted.",
  "W-38":
    "Our clock is {0.62} s behind the exchange. · Our clock is {0.62} s ahead of the exchange.",
  "W-39": "About every 5 minutes · Last measured {14:00:03} ({2m} ago)",
  "W-40":
    "A {5}-account fan-out with brackets costs about {15} requests — {9} % of each account's spendable budget per minute.",
  "W-41":
    "Accounts · Entry legs per account · Take-profit legs per account · Stop-loss: always counted · Fan-out policy · All or nothing · Best effort · Estimate cost",
  "W-42":
    "Served now · Deferred · Refused — the whole group · {3} accounts served now, {2} deferred.",
  "W-43": "Out of date — estimate again.",
  "W-44": "Subscriptions ({3} connections, {120} topics)",
  "W-45": "Public market data · socket {1}",
  "W-46":
    "Largest request: {10} of 10 topics · {1 840} of 21 000 characters · {120} of 500 topics on this socket",
  "W-47":
    "Binding: topics per request · Binding: characters per request · Binding: topics per socket",
  "W-48": "{3} s ago · Gaps {0} · Last resubscribe {14:01:12} · Last re-seed {13:58:40}",
  "W-50": "Reconnect market data",
  "W-51":
    "Every market-data subscription is dropped and re-established. · Charts, the order book and the tape resync for a moment. · Subscriptions come back in the usual order: your focused panel first, then the rest. · Native stops on the exchange are unaffected. · Nothing is ordered or cancelled.",
  "W-52": "{3} connections · {120} topics",
  "W-53":
    "Reconnect order and position updates for {Main} · Order and position updates pause. We check them against the exchange when the stream is back.",
  "W-54": "Step-up class: not defined yet",
  "W-55": "Recorded in the audit log · Reconnect forced (pending registration)",
  "W-56": "The connection budget can delay a reconnect.",
  "W-57": "Wait {40} s. The connection budget allows no new connection yet.",
  "W-58": "Market data reconnected. {120} topics subscribed.",
  "W-59": "Reconnected · {40} topics · Not reconnected · {mapped reason}",
  "W-60": "Change budget…",
  "W-61": "Allowed: {60} to {420} requests per minute",
  "W-62": "This changes how many requests we send for {Main}. You can change it back at any time.",
  "W-63": "Recorded in the audit log · Request budget changed (pending registration)",
  "W-64":
    "The exchange's limit for this account is the ceiling. · Raising this never raises the exchange's limit. · The reserve for stops and cancels is kept out of this budget. · This changes this account only.",
  "W-70": "Usage history",
  "W-71": "1 hour · 6 hours · 24 hours · View as table",
  "W-72": "{order} requests, {Main}, last hour: rising, {12} to {41} per second",
  "W-73": "No usage recorded in this window.",
  "W-74": "Read-only while viewing as {user}.",
} as const;

export type CopyKey = keyof typeof COPY;

// PROPOSED words that are not in the E08-D13 pack, kept out of `COPY` so the pack comparison stays exact.
/** The Change budget confirm button: E08-D09:379 names it "Save budget"; the pack has no entry (PROPOSED). */
export const SAVE_BUDGET = "Save budget";
/** An account row served without a label: the pack has no unnamed-account string (PROPOSED; owner: the copy deck's owner, E17-D02). */
export const UNNAMED_ACCOUNT = "Account";
