// E24-S05 (#780) slice 1: which position a liquidation print closed. The wire carries only the print's
// `side` (`23` §14.9 `LiquidationBatch`; `22` `Liquidation.side`); `24` §2.5 derives `liquidated_side`
// from it in the adapter (`"long" if side == "sell" else "short"`), and `22`'s `side` query reads
// "`buy` = short liquidated". BQ 1 (ruled 6612481277, #780): the client maps it here, in this one function,
// and nowhere else; every word and glyph on screen comes from its result (D02 §6, D03 §6.1).
import type { generated } from "@candleviewer/protocol";

export type WireSide = generated.ws.LiquidationsSymbolLiquidations["liquidations"][number]["side"];
export type LiquidatedSide = "long" | "short";

/** BQ 1 (ruled 6612481277): `sell` closed a long, `buy` closed a short (`24` §2.5). */
export function liquidatedSide(side: WireSide): LiquidatedSide {
  return side === "sell" ? "long" : "short";
}

/** D03 §6.1: the side word, never "Buy" / "Sell" (a liquidation is a forced event). */
export const SIDE_WORDS: Readonly<Record<LiquidatedSide, string>> = {
  long: "Long liquidated",
  short: "Short liquidated",
};

/** D03 §6.1: shorts above the axis ▲, longs below ▼; drawn beside the word, never read. */
export const SIDE_GLYPHS: Readonly<Record<LiquidatedSide, string>> = {
  long: "▼",
  short: "▲",
};
