/**
 * E42-S08 (#1137): the inspector's test bodies. `22`'s examples are verbatim but for their machine
 * hashes (each cites its lines in `docs/plan/22-api-openapi.yaml` at `67fe8b526`); the latched order
 * is the SC-CHAIN-TRIPS world of `services/api/tests/fixtures/admin/latched_machine.py` (E42-Q01):
 * one demo order machine, triggered with its stop-loss present, two chain trips and two deferred
 * events. The hashes are the committed `machine_hashes.lock` entries, read at run time, and the
 * order's chart is the frozen B01 (`frozenCharts.ts`), so a chart bump moves no test here.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { frozenChart, type FrozenChart } from "./frozenCharts";

const MACHINES = resolve(
  import.meta.dirname,
  "../../../../../../services/api/candleviewer/statechart/machines",
);

type Json = Readonly<Record<string, unknown>>;
const isRecord = (raw: unknown): raw is Json =>
  typeof raw === "object" && raw !== null && !Array.isArray(raw);

/** `kind`'s hash in the committed `machine_hashes.lock`, as it is when the tests run. */
export function lockHash(kind: string): string {
  const lock: unknown = JSON.parse(readFileSync(resolve(MACHINES, "machine_hashes.lock"), "utf8"));
  const machines = isRecord(lock) ? lock["machines"] : undefined;
  const entry = isRecord(machines) ? machines[kind] : undefined;
  const hash = isRecord(entry) ? entry["hash"] : undefined;
  if (typeof hash !== "string" || !/^[0-9a-f]{64}$/.test(hash)) {
    throw new Error(`machine_hashes.lock: no hash for ${kind}`);
  }
  return hash;
}

export const KILL_SWITCH_HASH = lockHash("kill_switch");
export const ORDER_HASH = lockHash("order");
/** The grid's hash cell: its first 8 hex and "matches the lock". */
export const shortHash = (hash: string): string => `${hash.slice(0, 8)} · matches the lock`;

/** `listStatecharts`' `degradedOrder` example (Y:15534-15587). */
export const DEGRADED_ORDER_LIST = {
  items: [
    {
      machine_key: "kill_switch",
      machine_kind: "kill_switch",
      environment: "demo",
      state: "clear",
      machine_hash: KILL_SWITCH_HASH,
      lock_matches: true,
      chain_trips: 0,
      degraded: false,
      deferred_depth: 0,
      updated_at: "2026-10-15T18:00:00Z",
    },
    {
      machine_key: "order:0a000000-0000-4000-8000-000000000001",
      machine_kind: "order",
      environment: "demo",
      state: "submitted",
      machine_hash: ORDER_HASH,
      lock_matches: true,
      chain_trips: 1,
      degraded: true,
      deferred_depth: 2,
      updated_at: "2026-10-15T18:00:02Z",
    },
  ],
  kinds: [
    {
      machine_kind: "kill_switch",
      environment: "demo",
      machines: 1,
      by_state: { clear: 1 },
      chain_trips: 0,
      degraded_machines: 0,
      dropped_receipts: null,
    },
    {
      machine_kind: "order",
      environment: "demo",
      machines: 1,
      by_state: { submitted: 1 },
      chain_trips: 1,
      degraded_machines: 1,
      dropped_receipts: null,
    },
    {
      machine_kind: "position_protection",
      environment: "demo",
      machines: 2,
      by_state: { protected: 2 },
      chain_trips: 0,
      degraded_machines: 0,
      dropped_receipts: null,
    },
  ],
  meta: { next_cursor: null, has_more: false, count: 2 },
  snapshots: { status: "ok", generated_at: "2026-10-15T18:00:05Z" },
  metrics: {
    status: "error",
    detail: "metrics timed out after 300 ms",
    generated_at: "2026-10-15T18:00:05Z",
  },
};

/** `getStatechart`'s `killSwitch` example (Y:15625-15650), its `config` trimmed as there. */
export const KILL_SWITCH_DETAIL = {
  snapshots: { status: "ok", generated_at: "2026-10-15T18:00:05Z" },
  events: { status: "ok", generated_at: "2026-10-15T18:00:05Z" },
  machine: DEGRADED_ORDER_LIST.items[0],
  context_summary: { scope: "global", cancel_working: true, flatten: false },
  configuration: ["kill_switch", "kill_switch.clear"],
  config: { id: "kill_switch", initial: "clear" },
  recent_events: [
    {
      event_type: "RELEASE",
      phase: "commit",
      from_states: ["kill_switch.engaged"],
      to_states: ["kill_switch.clear"],
      faulted: false,
      occurred_at: "2026-10-15T17:59:00Z",
    },
  ],
};

/** `exportStatechart`'s `killSwitch` example (Y:15684-15690): its states trimmed as there. */
export const KILL_SWITCH_EXPORT = {
  machine_kind: "kill_switch",
  machine_hash: KILL_SWITCH_HASH,
  stately: { id: "kill_switch", initial: "clear", states: { clear: {} } },
};

/** SC-CHAIN-TRIPS (`latched_machine.py`): the latched order's key and its row. */
export const LATCHED_KEY = "order:0a000000-0000-4000-8000-0000000000c7";
export const LATCHED_ROW = {
  machine_key: LATCHED_KEY,
  machine_kind: "order",
  environment: "demo",
  state: "triggered",
  machine_hash: ORDER_HASH,
  lock_matches: true,
  chain_trips: 2,
  degraded: true,
  deferred_depth: 2,
  updated_at: "2026-10-15T18:00:02Z",
};

/** Its detail: the snapshot's configuration and three events, newest first. */
export const LATCHED_DETAIL = {
  snapshots: { status: "ok", generated_at: "2026-10-15T18:00:05Z" },
  events: { status: "ok", generated_at: "2026-10-15T18:00:05Z" },
  machine: LATCHED_ROW,
  configuration: [
    "order",
    "order.lifecycle",
    "order.lifecycle.triggered",
    "order.protection",
    "order.protection.sl_present",
  ],
  recent_events: [
    {
      event_type: "PRICE_TRIGGERED",
      phase: "commit",
      from_states: ["order.lifecycle.submitted", "order.protection.sl_present"],
      to_states: ["order.lifecycle.triggered", "order.protection.sl_present"],
      faulted: false,
      occurred_at: "2026-10-15T18:00:01Z",
    },
    {
      event_type: "FILL",
      phase: "fault",
      from_states: ["order.lifecycle.submitted"],
      to_states: ["order.lifecycle.submitted"],
      faulted: true,
      occurred_at: "2026-10-15T17:59:58Z",
    },
    {
      event_type: "SUBMITTED",
      phase: "ahead",
      from_states: ["order.lifecycle.submitting"],
      to_states: [],
      occurred_at: "2026-10-14T23:59:57Z",
    },
  ],
};

/** The page's world (plan §8; E42-D05:201-202 with `latched_machine.py`, SC-CHAIN-TRIPS): the
 * demo kill switch, clear; the latched order, triggered with two chain trips and two deferred
 * events; and one latched B8 `position_protection`, which has no public id, so no row. The metrics
 * source timed out (`22`'s `degradedOrder`), so no dropped receipts count is known. */
export const WORLD_LIST = {
  items: [DEGRADED_ORDER_LIST.items[0], LATCHED_ROW],
  kinds: [
    DEGRADED_ORDER_LIST.kinds[0],
    {
      machine_kind: "order",
      environment: "demo",
      machines: 1,
      by_state: { triggered: 1 },
      chain_trips: 2,
      degraded_machines: 1,
      dropped_receipts: null,
    },
    {
      machine_kind: "position_protection",
      environment: "demo",
      machines: 1,
      by_state: { naked: 1 },
      chain_trips: 1,
      degraded_machines: 1,
      dropped_receipts: null,
    },
  ],
  meta: { next_cursor: null, has_more: false, count: 2 },
  snapshots: DEGRADED_ORDER_LIST.snapshots,
  metrics: DEGRADED_ORDER_LIST.metrics,
};

/** "Latched only" in that world: the order alone; `kinds` is the same on every filter (`22`). */
export const WORLD_LATCHED_LIST = {
  ...WORLD_LIST,
  items: [LATCHED_ROW],
  meta: { next_cursor: null, has_more: false, count: 1 },
};

const POLICY = new Set([
  "strictConfig",
  "strict",
  "strictTargets",
  "actionErrorPolicy",
  "guardErrorPolicy",
  "spawnBlockingTimeout",
]);

/** `registry.export_stately`: the chart without the six CV policy keys, at every depth. */
export function exported(node: unknown): unknown {
  if (Array.isArray(node)) return node.map(exported);
  if (typeof node !== "object" || node === null) return node;
  return Object.fromEntries(
    Object.entries(node)
      .filter(([name]) => !POLICY.has(name))
      .map(([name, value]) => [name, exported(value)]),
  );
}

/** A committed chart's `exportStatechart` answer, with `hash` (the lock's, unless a test races). */
export function exportOf(file: string, kind: string, hash: string): unknown {
  const chart: unknown = JSON.parse(readFileSync(resolve(MACHINES, file), "utf8"));
  return { machine_kind: kind, machine_hash: hash, stately: exported(chart) };
}

/** A frozen chart's `exportStatechart` answer (`frozenCharts.ts`), with `hash`. */
export function frozenExport(name: FrozenChart, kind: string, hash: string): unknown {
  return { machine_kind: kind, machine_hash: hash, stately: frozenChart(name) };
}

/** The frozen B01's export with the lock's hash: the latched order's chart. */
export const ORDER_EXPORT = frozenExport("B01.order", "order", ORDER_HASH);
