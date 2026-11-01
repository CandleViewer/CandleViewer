/**
 * The order-flow sentences (E47-S02, #1358): a footprint cell, a DOM-ladder row and a heatmap cell, each one
 * utterance, built from `format.ts` so a price, a size and a signed delta read exactly as the bar sentence and the
 * SCR-045 table read them. Numbers arrive as decimal strings (never floats). Words come from `orderflowCopy.ts`.
 */
import { MINUS, displayDecimal, signedDecimal } from "./format";
import { CELL, HEATMAP, LADDER, type BookSide, type OrderSide } from "./orderflowCopy";

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

/** "64,010.5, bid 12, ask 20, delta +8, ask imbalance": price first, the imbalance always said as a word. */
export function footprintCellSentence(cell: FootprintCellFields): string {
  const parts = [
    displayDecimal(cell.price),
    CELL.bid(sizeText(cell.bid)),
    CELL.ask(sizeText(cell.ask)),
    CELL.delta(signedDecimal(cell.delta)),
    cell.imbalance === null ? CELL.imbalance.none : CELL.imbalance[cell.imbalance],
  ];
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

/** "64,010.0, bid 12, ask 0, bid side, your buy order 0.1 working". */
export function ladderRowSentence(row: LadderRowFields): string {
  const parts = [
    displayDecimal(row.price),
    CELL.bid(sizeText(row.bid)),
    CELL.ask(sizeText(row.ask)),
    LADDER.side[row.side],
  ];
  const own = row.own ?? [];
  if (own.length === 1 && own[0] !== undefined)
    parts.push(LADDER.ownOrder(own[0].side, sizeText(own[0].qty)));
  else if (own.length > 1) parts.push(LADDER.ownOrders(own.length));
  if (row.position !== undefined && row.position !== null)
    parts.push(LADDER.position(row.position.side, sizeText(row.position.qty)));
  return parts.join(", ");
}

export interface HeatmapCellFields {
  readonly price: string;
  readonly size: string;
  readonly side: BookSide;
}

/** The focused heatmap cell's readout: "64,010.0, resting 125.5, bid side" (05 §4.1). */
export function heatmapCellSentence(cell: HeatmapCellFields): string {
  return [
    displayDecimal(cell.price),
    HEATMAP.size(sizeText(cell.size)),
    HEATMAP.side[cell.side],
  ].join(", ");
}
