/**
 * The words the node library and the inspector show (E37-S02), each under its deck key and verbatim: E36-D05's
 * keys that E37-D05 §8.2 and §9 cite (`docs/design/E36/E36-D05-copy-deck.json`), E37-D05's node, stop and
 * inspector rows (`docs/design/E37/E37-D05-copy-deck.jsonl`), and two PROPOSED keys no deck has yet (the #950
 * addendum). A `{slot}` is filled by `fill`; a deck row written as an instance ("41 metrics") is held as its
 * template here and checked against the deck filled with the instance's values. Pure: no React, no DOM global.
 */

/** E36-D05 (merged): the editors' shared strings S02 renders. FS-1, FS-2 and FS-3 are frozen (E36-D05). */
export const E36_COPY = {
  "rules.editor.name.metric": "Metric",
  "rules.editor.name.estimated": "Estimated, {display name}",
  "rules.editor.row.estimated": "(estimated)",
  "rules.editor.row.unavailable": "(not available — {reason} · Start recording)",
  "rules.editor.row.start_recording": "Start recording",
  "rules.editor.announce.metrics": "{n} metrics",
  "rules.editor.summary.estimated": "Uses an estimated detector — behaviour is heuristic.",
  "rules.editor.action.simulate_only": "simulate only",
  "rules.editor.action.places_orders": "places orders",
  "rules.editor.action.flattens": "flattens",
  "rules.editor.flatten.ack":
    "I understand this flattens every open position on the accounts in scope.",
  "rules.editor.validity.flatten": "Tick ‘I understand’ on Flatten all positions first.",
  "rbac.owner_only.start_recording": "Only the owner can start recording.",
  "rbac.owner_only.arm_live": "Only the owner can arm rules against live.",
  "rbac.permission.place_orders": "Your role can't place orders.",
  // FZ-1 (E37-D05 §9): the price is the field's own value.
  "rules.editor.stop.kept":
    "Kept at {price} — every position keeps a native stop. Move it instead.",
  // FS-3, FS-1, FS-2 (E36-D05; cited by E37-D05 §8.2, not re-frozen there).
  "rules.editor.stop.never_loosen": "Rules never loosen a stop.",
  "rules.editor.notice.native_stop_1":
    "Every position keeps a native stop — you can move it, not delete it.",
  "rules.editor.notice.native_stop_2":
    "Rules can tighten it, never remove it — the stop is held by the exchange, not by this app.",
  // The rule sentence (E37-S02 slice 4): the safety line (frozen by E36-D05), the graph-only cards' sentences,
  // the action phrases and the limit sentences E36-D05 keys (E36-D01 §5.3, §5.4 G6, §5.6).
  "rules.editor.stop.tightens": "The stop only ever tightens.",
  "rules.editor.card.within": "{A} happened within the last {w}",
  "rules.editor.card.count": "{A} happened at least {n} times in {w}",
  "rules.editor.card.stable": "{A} has not changed for {w}",
  "rules.editor.action.phrase.tighten": "tighten the stop to {level}",
  "rules.editor.action.phrase.breakeven":
    "move the stop to break-even (your average entry) plus {n} ticks",
  "rules.editor.action.phrase.scale_out": "scale out {amount} at {order type}",
  "rules.editor.action.phrase.flatten": "flatten every position",
  "rules.editor.action.phrase.halt": "halt new orders on this {scope} until the next UTC day",
  "rules.editor.action.phrase.notify": "notify me ({channel}, {severity})",
  "rules.editor.action.phrase.tag": "tag the journal {tag}",
  "rules.editor.limit.once": "Once.",
  "rules.editor.limit.once_position": "Once per position.",
  "rules.editor.limit.once_day": "Once per day.",
  "rules.editor.limit.once_group": "Once per group.",
  "rules.editor.limit.once_lifetime": "Once in this rule's lifetime.",
  "rules.editor.limit.cooldown": "At most every {d}.",
  "rules.editor.limit.per_hour": "Up to {n} times an hour.",
  "rules.editor.limit.per_day": "Up to {n} times a day.",
  "rules.editor.limit.per_fire": "Only the first {n} actions run per firing.",
  "rules.editor.limit.notional_fire": "At most {x} USDT per firing.",
  "rules.editor.limit.notional_day": "At most {x} USDT a day.",
  "rules.editor.limit.timeout": "Each check may take up to {n} ms.",
  "rules.editor.limit.confirm": "Asks before acting (skipped if unanswered in 60 s).",
  "rules.editor.limit.kill_switch": "Turns itself off after {n} errors in a row — you re-arm it.",
} as const;

/** E36-D05's operator verbs (`rules.editor.verb.<op>`): the one client table the design keys by operator id. */
export const VERBS: Readonly<Record<string, string>> = {
  gt: "is above",
  gte: "is at least",
  lt: "is below",
  lte: "is at most",
  eq: "is",
  neq: "is not",
  between: "is between {a} and {b}",
  outside: "is outside {a} to {b}",
  crosses_above: "crosses above",
  crosses_below: "crosses below",
  changed: "changes",
  in_set: "is one of {a}, {b}",
  not_in_set: "is none of {a}, {b}",
  sustained: "{comparison} for at least {w}",
};

/**
 * E36-D01 §5.6's "When …" clause per trigger id (`docs/design/research/e36-rules-in-words.md`; no deck keys them,
 * gap G9): the one client table the design keys by trigger id. A slot is named by the trigger's required field.
 */
export const TRIGGER_CLAUSES: Readonly<Record<string, string>> = {
  on_price_update: "When a trade prints",
  on_bar_close: "When a {timeframe} bar closes",
  on_order_fill: "When an order fills",
  on_position_open: "When a position opens",
  on_position_close: "When a position closes",
  on_position_update: "When a position changes",
  on_timer: "Every {interval_ms}",
  on_metric_change: "When the {metric} changes",
  on_signal: "When rule {name} signals {signal_name}",
  on_schedule: "On schedule {cron} (UTC)",
  pre_trade_check: "Before any order is sent",
  on_book_update: "When the book updates",
  on_liquidation: "When a liquidation prints",
};

/** E37-D05 §8.1 and §9: the node, stop and inspector rows S02 renders. FZ-6, FZ-7, FZ-8 and FZ-13 are frozen. */
export const D05_COPY = {
  "rules.graph.type.trigger": "Trigger",
  "rules.graph.type.condition": "Condition",
  "rules.graph.type.action": "Action",
  "rules.graph.type.logic_gate": "Logic gate",
  "rules.graph.type.comment": "Comment",
  "rules.graph.aria.node": "{Type} node: {sentence fragment}",
  "rules.graph.node.gate_all_of": "all of",
  "rules.graph.node.gate_any_of": "any of",
  "rules.graph.node.gate_none_of": "none of",
  "rules.graph.node.gate_n_of": "at least {n} of",
  "rules.graph.node.add_input": "+ input",
  "rules.graph.node.only_tighten": "only tighten",
  "rules.graph.node.stop_exchange": "Stop: the position's native stop, held by Bybit (exchange).",
  "rules.graph.node.stop_server": "Stop: attached by the server (native SL).",
  "rules.graph.badge.graph_only": "graph-only",
  "rules.graph.inspector.position": "Position",
  "rules.graph.inspector.nudge_left": "Nudge node left",
  "rules.graph.inspector.nudge_up": "Nudge node up",
  "rules.graph.inspector.nudge_down": "Nudge node down",
  "rules.graph.inspector.nudge_right": "Nudge node right",
} as const;

/** PROPOSED, in no deck yet (the #950 addendum): E37-S02's BQ-8 and BQ-9 defaults. */
export const PROPOSED_COPY = {
  /** BQ-8: a second trigger is refused where it was tried (at most 80 characters, the reason cap). */
  "rules.graph.refusal.second_trigger": "This rule already has a trigger: {name}.",
  /** BQ-9: an action node's one scope line, the vocabulary's `targets` sentence for its value, verbatim. */
  "rules.graph.node.targets": "{targets}",
} as const;

export type CopyKey = keyof typeof E36_COPY | keyof typeof D05_COPY | keyof typeof PROPOSED_COPY;

const ALL: Readonly<Record<CopyKey, string>> = { ...E36_COPY, ...D05_COPY, ...PROPOSED_COPY };

/** The text of `key` with each `{slot}` replaced by its value; a slot with no value is left as written. */
export function fill(template: string, slots: Readonly<Record<string, string>> = {}): string {
  return template.replace(/\{([^{}]+)\}/g, (whole, name: string) =>
    Object.hasOwn(slots, name) ? (slots[name] as string) : whole,
  );
}

/** A deck key's text, its slots filled. */
export const text = (key: CopyKey, slots?: Readonly<Record<string, string>>): string =>
  fill(ALL[key], slots);

/** An operator's verb, or its id when no verb is keyed for it (a new operator still reads). */
export const verbOf = (operator: string): string =>
  Object.hasOwn(VERBS, operator) ? (VERBS[operator] as string) : operator;

/** A trigger's clause, or its id when no clause is written for it (a new trigger still reads). */
export const clauseOf = (trigger: string): string =>
  Object.hasOwn(TRIGGER_CLAUSES, trigger) ? (TRIGGER_CLAUSES[trigger] as string) : trigger;
