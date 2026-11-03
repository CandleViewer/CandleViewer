/**
 * The statechart catalogue's kinds as the inspector names them (E42-S08;
 * `28-statechart-catalogue.md` B1-B20, one committed chart each:
 * `statechart/machines/B01.order.machine.json` …). A kind reads "order (B1)". Four kinds have no
 * public entity id yet (`23-ws-protocol.md` §6.4, W9), so `listStatecharts` gives them no row:
 * their machines show only in the kind counters.
 */
import type { generated } from "@candleviewer/protocol";

/** A kind with a public id: the `machines.{entity}.state` topic's `machine_kind` (E17-T08). */
export type RowKind = generated.ws.MachinesEntityState["machine_kind"];

/** Each catalogue kind's B-number, as the committed chart files are numbered. */
export const B_NUMBERS: Readonly<Record<string, number>> = Object.freeze({
  order: 1,
  trade_group: 2,
  leg: 3,
  oco: 4,
  iceberg: 5,
  twap: 6,
  chase: 7,
  position_protection: 8,
  rule_instance: 9,
  alert: 10,
  recording: 11,
  replay: 12,
  ws_conn: 13,
  book: 14,
  paper_account: 15,
  session: 16,
  live_gate: 17,
  kill_switch: 18,
  reconciliation: 19,
  risk_lockout: 20,
});

/** The kinds `listStatecharts` can list a row for: every kind the topic grammar names. */
export const ROW_KINDS = [
  "order",
  "trade_group",
  "leg",
  "oco",
  "iceberg",
  "twap",
  "chase",
  "alert",
  "recording",
  "replay",
  "book",
  "session",
  "live_gate",
  "kill_switch",
  "reconciliation",
  "risk_lockout",
] as const satisfies readonly RowKind[];

/** B8, B9, B13 and B15: no public id yet (W9), so never a row, only their kind's counters. */
export const ROWLESS_KINDS = [
  "position_protection",
  "rule_instance",
  "ws_conn",
  "paper_account",
] as const;

/** A table's own entry, never an inherited one: "constructor" names no kind. */
const own = (kind: string): number | undefined =>
  Object.hasOwn(B_NUMBERS, kind) ? B_NUMBERS[kind] : undefined;

/** "order (B1)"; a kind the catalogue does not number reads as itself. */
export function kindLabel(kind: string): string {
  const n = own(kind);
  return n === undefined ? kind : `${kind} (B${n})`;
}

/** Whether `kind` is one the list never gives a row (B8, B9, B13, B15). */
export function isRowless(kind: string): boolean {
  // Widened for the lookup only: any served string may be asked, and the tuple stays exact.
  return (ROWLESS_KINDS as readonly string[]).includes(kind);
}
