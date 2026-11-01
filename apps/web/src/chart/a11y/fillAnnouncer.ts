/**
 * The fill line (E47-S02, #1358 BQ-07; `05` §6.2, §3.4.3): an order fill is a discrete event, said assertively at once
 * and never coalesced; it never moves focus, so a trader walking the ladder stays on the row they were on. A surface
 * with an ambient writer passes it, so pending ambient values are dropped as stale behind the fill.
 */
import { displayDecimal } from "./format";
import { FILL, type OrderSide } from "./orderflowCopy";
import { sayToShell, type AmbientWriter } from "./politeWriter";
import { sizeText } from "./orderflowFormat";

export interface FillEvent {
  readonly side: OrderSide;
  readonly qty: string;
  readonly symbol: string;
  readonly price: string;
  /** The account's display name; fills arrive only for the caller's accounts (server-scoped). */
  readonly account: string;
  readonly partial?: boolean;
}

export function fillSentence(fill: FillEvent): string {
  const line = FILL.line(
    fill.side,
    sizeText(fill.qty),
    fill.symbol,
    displayDecimal(fill.price),
    fill.account,
  );
  return fill.partial === true ? `${line}, ${FILL.partial}` : line;
}

/** Says the fill assertively: through the surface's writer when it has one, else the shell announcer. */
export function announceFill(
  fill: FillEvent,
  writer?: Pick<AmbientWriter, "alert">,
  say: (politeness: "assertive", text: string) => void = sayToShell,
): void {
  const text = fillSentence(fill);
  if (writer === undefined) say("assertive", text);
  else writer.alert(text);
}
