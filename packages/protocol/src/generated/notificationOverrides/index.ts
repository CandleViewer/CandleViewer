// ==========================================================================
// GENERATED FILE — DO NOT EDIT BY HAND.
// Regenerate with `pnpm --filter @candleviewer/protocol generate`.
// Source: packages/protocol/notification-overrides.json (E40-D01 §5, E40-D02 §6.2)
// via scripts/generate-notification-overrides.mjs. The Python twin is
// services/api/candleviewer/alerts/_generated/notification_overrides.py.
// ==========================================================================
/* eslint-disable */
export const NOTIFICATION_OVERRIDES_VERSION = 1 as const;
export const NOTIFICATION_OVERRIDES_STATUS = "PROPOSED" as const;
export const USER_ALERTS_OVERRIDE = false as const;
export const NOTIFICATION_CATEGORIES = [
  "alerts",
  "rule_actions",
  "order_rejects",
  "risk_events",
  "system_health",
  "recorder",
] as const;
export type NotificationCategory = (typeof NOTIFICATION_CATEGORIES)[number];
export const NOTIFICATION_CHANNELS = ["toast", "centre", "desktop", "sound"] as const;
export type NotificationChannel = (typeof NOTIFICATION_CHANNELS)[number];
export const LOCKED_CELLS = [
  { category: "order_rejects", channel: "toast" },
  { category: "risk_events", channel: "toast" },
] as const;
export const CRITICAL_OVERRIDES = [
  {
    id: "CO-1",
    label: "Daily-loss lockout",
    category: "risk_events",
    toast: "banner",
    audience: "every_role",
  },
  {
    id: "CO-2",
    label: "Liquidation proximity",
    category: "risk_events",
    toast: "banner",
    audience: "every_role",
  },
  {
    id: "CO-3",
    label: "Connection lost with open positions",
    category: "system_health",
    toast: "banner",
    audience: "every_role",
  },
  {
    id: "CO-4",
    label: "Kill switch engaged",
    category: "risk_events",
    toast: "banner",
    audience: "every_role",
  },
  {
    id: "CO-5",
    label: "Trade group incomplete",
    category: "order_rejects",
    toast: "toast",
    audience: "every_role",
  },
  {
    id: "CO-6",
    label: "Position without an exchange stop",
    category: "risk_events",
    toast: "banner",
    audience: "every_role",
  },
  {
    id: "CO-7",
    label: "API key self-check failed",
    category: "system_health",
    toast: "toast",
    audience: "owner",
  },
  {
    id: "CO-8",
    label: "Recorder not writing",
    category: "recorder",
    toast: "toast",
    audience: "owner",
  },
  { id: "CO-9", label: "Disk threshold", category: "recorder", toast: "toast", audience: "owner" },
  {
    id: "CO-10",
    label: "Rate limit used up",
    category: "system_health",
    toast: "toast",
    audience: "owner",
  },
  {
    id: "CO-11",
    label: "Reconciliation mismatch",
    category: "system_health",
    toast: "toast",
    audience: "owner",
  },
  {
    id: "CO-12",
    label: "Rule engine errors",
    category: "system_health",
    toast: "banner",
    audience: "owner",
  },
] as const;
export type CriticalOverrideId = (typeof CRITICAL_OVERRIDES)[number]["id"];
export const OVERRIDE_CHANNELS = ["toast", "desktop", "sound"] as const;
export const OVERRIDE_TONE = "critical" as const;
