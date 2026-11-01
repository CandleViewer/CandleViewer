/**
 * E16-S03 (#485) fixtures: the `22` examples verbatim, typed by the generated contract
 * (`getStorageUsage` "usage", `listRetentionPolicies` "defaults"), plus the policy builder D03's
 * worked sets use. No market data and no recorded capture: the contract's own examples only.
 */
import type { generated } from "@candleviewer/protocol";

type Schemas = generated.rest.components["schemas"];
type PolicyList =
  generated.rest.operations["listRetentionPolicies"]["responses"][200]["content"]["application/json"];
type Policy = Schemas["RetentionPolicy"];

/** `22` `getStorageUsage`, example `usage`: BTCUSDT pinned (780 MB/day), ETHUSDT not (520 MB/day). */
export const STORAGE_USAGE = {
  disk_total_bytes: 4000000000000,
  disk_used_bytes: 1204000000000,
  disk_free_bytes: 2796000000000,
  projected_full_at: "2028-03-27T10:31:03Z",
  daily_growth_bytes: 1450000000,
  cap_bytes: 2000000000000,
  level: 0,
  write_gate: "open",
  write_gate_reason: null,
  accelerate_retention: false,
  tiers: [
    { tier: "questdb", used_bytes: 640000000000, retention_days: 7 },
    { tier: "parquet", used_bytes: 548000000000, retention_days: 30 },
    { tier: "postgres", used_bytes: 16000000000, retention_days: null },
  ],
  symbols: [
    { symbol: "BTCUSDT", used_bytes: 812340221100, daily_growth_bytes: 780000000, pinned: true },
    { symbol: "ETHUSDT", used_bytes: 1220004410, daily_growth_bytes: 520000000, pinned: false },
  ],
  generated_at: "2026-09-14T10:31:03.000Z",
} satisfies Schemas["StorageUsage"];

/** `22` `listRetentionPolicies`, example `defaults`: two global rows and ETHUSDT's override. */
export const POLICIES_DEFAULTS = {
  items: [
    {
      id: "f1000000-0000-4000-8000-000000000001",
      stream: "trades",
      retain_days: 30,
      action: "archive_parquet",
      symbol: null,
      applies_to_pinned: false,
    },
    {
      id: "f1000000-0000-4000-8000-000000000002",
      stream: "orderbook_delta",
      retain_days: 7,
      action: "archive_parquet",
      symbol: null,
      applies_to_pinned: false,
    },
    {
      id: "f1000000-0000-4000-8000-000000000003",
      stream: "orderbook_delta",
      retain_days: 3,
      action: "drop",
      symbol: "ETHUSDT",
      applies_to_pinned: false,
    },
  ],
} satisfies PolicyList;

/** One stored row, as `listRetentionPolicies` answers it (D03's worked sets: K2, K4, K6, K7). */
export const policy = (
  stream: Policy["stream"],
  retain_days: number,
  action: Policy["action"],
  symbol: string | null = null,
): Policy => ({ stream, retain_days, action, symbol, applies_to_pinned: false });
