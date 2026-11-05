/**
 * The kind counters (E42-S08 §5.1; E42-D05 §11 SI-1, SI-2): one CMP-049 table row per kind and
 * environment, as `listStatecharts` serves `kinds`: kind ("order (B1)"), environment, machines, by
 * state ("submitted 1 · filled 3"), chain trips, latched machines and dropped receipts. A dropped
 * receipts count the metrics source did not give (`null`, or the `metrics` slice not `ok`) reads
 * "— not received", never 0 (D02 D4; Q-24). Counters only: no row is focusable, and nothing here
 * is derived but the words (C-2.21). The table says nothing of its own (the page owns no live
 * region; the shell's announcer says the page's lines). It is no grid, so a cut would have no echo:
 * its headers, "by state" and "— not received" wrap in their cells instead (A-1137-d02, -d05).
 */
import { memo, type CSSProperties, type JSX } from "react";
import { ADMIN_COPY, Table, type TableColumn } from "@candleviewer/ui";
import { INSPECTOR_COPY } from "./copy";
import type { StatechartKindSummary } from "./inspectorReads";
import { kindLabel } from "./kinds";
import "./inspector.css";

const COPY = INSPECTOR_COPY.list;
const SILENT = (): void => undefined;
/** A cell's words wrap, never cut: a served state name can be long (the timeline's `WRAP`). */
const WRAP: CSSProperties = { whiteSpace: "normal", overflowWrap: "anywhere" };

/** "— not received": the dash is drawn, the words are read. */
function NotReceived(): JSX.Element {
  return (
    <span style={WRAP}>
      <span aria-hidden="true">— </span>
      {COPY.notReceived}
    </span>
  );
}

/** "submitted 1 · filled 3": each served state with its count, in the served order. */
export const byStateWords = (byState: Readonly<Record<string, number>>): string =>
  Object.entries(byState)
    .map(([state, n]) => `${state} ${n}`)
    .join(" · ");

export interface KindCountersProps {
  readonly kinds: readonly StatechartKindSummary[];
  /** The `metrics` slice read `ok`: otherwise no dropped receipts count is shown. */
  readonly metricsOk: boolean;
  readonly loading: boolean;
}

/**
 * The counters' minimums sum to 50 em: a table at 1280 px, cards at 200 % (D05 §4.2). Kind is
 * 13 em wide, room for its longest label ("position_protection (B8)") uncut (A-1137-08).
 */
export const KindCounters = memo(function KindCounters({
  kinds,
  metricsOk,
  loading,
}: KindCountersProps): JSX.Element {
  const columns: readonly TableColumn<StatechartKindSummary>[] = [
    {
      id: "kind",
      header: COPY.columns.kind,
      cell: (k) => kindLabel(k.machine_kind),
      widthEm: 13,
      minWidthEm: 13,
    },
    {
      id: "environment",
      header: COPY.columns.environment,
      cell: (k) => ADMIN_COPY.env[k.environment],
      minWidthEm: 5,
    },
    {
      id: "machines",
      header: COPY.columns.machines,
      cell: (k) => String(k.machines),
      align: "end",
      minWidthEm: 5,
    },
    {
      id: "by_state",
      header: COPY.columns.byState,
      cell: (k) => <span style={WRAP}>{byStateWords(k.by_state)}</span>,
      minWidthEm: 10,
    },
    {
      id: "chain_trips",
      header: COPY.columns.chainTrips,
      cell: (k) => String(k.chain_trips),
      align: "end",
      minWidthEm: 5,
    },
    {
      id: "latched",
      header: COPY.columns.latched,
      cell: (k) => String(k.degraded_machines),
      align: "end",
      minWidthEm: 5,
    },
    {
      id: "dropped_receipts",
      header: COPY.columns.droppedReceipts,
      cell: (k) =>
        k.dropped_receipts === null || !metricsOk ? <NotReceived /> : String(k.dropped_receipts),
      align: "end",
      minWidthEm: 7,
    },
  ];
  return (
    <div className="cv-inspector-counters">
      <Table
        caption={COPY.kindsHeading}
        captionHidden
        columns={columns}
        rows={kinds}
        rowKey={(k) => `${k.machine_kind}@${k.environment}`}
        loading={loading}
        announce={SILENT}
      />
    </div>
  );
});
