/**
 * The keyboard-order read-back (E47-S02, #1358 BQ-06; `05` §3.1.4, §3.3.5): the one sentence a confirm dialog says
 * before a ladder-row order is committed: side, kind, symbol, resolved price and every target account with its
 * resolved quantity. Pure: it places nothing, binds no key and opens no dialog (E21-S01/S06 and the US-SET-003
 * confirm policy wire it). The accounts it may name are the caller's accessible set, as the server scoped them; a leg
 * outside that set refuses the whole read-back without naming the account, so an order the user cannot fully see is
 * never shown as confirmable.
 */
import { displayDecimal } from "./format";
import { READBACK, type OrderSide } from "./orderflowCopy";
import { sizeText } from "./orderflowFormat";

export interface AccessibleAccount {
  readonly id: string;
  /** The display name the user already sees for this account. */
  readonly name: string;
}

export interface ResolvedLeg {
  readonly accountId: string;
  /** The per-account quantity after sizing rules resolved it, a decimal string. */
  readonly qty: string;
}

export interface KeyboardOrderIntent {
  readonly side: OrderSide;
  readonly kind: "limit" | "aggressive";
  readonly symbol: string;
  /** The focused row's price, resolved to the tick. */
  readonly price: string;
  readonly legs: readonly ResolvedLeg[];
}

export type Readback =
  | {
      readonly ok: true;
      /** The whole read-back as one utterance. */
      readonly sentence: string;
      /** One line per account, in leg order, for the dialog's list. */
      readonly lines: readonly string[];
    }
  | {
      readonly ok: false;
      readonly reason: "inaccessible" | "empty" | "zero";
      readonly sentence: string;
    };

const DECIMAL = /^\d+(?:\.\d+)?$/;

/** Exact sum of non-negative decimal strings (scaled BigInt): "0.1" + "0.2" is "0.3". */
export function sumDecimals(values: readonly string[]): string {
  let scale = 0;
  for (const v of values) {
    if (!DECIMAL.test(v)) throw new RangeError(`not a non-negative decimal: "${v}"`);
    scale = Math.max(scale, (v.split(".")[1] ?? "").length);
  }
  let total = 0n;
  for (const v of values) {
    const [int = "0", frac = ""] = v.split(".");
    total += BigInt(int + frac.padEnd(scale, "0"));
  }
  const digits = total.toString().padStart(scale + 1, "0");
  return scale === 0
    ? digits
    : `${digits.slice(0, digits.length - scale)}.${digits.slice(digits.length - scale)}`;
}

const isZero = (qty: string): boolean => /^0+(?:\.0+)?$/.test(qty);

export function keyboardOrderReadback(
  intent: KeyboardOrderIntent,
  accessible: readonly AccessibleAccount[],
): Readback {
  if (intent.legs.length === 0) return { ok: false, reason: "empty", sentence: READBACK.empty };
  const names = new Map(accessible.map((a) => [a.id, a.name]));
  const lines: string[] = [];
  for (const leg of intent.legs) {
    const name = names.get(leg.accountId);
    if (name === undefined)
      return { ok: false, reason: "inaccessible", sentence: READBACK.refused };
    if (isZero(leg.qty)) return { ok: false, reason: "zero", sentence: READBACK.zero };
    lines.push(READBACK.leg(name, sizeText(leg.qty)));
  }
  const head = READBACK.head(
    intent.side,
    READBACK.kind[intent.kind],
    intent.symbol,
    displayDecimal(intent.price),
  );
  const total = READBACK.total(
    intent.legs.length,
    displayDecimal(sumDecimals(intent.legs.map((l) => l.qty))),
  );
  return { ok: true, lines, sentence: `${head}: ${lines.join("; ")}. ${total}` };
}
