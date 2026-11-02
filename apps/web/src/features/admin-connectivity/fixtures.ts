import type { CapacityReport } from "./rateBudget";
import type { UsagePoint } from "./components";

// Illustrative values, not a market capture (W-01). No credential, hostname, address or identifier appears here: the wire
// id is optional in the contract and left out, and the text-scan test keeps it that way (C-13.5).

/** The clock every illustrative time derives from: W-03's 14:02:11 UTC on 2026-10-22. */
export const AS_OF = Date.UTC(2026, 9, 22, 14, 2, 11);
export const GOOD = Date.UTC(2026, 9, 22, 14, 1, 58);

/** `rate_budget_status: ok`, two accounts, a peak per minute each. */
export const SERVED_REPORT: CapacityReport = {
  rate_budget_status: { status: "ok" },
  rate_budget: [
    { label: "Main", limit_per_minute: 600, peak_used_per_minute: 120, utilisation_pct: 20 },
    { label: "Swing", limit_per_minute: 600, peak_used_per_minute: 510, utilisation_pct: 85 },
  ],
};

/** What the backend answers today: no provider wired (D09-G2), so S-19. */
export const UNAVAILABLE_REPORT: CapacityReport = {
  rate_budget_status: { status: "unavailable", detail: "rate-limit peak: no provider wired" },
  rate_budget: [],
};

/** A source that timed out or failed: S-17. The served `detail` is never printed. */
export const ERROR_REPORT: CapacityReport = {
  rate_budget_status: { status: "error", detail: "probe failed: upstream said no" },
  rate_budget: [],
};

export const USAGE_SERIES: readonly UsagePoint[] = [
  { at: "13:00", used: 12 },
  { at: "13:20", used: 18 },
  { at: "13:40", used: 30 },
  { at: "14:00", used: 41 },
];
