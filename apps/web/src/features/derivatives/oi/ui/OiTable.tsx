// E24-S01 (#776) slice 2: the OI table alternative (D02 §11, D03 S54-64; `05` §6.3) over CMP-049: one row
// per visible point with time, span, OI in base coin and in USDT (live points only, BQ 1) and the source
// in words (the provenance rule: `live` vs `REST history`), and the gaps as rows in words, so a gap is never
// only a missing line. E24-S02 (#777) adds the delta and quadrant columns
// when the served per-bar series is given: the quadrant in words (and glyph pair), never colour alone.
import { useEffect, useId, useRef, type JSX } from "react";
import { EmptyState, Table, type TableColumn } from "@candleviewer/ui";
import type { OiGap, OiRow } from "../series";
import { alignToBar } from "../intervals";
import type { OiBar, OiBarModel } from "../quadrant/bars";
import { QUADRANT_STYLE } from "../quadrant/quadrant";
import * as copy from "./copy";
import { groupedDecimal, signedDecimal, tableTime } from "./format";

/** CMP-049 draws at most 200 rows without a host window (#266); the newest are kept (PROPOSED). */
export const MAX_TABLE_ROWS = 200;

type Line =
  { readonly kind: "point"; readonly row: OiRow } | { readonly kind: "gap"; readonly gap: OiGap };

const MIN = 60_000;
const spanWords = (ms: number): string =>
  ms >= 86_400_000
    ? `${String(ms / 86_400_000)} d`
    : ms >= 3_600_000
      ? `${String(ms / 3_600_000)} h`
      : ms >= MIN
        ? `${String(ms / MIN)} min`
        : `${String(ms / 1000)} s`;

/** A dash drawn, a word read (as CMP-036 reads its "—"). */
const none = (word: string): JSX.Element => (
  <>
    <span aria-hidden="true">—</span>
    <span className="cv-visually-hidden">{word}</span>
  </>
);

const startOf = (l: Line): number => (l.kind === "point" ? l.row.tMs : l.gap.fromMs);

export interface OiTableProps {
  readonly symbol: string;
  readonly baseUnit: string;
  readonly rows: readonly OiRow[];
  readonly gaps: readonly OiGap[];
  /** The chart's visible range; the whole series when absent. */
  readonly visible?: { readonly fromMs: number; readonly toMs: number } | undefined;
  readonly density?: "comfortable" | "compact" | undefined;
  /** E24-S02: the served per-bar delta and quadrant; the columns are absent without it. */
  readonly bars?: OiBarModel | undefined;
}

export function OiTable({
  symbol,
  baseUnit,
  rows,
  gaps,
  visible,
  density = "compact",
  bars,
}: OiTableProps): JSX.Element {
  const capId = useId();
  const box = useRef<HTMLDivElement>(null);
  const inView = (from: number, to: number): boolean =>
    visible === undefined || (to >= visible.fromMs && from <= visible.toMs);
  const lines: Line[] = [
    ...rows
      .filter((r) => inView(r.tMs, r.tMs + r.spanMs))
      .map((row) => ({ kind: "point", row }) as const),
    ...gaps.filter((g) => inView(g.fromMs, g.toMs)).map((gap) => ({ kind: "gap", gap }) as const),
  ].sort((a, b) => startOf(a) - startOf(b));
  const shown = lines.slice(-MAX_TABLE_ROWS);

  const barAt = new Map<number, OiBar>((bars?.bars ?? []).map((b) => [b.tMs, b]));
  // a live or ticker row need not start on a bar open: align it to its bar. A row whose bar the metrics did
  // not serve reads "unclassified": the OI feed does hold its sample.
  const barOf = (l: Line): OiBar | null =>
    bars === undefined || l.kind !== "point"
      ? null
      : (barAt.get(alignToBar(l.row.tMs, bars.barMs)) ?? null);

  const columns: TableColumn<Line>[] = [
    {
      id: "time",
      header: copy.COL_TIME,
      minWidthEm: 11,
      cell: (l) =>
        l.kind === "point"
          ? tableTime(l.row.tMs)
          : `${tableTime(l.gap.fromMs)} – ${tableTime(l.gap.toMs)}`,
    },
    {
      id: "span",
      header: copy.COL_SPAN,
      minWidthEm: 5,
      cell: (l) =>
        l.kind === "gap"
          ? none("no span")
          : [
              spanWords(l.row.spanMs),
              l.row.clipped === true ? ` ${copy.CLIPPED}` : "",
              l.row.forming ? `, ${copy.FORMING}` : "",
            ].join(""),
    },
    {
      id: "base",
      header: copy.colBase(baseUnit),
      align: "end",
      minWidthEm: 9,
      cell: (l) => (l.kind === "point" ? groupedDecimal(l.row.base) : none("no value")),
    },
    {
      id: "value",
      header: copy.COL_VALUE,
      align: "end",
      minWidthEm: 10,
      cell: (l) =>
        l.kind === "point" && l.row.valueUsdt !== null
          ? groupedDecimal(l.row.valueUsdt)
          : none("no USDT value"),
    },
    ...(bars === undefined
      ? []
      : ([
          {
            id: "delta",
            header: copy.COL_DELTA(bars.deltaUnit),
            align: "end",
            minWidthEm: 9,
            cell: (l) => {
              const d = barOf(l)?.delta ?? null;
              return d === null ? none("no change for this bar") : signedDecimal(d);
            },
          },
          {
            id: "quadrant",
            header: copy.COL_QUADRANT,
            minWidthEm: 12,
            cell: (l) => {
              if (l.kind === "gap") return none("no quadrant");
              const q = barOf(l)?.quadrant ?? null;
              if (q !== null)
                return (
                  <>
                    <span aria-hidden="true">{QUADRANT_STYLE[q].glyphs} </span>
                    {QUADRANT_STYLE[q].words}
                  </>
                );
              return copy.UNCLASSIFIED;
            },
          },
        ] satisfies TableColumn<Line>[])),
    {
      id: "source",
      header: copy.COL_SOURCE,
      minWidthEm: 9,
      cell: (l) =>
        l.kind === "point" ? copy.SOURCE_WORDS[l.row.source] : copy.GAP_WORDS[l.gap.kind],
    },
  ];

  const capped = lines.length > shown.length;
  // CMP-049 takes no description id: the cap note is attached to the table's own element once it is drawn
  useEffect(() => {
    const table = box.current?.querySelector("table");
    if (table === null || table === undefined) return;
    if (capped) table.setAttribute("aria-describedby", capId);
    else table.removeAttribute("aria-describedby");
  });
  return (
    <>
      {capped ? (
        <p id={capId} className="cv-oi-pane__caption">
          {copy.showingNewest(shown.length, lines.length)}
        </p>
      ) : null}
      <div ref={box}>
        <Table
          columns={columns}
          rows={shown}
          rowKey={(l) =>
            l.kind === "point"
              ? `p:${l.row.source}:${String(l.row.tMs)}`
              : `g:${l.gap.kind}:${String(l.gap.fromMs)}:${String(l.gap.toMs)}`
          }
          caption={copy.tableCaption(symbol)}
          density={density}
          emptyState={<EmptyState title={copy.NO_ROWS} />}
        />
      </div>
    </>
  );
}
