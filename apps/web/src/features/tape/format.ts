// E22-S01 (#714) PR-B: the tape's text. Time with millisecond precision in the browser's zone
// (G-61: `22` has no time-zone setting yet), prices and sizes as the feed's decimal strings with
// grouping only (never re-rounded), the notional as a display product (no threshold maths, BQ-210),
// counts grouped by a space as the deck writes them ("2 010", "10 000").
import { SIDE_BUY, type TapeSide } from "./model/ring";

const pad2 = (n: number): string => (n < 10 ? `0${n}` : `${n}`);
const pad3 = (n: number): string => (n < 10 ? `00${n}` : n < 100 ? `0${n}` : `${n}`);

/** `HH:MM:SS.mmm` in the browser's zone. */
export function formatTime(tsMs: number): string {
  const d = new Date(tsMs);
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}.${pad3(d.getMilliseconds())}`;
}

/** `HH:MM:SS` (dividers and empty states name a second, D02 S12 / S14). */
export function formatSecond(tsMs: number): string {
  return formatTime(tsMs).slice(0, 8);
}

/** The `HH:MM:` prefix (dimmed on tiers 0-1, D7) and the rest of the time. */
export function splitTime(text: string): readonly [prefix: string, rest: string] {
  return [text.slice(0, 6), text.slice(6)];
}

/** A count grouped by spaces: "412", "2 010", "10 000". */
export function formatCount(n: number): string {
  const s = String(Math.max(0, Math.round(n)));
  return s.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

/** A feed decimal with its integer part grouped by commas: "64012.0" -> "64,012.0". */
export function formatDecimal(text: string): string {
  const negative = text.startsWith("-");
  const body = negative ? text.slice(1) : text;
  const dot = body.indexOf(".");
  const int = dot === -1 ? body : body.slice(0, dot);
  const frac = dot === -1 ? "" : body.slice(dot);
  return `${negative ? "-" : ""}${int.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${frac}`;
}

/** The notional, compact: "7.7k", "256.1k", "1.2M"; under 1 000 with no unit. */
export function formatNotional(value: number): string {
  if (!Number.isFinite(value) || value < 0) return "—";
  if (value >= 1_000_000) return `${trim1(value / 1_000_000)}M`;
  if (value >= 1_000) return `${trim1(value / 1_000)}k`;
  return trim1(value);
}

const trim1 = (v: number): string => (Math.round(v * 10) / 10).toFixed(1).replace(/\.0$/, "");

/** The base asset of a USDT perpetual: "BTCUSDT" -> "BTC". */
export const baseAsset = (symbol: string): string => symbol.replace(/USDT$/, "");

export type TapeTier = 0 | 1 | 2;

export const sideWord = (side: TapeSide): "Buy" | "Sell" => (side === SIDE_BUY ? "Buy" : "Sell");

export interface RowNameInput {
  readonly side: TapeSide;
  readonly size: string;
  readonly base: string;
  readonly price: string;
  readonly notional: number;
  readonly tier: TapeTier;
  readonly time: string;
  readonly clusterSize: number;
  readonly liquidation: boolean;
  readonly block: boolean;
}

/**
 * D02:112 (`d02.13.cp26`): side first, the size and base asset at the price, the notional, the
 * tier word only on tiers 1-2, the tags as words (D9 order), then the full time.
 */
export function rowName(r: RowNameInput): string {
  const parts = [
    sideWord(r.side),
    `${formatDecimal(r.size)} ${r.base} at ${formatDecimal(r.price)}`,
    formatNotional(r.notional),
  ];
  if (r.tier === 1) parts.push("big");
  if (r.tier === 2) parts.push("whale");
  if (r.clusterSize > 1) parts.push(`cluster of ${r.clusterSize}`);
  if (r.liquidation) parts.push("liquidation");
  if (r.block) parts.push("block trade");
  parts.push(r.time);
  return parts.join(", ");
}

/** "00:12": the age of the last print (S10), as the connection region writes an age. */
export { formatAge } from "../../lib/ws/state/connectionRegion";
