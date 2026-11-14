/** A `ReconciliationDigest` as `getReconciliationDigest` answers it (#5584's generated type). */
import type { ReconciliationDigest } from "../../../../src/features/reconciliation/digest";

export const A = "a1000000-0000-4000-8000-00000000000a";

export const digest = (over: Partial<ReconciliationDigest> = {}): ReconciliationDigest => ({
  exchange_account_id: A,
  pass_id: "b1000000-0000-4000-8000-000000000001",
  trigger: "reconnect",
  result: "corrected",
  confirmed_at: "2026-11-03T14:02:10.000000Z",
  gap_window: { from: "2026-11-03T14:01:25.000000Z", to: "2026-11-03T14:02:10.000000Z" },
  counts: {},
  abandoned: [],
  anomalies: [],
  corrected: [],
  foreign_stops: [],
  held: [],
  newly_unknown: [],
  position_drift: [],
  resolved_from_history: [],
  sl_repaired: [],
  sl_restore_refused: [],
  sl_restored: [],
  sl_tighter: [],
  unpaired: [],
  unprotected: [],
  untracked: [],
  ...over,
});
