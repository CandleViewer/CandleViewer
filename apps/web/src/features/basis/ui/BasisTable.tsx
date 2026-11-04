// E24-S08 (#783) slice 2: the table alternative (D03 S54-68): the latest mark, index, basis and basis %
// with their units and the source, and the row `L/S ratio · source unavailable` (S54-9). One real
// `<table>`, headers scoped; the sign of the basis is text.
import type { JSX } from "react";
import { basisOf } from "../basis";
import type { BasisTick } from "../ticker";
import type { BasisSource } from "../settings";
import * as copy from "./copy";
import { groupedDecimal, signedDecimal, tableTime } from "./format";

export interface BasisTableProps {
  readonly symbol: string;
  readonly latest: BasisTick | null;
  readonly source: BasisSource;
}

const num = (v: string | null): string => (v === null ? "—" : groupedDecimal(v));

export function BasisTable({ symbol, latest, source }: BasisTableProps): JSX.Element {
  const reading = latest === null ? null : basisOf(latest, source);
  return (
    <table className="cv-basis__table">
      <caption>{copy.tableCaption(symbol)}</caption>
      <thead>
        <tr>
          <th scope="col">{copy.COL_TIME}</th>
          <th scope="col">{copy.COL_MARK}</th>
          <th scope="col">{copy.COL_INDEX}</th>
          <th scope="col">{copy.COL_BASIS}</th>
          <th scope="col">{copy.COL_PCT}</th>
          <th scope="col">{copy.COL_SOURCE}</th>
        </tr>
      </thead>
      <tbody>
        {latest === null ? (
          <tr>
            <td colSpan={6}>{copy.NO_ROWS}</td>
          </tr>
        ) : (
          <tr>
            <td>{tableTime(latest.tsMs)}</td>
            <td>{num(latest.mark)}</td>
            <td>{num(latest.index)}</td>
            <td>{reading === null ? "—" : signedDecimal(reading.basis)}</td>
            <td>{reading === null ? "—" : `${signedDecimal(reading.pct)} %`}</td>
            <td>{source}</td>
          </tr>
        )}
        <tr className="cv-basis__ratio">
          <td colSpan={6}>{copy.RATIO_ROW}</td>
        </tr>
      </tbody>
    </table>
  );
}
