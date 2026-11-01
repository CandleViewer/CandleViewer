/**
 * The fill line (E47-S02, #1358 BQ-07; `05` §6.2, §3.4.3): an order fill is a discrete event, said assertively at once;
 * it never moves focus, so a trader walking the ladder stays on the row they were on. A surface with an ambient
 * writer passes it, so pending ambient values are dropped as stale behind the fill.
 *
 * Bounded: one call is one assertive write, and the shell's assertive region holds one message (the latest), so a
 * burst of single calls can never grow the DOM, but each write interrupts the last. A caller with several fills at
 * once (one trade group's fan-out, E21-S06) passes them together to `announceFills`: one utterance, at most
 * `FILL_BATCH_CEILING` fills said in full, the rest counted.
 *
 * The account is named only through the caller's accessible set (`accountDirectory`); a fill whose account is not in
 * it, or a set that cannot name accounts unambiguously, is said without an account. An id is never said.
 */
import { displayDecimal } from "./format";
import { FILL, type OrderSide } from "./orderflowCopy";
import { sayToShell, type AmbientWriter } from "./politeWriter";
import { sizeText } from "./orderflowFormat";
import { accountDirectory, type AccessibleAccount } from "./readback";

export interface FillEvent {
  readonly side: OrderSide;
  readonly qty: string;
  readonly symbol: string;
  readonly price: string;
  /** The account's id; its name comes from the accessible set, never from the event. */
  readonly accountId: string;
  readonly partial?: boolean;
}

/** The most fills one utterance says in full; the rest are counted ("47 more fills"). */
export const FILL_BATCH_CEILING = 3;

export function fillSentence(fill: FillEvent, accessible: readonly AccessibleAccount[]): string {
  const line = FILL.line(
    fill.partial === true ? FILL.state.partial : FILL.state.full,
    fill.side,
    sizeText(fill.qty),
    fill.symbol,
    displayDecimal(fill.price),
  );
  const name = accountDirectory(accessible)?.get(fill.accountId)?.name;
  return name === undefined ? line : FILL.account(line, name);
}

/** One utterance for a batch: the first `FILL_BATCH_CEILING` fills in full, then the count of the rest. */
export function fillBatchSentence(
  fills: readonly FillEvent[],
  accessible: readonly AccessibleAccount[],
): string {
  const said = fills.slice(0, FILL_BATCH_CEILING).map((f) => fillSentence(f, accessible));
  const rest = fills.length - said.length;
  return [...said, ...(rest > 0 ? [FILL.more(rest)] : [])].join(". ");
}

type Say = (politeness: "assertive", text: string) => void;

/** Says a batch of fills assertively, once: through the surface's writer when it has one, else the shell announcer. */
export function announceFills(
  fills: readonly FillEvent[],
  accessible: readonly AccessibleAccount[],
  writer?: Pick<AmbientWriter, "alert">,
  say: Say = sayToShell,
): void {
  if (fills.length === 0) return;
  const text = fillBatchSentence(fills, accessible);
  if (writer === undefined) say("assertive", text);
  else writer.alert(text);
}

/** Says one fill assertively (`announceFills` with one fill). */
export function announceFill(
  fill: FillEvent,
  accessible: readonly AccessibleAccount[],
  writer?: Pick<AmbientWriter, "alert">,
  say: Say = sayToShell,
): void {
  announceFills([fill], accessible, writer, say);
}
