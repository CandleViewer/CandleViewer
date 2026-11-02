/**
 * The keyboard-order read-back (E47-S02, #1358 BQ-06; `05` §3.1.4, §3.3.5): the one sentence a confirm dialog says
 * before a ladder-row order is committed: kind, side, symbol, environment, resolved price and every target account with its
 * resolved quantity. Pure: it places nothing, binds no key and opens no dialog (E21-S01/S06 and the US-SET-003
 * confirm policy wire it). The accounts it may name are the caller's accessible set, as the server scoped them; a leg
 * outside that set refuses the whole read-back without naming the account, so an order the user cannot fully see is
 * never shown as confirmable.
 */
import { displayDecimal } from "./format";
import { READBACK, type OrderEnv, type OrderSide } from "./orderflowCopy";

export interface AccessibleAccount {
  /** Matched exactly (case and whitespace sensitive), so a near-miss id fails closed. */
  readonly id: string;
  /** The display name the user already sees for this account. */
  readonly name: string;
  readonly env: OrderEnv;
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
  /** The environment the order goes to; every leg's account must be in it (C-2.11). */
  readonly env: OrderEnv;
  /** The focused row's price, resolved to the tick. */
  readonly price: string;
  /** The quantity unit, the instrument's `base_coin` when the caller has it ("BTC"). */
  readonly unit?: string;
  readonly legs: readonly ResolvedLeg[];
}

/**
 * Why a read-back was refused. Every reason's sentence is generic: no account name, id, quantity or price. Only
 * "zero" and "invalid" are about the user's input; "inaccessible" outranks every other reason, so a caller that
 * offers "fix the quantity" never does so for an order that also targets a foreign account.
 */
export type RefusalReason =
  "inaccessible" | "empty" | "zero" | "duplicate" | "env" | "ambiguous" | "invalid";

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
      readonly reason: RefusalReason;
      readonly sentence: string;
    };

const DECIMAL = /^\d+(?:\.\d+)?$/;
/** Symbols and units are words in the sentence: plain upper-case alphanumerics only. */
const WORD = /^[A-Z0-9]{1,32}$/;

/** Exact sum of non-negative decimal strings (scaled BigInt): "0.1" + "0.2" is "0.3". Throws on a non-decimal. */
export function sumDecimals(values: readonly string[]): string {
  let scale = 0;
  for (const v of values) {
    if (!DECIMAL.test(v)) throw new RangeError("not a non-negative decimal");
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

/** The name as said: format characters dropped, control characters and runs of space as one space. */
export const shownName = (name: string): string =>
  name
    .replace(/\p{Cf}/gu, "")
    .replace(/[\p{Cc}\s]+/gu, " ")
    .trim();

/** The collision key: the shown name, NFKC-normalised and case-folded. */
const nameKey = (name: string): string =>
  shownName(name).normalize("NFKC").toUpperCase().toLowerCase();

export interface AccountEntry {
  readonly name: string;
  readonly env: OrderEnv;
}

/**
 * The accessible set as a lookup, or null when it cannot name accounts unambiguously: a repeated id, a name empty
 * once cleaned, or two names that read alike after normalisation ("Main" and "MAIN", "Main" and "Main\u200b").
 */
export function accountDirectory(
  accessible: readonly AccessibleAccount[],
): ReadonlyMap<string, AccountEntry> | null {
  const byId = new Map<string, AccountEntry>();
  const keys = new Set<string>();
  for (const a of accessible) {
    const name = shownName(a.name);
    const key = nameKey(a.name);
    if (byId.has(a.id) || key === "" || keys.has(key)) return null;
    byId.set(a.id, { name, env: a.env });
    keys.add(key);
  }
  return byId;
}

const refuse = (reason: RefusalReason, sentence: string): Readback => ({
  ok: false,
  reason,
  sentence,
});

/**
 * The read-back, or a refusal; it never throws. Checks run over every leg before the next check, in this order:
 * access, then the accessible set's names, a repeated account, the environment, malformed values, zero quantities.
 */
export function keyboardOrderReadback(
  intent: KeyboardOrderIntent,
  accessible: readonly AccessibleAccount[],
): Readback {
  const { legs } = intent;
  if (legs.length === 0) return refuse("empty", READBACK.empty);
  const ids = new Set(accessible.map((a) => a.id));
  if (legs.some((leg) => !ids.has(leg.accountId))) return refuse("inaccessible", READBACK.refused);
  const directory = accountDirectory(accessible);
  if (directory === null) return refuse("ambiguous", READBACK.ambiguous);
  if (new Set(legs.map((leg) => leg.accountId)).size !== legs.length)
    return refuse("duplicate", READBACK.duplicate);
  if (legs.some((leg) => directory.get(leg.accountId)?.env !== intent.env))
    return refuse("env", READBACK.envMismatch);
  const valid =
    WORD.test(intent.symbol) &&
    (intent.unit === undefined || WORD.test(intent.unit)) &&
    DECIMAL.test(intent.price) &&
    !isZero(intent.price) &&
    legs.every((leg) => DECIMAL.test(leg.qty));
  if (!valid) return refuse("invalid", READBACK.invalid);
  if (legs.some((leg) => isZero(leg.qty))) return refuse("zero", READBACK.zero);

  const qty = (v: string): string => READBACK.qty(displayDecimal(v), intent.unit);
  const lines = legs.map((leg) =>
    READBACK.leg(directory.get(leg.accountId)?.name ?? "", qty(leg.qty)),
  );
  const head = READBACK.head(
    READBACK.kind[intent.kind],
    intent.side,
    intent.symbol,
    READBACK.env[intent.env],
    displayDecimal(intent.price),
  );
  const total = READBACK.total(legs.length, qty(sumDecimals(legs.map((l) => l.qty))));
  return { ok: true, lines, sentence: `${head}. ${lines.join("; ")}. ${total}` };
}
