/**
 * The order-flow marks (E47-S02, #1358 BQ-08; `05` §4): colour is a reinforcing channel only. A delta carries its
 * `+`/`−` sign and a ▲/▼ glyph, an imbalance a dashed border, a corner glyph and its word, a book side its word and
 * its column, a trade side ▲ Buy / ▼ Sell. Colours come from the shipped palette (E47-S06) through `orderflowMarks.css`
 * tokens; the shapes are PROPOSED pending E18-D04 #498 and E47-D06 #1305.
 */
import type { JSX } from "react";
import { signedDecimal } from "./format";
import {
  DIRECTION_GLYPH,
  directionOf,
  sizeText,
  type FootprintCellFields,
} from "./orderflowFormat";
import { LEGEND, MARK, type BookSide, type OrderSide } from "./orderflowCopy";
import "./orderflowMarks.css";

/** A signed value (delta, CVD, imbalance-tracker change): the sign and the glyph survive grayscale. */
export function SignedValue({ value }: { readonly value: string }): JSX.Element {
  const direction = directionOf(value);
  return (
    <span className={`cv-of-signed cv-of-signed--${direction}`} data-cv-direction={direction}>
      {direction === "flat" ? null : (
        <span className="cv-of-signed__glyph" aria-hidden="true">
          {DIRECTION_GLYPH[direction]}
        </span>
      )}
      {signedDecimal(value)}
    </span>
  );
}

/** An imbalance flag: border + pattern + the word (05 §4.3). */
export function ImbalanceMark({ side }: { readonly side: BookSide }): JSX.Element {
  return (
    <span className={`cv-of-imbalance cv-of-imbalance--${side}`} data-cv-pattern="dashed">
      <span className="cv-of-imbalance__glyph" aria-hidden="true">
        ◢
      </span>
      {MARK.imbalance[side]}
    </span>
  );
}

const TRADE_GLYPH: Readonly<Record<OrderSide, string>> = { buy: "▲", sell: "▼" };
const TRADE_WORD: Readonly<Record<OrderSide, string>> = { buy: "Buy", sell: "Sell" };

/** A side as its word: a book side (bid / ask), or a trade side with its ▲ / ▼ glyph (05 §4.1). */
export function SideMark({ side }: { readonly side: BookSide | OrderSide }): JSX.Element {
  if (side === "bid" || side === "ask")
    return <span className={`cv-of-side cv-of-side--${side}`}>{MARK.side[side]}</span>;
  return (
    <span className={`cv-of-side cv-of-side--${side}`}>
      <span aria-hidden="true">{TRADE_GLYPH[side]} </span>
      {TRADE_WORD[side]}
    </span>
  );
}

/** The footprint cell's visible content: bid × ask, the signed delta, and the imbalance mark when flagged. */
export function FootprintCellContent({
  cell,
}: {
  readonly cell: FootprintCellFields;
}): JSX.Element {
  const flagged = cell.imbalance !== null;
  return (
    <span
      className={`cv-of-cell${flagged ? " cv-of-cell--imbalance" : ""}`}
      data-cv-pattern={flagged ? "dashed" : undefined}
    >
      <span className="cv-of-cell__volumes">{`${sizeText(cell.bid)} × ${sizeText(cell.ask)}`}</span>
      <SignedValue value={cell.delta} />
      {cell.imbalance === null ? null : <ImbalanceMark side={cell.imbalance} />}
    </span>
  );
}

/** The persistent text legend: side by word and column, never hue alone (CMP-113's convention line). */
export function SideLegend(): JSX.Element {
  return (
    <ul className="cv-of-legend" aria-label={LEGEND.name}>
      <li>
        <span className="cv-of-legend__swatch cv-of-legend__swatch--bid" aria-hidden="true" />
        {LEGEND.bid}
      </li>
      <li>
        <span className="cv-of-legend__swatch cv-of-legend__swatch--ask" aria-hidden="true" />
        {LEGEND.ask}
      </li>
    </ul>
  );
}
