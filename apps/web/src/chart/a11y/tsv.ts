/**
 * SCR-045's `Ctrl+C` (E11-D04 §8.3): TSV with a header of the visible column names, ISO-8601 UTC times, numbers at the
 * displayed precision with ASCII `-` and no grouping, an expanded bar's levels beneath it indented by one empty first
 * column, and at most `TSV_ROW_CAP` bar rows per copy. Only the series' own data: no account identifiers.
 */
import { BAR_HEADERS } from "./copy";
import { tsvDecimal, tsvTime } from "./format";
import { barFields, cvdAt, levelsOf, type ChartTableSeries } from "./series";

/** E11-D04 §8.3 (O-4): 10,000 rows per copy, about 1 MB. */
export const TSV_ROW_CAP = 10_000;

export interface Tsv {
  readonly text: string;
  /** Bar rows copied. */
  readonly rows: number;
  readonly columns: number;
  /** True when the selection was longer than the cap. */
  readonly capped: boolean;
}

const opt = (value: string | undefined): string => (value === undefined ? "" : tsvDecimal(value));

export function buildTsv(
  series: ChartTableSeries,
  bars: readonly number[],
  expanded: number | null,
  cvd: Float64Array | null,
): Tsv {
  const take = bars.slice(0, TSV_ROW_CAP);
  const lines = [BAR_HEADERS.join("\t")];
  for (const i of take) {
    const f = barFields(series, i);
    lines.push(
      [
        tsvTime(f.timeUs),
        tsvDecimal(f.open),
        tsvDecimal(f.high),
        tsvDecimal(f.low),
        tsvDecimal(f.close),
        tsvDecimal(f.volume),
        opt(f.delta),
        opt(cvdAt(series, cvd, i)),
      ].join("\t"),
    );
    if (i !== expanded) continue;
    for (const l of levelsOf(series, i)) {
      const flag = l.imbalance === "—" ? "" : l.imbalance;
      lines.push(
        [
          "",
          tsvDecimal(l.price),
          tsvDecimal(l.bid),
          tsvDecimal(l.ask),
          tsvDecimal(l.delta),
          flag,
        ].join("\t"),
      );
    }
  }
  return {
    text: `${lines.join("\n")}\n`,
    rows: take.length,
    columns: BAR_HEADERS.length,
    capped: bars.length > TSV_ROW_CAP,
  };
}
