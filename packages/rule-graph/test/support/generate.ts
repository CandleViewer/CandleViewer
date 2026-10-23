// A seeded port of the server's rule IR generator, services/api/tests/rules/roundtrip/strategies.py
// (E35-Q02): the same grammar and biases, drawn from one mulberry32 stream, so a seed replays its
// documents. A document is what JS sends: a Hypothesis Decimal is the nearest double. The ops and
// list bounds are the published schema's; node ids differ from the server's in spelling only.
import { RULE_IR_SCHEMA, type RuleIr } from "@candleviewer/protocol/rule-ir";

type Doc = Record<string, unknown>;
type Model = { properties: Record<string, { enum?: string[]; maxItems?: number }> };
const DEFS = RULE_IR_SCHEMA["$defs"] as Record<string, Model>;
const field = (model: string, key: string) =>
  ((model === "Rule" ? RULE_IR_SCHEMA : DEFS[model]) as Model).properties[key] ?? {};
const ops = (model: string, key = "op") => field(model, key).enum as string[];
const MAX_ACTIONS = field("Rule", "actions").maxItems as number;
const MAX_OPERANDS = field("ArithmeticNode", "operands").maxItems as number;
const MAX_CHILDREN = field("BooleanNode", "children").maxItems as number;
const METRICS = "price atr rsi vwap cvd spread_bps position_open market_regime".split(" ");
const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"];
const KEYS = "n anchor source window_ms z mode k".split(" ");
const UNARY = "is_true is_false changed in_set not_in_set".split(" ");
const TARGETS = "scope_accounts originating_account all_accounts".split(" ");
const SETS = ["trend", "range", "long"];
const RULE_ID = "00000000-0000-4000-8000-0000000000aa";

/** The documents of `seed`, in order; `rule(true)` draws one of the form subset. */
export function generator(seed: number): { rule: (formOnly?: boolean) => RuleIr } {
  let state = seed >>> 0;
  const next = (): number => {
    state = (state + 0x6d2b79f5) >>> 0; // mulberry32
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const int = (lo: number, hi: number) => lo + Math.floor(next() * (hi - lo + 1));
  const pick = <T>(items: readonly T[]): T => items[int(0, items.length - 1)] as T;
  const one = (n: number) => int(1, n) === 1; // a 1-in-n chance
  const times = <T>(n: number, draw: () => T): T[] => Array.from({ length: n }, draw);
  const maybe = (n: number, draw: () => Doc): Doc => (one(n) ? draw() : {});
  let ids = 0; // unique per document
  const id = (prefix: string) => `${prefix}${++ids}`;
  const gate = (op: string, children: Doc[]): Doc => ({ node_id: id("g"), op, children });

  // Text a stored rule can hold: no U+0000 and no lone surrogate; ASCII three times in four.
  const skip = (c: number) => (c < 0xd800 ? c : c + 0x800); // past the surrogates
  const char = () => String.fromCodePoint(one(4) ? skip(int(1, 0x10f7ff)) : int(0x20, 0x7e));
  const text = (max: number, min = 0, draw = char) => times(int(min, max), draw).join("");
  const named = (name = text(20, 1)): string => (name.trim() === "" ? named() : name);
  // _decimals (8 places, |x| < 1e12), _scalars, and _floats (1e-30 to 1e30 either sign, or 0).
  const fraction = () => String(int(0, 99_999_999)).padStart(8, "0");
  const decimal = () => Number(`${pick(["", "-"])}${int(0, 999_999_999_999)}.${fraction()}`);
  const word = () => text(6, 0, () => pick([..."abcxyz_ "]));
  const scalar = () => pick([() => one(2), () => int(-1e9, 1e9), decimal, word])();
  const magnitude = () => 10 ** (next() * 60 - 30);
  const float = () => pick([magnitude, () => -magnitude(), () => 0])();
  const params = (): Doc =>
    Object.fromEntries(times(int(0, 3), () => [pick(KEYS), one(2) ? scalar() : float()]));

  const metric = (): Doc => ({
    metric: pick(METRICS),
    params: params(),
    ...maybe(2, () => ({ symbol: pick(SYMBOLS) })),
    ...maybe(4, () => ({ timeframe: pick(["1m", "5m", "1h"]) })),
  });
  const operand = (depth: number, arithmetic: boolean): Doc => {
    const kind = arithmetic && depth < 3 ? int(0, 4) : int(0, 1);
    if (kind < 2) return kind === 0 ? metric() : { const: scalar() };
    const wide = one(10); // now and then on the 8-operand bound, with leaf operands
    const n = wide ? MAX_OPERANDS : int(1, 3);
    const operands = () => times(n, () => operand(wide ? 3 : depth + 1, true));
    return { node_id: id("x"), op: pick(ops("ArithmeticNode")), operands: operands() };
  };
  const comparison = (arithmetic = true): Doc => {
    const op = pick(ops("Comparison"));
    const arity = UNARY.includes(op) ? 1 : op === "between" || op === "outside" ? 3 : 2;
    const out: Doc = { node_id: id("c"), op };
    ["left", "right", "right2"].slice(0, arity).forEach((p) => (out[p] = operand(0, arithmetic)));
    if (op.endsWith("in_set")) out["set_values"] = times(int(1, 3), () => pick(SETS));
    if (one(5)) out["tolerance"] = int(0, 100_000) / 10_000; // 0 to 10, 4 places
    return out;
  };
  /** Any condition; a node drawn before is now and then used again: a shared node. */
  const condition = (pool: Doc[], depth = 0): Doc => {
    if (pool.length > 0 && one(6)) return pick(pool);
    const kind = depth < 3 ? int(0, 9) : 0;
    let node: Doc;
    if (kind <= 3) node = comparison();
    else if (kind <= 6) {
      const op = pick(ops("BooleanNode"));
      const wide = one(10); // now and then on the 32-child bound
      const n = wide ? MAX_CHILDREN : int(1, 3);
      node = gate(
        op,
        times(n, () => (wide ? comparison(false) : condition(pool, depth + 1))),
      );
      if (op === "n_of" || one(7)) node["n"] = int(1, n + 1); // n > len is the validator's
    } else {
      const op = pick(ops("TemporalNode"));
      node = { node_id: id("t"), op, child: condition(pool, depth + 1) };
      Object.assign(node, { window_ms: int(100, 86_400_000), min_count: int(1, 50) });
    }
    pool.push(node);
    return node;
  };
  /** The form subset: all_of of any_of of comparisons or sustained_for(comparison). */
  const formCondition = (): Doc => {
    const leaf = (): Doc => {
      const c = comparison(false);
      const held = () => ({ node_id: id("t"), op: "sustained_for", child: c });
      return one(4) ? { ...held(), window_ms: int(100, 3_600_000) } : c;
    };
    const anyOf = (max: number) => gate("any_of", times(int(1, max), leaf));
    const shape = int(0, 3);
    if (shape < 2) return shape === 0 ? leaf() : anyOf(4);
    const children = times(int(1, 4), () => (one(2) ? anyOf(3) : leaf()));
    return gate("all_of", children);
  };

  const action = (): Doc => ({
    node_id: id("a"),
    type: pick(ops("Action", "type")),
    params: params(),
    ...maybe(2, () => ({ on_error: pick(["abort_remaining", "continue", "retry_once"]) })),
    ...maybe(4, () => ({ targets: pick(TARGETS) })),
    ...maybe(4, () => ({ dry_run_only: true })),
  });
  const NEEDS: Record<string, () => Doc> = {
    on_timer: () => ({ interval_ms: int(100, 1e7) }),
    on_bar_close: () => ({ timeframe: pick(["1m", "15m", "4h"]) }),
    on_schedule: () => ({ cron: pick(["0 0 * * *", "*/5 * * * *"]) }),
    on_metric_change: () => ({ metric: pick(METRICS) }),
  };
  const trigger = (type = pick(ops("Trigger", "type"))): Doc => {
    return { type, ...NEEDS[type]?.(), ...maybe(2, () => ({ debounce_ms: int(0, 60_000) })) };
  };
  const hex = (n: number) => text(n, n, () => int(0, 15).toString(16));
  const env = () => pick(["demo", "testnet", "live"]);
  const scope = (): Doc => ({
    level: pick(["global", "account", "symbol", "position", "trade_group"]),
    ...maybe(2, () => ({ symbols: times(int(0, 3), () => pick(SYMBOLS)) })),
    ...maybe(3, () => ({ account_ids: [`00000000-0000-0000-${hex(4)}-${hex(12)}`] })),
    ...maybe(3, () => ({ environments: [...new Set(times(int(1, 2), env))] })),
    ...maybe(2, () => ({ applies_to: pick(["open_positions", "pending_orders", "any"]) })),
  });
  const limits = (): Doc => {
    const all = { once: one(2), once_per: pick(["position", "day", "group", "rule_lifetime"]) };
    Object.assign(all, { cooldown_ms: int(0, 1e7), max_fires_per_hour: int(1, 1000) });
    Object.assign(all, { max_actions_per_fire: int(1, MAX_ACTIONS), require_confirmation: one(2) });
    const notional = int(100, 1e8) / 100; // 1 to 10**6, 2 places
    Object.assign(all, { max_notional_per_fire: notional, evaluation_timeout_ms: int(10, 5000) });
    return Object.fromEntries(Object.entries(all).filter(() => one(2))); // each key optional
  };
  const place = () => [pick(["c1", "g1", "a1"]), { x: int(0, 2000), y: int(0, 2000) }];
  const layout = (): Doc => ({
    positions: Object.fromEntries(times(int(1, 3), place)),
    ...maybe(2, () => ({ zoom: pick([1, 2, 0.5]) })),
    ...maybe(2, () => ({ note: text(8) })),
  });

  const rule = (formOnly = false): RuleIr => {
    ids = 0;
    const conditions = formOnly ? formCondition() : condition([]);
    const doc: Doc = {
      rule_id: RULE_ID,
      version: int(1, 1000),
      name: named(),
      description: text(30),
      enabled: one(2),
      mode: pick(["disabled", "simulate", "armed"]),
      scope: scope(),
      trigger: trigger(),
      conditions,
      actions: times(pick([1, 2, 3, MAX_ACTIONS]), action),
      limits: limits(),
      editor: pick(["form", "graph"]),
      ...maybe(2, () => ({ graph_layout: layout() })),
    };
    return doc as unknown as RuleIr;
  };
  return { rule };
}
