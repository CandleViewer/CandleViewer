// E24-S05 (#780) slice 1: the feed's number and time formats, D03 §2's rows: prices and sizes comma-grouped as
// sent; the liquidation notional exact to two decimals, comma-grouped, + " USDT" in the feed; the print rate an
// integer comma-grouped + " prints/s" (spoken "per second", D03 §13); times in UTC. Formatting only — the
// decimals arrive as strings and are never combined (`22`: the notional is computed once, at ingest).

const groupInt = (digits: string): string => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");

/** "62880.00" → "62,880.00": the decimal as sent, grouped. */
export function groupedDecimal(value: string): string {
  const [int = "", frac] = value.split(".");
  return frac === undefined ? groupInt(int) : `${groupInt(int)}.${frac}`;
}

/** D03 §2 "liquidation notional" in the feed: "202473.6" → "202,473.60". */
export function notional2(value: string): string {
  const n = Number(value);
  return Number.isFinite(n) ? groupedDecimal(n.toFixed(2)) : groupedDecimal(value);
}

/** "1,240 prints/s" and its spoken twin. */
export const rateText = (perSec: number): string => `${groupInt(String(perSec))} prints/s`;
export const rateSpoken = (perSec: number): string =>
  `${groupInt(String(perSec))} prints per second`;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pad = (n: number): string => String(n).padStart(2, "0");

/** The feed's time cell, "09:14:02" (the column header carries "UTC"). */
export function feedTime(ms: number): string {
  const d = new Date(ms);
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
}

/** "09:14:02 UTC". */
export const utcTime = (ms: number): string => `${feedTime(ms)} UTC`;

/** "09:14 UTC" today, "21 Oct 09:14 UTC" on another day (D02 §15, the partial chip). */
export function coverageTime(ms: number, nowMs: number): string {
  const d = new Date(ms);
  const hm = `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`;
  if (new Date(nowMs).toISOString().slice(0, 10) === d.toISOString().slice(0, 10)) return hm;
  return `${String(d.getUTCDate())} ${MONTHS[d.getUTCMonth()] ?? ""} ${hm}`;
}

/** BTCUSDT → BTC: the base unit of a USDT perpetual's size. */
export const baseUnit = (symbol: string): string => symbol.replace(/USDT$/, "");
