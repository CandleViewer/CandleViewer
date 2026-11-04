/**
 * The node fragments and the rule sentence (E37-S02): the words a node's card and its accessible name carry
 * (`rules.graph.aria.node`, "{Type} node: {sentence fragment}"), and the rule's one sentence that describes the
 * canvas, in E36-D01's grammar by reference (`docs/design/research/e36-rules-in-words.md` R1, G1–G13 and §5.6),
 * each string under its deck key where a deck keys it and the memo's own words where none does. Names are the
 * served `display_name`s, an id only where none is served (P1); an estimated metric carries "(estimated)" after
 * its name wherever it shows (G8). Feature-local until E36-T01's `summarise` replaces it. Pure: no React, no DOM.
 */
import type { GraphNode, RuleIr } from "@candleviewer/rule-graph";
import { placesOrders, stopLineOf, targetsSentence, type ActionTargets } from "./actions.js";
import { clauseOf, fill, text, verbOf, type CopyKey } from "./copy.js";
import type { RuleVocabulary, VocabularyAction, VocabularySignal } from "./types.js";

/** What the words read besides the rule: the served vocabulary, and the accounts' names (never their ids). */
export interface SentenceContext {
  readonly vocabulary: RuleVocabulary;
  /** An account's name as `GET /rules/accounts` lists it; an account it cannot name is counted, never shown. */
  readonly accountName?: (id: string) => string | undefined;
}

/** The parts of a rule IR the sentence reads: G1's clauses. */
export type SentenceRule = Pick<RuleIr, "scope" | "trigger" | "conditions" | "actions"> & {
  readonly limits?: RuleIr["limits"];
};

/** E36-D01's phrases no deck keys (§5.4, §5.6; the memo's words and slots, verbatim). */
export const MEMO = {
  debounce: "(at most once every {d})",
  debounceSecond: "(at most once a second)",
  appliesOpen: "for open positions",
  appliesPending: "for pending orders",
  appliesAccount: "for the account",
  algoChildren: "including algo child orders",
  either: "either {A} or {B}",
  levelEntry: "{n} ticks past entry in your favour",
  levelPrice: "{n} ticks from the price",
  levelAtr: "{v} × ATR(14) from the close",
  levelStructure: "{n} ticks beyond the last swing",
  takeProfit: "move the take-profit to {level}",
  cancel: "cancel the working {purpose} order",
  cancelAll: "cancel every working {purpose} order",
  scaleIn: "add {amount} to the position, within the profile's caps",
  flatten: "flatten the {symbols} position",
  reverse: "reverse the position — flatten, then open the other side with a native stop",
  leverageTo: "reduce leverage to {target}×",
  leverageBy: "reduce leverage by {by}×",
  halt: "halt new orders on this {scope}",
  haltManual: "until you resume them",
  haltFor: "for {d}",
  resume: "resume new orders on this {scope} (needs the live-arming permission)",
  chase: "arm the chase limit",
  iceberg: "start an iceberg slice",
  twap: "start a TWAP",
  remember: "remember {name} = {value}",
  rememberFor: "for {ttl}",
  signal: "signal {signal_name} to other rules",
  dryRun: "— simulated, never sent",
  readings: "on at least {n} readings",
  continues: "If an action fails, the rest still run.",
  retries: "A failed action is retried once, then the rest are skipped.",
} as const;

/**
 * E36-D01's phrases with no words written for them, PROPOSED (the #950 addendum): `place_order` (§5.6's instance
 * has the stop's level, which the opaque stop object does not give), the arithmetic beyond R3's "minus" card, a
 * phrase-less action that places orders (with its stop, C-2.6), environments beyond demo, and per-action `on_error`.
 */
export const PROPOSED_WORDS = {
  order: "{side} {size} at {price} with a native stop",
  profileSize: "the profile's size",
  add: "plus",
  sub: "minus",
  mul: "times",
  div: "divided by",
  min: "the lower of",
  max: "the higher of",
  abs: "the size of {A}",
  neg: "minus {A}",
  pct_of: "{A} as a percent of {B}",
  placing: "{name} ({places}, with a native stop)",
  environments: "on {environments}",
  live: "LIVE",
  continuesEach: "If action {n} fails, the rest still run.",
  retriesEach: "If action {n} fails, it is retried once, then the rest are skipped.",
} as const;

/** `22` `RuleLimits`' defaults, said only where a limit differs (G6, P8); the test pins them to `RULE_IR_SCHEMA`. */
const DEFAULTS = { cooldown: 1000, hour: 60, day: 500, timeout: 250, errors: 5 } as const;

/** G11's words after a constant, by the vocabulary's unit (ms reads as a duration). */
const UNIT_WORDS: Readonly<Record<string, string>> = {
  bps: "bps",
  pct: "%",
  zscore: "sigma",
  notional: "USDT",
};

/** The word for a value not set yet: an operand that is a connected node, or a field left empty. */
const UNSET = "…";

type Tree = Readonly<Record<string, unknown>>;
const isTree = (value: unknown): value is Tree =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const treeOf = (value: unknown): Tree => (isTree(value) ? value : {});
const listOf = (value: unknown): readonly unknown[] => (Array.isArray(value) ? value : []);
const wordOf = (value: unknown): string | undefined =>
  typeof value === "string" && value !== "" ? value : undefined;

const NUMBER = new Intl.NumberFormat("en-US", { maximumFractionDigits: 10 });

/** A value as said: numbers grouped ("63,900"), text as written, nothing set as "…". */
const say = (value: unknown): string =>
  typeof value === "number"
    ? NUMBER.format(value)
    : typeof value === "string" || typeof value === "boolean"
      ? String(value)
      : UNSET;

/** A Decimal as `22` serves one (`Notional`, a non-integer constant): a string of digits. */
const DECIMAL = /^-?\d+(?:\.\d+)?$/;

/** A number's value as said: grouped as `say` groups a number, a Decimal string too, its digits as served. */
const amount = (value: unknown): string =>
  typeof value === "string" && DECIMAL.test(value)
    ? value.replace(
        /^(-?)(\d+)/,
        (_, sign: string, whole: string) => sign + NUMBER.format(BigInt(whole)),
      )
    : say(value);

/** G11: milliseconds as s or min ("60 s", "5 min"), below a second as ms. */
const duration = (ms: number): string =>
  ms >= 120_000 && ms % 60_000 === 0
    ? `${ms / 60_000} min`
    : ms >= 1000
      ? `${NUMBER.format(ms / 1000)} s`
      : `${ms} ms`;

/** "A", "A and B", "A, B and C". */
const and = (parts: readonly string[]): string =>
  parts.length <= 1
    ? (parts[0] ?? UNSET)
    : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1] as string}`;

/** One or two by name, three or more as a count (§5.6 `RuleScope.symbols`: "on BTCUSDT, ETHUSDT", "on 4 symbols"). */
const named = (names: readonly string[], many: string): string =>
  names.length <= 2 ? names.join(", ") : `${names.length} ${many}`;

/** A `{slot}` left unfilled (one to test for; every one to replace). */
const SLOT = /\{[^{}]+\}/;
const SLOTS = /\{[^{}]+\}/g;

/** E37-D05's gate words, by the IR's `BooleanNode.op`. */
const GATES: Readonly<Record<string, CopyKey>> = {
  all_of: "rules.graph.node.gate_all_of",
  any_of: "rules.graph.node.gate_any_of",
  none_of: "rules.graph.node.gate_none_of",
  n_of: "rules.graph.node.gate_n_of",
};

/** A one-input gate reads as its input only where the evaluator does: `all_of`, `any_of`, an `n_of` needing one. */
const passesThrough = (op: string | undefined, n: unknown): boolean =>
  op === "all_of" || op === "any_of" || (op === "n_of" && typeof n === "number" && n <= 1);

const firstLower = (words: string): string => words.charAt(0).toLowerCase() + words.slice(1);

/** The served signals and actions by id, built once per vocabulary: fragments are read per node. */
interface Lookup {
  readonly signals: ReadonlyMap<string, VocabularySignal>;
  readonly actions: ReadonlyMap<string, VocabularyAction>;
}
const LOOKUPS = new WeakMap<RuleVocabulary, Lookup>();
const lookupOf = (vocabulary: RuleVocabulary): Lookup => {
  const lookup = LOOKUPS.get(vocabulary) ?? {
    signals: new Map(vocabulary.signals.map((s) => [s.id, s])),
    actions: new Map(vocabulary.actions.map((a) => [a.id, a])),
  };
  LOOKUPS.set(vocabulary, lookup);
  return lookup;
};

/** The words of one rule, or of one node: it notes whether an estimated metric was named (G8). */
class Words {
  estimated = false;
  private readonly signals: ReadonlyMap<string, VocabularySignal>;
  private readonly actions: ReadonlyMap<string, VocabularyAction>;

  constructor(
    private readonly context: SentenceContext,
    private readonly scopeSymbols: readonly string[] = [],
  ) {
    const lookup = lookupOf(context.vocabulary);
    this.signals = lookup.signals;
    this.actions = lookup.actions;
  }

  /**
   * G3 and G8: the display name with its parameters, "(estimated)", an override, and why it is unavailable in
   * the row's words (P9; E36-D05 `rules.editor.row.unavailable`).
   */
  metric(ref: Tree): string {
    const id = wordOf(ref["metric"]) ?? UNSET;
    const signal = this.signals.get(id);
    const params = Object.values(treeOf(ref["params"])).map(say);
    let name = (signal?.display_name ?? id) + (params.length > 0 ? `(${params.join(", ")})` : "");
    if (signal?.estimated === true) {
      name += ` ${text("rules.editor.row.estimated")}`;
      this.estimated = true;
    }
    const timeframe = wordOf(ref["timeframe"]);
    if (timeframe !== undefined) name += ` on the ${timeframe}`;
    const symbol = wordOf(ref["symbol"]);
    const own = this.scopeSymbols.length === 1 && this.scopeSymbols[0] === symbol;
    if (symbol !== undefined && !own) name += ` on ${symbol}`;
    if (signal !== undefined && !signal.available) {
      name += ` ${text("rules.editor.row.unavailable", { reason: signal.unavailable_reason ?? UNSET })}`;
    }
    return name;
  }

  private unitOf(operand: unknown): string | undefined {
    const id = wordOf(treeOf(operand)["metric"]);
    return id === undefined ? undefined : (this.signals.get(id)?.unit ?? undefined);
  }

  /** A comparison's operand: a metric, a constant in the metric's unit, an arithmetic node, or "…". */
  operand(value: unknown, unit: string | undefined): string {
    const tree = treeOf(value);
    if (Object.hasOwn(tree, "metric")) return this.metric(tree);
    if (Object.hasOwn(tree, "operands")) return this.arithmetic(tree);
    if (!Object.hasOwn(tree, "const")) return UNSET;
    const constant = tree["const"];
    const ms = typeof constant === "string" && DECIMAL.test(constant) ? Number(constant) : constant;
    if (unit === "ms" && typeof ms === "number") return duration(ms);
    const word =
      unit !== undefined && Object.hasOwn(UNIT_WORDS, unit) ? UNIT_WORDS[unit] : undefined;
    return word === undefined ? amount(constant) : `${amount(constant)} ${word}`;
  }

  /** G2's reason holds here too: an operand that is itself arithmetic is bracketed, "(Price plus 2) times 3". */
  arithmetic(node: Tree): string {
    const op = wordOf(node["op"]) ?? UNSET;
    const parts = listOf(node["operands"]).map((o) => {
      const said = this.operand(o, undefined);
      return Object.hasOwn(treeOf(o), "operands") ? `(${said})` : said;
    });
    const [a = UNSET, b = UNSET] = parts;
    if (op === "add" || op === "sub" || op === "mul" || op === "div") {
      return parts.join(` ${PROPOSED_WORDS[op]} `);
    }
    if (op === "min" || op === "max") return `${PROPOSED_WORDS[op]} ${and(parts)}`;
    if (op === "abs" || op === "neg" || op === "pct_of")
      return fill(PROPOSED_WORDS[op], { A: a, B: b });
    return `${op} ${and(parts)}`;
  }

  /** G4: the metric, the operator's verb, the value; `is_true` the predicate itself, `is_false` its negation. */
  comparison(node: Tree): string {
    const op = wordOf(node["op"]) ?? UNSET;
    const unit = this.unitOf(node["left"]) ?? this.unitOf(node["right"]);
    const left = this.operand(node["left"], unit);
    const right = this.operand(node["right"], unit);
    const tolerance = node["tolerance"];
    const within =
      tolerance === undefined || tolerance === null ? "" : ` (within ${amount(tolerance)})`;
    if (op === "is_true") return left;
    if (op === "is_false") return `not ${left}`;
    if (op === "in_set" || op === "not_in_set") {
      const set = listOf(node["set_values"]).map(say).join(", ") || UNSET;
      return `${left} ${fill(verbOf(op).replace("{a}, {b}", "{set}"), { set })}`;
    }
    if (op === "between" || op === "outside") {
      return `${left} ${fill(verbOf(op), { a: right, b: this.operand(node["right2"], unit) })}`;
    }
    return `${left} ${verbOf(op)}${op === "changed" ? "" : ` ${right}`}${within}`;
  }

  temporal(node: Tree): string {
    const op = wordOf(node["op"]);
    const window = node["window_ms"];
    const w = typeof window === "number" ? duration(window) : UNSET;
    const child = isTree(node["child"]) ? this.condition(node["child"], "temporal") : UNSET;
    const count = typeof node["min_count"] === "number" ? node["min_count"] : 1;
    if (op === "occurred_within") return text("rules.editor.card.within", { A: child, w });
    if (op === "count_within")
      return text("rules.editor.card.count", { A: child, n: say(count), w });
    if (op === "stable_for") return text("rules.editor.card.stable", { A: child, w });
    const sustained = fill(verbOf("sustained"), { comparison: child, w });
    return count > 1 ? `${sustained} ${fill(MEMO.readings, { n: say(count) })}` : sustained;
  }

  /** A logic gate's words (E37-D05 `rules.graph.node.gate_*`): "all of", …, "at least {n} of". */
  gate(node: Tree): string {
    const op = wordOf(node["op"]) ?? UNSET;
    const key = Object.hasOwn(GATES, op) ? GATES[op] : undefined;
    return key === undefined ? op : text(key, { n: say(node["n"]) });
  }

  /**
   * G2: "and", "either A or B", "any of: A, B, C", and the graph-only "none of: …" and "at least n of: …"
   * (E36-D05 `rules.editor.card.*`). A nested group is bracketed, "either (A and B) or C", except an
   * "either … or …" closing an "and" list: "A and either B or C". A gate with one input that passes it through
   * reads as that input in the gate's place; any other keeps its words ("none of: A" negates A).
   */
  group(node: Tree, parent: string | undefined, last: boolean): string {
    const op = wordOf(node["op"]);
    const kids = listOf(node["children"]);
    if (kids.length === 1 && passesThrough(op, node["n"])) {
      return this.condition(kids[0], parent, last);
    }
    const parts = kids.map((kid, i) => this.condition(kid, op, i === kids.length - 1));
    if (parts.length === 0) return UNSET;
    const either = op === "any_of" && parts.length === 2;
    const said =
      op === "all_of"
        ? parts.join(" and ")
        : either
          ? fill(MEMO.either, { A: parts[0] as string, B: parts[1] as string })
          : `${this.gate(node)}: ${parts.join(", ")}`;
    const open = parent === undefined || (either && parent === "all_of" && last);
    return open ? said : `(${said})`;
  }

  condition(node: unknown, parent?: string, last = false): string {
    const tree = treeOf(node);
    const kind = wordOf(tree["kind"]);
    if (Object.hasOwn(tree, "children")) return this.group(tree, parent, last);
    if (kind === "temporal" || Object.hasOwn(tree, "child")) return this.temporal(tree);
    if (kind === "arithmetic" || Object.hasOwn(tree, "operands")) return this.arithmetic(tree);
    return Object.keys(tree).length === 0 ? UNSET : this.comparison(tree);
  }

  /** The trigger's parameter in its unit (§5.6 `Trigger.timeframe`, `interval_ms`, `cron`, `metric`). */
  private triggerSlots(trigger: Tree): Record<string, string> {
    const slots: Record<string, string> = {};
    const timeframe = wordOf(trigger["timeframe"]);
    if (timeframe !== undefined) slots["timeframe"] = timeframe;
    const interval = trigger["interval_ms"];
    if (typeof interval === "number") slots["interval_ms"] = duration(interval);
    const cron = wordOf(trigger["cron"]);
    if (cron !== undefined) slots["cron"] = cron;
    const metric = wordOf(trigger["metric"]);
    if (metric !== undefined) slots["metric"] = this.metric({ metric });
    return slots;
  }

  /**
   * The "When …" clause (§5.6 `Trigger.type`), its slots filled; a trigger the memo has no clause for, or whose
   * slot has no value, reads by its served description, then its id. "(at most once every {d})" when debounced.
   */
  trigger(trigger: Tree): string {
    const id = wordOf(trigger["type"]) ?? UNSET;
    const filled = fill(clauseOf(id), this.triggerSlots(trigger));
    const served = this.context.vocabulary.triggers?.find((t) => t.id === id)?.description;
    const clause =
      filled === id || SLOT.test(filled) ? (served ?? filled.replace(SLOTS, UNSET)) : filled;
    const debounce = trigger["debounce_ms"];
    if (typeof debounce !== "number" || debounce <= 0) return clause;
    const d =
      debounce === 1000 ? MEMO.debounceSecond : fill(MEMO.debounce, { d: duration(debounce) });
    return `${clause} ${d}`;
  }

  /** The trigger node's fragment, in `15`'s CMP-147 name ("Trigger node: on bar close, 5m"). */
  triggerFragment(trigger: Tree): string {
    const words = (wordOf(trigger["type"]) ?? UNSET).replaceAll("_", " ");
    const slots = this.triggerSlots(trigger);
    const param = slots["timeframe"] ?? slots["interval_ms"] ?? slots["metric"];
    const cron = slots["cron"];
    const said = param ?? (cron === undefined ? undefined : `${cron} (UTC)`);
    return said === undefined ? words : `${words}, ${said}`;
  }

  private level(params: Tree): string {
    const value = amount(params["value"]);
    const mode = wordOf(params["mode"]);
    if (mode === "absolute") return value;
    const template =
      mode === "offset_from_entry"
        ? MEMO.levelEntry
        : mode === "offset_from_price"
          ? MEMO.levelPrice
          : mode === "atr"
            ? MEMO.levelAtr
            : mode === "structure"
              ? MEMO.levelStructure
              : undefined;
    return template === undefined ? UNSET : fill(template, { n: value, v: value });
  }

  /** §5.6's phrase of one action, with its parameters; an action it has none for reads by its served name. */
  private phrase(type: string, p: Tree, served: VocabularyAction | undefined): string {
    const amountOf = p["qty_pct"] !== undefined ? `${amount(p["qty_pct"])} %` : amount(p["qty"]);
    const purpose = wordOf(p["purpose"]);
    const scope = say(p["scope"]);
    switch (type) {
      case "place_order":
        return fill(PROPOSED_WORDS.order, {
          side: say(p["side"]),
          size: p["qty_mode"] === "profile" ? PROPOSED_WORDS.profileSize : amount(p["qty"]),
          price: p["order_type"] === "limit" ? amount(p["price"]) : say(p["order_type"]),
        });
      case "modify_stop_loss":
      case "tighten_stop":
        return text("rules.editor.action.phrase.tighten", { level: this.level(p) });
      case "modify_take_profit":
        return fill(MEMO.takeProfit, { level: this.level(p) });
      case "move_to_breakeven": {
        const ticks =
          p["offset_ticks"] ??
          treeOf(treeOf(served?.params_schema?.["properties"])["offset_ticks"])["default"];
        return text("rules.editor.action.phrase.breakeven", { n: amount(ticks) });
      }
      case "scale_out":
        return text("rules.editor.action.phrase.scale_out", {
          amount: amountOf,
          "order type": say(p["order_type"]),
        });
      case "scale_in":
        return fill(MEMO.scaleIn, { amount: amountOf });
      case "cancel_order":
      case "cancel_all_orders": {
        const template = type === "cancel_order" ? MEMO.cancel : MEMO.cancelAll;
        return purpose === undefined
          ? template.replace(" {purpose}", "")
          : fill(template, { purpose });
      }
      case "flatten_position": {
        const symbols = listOf(p["symbols"]).map(say);
        return symbols.length === 0
          ? MEMO.flatten.replace(" {symbols}", "")
          : fill(MEMO.flatten, { symbols: and(symbols) });
      }
      case "flatten_all_positions":
        return text("rules.editor.action.phrase.flatten");
      case "reverse_position":
        return MEMO.reverse;
      case "reduce_leverage":
        return p["target"] !== undefined
          ? fill(MEMO.leverageTo, { target: amount(p["target"]) })
          : fill(MEMO.leverageBy, { by: amount(p["by"]) });
      case "halt_new_orders": {
        const halt = fill(MEMO.halt, { scope });
        // `duration_ms` has no field for its length yet (G6): "for …" until it has.
        return p["until"] === "next_utc_day"
          ? text("rules.editor.action.phrase.halt", { scope })
          : p["until"] === "manual"
            ? `${halt} ${MEMO.haltManual}`
            : p["until"] === "duration_ms"
              ? `${halt} ${fill(MEMO.haltFor, { d: UNSET })}`
              : halt;
      }
      case "resume_new_orders":
        return fill(MEMO.resume, { scope });
      case "arm_chase_limit":
        return MEMO.chase;
      case "start_iceberg_slice":
        return MEMO.iceberg;
      case "start_twap":
        return MEMO.twap;
      case "send_notification":
        return text("rules.editor.action.phrase.notify", {
          channel: say(p["channel"]),
          severity: say(p["severity"]),
        });
      case "log_journal_tag":
        return text("rules.editor.action.phrase.tag", { tag: say(p["tag"]) });
      case "set_variable": {
        const remember = fill(MEMO.remember, { name: say(p["name"]), value: say(p["value"]) });
        const ttl = p["ttl_ms"];
        return typeof ttl === "number"
          ? `${remember} ${fill(MEMO.rememberFor, { ttl: duration(ttl) })}`
          : remember;
      }
      case "emit_signal":
        return fill(MEMO.signal, { signal_name: say(p["signal_name"]) });
      default: {
        // A phrase-less action that can place orders (an absent flag counts, `22`) says so, with its native stop.
        const name = firstLower(served?.display_name ?? type);
        const places = text("rules.editor.action.places_orders");
        return served !== undefined && placesOrders(served)
          ? fill(PROPOSED_WORDS.placing, { name, places })
          : name;
      }
    }
  }

  /** An action's clause: its phrase, then a `targets` other than the rule scope (G9), then a dry run. */
  action(node: Tree): string {
    const type = wordOf(node["type"]) ?? UNSET;
    const served = this.actions.get(type);
    let said = this.phrase(type, treeOf(node["params"]), served);
    const targets = wordOf(node["targets"]);
    const sentence =
      served === undefined || targets === undefined || targets === "scope_accounts"
        ? undefined
        : targetsSentence(served, targets as ActionTargets);
    if (sentence !== undefined) said += ` on ${sentence}`;
    if (node["dry_run_only"] === true) said += ` ${MEMO.dryRun}`;
    return said;
  }

  /** G7's frozen safety line: a stop moves and none holds `only_tighten` other than `true` (#4137: no other words). */
  onlyTightens(actions: readonly unknown[]): boolean {
    const stops = actions.map(treeOf).filter((node) => {
      const served = this.actions.get(wordOf(node["type"]) ?? "");
      return served !== undefined && stopLineOf(served).ratchet !== undefined;
    });
    const tightens = (params: Tree): boolean =>
      !Object.hasOwn(params, "only_tighten") || params["only_tighten"] === true;
    return stops.length > 0 && stops.every((node) => tightens(treeOf(node["params"])));
  }
}

/** §5.6 `RuleScope.environments`: unsaid at the default, demo alone; LIVE as the memo writes it; empty is unset. */
function environmentsOf(value: unknown): string | undefined {
  const said = value === undefined ? ["demo"] : [...new Set(listOf(value).map(say))];
  if (said.length === 1 && said[0] === "demo") return undefined;
  const words = and(said.map((e) => (e === "live" ? PROPOSED_WORDS.live : e)));
  return fill(PROPOSED_WORDS.environments, { environments: words });
}

/** §5.6 `RuleScope`: it opens the sentence, `applies_to`, the algo children and the environments after it. */
function scopeClause(scope: Tree, context: SentenceContext): string {
  const symbols = listOf(scope["symbols"]).map(say);
  const ids = listOf(scope["account_ids"]).filter((id): id is string => typeof id === "string");
  const names = ids.map((id) => context.accountName?.(id));
  const known = names.every((name): name is string => name !== undefined);
  const accounts =
    ids.length === 0
      ? undefined
      : known && ids.length <= 2
        ? names.join(", ")
        : `${ids.length} ${ids.length === 1 ? "account" : "accounts"}`;
  const symbolWords = symbols.length === 0 ? "every symbol" : named(symbols, "symbols");
  const tail = accounts === undefined ? "" : ` (${accounts})`;
  const level = scope["level"];
  const opens =
    level === "global"
      ? "on every account"
      : level === "account"
        ? `on ${accounts ?? "every account"}, ${symbolWords}`
        : level === "position"
          ? `on this ${symbols.length === 0 ? "" : `${symbolWords} `}position${tail}`
          : `on ${symbolWords}${tail}`;
  const applies =
    scope["applies_to"] === "open_positions"
      ? MEMO.appliesOpen
      : scope["applies_to"] === "pending_orders"
        ? MEMO.appliesPending
        : scope["applies_to"] === "account"
          ? MEMO.appliesAccount
          : undefined;
  const algo = scope["exclude_algo_children"] === false ? `, ${MEMO.algoChildren}` : "";
  const environments = environmentsOf(scope["environments"]);
  const runs = environments === undefined ? "" : `, ${environments}`;
  return `${opens}${applies === undefined ? "" : ` ${applies}`}${algo}${runs}`;
}

/** §5.6 `Action.on_error` beyond the default: the memo's sentence when every action holds it, else per action. */
const ON_ERROR: Readonly<Record<string, readonly [every: string, each: string]>> = {
  continue: [MEMO.continues, PROPOSED_WORDS.continuesEach],
  retry_once: [MEMO.retries, PROPOSED_WORDS.retriesEach],
};

function onErrorSentences(actions: readonly unknown[]): string[] {
  const values = actions.map((action) => wordOf(treeOf(action)["on_error"]) ?? "");
  const words = values.map((value) =>
    Object.hasOwn(ON_ERROR, value) ? ON_ERROR[value] : undefined,
  );
  const [first] = words;
  if (first !== undefined && values.every((value) => value === values[0])) return [first[0]];
  return words.flatMap((pair, i) => (pair === undefined ? [] : [fill(pair[1], { n: `${i + 1}` })]));
}

/** G6: the limits that differ from the defaults, each a short sentence, in the memo's order. */
function limitSentences(limits: Tree, actionCount: number): string[] {
  const said: string[] = [];
  const add = (key: CopyKey, slots?: Readonly<Record<string, string>>): void => {
    said.push(text(key, slots));
  };
  const number = (key: string): number | undefined =>
    typeof limits[key] === "number" ? (limits[key] as number) : undefined;
  if (limits["once"] === true) add("rules.editor.limit.once");
  const per = limits["once_per"];
  if (per === "position") add("rules.editor.limit.once_position");
  if (per === "day") add("rules.editor.limit.once_day");
  if (per === "group") add("rules.editor.limit.once_group");
  if (per === "rule_lifetime") add("rules.editor.limit.once_lifetime");
  const cooldown = number("cooldown_ms");
  if (cooldown !== undefined && cooldown !== DEFAULTS.cooldown) {
    add("rules.editor.limit.cooldown", { d: duration(cooldown) });
  }
  const hour = number("max_fires_per_hour");
  if (hour !== undefined && hour !== DEFAULTS.hour)
    add("rules.editor.limit.per_hour", { n: say(hour) });
  const day = number("max_fires_per_day");
  if (day !== undefined && day !== DEFAULTS.day) add("rules.editor.limit.per_day", { n: say(day) });
  const perFire = number("max_actions_per_fire");
  if (perFire !== undefined && perFire < actionCount) {
    add("rules.editor.limit.per_fire", { n: say(perFire) });
  }
  const fire = limits["max_notional_per_fire"];
  if (fire !== undefined && fire !== null)
    add("rules.editor.limit.notional_fire", { x: amount(fire) });
  const daily = limits["max_daily_notional"];
  if (daily !== undefined && daily !== null)
    add("rules.editor.limit.notional_day", { x: amount(daily) });
  if (limits["require_confirmation"] === true) add("rules.editor.limit.confirm");
  const timeout = number("evaluation_timeout_ms");
  if (timeout !== undefined && timeout !== DEFAULTS.timeout) {
    add("rules.editor.limit.timeout", { n: say(timeout) });
  }
  const errors = number("kill_switch_on_error_count");
  if (errors !== undefined && errors !== DEFAULTS.errors) {
    add("rules.editor.limit.kill_switch", { n: say(errors) });
  }
  return said;
}

/**
 * The rule's sentence (R1): "{trigger} on {scope}, if {conditions}: {actions}." then an `on_error` other than the
 * default, the limits that differ, "Uses an estimated detector — behaviour is heuristic." when a metric it names is
 * estimated (G8), and the safety line last when an action moves a stop and none may loosen it (G7): "The stop only
 * ever tightens."
 */
export function ruleSentence(rule: SentenceRule, context: SentenceContext): string {
  const scope = treeOf(rule.scope);
  const symbols = listOf(scope["symbols"]).filter((s): s is string => typeof s === "string");
  const words = new Words(context, symbols);
  const actions = listOf(rule.actions);
  const trigger = words.trigger(treeOf(rule.trigger));
  const conditions = words.condition(rule.conditions);
  const done = and(actions.map((action) => words.action(treeOf(action))));
  return [
    `${trigger} ${scopeClause(scope, context)}, if ${conditions}: ${done}.`,
    ...onErrorSentences(actions),
    ...limitSentences(treeOf(rule.limits), actions.length),
    ...(words.estimated ? [text("rules.editor.summary.estimated")] : []),
    ...(words.onlyTightens(actions) ? [text("rules.editor.stop.tightens")] : []),
  ].join(" ");
}

/**
 * A node's sentence fragment, the words its card body and its name carry: the trigger in `15`'s CMP-147 form,
 * a condition or an action as the rule sentence says it ("…" for an input connected to another node), a gate's
 * words, a comment's text. Ids only where the vocabulary serves no name (P1).
 */
export function fragmentOf(node: GraphNode, context: SentenceContext): string {
  const words = new Words(context);
  switch (node.type) {
    case "trigger":
      return words.triggerFragment(node.data);
    case "condition":
      return words.condition(node.data);
    case "logicGate":
      return words.gate(node.data);
    case "action":
      return words.action(node.data);
    case "comment":
      return wordOf(node.data["text"]) ?? UNSET;
  }
}
