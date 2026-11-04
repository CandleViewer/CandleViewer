// E24-S03 (#778) slice 1: the funding history's table alternative (D02 §11; `05` §6.3) over CMP-049: one row
// per settlement in view with its time, rate (sign as text) and interval, and the missing settlements as rows
// in words, so no state is only a shape on the plot, and a tri-state sort on time and rate (`aria-sort`).
// E24-S04 adds the Annualised column (the server's value) and the predicted row, worded "predicted (estimated)"
// in Status, last and never among the settled ones, whatever the sort.
import { useState, type JSX } from "react";
import {
  EmptyState,
  EstimatedBadge,
  Table,
  type HeadingLevel,
  type TableColumn,
  type TableSort,
} from "@candleviewer/ui";
import type { FundingSeriesModel } from "../series";
import * as copy from "./copy";
import { annualisedPercent, ratePercent, settlementTime } from "./format";
import { FundingMethodologyHost } from "./FundingMethodologyHost";

/** CMP-049 draws at most 200 rows without a host window (#266); the newest are kept (PROPOSED). */
export const MAX_TABLE_ROWS = 200;

type Line =
  | {
      readonly kind: "settled";
      readonly tMs: number;
      readonly rate: string;
      readonly annualisedPct: string | null;
    }
  | {
      readonly kind: "predicted";
      readonly tMs: number | null;
      readonly rate: string;
      readonly annualisedPct: string | null;
    }
  | { readonly kind: "gap"; readonly fromMs: number; readonly toMs: number };

/** Drawn text with its spoken twin ("—" read as a word, "−0.0040 %" as "minus 0.0040 percent"). */
const said = (text: string, words: string): JSX.Element => (
  <>
    <span aria-hidden="true">{text}</span>
    <span className="cv-visually-hidden">{words}</span>
  </>
);
const none = (word: string): JSX.Element => said("—", word);
/** "predicted" and the CMP-227 chip's "(estimated)": the words are the status, the chip opens CMP-069. */
const predictedStatus = (): JSX.Element => (
  <>
    {`${copy.PREDICTED_WORD} `}
    <EstimatedBadge
      detector="funding"
      variant="inline"
      size="sm"
      name="Funding rate"
      tooltip={copy.PREDICTED_PROVENANCE}
    />
  </>
);
const startOf = (l: Line): number =>
  l.kind === "gap" ? l.fromMs : l.tMs === null ? Number.POSITIVE_INFINITY : l.tMs;

/** Orders two `22` Decimals exactly, never through a float. */
export function compareDecimal(a: string, b: string): number {
  const parts = (v: string) => {
    const negative = v.startsWith("-");
    const [int = "0", frac = ""] = (negative ? v.slice(1) : v).split(".");
    return { negative, int, frac };
  };
  const [pa, pb] = [parts(a), parts(b)];
  const width = Math.max(pa.frac.length, pb.frac.length);
  const big = (p: ReturnType<typeof parts>): bigint =>
    (p.negative ? -1n : 1n) * BigInt(`${p.int}${p.frac.padEnd(width, "0")}`);
  const d = big(pa) - big(pb);
  return d < 0n ? -1 : d > 0n ? 1 : 0;
}

/** D02 §11's sort: by time, or by rate with the gap rows last either way. */
function sorted(lines: readonly Line[], sort: TableSort | undefined): readonly Line[] {
  if (sort === undefined) return lines;
  const sign = sort.direction === "descending" ? -1 : 1;
  const byRate = (a: Line, b: Line): number =>
    a.kind === "gap" || b.kind === "gap"
      ? Number(a.kind === "gap") - Number(b.kind === "gap")
      : sign * compareDecimal(a.rate, b.rate);
  return [...lines].sort((a, b) =>
    sort.columnId === "rate" ? byRate(a, b) : sign * (startOf(a) - startOf(b)),
  );
}

export interface FundingTableProps {
  readonly symbol: string;
  readonly series: FundingSeriesModel;
  /** The chart's visible range; the whole series when absent. */
  readonly visible?: { readonly fromMs: number; readonly toMs: number } | undefined;
  readonly density?: "comfortable" | "compact" | undefined;
  /** The empty state's heading level, one below the pane's label. */
  readonly headingLevel?: HeadingLevel | undefined;
}

export function FundingTable({
  symbol,
  series,
  visible,
  density = "compact",
  headingLevel = 4,
}: FundingTableProps): JSX.Element {
  const [sort, setSort] = useState<TableSort | undefined>(undefined);
  // tri-state (D02 §11): CMP-049 asks ascending, then descending; the press after descending clears it
  const onSortChange = (next: TableSort): void =>
    setSort((prev) =>
      prev?.columnId === next.columnId && prev.direction === "descending" ? undefined : next,
    );
  const inView = (from: number, to: number): boolean =>
    visible === undefined || (to >= visible.fromMs && from <= visible.toMs);
  const lines: Line[] = [
    ...series.settled
      .filter((p) => inView(p.tMs, p.tMs))
      .map(
        (p) =>
          ({
            kind: "settled",
            tMs: p.tMs,
            rate: p.rate,
            annualisedPct: p.annualisedPct ?? null,
          }) as const,
      ),
    ...series.gaps
      .filter((g) => inView(g.fromMs, g.toMs))
      .map((g) => ({ kind: "gap", fromMs: g.fromMs, toMs: g.toMs }) as const),
  ].sort((a, b) => startOf(a) - startOf(b));
  const { predicted } = series;
  // the accruing rate is last, whatever its time or the sort says, and always in view: the next row, never history
  if (predicted !== null) lines.push({ kind: "predicted", ...predicted });
  const kept = lines.slice(-MAX_TABLE_ROWS);
  const next = kept.at(-1)?.kind === "predicted" ? kept.slice(-1) : [];
  const shown = [...sorted(kept.slice(0, kept.length - next.length), sort), ...next];
  const hours = series.intervalMs === null ? null : String(series.intervalMs / 3_600_000);

  const columns: TableColumn<Line>[] = [
    {
      id: "settlement",
      header: copy.COL_SETTLEMENT,
      sortable: true,
      minWidthEm: 11,
      cell: (l) =>
        l.kind === "gap"
          ? `${settlementTime(l.fromMs)} – ${settlementTime(l.toMs)}`
          : l.tMs === null
            ? copy.NEXT_SETTLEMENT
            : settlementTime(l.tMs),
    },
    {
      id: "rate",
      header: copy.COL_RATE,
      sortable: true,
      align: "end",
      minWidthEm: 9,
      cell: (l) =>
        l.kind === "gap"
          ? none(copy.NO_RATE)
          : said(ratePercent(l.rate).text, ratePercent(l.rate).spoken),
    },
    {
      id: "annualised",
      header: copy.COL_ANNUALISED,
      align: "end",
      minWidthEm: 9,
      cell: (l) => {
        if (l.kind === "gap") return none(copy.NO_RATE);
        if (l.annualisedPct === null) return none(copy.NOT_PUBLISHED);
        const a = annualisedPercent(l.annualisedPct);
        return said(a.text.replace(" p.a.", ""), a.spoken);
      },
    },
    {
      id: "status",
      header: copy.COL_STATUS,
      minWidthEm: 10,
      cell: (l) =>
        l.kind === "gap"
          ? copy.GAP_WORDS
          : l.kind === "predicted"
            ? predictedStatus()
            : copy.STATUS_SETTLED,
    },
    {
      id: "interval",
      header: copy.COL_INTERVAL,
      align: "end",
      minWidthEm: 5,
      cell: () => hours ?? none(copy.NOT_PUBLISHED),
    },
  ];

  const base = copy.tableCaption(symbol, predicted !== null);
  const caption =
    lines.length > MAX_TABLE_ROWS
      ? `${base}, ${copy.showingNewest(MAX_TABLE_ROWS, lines.length)}`
      : base;
  return (
    <FundingMethodologyHost>
      <Table
        columns={columns}
        rows={shown}
        rowKey={(l) => (l.kind === "gap" ? `gap${String(l.fromMs)}` : `${l.kind}${String(l.tMs)}`)}
        caption={caption}
        sort={sort}
        onSortChange={onSortChange}
        density={density}
        emptyState={<EmptyState title={copy.NO_ROWS} headingLevel={headingLevel} />}
      />
    </FundingMethodologyHost>
  );
}
