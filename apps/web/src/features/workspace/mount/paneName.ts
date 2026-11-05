/**
 * A pane's region name (E15-D03 D-5; D03:670): kind, symbol and spelled interval, plus the
 * environment for an order-capable kind (`chart`, `dom`, `positions`; D03 D-4), "unconfirmed"
 * while unknown (D03:677): "Chart, BTCUSDT 1 minute, Live", "Positions, all symbols, Live".
 */
import type { PaneFields } from "@candleviewer/dock";

const ORDER_CAPABLE = new Set(["chart", "dom", "positions"]);
const ENV: Readonly<Record<string, string>> = { live: "Live", demo: "Demo", testnet: "Testnet" };
const UNIT: Readonly<Record<string, string>> = { D: "1 day", W: "1 week", M: "1 month" };
const count = (n: number, unit: string): string => `${n} ${unit}${n === 1 ? "" : "s"}`;

/** `22` `PaneIntervalCode` spelled: `time:1` "1 minute", `time:240` "4 hours", `time:D` "1 day". */
export function spellInterval(code: string): string {
  const param = code.startsWith("time:") ? code.slice(5) : "";
  const minutes = /^[1-9]\d{0,5}$/.test(param) ? Number(param) : 0;
  if (minutes === 0) return UNIT[param] ?? code;
  return minutes % 60 === 0 ? count(minutes / 60, "hour") : count(minutes, "minute");
}

export function regionName(kind: string, label: string, f: PaneFields | undefined, env: string) {
  const symbol = f?.symbol ?? null;
  const interval = f?.interval_code ?? null;
  const parts = [label];
  if (symbol !== null)
    parts.push(interval === null ? symbol : `${symbol} ${spellInterval(interval)}`);
  else if (kind === "positions") parts.push("all symbols");
  if (ORDER_CAPABLE.has(kind)) parts.push(ENV[env] ?? "unconfirmed");
  return parts.join(", ");
}
