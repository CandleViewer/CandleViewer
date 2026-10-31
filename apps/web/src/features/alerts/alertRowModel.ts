/**
 * Row model for the alerts table (E40-S01; E40-D02 §2.3 status words, §2.4 tabs and groups, §2.8
 * filters). Pure: the clock is injected. Condition text is plain text, cut to a fixed length.
 */
import { hasFired, isSnoozed, type AlertTab } from "./alertStatus.js";
import type { Alert, DeliveryRow, VocabularySignal } from "./types.js";

export type StatusKey = "armed" | "fired" | "snoozed" | "disarmed" | "disabled" | "expired";
export type StatusFilter = "all" | "attention" | "armed" | "not_armed" | "snoozed";
export type RowGroup = "attention" | "armed" | "snoozed" | "not_armed";

/** The server's disarm and one-shot writes stamp `updated_at` with the firing's time (D-4). */
const STAMP_WINDOW_MS = 5_000;
export const CONDITION_MAX = 80;

export function statusOf(alert: Alert, nowMs: number): StatusKey {
  if (alert.enabled === false) {
    if (alert.disarm_reason != null) return "disarmed";
    const updated = Date.parse(alert.updated_at ?? "");
    const fired = Date.parse(alert.last_fired_at ?? "");
    if (
      alert.trigger_mode === "once" &&
      (alert.fire_count ?? 0) >= 1 &&
      Math.abs(updated - fired) <= STAMP_WINDOW_MS
    )
      return "fired";
    return "disabled";
  }
  const expires = Date.parse(alert.expires_at ?? "");
  if (Number.isFinite(expires) && expires <= nowMs) return "expired";
  return isSnoozed(alert, nowMs) ? "snoozed" : "armed";
}

export const STATUS_WORD: Readonly<Record<StatusKey, string>> = {
  armed: "Armed",
  fired: "Fired",
  snoozed: "Snoozed",
  disarmed: "Disarmed",
  disabled: "Disabled",
  expired: "Expired",
};

export function groupOf(key: StatusKey, failedDelivery: boolean): RowGroup {
  if (key === "disarmed" || (key === "armed" && failedDelivery)) return "attention";
  if (key === "armed") return "armed";
  if (key === "snoozed") return "snoozed";
  return "not_armed";
}

export function inTab(alert: Alert, tab: AlertTab, nowMs: number): boolean {
  if (tab === "fired") return hasFired(alert);
  if (tab === "snoozed") return isSnoozed(alert, nowMs);
  return true;
}

export function matchesStatus(group: RowGroup, filter: StatusFilter): boolean {
  return filter === "all" || filter === group;
}

const GROUP_ORDER: readonly RowGroup[] = ["attention", "armed", "snoozed", "not_armed"];

/** Needs attention first, then Armed, Snoozed, Not armed; the tab's own order inside a group. */
export function sortRows(
  rows: readonly Alert[],
  tab: AlertTab,
  groupFor: (alert: Alert) => RowGroup,
): readonly Alert[] {
  const time = (a: Alert, field: "last_fired_at" | "snoozed_until"): number => {
    const t = Date.parse(a[field] ?? "");
    return Number.isFinite(t) ? t : 0;
  };
  return [...rows].sort((a, b) => {
    if (tab === "fired") return time(b, "last_fired_at") - time(a, "last_fired_at");
    if (tab === "snoozed") return time(a, "snoozed_until") - time(b, "snoozed_until");
    return GROUP_ORDER.indexOf(groupFor(a)) - GROUP_ORDER.indexOf(groupFor(b));
  });
}

interface IrNode {
  readonly op?: string;
  readonly left?: { readonly metric?: string; readonly const?: unknown };
  readonly right?: { readonly metric?: string; readonly const?: unknown };
  readonly children?: readonly IrNode[];
}

const OP_WORDS: Readonly<Record<string, string>> = {
  gt: "is above",
  gte: "is at or above",
  lt: "is below",
  lte: "is at or below",
  eq: "equals",
  crosses_above: "crosses above",
  crosses_below: "crosses below",
};

export const TRIGGER_WORDS: Readonly<Record<string, string>> = {
  once: "once",
  every_time: "every time",
  once_per_bar: "once per bar",
};

/** The metric ids a condition reads, in order (a tree walk; never throws on odd shapes). */
export function metricsOf(node: unknown, out: string[] = []): string[] {
  if (typeof node !== "object" || node === null) return out;
  const n = node as IrNode & Record<string, unknown>;
  for (const side of [n.left, n.right]) {
    if (side?.metric !== undefined) out.push(side.metric);
  }
  for (const value of Object.values(n)) {
    if (Array.isArray(value)) for (const child of value) metricsOf(child, out);
  }
  return out;
}

export interface ConditionView {
  readonly text: string;
  readonly estimated: boolean;
}

export function describeCondition(
  alert: Alert,
  signals: ReadonlyMap<string, VocabularySignal> | null,
): ConditionView {
  const root = (alert.condition_ir as { conditions?: IrNode } | undefined)?.conditions;
  const name = (id: string): string => signals?.get(id)?.display_name ?? id;
  const operand = (side: IrNode["left"]): string =>
    side?.metric !== undefined ? name(side.metric) : String(side?.const ?? "?");
  const sentence =
    root?.children !== undefined
      ? `${root.children.length} conditions`
      : `${operand(root?.left)} ${OP_WORDS[root?.op ?? ""] ?? root?.op ?? "?"} ${operand(root?.right)}`;
  const text =
    sentence.length > CONDITION_MAX ? `${sentence.slice(0, CONDITION_MAX - 1)}…` : sentence;
  const estimated = metricsOf(root).some((id) => signals?.get(id)?.estimated === true);
  return { text, estimated };
}

/** Alert ids whose newest failed desktop delivery is within the stamp window of their last firing. */
export function failedDesktopAlerts(
  rows: readonly DeliveryRow[],
  alerts: readonly Alert[],
): ReadonlySet<string> {
  const lastFired = new Map(alerts.map((a) => [a.id, Date.parse(a.last_fired_at ?? "")]));
  const ids = new Set<string>();
  for (const row of rows) {
    if (row.channel !== "desktop" || row.status !== "failed" || row.alert_id === undefined)
      continue;
    const fired = lastFired.get(row.alert_id);
    if (fired !== undefined && Math.abs(Date.parse(row.fired_at ?? "") - fired) <= STAMP_WINDOW_MS)
      ids.add(row.alert_id);
  }
  return ids;
}
