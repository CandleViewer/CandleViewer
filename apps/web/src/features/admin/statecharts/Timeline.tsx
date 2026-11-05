/**
 * The machine's event timeline (E42-S08 §5.2; E42-D05 §11 SI-5): `recent_events` as served, newest
 * first and at most 50, in a CMP-049 table (time · event · phase · from → to · faulted), drawn
 * whole and never windowed or live: the table says nothing of its own (the page owns no live
 * region). A phase reads "ahead", "commit" or "fault", and a faulted row says "faulted" in words.
 * Each side's states are the served ids, without the chart root's segment. The narrow columns have
 * widths, and "From → to" wraps in the rest rather than being cut (a parallel chart's two regions
 * are long); below the minimums' sum, 56 em, the table stacks.
 */
import { memo, type CSSProperties, type JSX } from "react";
import { Table, type TableColumn } from "@candleviewer/ui";
import { INSPECTOR_COPY as COPY } from "./copy";
import { stateIds, utcTime } from "./format";
import type { RecentEvent } from "./inspectorReads";

interface Row {
  readonly event: RecentEvent;
  readonly index: number;
}

const SILENT = (): void => undefined;
/** "From → to" wraps in its cell, never cut: both sides are always whole (A-1137-08). */
const WRAP: CSSProperties = { whiteSpace: "normal", overflowWrap: "anywhere" };

/** "—", named "none" for assistive technology. */
function None(): JSX.Element {
  return (
    <>
      <span aria-hidden="true">—</span>
      <span className="cv-visually-hidden">{COPY.timeline.none}</span>
    </>
  );
}

/** "submitted → triggered", read as "submitted to triggered". */
function FromTo({ from, to }: { readonly from: string; readonly to: string }): JSX.Element {
  return (
    <span style={WRAP}>
      {from === "" ? <None /> : from} <span aria-hidden="true">→</span>
      <span className="cv-visually-hidden">{COPY.chart.to}</span> {to === "" ? <None /> : to}
    </span>
  );
}

export interface TimelineProps {
  /** The served rows, newest first. */
  readonly events: readonly RecentEvent[];
  /** The chart root's id (the machine's kind), left off each state id it leads. */
  readonly root: string;
  /** When the detail answered: an event of another UTC day shows its date. */
  readonly today: number;
}

export const Timeline = memo(function Timeline({
  events,
  root,
  today,
}: TimelineProps): JSX.Element {
  const columns: readonly TableColumn<Row>[] = [
    {
      id: "time",
      header: COPY.timeline.time,
      cell: ({ event }) => utcTime(Date.parse(event.occurred_at), today),
      widthEm: 17,
      minWidthEm: 17,
    },
    {
      id: "event",
      header: COPY.timeline.event,
      cell: ({ event }) => event.event_type,
      widthEm: 15,
      minWidthEm: 15,
    },
    {
      id: "phase",
      header: COPY.timeline.phase,
      cell: ({ event }) => COPY.timeline.phases[event.phase],
      widthEm: 6,
      minWidthEm: 6,
    },
    {
      id: "from_to",
      header: COPY.timeline.fromTo,
      cell: ({ event }) => (
        <FromTo
          from={stateIds(event.from_states ?? [], root)}
          to={stateIds(event.to_states ?? [], root)}
        />
      ),
      minWidthEm: 12,
    },
    {
      id: "faulted",
      header: COPY.timeline.faulted,
      cell: ({ event }) => (event.faulted === true ? COPY.timeline.faultedWord : ""),
      widthEm: 6,
      minWidthEm: 6,
    },
  ];
  return (
    <Table
      caption={COPY.timeline.caption}
      columns={columns}
      rows={events.map((event, index) => ({ event, index }))}
      rowKey={(row) => String(row.index)}
      announce={SILENT}
    />
  );
});
