/**
 * The order-flow sentences (E47-S02, #1358): a footprint cell, a DOM-ladder row and a heatmap cell, each one
 * utterance, built from `format.ts` so a price, a size and a signed delta read exactly as the bar sentence and the
 * SCR-045 table read them. Numbers arrive as decimal strings (never floats). Words come from `orderflowCopy.ts`.
 */
import { MINUS, displayDecimal, signedDecimal } from "./format";
import { CELL, HEATMAP, LADDER, UNAVAILABLE, type BookSide, type OrderSide } from "./orderflowCopy";

export type Direction = "up" | "down" | "flat";

/** The glyph that carries a sign beside the `+`/`−` (05 §4.3); a zero has no direction and reads "+0". */
export const DIRECTION_GLYPH: Readonly<Record<Direction, string>> = {
  up: "▲",
  down: "▼",
  flat: "",
};

/** The direction of a signed decimal: "−0" and "0.00" are flat. */
export function directionOf(value: string): Direction {
  const shown = displayDecimal(value);
  if (shown.startsWith(MINUS)) return "down";
  return /^[0.,]+$/.test(shown) ? "flat" : "up";
}

/** A size is a non-negative decimal: a negative size is a data fault, never shown. */
export function sizeText(value: string): string {
  const shown = displayDecimal(value);
  if (shown.startsWith(MINUS)) throw new RangeError(`negative size: "${value}"`);
  return shown;
}

/**
 * `format(value)`, or `fallback` when the value is a data fault (malformed, a negative size): one bad book field
 * degrades its own text instead of unmounting the surface (as SCR-045 shows "not available").
 */
export function orUnavailable(
  format: (value: string) => string,
  value: string,
  fallback: string = UNAVAILABLE.said,
): string {
  try {
    return format(value);
  } catch {
    return fallback;
  }
}

export interface FootprintCellFields {
  readonly price: string;
  readonly bid: string;
  readonly ask: string;
  /** Ask − bid, signed. */
  readonly delta: string;
  readonly imbalance: BookSide | null;
  /** The order-estimated input source (CMP-109's "(estimated)"). */
  readonly estimated?: boolean;
}

/**
 * "64,010.5, bid 12, ask 20, delta +8, ask imbalance": price first, a flagged imbalance said as a word. Never throws:
 * a faulty field reads "not available" and the rest of the cell still reads.
 */
export function footprintCellSentence(cell: FootprintCellFields): string {
  const parts = [
    orUnavailable(displayDecimal, cell.price),
    CELL.bid(orUnavailable(sizeText, cell.bid)),
    CELL.ask(orUnavailable(sizeText, cell.ask)),
    CELL.delta(orUnavailable(signedDecimal, cell.delta)),
  ];
  if (cell.imbalance !== null) parts.push(CELL.imbalance[cell.imbalance]);
  if (cell.estimated === true) parts.push(CELL.estimated);
  return parts.join(", ");
}

export interface OwnOrder {
  readonly side: OrderSide;
  readonly qty: string;
}

export interface LadderRowFields {
  readonly price: string;
  readonly bid: string;
  readonly ask: string;
  /** The book side this price sits on; `spread` between the best bid and ask. */
  readonly side: BookSide | "spread";
  /** The caller's own working orders at this price (already RBAC-scoped by the server). */
  readonly own?: readonly OwnOrder[];
  readonly position?: { readonly side: "long" | "short"; readonly qty: string } | null;
}

/**
 * "64,010, bid 12, ask 0, bid side, your buy order 0.1 working". Price first (the row's identity), then the columns
 * left to right. Never throws: a faulty field reads "not available" and the rest of the row still reads.
 */
export function ladderRowSentence(row: LadderRowFields): string {
  const parts = [
    orUnavailable(displayDecimal, row.price),
    CELL.bid(orUnavailable(sizeText, row.bid)),
    CELL.ask(orUnavailable(sizeText, row.ask)),
    LADDER.side[row.side],
  ];
  const own = row.own ?? [];
  if (own.length === 1 && own[0] !== undefined)
    parts.push(LADDER.ownOrder(own[0].side, orUnavailable(sizeText, own[0].qty)));
  else if (own.length > 1) parts.push(LADDER.ownOrders(own.length));
  if (row.position !== undefined && row.position !== null)
    parts.push(LADDER.position(row.position.side, orUnavailable(sizeText, row.position.qty)));
  return parts.join(", ");
}

/** The visible own-order and position marks of a row (the name's words, drawn; a11y lens M-3). */
export function ladderRowMarks(row: LadderRowFields): {
  own: string | null;
  position: string | null;
} {
  const own = row.own ?? [];
  const size = (v: string): string => orUnavailable(sizeText, v, UNAVAILABLE.shown);
  const first = own[0];
  return {
    own:
      own.length === 1 && first !== undefined
        ? LADDER.ownShown(first.side, size(first.qty))
        : own.length > 1
          ? LADDER.ownsShown(own.length)
          : null,
    position:
      row.position === undefined || row.position === null
        ? null
        : LADDER.positionShown(row.position.side, size(row.position.qty)),
  };
}

export interface HeatmapCellFields {
  readonly price: string;
  readonly size: string;
  readonly side: BookSide;
}

/** The focused heatmap cell's readout: "64,010.0, resting 125.5, bid side" (05 §4.1); a faulty field reads "not available". */
export function heatmapCellSentence(cell: HeatmapCellFields): string {
  return [
    orUnavailable(displayDecimal, cell.price),
    HEATMAP.size(orUnavailable(sizeText, cell.size)),
    HEATMAP.side[cell.side],
  ].join(", ");
}
