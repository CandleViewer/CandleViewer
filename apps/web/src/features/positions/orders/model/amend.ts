/**
 * The inline amend's model (E29-S02 #912, PR3a: the engine, no UI): the field an edit changes,
 * whether the change raises exposure, the one-field body, and the reducers that resolve a pending
 * amend on the venue's word alone. Pure: no DOM, no clock, no I/O (`../amendStore.ts` runs it).
 *
 * - **Risk** (`24` §8.10's one definition; P3-BQ-5): any edit of a reduce-only order is none, read
 *   from `reduce_only` alone as the server reads it (`exits.py` `risk_increasing`; `24`'s
 *   "take-profit change" is the amend's `take_profit` component, which no body here carries); a
 *   change of another order's price or trigger is risk-increasing (a resting entry repriced to a
 *   marketable price fills at once); its quantity raised is risk-increasing, cut is none. A
 *   quantity this client cannot read is risk-increasing (fail closed).
 * - **Provenance** (D-13; `exits.py`'s admission refuses any `provenance` but `placed` with `422
 *   order_not_amendable`): a row whose provenance a read gave is refused before any request unless
 *   it is `placed`; one no read has given (`23` §15.1 carries none: a WS-only row) is refused when
 *   it is a reduce-only take-profit, which may be a recorded one (fail closed), until the feed's
 *   next `open_only` read, after a snapshot, lists it.
 * - **The arm** (`22` `ArmToken`, SR-043): a risk-increasing amend on a live account carries the
 *   session's token; nothing else ever does (a cut, a reduce-only edit: C-2.6, R5). Live is
 *   `environment === "live"`, and an environment this client does not know is live (fail
 *   closed); demo and testnet never arm. The token comes from an injected `ArmTokenSource`, none by
 *   default (the keymap's `ArmPort` holds no token), so such an amend is never sent (T2 `arm.locked`).
 * - **The body** (P3-BQ-1, D-13): exactly one of `price`, `trigger_price` and `qty`, decimal text,
 *   never `stop_loss` or `take_profit`.
 * - **Resolution** (P3-BQ-7; E29-D02 §7, D01 D4): the confirmed value is never replaced before the
 *   venue answers. Frames are judged in arrival order, and one confirms or rejects only once the
 *   request frame (`amend_pending`) or the HTTP answer came, as no frame carries a correlation id;
 *   a frame that came before either is held and judged at the answer. An `amend` frame with the
 *   requested value confirms, with the prior one rejects; a read (a snapshot item, a `reconcile`
 *   step) confirms a pending amend only after a `202` whose order rests, and never rejects it.
 *   Unknown (the order `unknown`; a `202` whose order does not rest, `amend_pending` or `unknown`
 *   among them, or that names no state; no answer; or `AMEND_STALE_MS` with no word) is
 *   Unconfirmed, which a later read settles in D01:228–229's words. An ended, held or adopted
 *   order, a third value, or a refusal (nothing sent) ends the overlay.
 */
import type { generated } from "@candleviewer/protocol";
import { bindDeck, bindText, DECK } from "../../copy";
import { add, cmp, parseDecimal, sameAmount, toPlain } from "../../model/decimal";
import { AMEND_TEXT, bindProposed } from "../copy";
import { stateOfItem, type Figure, type OrderRowModel } from "./orderRow";

export type AmendField = "price" | "trigger_price" | "qty";
export type AmendRequest = generated.rest.components["schemas"]["AmendOrderRequest"];
export type RiskClass = "increasing" | "none";

/**
 * PROPOSED (P3-BQ-7: neither `23` nor `24` fixes a client bound): a pending amend with no word
 * this long after its press, or after its HTTP answer, reads Unconfirmed. `CV_COMMAND_TIMEOUT`
 * (10 s, `20` §4) bounds the server's step, and its `202` waits that plus 1 s (`24` §8.4).
 */
export const AMEND_STALE_MS = 15_000;

type Amendable = Pick<OrderRowModel, "price" | "isMarket" | "trigger" | "qty">;

/** The field's confirmed value on the row, or `null` when the order has none (no Edit item). */
export function valueOf(row: Amendable, field: AmendField): string | null {
  if (field === "price") return row.isMarket ? null : row.price;
  if (field === "trigger_price") return row.trigger?.price ?? null;
  return row.qty;
}

/**
 * `24` §8.10's class of setting `field` to `requested` (`null`: not typed yet, a price's any), by
 * `reduce_only` alone, as `exits.py`'s `risk_increasing` reads it: never by the intent.
 */
export function riskClass(
  row: Pick<OrderRowModel, "reduceOnly" | "qty">,
  field: AmendField,
  requested: string | null,
): RiskClass {
  if (row.reduceOnly) return "none";
  if (field !== "qty") return "increasing";
  const next = parseDecimal(requested);
  const held = parseDecimal(row.qty);
  if (next === null || held === null) return "increasing";
  return cmp(next, held) > 0 ? "increasing" : "none";
}

/** Demo and testnet never arm (SR-043); live, and an environment not known, do. */
const ARM_FREE: ReadonlySet<string> = new Set(["demo", "testnet"]);

/** Whether this amend needs the session's arm token (`22` `ArmToken`). */
export function needsArm(
  row: Pick<OrderRowModel, "reduceOnly" | "qty" | "environment">,
  field: AmendField,
  requested: string | null,
): boolean {
  if (riskClass(row, field, requested) === "none") return false;
  return row.environment === null || !ARM_FREE.has(row.environment);
}

/** Why a row's provenance bars its amend before any request (P3-BQ-1, D-13). */
export type ProvenanceBar = "not_placed" | "unread";

/**
 * `not_placed`: a read gave a provenance other than `placed`, which `exits.py`'s admission refuses
 * (`422 order_not_amendable`). `unread`: no read has given one (`23` §15.1 carries none) and the
 * row is a reduce-only take-profit, which may be a recorded one: refused, fail closed, until the
 * feed's next `open_only` read, which follows a snapshot, lists it. Any other row: `null`.
 */
export function provenanceBar(
  row: Pick<OrderRowModel, "provenance" | "intent" | "reduceOnly">,
): ProvenanceBar | null {
  if (row.provenance !== null) return row.provenance === "placed" ? null : "not_placed";
  return row.reduceOnly && row.intent === "take_profit" ? "unread" : null;
}

/** The session's arm token for an account (E30-S04's), or `null` while it is not armed. */
export interface ArmTokenSource {
  readonly token: (accountId: string) => string | null;
}

/** The default until E30 injects one: never a token, so a live risk-increasing amend fails closed. */
export const NO_ARM: ArmTokenSource = Object.freeze({ token: () => null });

/** `22`'s `ArmToken` bounds. */
const MAX_TOKEN = 256;

/** The token `source` holds for `accountId` now; one that throws or holds no usable string, none. */
export function armToken(source: ArmTokenSource, accountId: string): string | null {
  try {
    const token = source.token(accountId);
    return typeof token === "string" && token.length > 0 && token.length <= MAX_TOKEN
      ? token
      : null;
  } catch {
    return null;
  }
}

/** `22` `AmendOrderRequest` for one field, or `null` unless `requested` is a positive decimal. */
export function amendBody(field: AmendField, requested: string): AmendRequest | null {
  const parsed = parseDecimal(requested);
  if (parsed === null || parsed.units <= 0n) return null;
  if (field === "price") return { price: requested };
  if (field === "trigger_price") return { trigger_price: requested };
  return { qty: requested };
}

/** Why a request is not sendable as typed, or `null`: the editor's checks, kept as a last guard. */
export type RequestFault = "absent" | "invalid" | "unchanged" | "not_above_filled";

export function requestFault(
  row: Amendable & Pick<OrderRowModel, "filledQty">,
  field: AmendField,
  requested: string,
): RequestFault | null {
  const prior = valueOf(row, field);
  if (prior === null) return "absent";
  if (amendBody(field, requested) === null) return "invalid";
  if (sameAmount(requested, prior)) return "unchanged";
  const next = parseDecimal(requested);
  const filled = parseDecimal(row.filledQty ?? "0");
  if (field === "qty" && (next === null || filled === null || cmp(next, filled) <= 0))
    return "not_above_filled"; // `22`: `qty_not_above_filled`
  return null;
}

/** The lowest quantity an edit may ask (D01:399): one lot above the fill, at least the minimum. */
export function qtyFloor(
  row: Pick<OrderRowModel, "filledQty">,
  steps: { readonly qtyStep: string; readonly minOrderQty: string | null },
): string | null {
  const filled = parseDecimal(row.filledQty ?? "0");
  const lot = parseDecimal(steps.qtyStep);
  if (filled === null || lot === null) return null;
  const floor = add(filled, lot);
  const least = parseDecimal(steps.minOrderQty);
  return toPlain(least !== null && cmp(least, floor) > 0 ? least : floor);
}

/** Where a frame item came from: a snapshot (a read, never a `change`) or a delta (one step). */
export type FrameVia = "snap" | "delta";

/** The HTTP answer as the resolution reads it: none yet, the `202`, unknown, or refused. */
export type HttpState = "none" | "accepted" | "unknown" | "refused";

/**
 * The moment (E29-D02 §7): Amending, Unknown — checking, rejected (S2), not applied (D01:229) and
 * not sent (a refusal at the point of action); the last three stay until dismissed.
 */
export type AmendPhase = "pending" | "unconfirmed" | "rejected" | "not_applied" | "not_sent";

/** What one event settled, said and measured once; confirmed, reconciled and dropped leave the map. */
export type Resolution = Exclude<AmendPhase, "pending"> | "confirmed" | "reconciled" | "dropped";

export interface HeldItem {
  readonly item: unknown;
  readonly via: FrameVia;
}

/** One order's entry in `pendingMutations` (the ticket's map), additive to the store's rows. */
export interface PendingMutation {
  readonly orderId: string;
  /** The press's number: a late answer of an earlier press never settles a newer one. */
  readonly seq: number;
  readonly field: AmendField;
  /** The value sent, decimal text. */
  readonly requested: string;
  /** The confirmed value at the press, which the cell keeps until the venue answers (D-10). */
  readonly prior: string;
  /** The press, on the store's monotonic clock. */
  readonly sentAt: number;
  readonly phase: AmendPhase;
  /** The request frame (`amend_pending`) came. */
  readonly sawPending: boolean;
  readonly http: HttpState;
  readonly httpAt: number | null;
  /** The resolution last announced: each is said once, however much evidence repeats it (M25). */
  readonly said: Resolution | null;
  /** The newest frame that spoke before it could count (P3-BQ-7), judged at the HTTP answer. */
  readonly held: HeldItem | null;
  /** The refusal's fixed kind, while `not_sent`. */
  readonly refusal: string | null;
}

export interface AmendStep {
  /** The entry after the event; `null` once it leaves the map. */
  readonly next: PendingMutation | null;
  /** What the event settled; `null` when no moment changed. */
  readonly resolution: Resolution | null;
}

const stay = (m: PendingMutation): AmendStep => ({ next: m, resolution: null });
const leave = (resolution: Resolution): AmendStep => ({ next: null, resolution });
const enter = (m: PendingMutation, phase: Exclude<AmendPhase, "pending">): AmendStep => ({
  next: { ...m, phase },
  resolution: phase,
});

/** A resting order: its terms answer the amend. */
const RESTING: ReadonlySet<string> = new Set(["submitted", "partially_filled"]);
/** No longer the OMS's to amend: the overlay ends (S9, INV-B1-n; D01 D4 × Unknown's last row). */
const NOT_OURS: ReadonlySet<string> = new Set(["held", "quarantined", "untracked"]);

const settled = (m: PendingMutation): boolean =>
  m.phase === "rejected" || m.phase === "not_applied" || m.phase === "not_sent";
/** P3-BQ-7: a frame counts once the request frame or the HTTP answer came (no correlation id). */
const counts = (m: PendingMutation): boolean => m.sawPending || m.http !== "none";

const read = (item: unknown, key: string): unknown =>
  typeof item === "object" && item !== null ? Reflect.get(item, key) : undefined;

/** One accepted frame item for the order, in arrival order (the store's observer, after its drops). */
export function onItem(m: PendingMutation, item: unknown, via: FrameVia): AmendStep {
  const { lifecycle, terminal } = stateOfItem(item);
  if (terminal || (lifecycle !== null && NOT_OURS.has(lifecycle))) return leave("dropped");
  if (lifecycle === "amend_pending")
    return stay(m.phase === "pending" ? { ...m, sawPending: true } : m);
  if (lifecycle === "unknown") return m.phase === "pending" ? enter(m, "unconfirmed") : stay(m);
  if (lifecycle === null || !RESTING.has(lifecycle)) return stay(m);
  const change = read(item, "change");
  if (via === "delta" && change !== "amend" && change !== "reconcile") return stay(m);
  // nothing was sent: "your order is unchanged" holds only while the order keeps its prior value
  if (m.phase === "not_sent")
    return sameAmount(read(item, m.field), m.prior) ? stay(m) : leave("dropped");
  if (!counts(m)) return stay({ ...m, held: { item, via } });
  return judge(m, { item, via }, via === "delta" && change === "amend");
}

/** A resting order's terms against the amend: `answer` is the venue's `change: "amend"` step. */
function judge(m: PendingMutation, held: HeldItem, answer: boolean): AmendStep {
  const value = read(held.item, m.field);
  if (sameAmount(value, m.requested)) {
    if (answer) return leave("confirmed");
    // a read confirms a pending amend only once its `202` took it (a `snap` after a reset)
    if (m.phase === "pending" && m.http !== "accepted") return stay({ ...m, held });
    return leave(m.phase === "pending" ? "confirmed" : "reconciled");
  }
  if (sameAmount(value, m.prior)) {
    if (answer) return enter(m, "rejected");
    // a read never rejects a pending amend, one whose `202` said the venue took it, or a rejection
    if (m.phase === "pending" || m.phase === "rejected" || m.http === "accepted") return stay(m);
    return enter(m, "not_applied");
  }
  return leave("dropped"); // a third value: another write moved the order
}

/** The answer's class: a `202` whose order rests, unknown, a `502`, or a refusal (`answerOf`). */
export type AnswerClass = "accepted" | "unknown" | "rejected" | "not_sent";

/** `amendOrder`'s outcome as the reducer reads it (`api.ts` makes it; no import, no cycle). */
export interface AnswerLike {
  readonly kind: string;
  readonly lifecycle?: string | null;
}

/**
 * The answer's class (P3-BQ-7). A `202` comes once B1's step settles, else after
 * `CV_COMMAND_TIMEOUT` + 1 s "as the order then stands" (`24` §8.4 rule 11): one whose order rests
 * again (`submitted`, `partially_filled`) took the amend; one whose order does not rest
 * (`amend_pending`, `unknown`, any other) or names no state is unknown, so a later read settles it
 * in D01:228–229's words. A `502` is rejected; any other refusal sent nothing.
 */
export function answerOf(outcome: AnswerLike): AnswerClass {
  if (outcome.kind === "accepted") {
    const { lifecycle } = outcome;
    return typeof lifecycle === "string" && RESTING.has(lifecycle) ? "accepted" : "unknown";
  }
  if (outcome.kind === "unavailable") return "unknown";
  return outcome.kind === "exchange_refused" ? "rejected" : "not_sent";
}

/** The HTTP answer: a `202` never confirms (M2); a frame held for it is judged now. */
export function onAnswer(m: PendingMutation, outcome: AnswerLike, now: number): AmendStep {
  if (m.http !== "none") return stay(m);
  const cls = answerOf(outcome);
  if (cls === "rejected" || cls === "not_sent") {
    const refused: PendingMutation = { ...m, http: "refused", httpAt: now, held: null };
    // a frame settled it first: a `502` re-affirms its rejection, a refusal never overrules it
    if (settled(m)) return { next: refused, resolution: cls === m.phase ? cls : null };
    return enter({ ...refused, refusal: cls === "not_sent" ? outcome.kind : null }, cls);
  }
  const answered: PendingMutation = { ...m, http: cls, httpAt: now, held: null };
  const step =
    cls === "unknown" && m.phase === "pending" ? enter(answered, "unconfirmed") : stay(answered);
  if (m.held === null || step.next === null) return step;
  const again = onItem(step.next, m.held.item, m.held.via);
  return { next: again.next, resolution: again.resolution ?? step.resolution };
}

/** The stale bound: a pending amend with no word for `AMEND_STALE_MS` reads Unconfirmed, never confirmed. */
export function onTick(m: PendingMutation, now: number): AmendStep {
  if (m.phase !== "pending" || now - (m.httpAt ?? m.sentAt) < AMEND_STALE_MS) return stay(m);
  return enter(m, "unconfirmed");
}

type Moment = Pick<PendingMutation, "phase" | "requested" | "prior" | "refusal">;

/** The State cell's line (E29-D02 §7; the deck's S-12 keys, D01:229, `arm.refused`, PROPOSED). */
export function momentLine(m: Moment, figure: Figure): string {
  switch (m.phase) {
    case "pending":
      return bindDeck("blotter.ui.amend.pending", {
        "2,495.00": figure(m.requested),
        "2,500.00": figure(m.prior),
      });
    case "unconfirmed":
      return bindDeck("blotter.ui.amend.unconfirmed", { "2,500.00": figure(m.prior) });
    case "rejected":
      return DECK["blotter.ui.amend.rejected"].string;
    case "not_applied":
      return bindText(AMEND_TEXT.notApplied, "AMEND_TEXT.notApplied", {
        "63,000": figure(m.prior),
      });
    case "not_sent":
      return m.refusal === "arm_refused"
        ? DECK["arm.refused"].string
        : bindProposed("blotter.ui.amend.not_sent");
  }
}

/** A row's cell under its amend: the confirmed value, never the requested one (D-10, D01 D4). */
export function overlayOf(
  row: Amendable,
  m: PendingMutation,
  figure: Figure,
): { readonly value: string | null; readonly line: string } {
  const value = valueOf(row, m.field);
  return { value: value === null ? null : figure(value), line: momentLine(m, figure) };
}

export interface AmendAnnouncement {
  readonly politeness: "polite" | "assertive";
  readonly text: string;
}

/** What a resolution says, once (E29-D05 RT-14 polite, RT-06 assertive); the rest say nothing. */
export function announcementOf(
  m: PendingMutation,
  resolution: Resolution,
  figure: Figure,
): AmendAnnouncement | null {
  const requested = figure(m.requested);
  const prior = figure(m.prior);
  switch (resolution) {
    case "confirmed":
      return {
        politeness: "polite",
        text:
          m.field === "price"
            ? bindDeck("blotter.ui.amend.confirmed", { "2,495.00": requested })
            : m.field === "trigger_price"
              ? bindProposed("blotter.ui.amend.confirmed.trigger", { "63,980.0": requested })
              : bindProposed("blotter.ui.amend.confirmed.qty", { "0.200": requested }),
      };
    case "reconciled":
      // PROPOSED for E29-D05 (no RT row words D01:228–229's lines): polite, as RT-14's
      // confirmation; "not applied" below assertive, as RT-06's rejection
      return { politeness: "polite", text: AMEND_TEXT.reconciled.string };
    case "rejected":
      return {
        politeness: "assertive",
        text:
          m.field === "price"
            ? bindDeck("blotter.ui.amend.rejected_desc", { "2,500.00": prior })
            : m.field === "trigger_price"
              ? bindProposed("blotter.ui.amend.rejected_desc.trigger", { "63,950.0": prior })
              : bindProposed("blotter.ui.amend.rejected_desc.qty", { "0.150": prior }),
      };
    case "not_applied":
      // PROPOSED for E29-D05, with "reconciled" above: D01:229's line is said assertively
      return { politeness: "assertive", text: momentLine({ ...m, phase: "not_applied" }, figure) };
    default:
      return null;
  }
}
