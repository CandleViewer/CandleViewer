/**
 * The ticket's validation copy (#984 BQ 11 ruling): every key, template and parameter comes from
 * the E30-D06 deck (`docs/design/E30/E30-D06-copy.json`, PR 1 #5107), never written here. The
 * templates below are pinned copies, and `test/messages.test.ts` fails when a key is missing from
 * the deck, its string is reworded or its parameters change, so the deck stays the one owner.
 *
 * A rule is shown through a deck `ticket.order.v.*` key, or through the key an existing `by_code`
 * row names for the server code the rule mirrors (sentence-true, D06 §6.1, RULED row 3). A rule
 * the deck has no sentence for is `pending`: it still blocks the submit and counts in the
 * summary, but its sentence is a deck question (routed to #919), never invented here (D06 §6.1:
 * "no copy is invented").
 */
import type { ValidationFailure } from "./validate.js";

/** A pinned deck string: its template and its parameters in order (none when omitted). */
interface DeckString {
  readonly template: string;
  readonly params?: readonly string[];
}

/** The deck strings validation uses: key → pinned template and its parameters, in order. */
export const DECK_STRINGS = {
  "ticket.order.v.price.tick": {
    template: "Price must be a multiple of {tick}.",
    params: ["tick"],
  },
  "ticket.order.v.qty.lot": { template: "Minimum {min}, step {step}.", params: ["min", "step"] },
  "ticket.reject.reason.lot": {
    template: "{qty} is not a multiple of the {step} step.",
    params: ["qty", "step"],
  },
  "ticket.order.v.notional.min": {
    template: "Order value must be at least {min} USDT.",
    params: ["min"],
  },
  "ticket.order.v.sl.required": { template: "Every position-opening order requires a stop-loss." },
  "ticket.order.v.sl.side.long": { template: "Stop-loss must be below entry for a long." },
  "ticket.order.v.sl.side.short": { template: "Stop-loss must be above entry for a short." },
  "ticket.order.refusal.invalid_stop_distance": {
    template: "Stop distance must be greater than zero — move the stop away from the entry",
  },
  "ticket.order.v.tp.side.long": { template: "Take-profit must be above entry for a long." },
  "ticket.order.v.tp.side.short": { template: "Take-profit must be below entry for a short." },
  "ticket.order.v.post_only.cross": {
    template: "Post-only would execute immediately — adjust the price or uncheck Post-only.",
  },
  "ticket.order.v.reduce_only.no_position": { template: "Reduce-only needs an open position." },
  "ticket.order.v.summary.heading": { template: "Can't submit — {n} problems", params: ["n"] },
  "ticket.order.v.submit.reason": { template: "Fix {n} problems to submit", params: ["n"] },
} as const satisfies Record<string, DeckString>;

export type DeckKey = keyof typeof DECK_STRINGS;

/**
 * The deck keys a validation rule reaches through a `by_code` row rather than a `v.*` key, with
 * that row's code: the test checks the deck's `by_code` table still names the key for the code.
 */
export const BY_CODE_KEYS = {
  "ticket.reject.reason.lot": "problem:lot_size_violation",
  "ticket.order.v.notional.min": "sizing:below_min_notional",
  "ticket.order.refusal.invalid_stop_distance": "sizing:invalid_stop_distance",
} as const satisfies Partial<Record<DeckKey, string>>;

/** A message the ticket can render: a deck key and its parameters (plain decimal strings). */
export interface Message {
  readonly key: DeckKey;
  readonly params: Readonly<Record<string, string>>;
}

/**
 * A rule with no deck sentence yet: it blocks and counts, and names the deck question it waits
 * on. The renderer shows the field as invalid and the summary counts it; no copy is invented.
 */
export interface PendingMessage {
  readonly key: null;
  readonly pending: "deck-question-919";
}

export type RuleMessage = Message | PendingMessage;

export const PENDING: PendingMessage = Object.freeze({ key: null, pending: "deck-question-919" });

/** Keep only `names` from a failure's params (a failure may carry more than its sentence shows). */
function pick(
  params: Readonly<Record<string, string>>,
  ...names: string[]
): Record<string, string> | null {
  const out: Record<string, string> = {};
  for (const name of names) {
    const value = params[name];
    if (value === undefined) return null;
    out[name] = value;
  }
  return out;
}

/**
 * The message of a `validate()` failure (#984 BQ 11; the code lens's m1 / m2). Sentence-true only
 * (D06 §6.1, RULED row 3): a deck key whose sentence is not true of the failure is never used, so
 *
 * - `qty_step` takes `by_code` `problem:lot_size_violation`'s `ticket.reject.reason.lot`, whose
 *   sentence is exactly the step rule; `max_order_qty` does not (that sentence names the step,
 *   not a ceiling), nor does `symbol_not_trading` take `preview:symbol_not_allowed` (an owner
 *   setting, not the market's status): both stay `PENDING`;
 * - an unread position is not "no open position": it is `PENDING` until the deck has a
 *   "position not read yet" sentence (#919).
 */
export function messageFor(failure: ValidationFailure): RuleMessage {
  const p = failure.params;
  const keyed = (key: DeckKey, ...names: string[]): RuleMessage => {
    const params = pick(p, ...names);
    return params === null ? PENDING : message(key, params);
  };
  const side = p["side"] === "short" ? "short" : "long";
  switch (failure.rule) {
    case "tick_size":
      return keyed("ticket.order.v.price.tick", "tick");
    case "min_order_qty":
      return keyed("ticket.order.v.qty.lot", "min", "step");
    case "qty_step":
      return keyed("ticket.reject.reason.lot", "qty", "step");
    case "min_notional":
      return keyed("ticket.order.v.notional.min", "min");
    case "native_stop_required":
      return message("ticket.order.v.sl.required");
    case "invalid_stop_distance":
      return p["kind"] === "level"
        ? message(`ticket.order.v.sl.side.${side}`)
        : message("ticket.order.refusal.invalid_stop_distance");
    case "take_profit_side":
      return message(`ticket.order.v.tp.side.${side}`);
    case "post_only_cross":
      return message("ticket.order.v.post_only.cross");
    case "reduce_only_no_position":
      return p["read"] === "none" ? message("ticket.order.v.reduce_only.no_position") : PENDING;
    default:
      return PENDING;
  }
}

/** A deck message; the parameter names are checked against the pinned template's. */
export function message(key: DeckKey, params: Readonly<Record<string, string>> = {}): Message {
  const entry: DeckString = DECK_STRINGS[key];
  const expected = entry.params ?? [];
  const given = Object.keys(params);
  if (given.length !== expected.length || !expected.every((name) => name in params)) {
    throw new RangeError(`${key} takes {${expected.join(", ")}}, not {${given.join(", ")}}`);
  }
  return { key, params };
}

/** The deck sentence of a message, its `{param}` placeholders filled in. */
export function formatMessage(msg: Message): string {
  return DECK_STRINGS[msg.key].template.replace(/\{(\w+)\}/g, (_, name: string) => {
    const value = msg.params[name];
    if (value === undefined) throw new RangeError(`${msg.key} needs {${name}}`);
    return value;
  });
}

/** The summary heading and the submit reason for `n` blocking problems (D02 §14, LR-24). */
export const summaryMessages = (n: number): { heading: Message; reason: Message } => ({
  heading: message("ticket.order.v.summary.heading", { n: String(n) }),
  reason: message("ticket.order.v.submit.reason", { n: String(n) }),
});
