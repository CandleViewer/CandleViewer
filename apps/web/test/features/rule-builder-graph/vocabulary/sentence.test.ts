import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { RULE_IR_SCHEMA } from "@candleviewer/protocol/rule-ir";
import type { GraphNode } from "@candleviewer/rule-graph";
import { describe, expect, it } from "vitest";
import { fill, text } from "../../../../src/features/rule-builder-graph/model/vocabulary/copy.js";
import {
  MEMO,
  fragmentOf,
  ruleSentence,
  type SentenceContext,
  type SentenceRule,
} from "../../../../src/features/rule-builder-graph/model/vocabulary/sentence.js";
import type {
  RuleVocabulary,
  VocabularyAction,
} from "../../../../src/features/rule-builder-graph/model/vocabulary/types.js";
import { extended, served, type Persona } from "./fixtures.js";

const ROOT = resolve(import.meta.dirname, "../../../../../..");
const E36 = (
  JSON.parse(readFileSync(resolve(ROOT, "docs/design/E36/E36-D05-copy-deck.json"), "utf8")) as {
    strings: Record<string, { text?: string }>;
  }
).strings;
const deck = (key: string): string | undefined => E36[key]?.text;

type Condition = SentenceRule["conditions"];
type Comparison = Extract<Condition, { left: unknown }>;
type Operand = Comparison["left"];
type Action = SentenceRule["actions"][number];
type Actions = SentenceRule["actions"];

const NAMES: Readonly<Record<string, string>> = { "acc-main": "Main", "acc-alt": "Alt" };
const context = (persona: Persona = "manager"): SentenceContext => ({
  vocabulary: served(persona),
  accountName: (id) => NAMES[id],
});
const signalOf = (vocabulary: RuleVocabulary, id: string) =>
  vocabulary.signals.find((s) => s.id === id) ?? expect.unreachable(`${id} is not served`);

const metric = (id: string, more: Partial<Extract<Operand, { metric: string }>> = {}): Operand => ({
  metric: id,
  ...more,
});
const value = (constant: number | string | boolean): Operand => ({ const: constant });
const cmp = (op: Comparison["op"], left: Operand, right?: Operand, more = {}): Comparison => ({
  node_id: "c",
  op,
  left,
  ...(right === undefined ? {} : { right }),
  ...more,
});
const group = (
  op: "all_of" | "any_of" | "none_of" | "n_of",
  children: [Condition, ...Condition[]],
  n?: number,
): Condition => ({ node_id: "g", op, children, ...(n === undefined ? {} : { n }) });
const act = (type: Action["type"], params: Action["params"] = {}, more = {}): Action => ({
  node_id: "a",
  type,
  params,
  ...more,
});

const A = cmp("gt", metric("atr", { params: { n: 14 } }), value(2));
const B = cmp("lt", metric("spread_bps"), value(8));
const C = cmp("is_true", metric("position_open"));
const temporal = (op: string, more = {}): Condition =>
  ({ node_id: "t", op, window_ms: 60_000, child: A, ...more }) as Condition;
const ATR = "ATR(14) is above 2";
const SPREAD = "Spread (bps) is below 8 bps";
const OPEN = "Position open";

const rule = (more: Partial<SentenceRule> = {}): SentenceRule => ({
  scope: { level: "symbol", symbols: ["BTCUSDT"], account_ids: ["acc-main"] },
  trigger: { type: "on_bar_close", timeframe: "1m" },
  conditions: A,
  actions: [act("move_to_breakeven")],
  ...more,
});
const say = (more: Partial<SentenceRule>, persona: Persona = "manager"): string =>
  ruleSentence(rule(more), context(persona));
/** The words between "if" and the actions' colon. */
const ifClause = (conditions: Condition): string =>
  /, if (.*): [^:]*$/.exec(say({ conditions, actions: [act("flatten_all_positions")] }))?.[1] ?? "";
/** The words between the conditions' colon and the first sentence's full stop. */
const actionClause = (action: Action, persona: Persona = "manager"): string =>
  /: ([^:]*?)\.(?: |$)/.exec(say({ actions: [action] }, persona))?.[1] ?? "";
const node = (type: GraphNode["type"], data: GraphNode["data"]): GraphNode => ({
  id: "n",
  type,
  data,
});

describe("the rule sentence (E37-S02; E36-D01 R1, G1–G13, §5.6 by reference)", () => {
  it("Gherkin 'Estimated metrics are badged as text': stop_run_detected carries '(estimated)' after its name in its fragment and in the rule sentence, and the sentence says E36-D05's estimated line after the limits and before its safety line; distance_to_liquidity_cluster carries neither", () => {
    const stopRun = cmp("is_true", metric("stop_run_detected"));
    expect(fragmentOf(node("condition", { kind: "comparison", ...stopRun }), context())).toBe(
      "Stop-run detected (estimated)",
    );
    const sentence = say({
      conditions: stopRun,
      actions: [act("tighten_stop", { mode: "atr", value: 2 })],
      limits: { once: true },
    });
    expect(sentence).toBe(
      "When a 1m bar closes on BTCUSDT (Main), if Stop-run detected (estimated): tighten the stop to 2 × ATR(14) " +
        "from the close. Once. Uses an estimated detector — behaviour is heuristic. The stop only ever tightens.",
    );
    const estimated = sentence.indexOf(text("rules.editor.summary.estimated"));
    expect(estimated).toBeGreaterThan(sentence.indexOf("(estimated)"));
    expect(sentence.endsWith(` ${text("rules.editor.stop.tightens")}`)).toBe(true);
    const exact = cmp("lt", metric("distance_to_liquidity_cluster"), value(5));
    expect(fragmentOf(node("condition", { kind: "comparison", ...exact }), context())).toBe(
      "Distance to liquidity cluster is below 5",
    );
    expect(say({ conditions: exact })).not.toMatch(/estimated/);
  });

  it("follows R1's frame (G1): the trigger, the scope, the conditions, the actions, the limits that differ, then the safety line", () => {
    expect(
      say({
        conditions: group("all_of", [
          cmp("gte", metric("unrealised_r_multiple"), value(1)),
          cmp("eq", metric("position_side"), value("long")),
        ]),
        actions: [act("move_to_breakeven"), act("log_journal_tag", { tag: "be-moved" })],
        limits: { once_per: "position" },
      }),
    ).toBe(
      "When a 1m bar closes on BTCUSDT (Main), if Unrealised R is at least 1 and Position side is long: move " +
        "the stop to break-even (your average entry) plus 2 ticks and tag the journal be-moved. Once per " +
        "position. The stop only ever tightens.",
    );
    // No action moves a stop: no safety line; three actions read as a list.
    expect(
      say({
        actions: [
          act("flatten_all_positions"),
          act("halt_new_orders", { scope: "account", until: "manual" }),
          act("emit_signal", { signal_name: "out" }),
        ],
      }),
    ).toBe(
      "When a 1m bar closes on BTCUSDT (Main), if ATR(14) is above 2: flatten every position, halt new orders " +
        "on this account until you resume them and signal out to other rules.",
    );
    // Environments beyond demo end the scope clause; an on_error beyond the default follows the actions: the
    // memo's sentence when every action holds it, else per action (both PROPOSED in the header).
    const live = { level: "symbol", environments: ["live"] } as SentenceRule["scope"];
    expect(say({ scope: live, actions: [act("emit_signal", {}, { on_error: "continue" })] })).toBe(
      "When a 1m bar closes on every symbol, on LIVE, if ATR(14) is above 2: signal … to other rules. " +
        "If an action fails, the rest still run.",
    );
    const after = (...errors: string[]): string | undefined =>
      say({ actions: errors.map((e) => act("emit_signal", {}, { on_error: e })) as Actions })
        .split("to other rules. ")
        .at(1);
    expect([
      after("retry_once", "retry_once"),
      after("continue", "abort_remaining", "retry_once"),
      after("abort_remaining", "abort_remaining"),
    ]).toEqual([
      "A failed action is retried once, then the rest are skipped.",
      "If action 1 fails, the rest still run. If action 3 fails, it is retried once, then the rest are skipped.",
      undefined,
    ]);
  });

  it("makes grouping audible (G2): 'and', 'either … or …', 'any of:', the graph-only 'none of:' and 'at least n of:', and brackets a nested group, as E36-D05's cards read", () => {
    expect(ifClause(group("all_of", [A, group("any_of", [B, C])]))).toBe(
      `${ATR} and either ${SPREAD} or ${OPEN}`,
    );
    expect(ifClause(group("all_of", [group("any_of", [B, C]), A]))).toBe(
      `(either ${SPREAD} or ${OPEN}) and ${ATR}`,
    );
    expect(ifClause(group("any_of", [A, B]))).toBe(`either ${ATR} or ${SPREAD}`);
    expect(ifClause(group("any_of", [A, B, C]))).toBe(`any of: ${ATR}, ${SPREAD}, ${OPEN}`);
    expect(ifClause(group("any_of", [group("all_of", [A, B]), C]))).toBe(
      fill(deck("rules.editor.card.nested") ?? "", { A: ATR, B: SPREAD, C: OPEN }),
    );
    expect(ifClause(group("none_of", [A, B]))).toBe(
      fill(deck("rules.editor.card.none_of") ?? "", { A: ATR, B: SPREAD }),
    );
    expect(ifClause(group("n_of", [A, B, C], 2))).toBe(
      (deck("rules.editor.card.n_of") ?? "")
        .replace("{n}", "2")
        .replace("…", `${ATR}, ${SPREAD}, ${OPEN}`),
    );
    expect(ifClause(group("all_of", [A]))).toBe(ATR);
    // One input: none_of (the graph's NOT) and an n_of needing more keep their words, as the cards with one input
    // read, bracketed as any nested group; all_of, any_of and an n_of needing one read as the input, in its place.
    const NOT = fill((deck("rules.editor.card.none_of") ?? "").replace(", {B}", ""), { A: OPEN });
    expect([
      ifClause(group("none_of", [C])),
      ifClause(group("all_of", [A, group("none_of", [C])])),
      ifClause(group("any_of", [A, group("none_of", [C])])),
      ifClause(temporal("sustained_for", { child: group("none_of", [C]) })),
      ifClause(group("n_of", [C], 2)),
      ifClause(group("all_of", [A, group("n_of", [C], 3)])),
      ifClause(group("all_of", [A, group("n_of", [C], 1)])),
      ifClause(group("any_of", [group("all_of", [group("any_of", [A, B])]), C])),
    ]).toEqual([
      NOT,
      `${ATR} and (${NOT})`,
      `either ${ATR} or (${NOT})`,
      `(${NOT}) for at least 60 s`,
      (deck("rules.editor.card.n_of") ?? "").replace("{n}", "2").replace("…", OPEN),
      `${ATR} and (at least 3 of: ${OPEN})`,
      `${ATR} and ${OPEN}`,
      `either (either ${ATR} or ${SPREAD}) or ${OPEN}`,
    ]);
  });

  it("says each operator with E36-D05's verb (G4), the three-operand, set, temporal and arithmetic forms as its cards do", () => {
    const price = (op: Comparison["op"], more = {}) => cmp(op, metric("price"), value(63900), more);
    expect(ifClause(price("between", { right2: value(64100) }))).toBe(
      "Price is between 63,900 and 64,100",
    );
    expect(ifClause(price("outside", { right2: value(64100.5) }))).toBe(
      "Price is outside 63,900 to 64,100.5",
    );
    expect(ifClause(price("eq", { tolerance: 5 }))).toBe("Price is 63,900 (within 5)");
    expect(ifClause(cmp("changed", metric("price")))).toBe("Price changes");
    expect(ifClause(cmp("is_false", metric("position_open")))).toBe("not Position open");
    expect(
      ifClause(
        cmp("in_set", metric("market_regime"), undefined, {
          set_values: ["trend", "range", "chop"],
        }),
      ),
    ).toBe("Market regime (estimated) is one of trend, range, chop");
    expect(
      ifClause(cmp("not_in_set", metric("position_side"), undefined, { set_values: ["short"] })),
    ).toBe("Position side is none of short");
    expect(ifClause(temporal("sustained_for"))).toBe(`${ATR} for at least 60 s`);
    expect(ifClause(temporal("sustained_for", { min_count: 3 }))).toBe(
      `${ATR} for at least 60 s on at least 3 readings`,
    );
    expect(ifClause(temporal("occurred_within", { window_ms: 300_000 }))).toBe(
      fill(deck("rules.editor.card.within") ?? "", { A: ATR, w: "5 min" }),
    );
    expect(ifClause(temporal("count_within", { min_count: 4 }))).toBe(
      fill(deck("rules.editor.card.count") ?? "", { A: ATR, n: "4", w: "60 s" }),
    );
    expect(ifClause(temporal("stable_for", { window_ms: 1500 }))).toBe(
      fill(deck("rules.editor.card.stable") ?? "", { A: ATR, w: "1.5 s" }),
    );
    expect(ifClause(temporal("sustained_for", { child: group("all_of", [A, B]) }))).toBe(
      `(${ATR} and ${SPREAD}) for at least 60 s`,
    );
    const arithmetic = (op: string, operands: Operand[]): Operand =>
      ({ node_id: "x", op, operands }) as unknown as Operand;
    expect(
      ifClause(
        cmp(
          "gt",
          arithmetic("sub", [metric("price"), metric("ema", { params: { n: 21 } })]),
          value(10),
        ),
      ),
    ).toBe(fill(deck("rules.editor.card.arithmetic") ?? "", { A: "Price", B: "EMA(21)", x: "10" }));
    expect(
      ["add", "mul", "div", "min", "max", "abs", "neg", "pct_of"].map((op) =>
        ifClause(cmp("gt", arithmetic(op, [metric("price"), value(2)]), value(1))),
      ),
    ).toEqual([
      "Price plus 2 is above 1",
      "Price times 2 is above 1",
      "Price divided by 2 is above 1",
      "the lower of Price and 2 is above 1",
      "the higher of Price and 2 is above 1",
      "the size of Price is above 1",
      "minus Price is above 1",
      "Price as a percent of 2 is above 1",
    ]);
    // An operand that is itself arithmetic is bracketed: the two nestings read apart.
    const plus = arithmetic("add", [metric("price"), value(2)]);
    const times = arithmetic("mul", [value(2), value(3)]);
    expect([
      ifClause(cmp("gt", arithmetic("mul", [plus, value(3)]), value(1))),
      ifClause(cmp("gt", arithmetic("add", [metric("price"), times]), value(1))),
    ]).toEqual(["(Price plus 2) times 3 is above 1", "Price plus (2 times 3) is above 1"]);
    // An operator with no keyed verb reads by its id, as slice 2a's verbOf does (G9).
    expect(ifClause(cmp("zz_op" as Comparison["op"], metric("price"), value(1)))).toBe(
      "Price zz_op 1",
    );
  });

  it("names metrics by their display name with their parameters, unit and overrides (G3, G11), and an unavailable one in the row's words (P9)", () => {
    expect(ifClause(cmp("gt", metric("funding_rate"), value(0.01)))).toBe(
      "Funding rate is above 0.01 %",
    );
    expect(ifClause(cmp("gte", metric("time_in_trade_ms"), value(300_000)))).toBe(
      "Position age is at least 5 min",
    );
    expect(
      ifClause(cmp("gt", metric("atr", { params: { n: 14 }, timeframe: "5m" }), value(2000.5))),
    ).toBe("ATR(14) on the 5m is above 2,000.5");
    // The scope's own symbol is not said again; another one is; an account id is never said.
    expect(ifClause(cmp("gt", metric("funding_rate", { symbol: "BTCUSDT" }), value(0)))).toBe(
      "Funding rate is above 0 %",
    );
    expect(
      ifClause(
        cmp("gt", metric("funding_rate", { symbol: "ETHUSDT", account_id: "acc-x" }), value(0)),
      ),
    ).toBe("Funding rate on ETHUSDT is above 0 %");
    expect(ruleSentence(rule({ conditions: B }), context("unrecorded-solusdt"))).toContain(
      "Spread (bps) (not available — SOLUSDT is not on the recorded-symbol list · Start recording) is below 8 bps",
    );
    // "(estimated)" before an override; a Decimal string grouped, its digits as served; a ms one as a duration.
    expect([
      ifClause(cmp("changed", metric("market_regime", { timeframe: "5m" }))),
      ifClause(cmp("between", metric("price"), value("63900"), { right2: value("64100.50") })),
      ifClause(cmp("gte", metric("time_in_trade_ms"), value("300000"))),
    ]).toEqual([
      "Market regime (estimated) on the 5m changes",
      "Price is between 63,900 and 64,100.50",
      "Position age is at least 5 min",
    ]);
    // A served unit named like an Object member has no unit word.
    const price = { ...signalOf(served("manager"), "price"), unit: "constructor" };
    const odd = { vocabulary: { ...served("manager"), signals: [price] } };
    expect(ruleSentence(rule({ conditions: cmp("gt", metric("price"), value(2)) }), odd)).toMatch(
      /, if Price is above 2: /,
    );
  });

  it("names every served metric by its display name, never its id where one is served (P1); one it does not serve, by its id", () => {
    for (const signal of served("owner").signals) {
      const said = fragmentOf(
        node("condition", { kind: "comparison", op: "changed", left: { metric: signal.id } }),
        context("owner"),
      );
      expect(said.startsWith(signal.display_name ?? "?"), signal.id).toBe(true);
    }
    expect(ifClause(cmp("changed", metric("zz_unserved")))).toBe("zz_unserved changes");
  });
});

describe("the scope, the trigger and the limits (E36-D01 §5.6, G6)", () => {
  it("opens with the scope (§5.6 RuleScope): one or two named, three or more counted, never an account id", () => {
    const scoped = (scope: SentenceRule["scope"]): string =>
      /^When a 1m bar closes (.*), if /.exec(say({ scope }))?.[1] ?? "";
    expect([
      scoped({
        level: "symbol",
        symbols: ["BTCUSDT", "ETHUSDT"],
        account_ids: ["acc-main", "acc-alt"],
      }),
      scoped({
        level: "symbol",
        symbols: ["A", "B", "C", "D"],
        account_ids: ["acc-main", "acc-alt", "acc-x"],
      }),
      scoped({ level: "symbol", account_ids: ["acc-x"] }),
      scoped({ level: "account", account_ids: ["acc-main"] }),
      scoped({
        level: "position",
        symbols: ["BTCUSDT"],
        account_ids: ["acc-main"],
        applies_to: "open_positions",
      }),
      scoped({ level: "global", exclude_algo_children: false }),
      scoped({ level: "symbol", symbols: ["BTCUSDT"], applies_to: "pending_orders" }),
      scoped({ level: "position", applies_to: "account" }),
      scoped({ level: "symbol", symbols: ["BTCUSDT"], environments: ["demo", "live", "live"] }),
      scoped({ level: "symbol", symbols: ["BTCUSDT"], environments: ["testnet"] }),
      scoped({ level: "symbol", symbols: ["BTCUSDT"], environments: ["demo"] }),
      scoped({ level: "symbol", symbols: ["BTCUSDT"], environments: [] }),
    ]).toEqual([
      "on BTCUSDT, ETHUSDT (Main, Alt)",
      "on 4 symbols (3 accounts)",
      "on every symbol (1 account)",
      "on Main, every symbol",
      "on this BTCUSDT position (Main) for open positions",
      "on every account, including algo child orders",
      "on BTCUSDT for pending orders",
      "on this position for the account",
      "on BTCUSDT, on demo and LIVE",
      "on BTCUSDT, on testnet",
      "on BTCUSDT",
      "on BTCUSDT, on …",
    ]);
    expect(say({ scope: { level: "symbol", account_ids: ["acc-x"] } })).not.toContain("acc-x");
  });

  it("starts with the trigger's clause, its parameter in its unit; a clause with no value or none written reads as the served description", () => {
    const clause = (trigger: object, persona: Persona = "manager"): string =>
      ruleSentence(rule({ trigger: trigger as SentenceRule["trigger"] }), context(persona)).split(
        " on BTCUSDT",
      )[0] ?? "";
    expect([
      clause({ type: "on_timer", interval_ms: 60_000 }),
      clause({ type: "on_schedule", cron: "0 9 * * 1" }),
      clause({ type: "on_metric_change", metric: "market_regime" }),
      clause({ type: "on_price_update", debounce_ms: 1000 }),
      clause({ type: "on_price_update", debounce_ms: 5000 }),
      clause({ type: "on_price_update", debounce_ms: 0 }),
      clause({ type: "on_signal" }),
      clause({ type: "on_bar_close" }),
    ]).toEqual([
      "Every 60 s",
      "On schedule 0 9 * * 1 (UTC)",
      "When the Market regime (estimated) changes",
      "When a trade prints (at most once a second)",
      "When a trade prints (at most once every 5 s)",
      "When a trade prints",
      "When another rule emits a signal",
      "When a bar closes",
    ]);
    const fresh = {
      ...rule({ trigger: { type: "zz_new_trigger" } as unknown as SentenceRule["trigger"] }),
    };
    expect(ruleSentence(fresh, { vocabulary: extended() })).toMatch(
      /^When a new thing happens on /,
    );
    const unserved = { ...served("manager"), triggers: [] };
    expect(
      ruleSentence(rule({ trigger: { type: "on_bar_close" } }), { vocabulary: unserved }),
    ).toMatch(/^When a … bar closes on /);
    // The metric a trigger names counts as a metric the rule uses (G8).
    expect(say({ trigger: { type: "on_metric_change", metric: "market_regime" } })).toContain(
      text("rules.editor.summary.estimated"),
    );
  });

  it("says only the limits that differ from the defaults (G6), each as E36-D05 writes it", () => {
    const limited = (limits: NonNullable<SentenceRule["limits"]>): string =>
      say({ limits, actions: [act("flatten_all_positions"), act("cancel_all_orders")] }).split(
        ": ",
      )[1] ?? "";
    const NONE = "flatten every position and cancel every working order.";
    expect(
      limited({
        cooldown_ms: 1000,
        max_fires_per_hour: 60,
        max_fires_per_day: 500,
        max_actions_per_fire: 10,
        evaluation_timeout_ms: 250,
        kill_switch_on_error_count: 5,
        once: false,
        require_confirmation: false,
        max_notional_per_fire: null,
      }),
    ).toBe(NONE);
    expect(limited({ max_actions_per_fire: 2 })).toBe(NONE); // as many as the rule's two actions
    expect(
      limited({
        once: true,
        once_per: "day",
        cooldown_ms: 60_000,
        max_fires_per_hour: 10,
        max_fires_per_day: 400,
        max_actions_per_fire: 1,
        max_notional_per_fire: 2500,
        max_daily_notional: "10000",
        require_confirmation: true,
        evaluation_timeout_ms: 500,
        kill_switch_on_error_count: 3,
      }),
    ).toBe(
      "flatten every position and cancel every working order. Once. Once per day. " +
        `${deck("rules.editor.limit.cooldown")} ${deck("rules.editor.limit.per_hour")} Up to 400 times a day. ` +
        "Only the first 1 actions run per firing. At most 2,500 USDT per firing. At most 10,000 USDT a day. " +
        `${deck("rules.editor.limit.confirm")} Each check may take up to 500 ms. ` +
        "Turns itself off after 3 errors in a row — you re-arm it.",
    );
    expect(
      ["position", "group", "rule_lifetime"].map(
        (per) => limited({ once_per: per as "position" }).split(". ")[1],
      ),
    ).toEqual(["Once per position.", "Once per group.", "Once in this rule's lifetime."]);
    // Each default left unsaid is the published rule IR schema's (P8): unsaid at it, said one past it.
    const schema = RULE_IR_SCHEMA["$defs"] as Record<
      string,
      { properties: Record<string, object> }
    >;
    const onePast: Readonly<Record<string, string>> = {
      cooldown_ms: "At most every 1.001 s.",
      max_fires_per_hour: "Up to 61 times an hour.",
      max_fires_per_day: "Up to 501 times a day.",
      evaluation_timeout_ms: "Each check may take up to 251 ms.",
      kill_switch_on_error_count: "Turns itself off after 6 errors in a row — you re-arm it.",
    };
    for (const [key, words] of Object.entries(onePast)) {
      const { default: value } = schema["RuleLimits"]?.properties[key] as { default: number };
      const at = (n: number) => limited({ [key]: n } as NonNullable<SentenceRule["limits"]>);
      expect([at(value), at(value + 1)], key).toEqual([NONE, `${NONE} ${words}`]);
    }
  });
});

describe("each action's clause (E36-D01 §5.6)", () => {
  it("says every served action with its parameters, E36-D05's instances byte for byte; an action with no phrase reads by its served name", () => {
    const said = (type: Action["type"], params: Action["params"] = {}): string =>
      actionClause(act(type, params));
    expect([
      said("place_order", { side: "buy", order_type: "market", qty_mode: "explicit", qty: 0.25 }),
      said("place_order", {
        side: "sell",
        order_type: "limit",
        qty_mode: "explicit",
        qty: 0.5,
        price: 63900,
      }),
      said("place_order", { side: "buy", order_type: "market", qty_mode: "profile" }),
      said("modify_stop_loss", { mode: "absolute", value: 63900 }),
      said("modify_stop_loss", { mode: "offset_from_entry", value: 4 }),
      said("tighten_stop", { mode: "offset_from_price", value: 6 }),
      said("tighten_stop", { mode: "atr", value: 2 }),
      said("tighten_stop", { mode: "structure", value: 3 }),
      said("tighten_stop", {}),
      said("modify_take_profit", { mode: "absolute", value: 65000 }),
      said("move_to_breakeven", { offset_ticks: 3 }),
      said("scale_in", { qty_pct: 50 }),
      said("scale_in", { qty: 0.1 }),
      said("flatten_position", {}),
      said("flatten_position", { symbols: ["BTCUSDT", "ETHUSDT"] }),
      said("reverse_position"),
      said("cancel_order", {}),
      said("cancel_order", { purpose: "take_profit" }),
      said("cancel_all_orders", { purpose: "entry" }),
      said("halt_new_orders", { scope: "symbol", until: "duration_ms" }),
      said("resume_new_orders", { scope: "account" }),
      said("reduce_leverage", { target: 3 }),
      said("reduce_leverage", { by: 2 }),
      said("arm_chase_limit", { params: {} }),
      said("start_iceberg_slice", { params: {} }),
      said("start_twap", { params: {} }),
      said("set_variable", { name: "armed", value: 1, ttl_ms: 60_000 }),
      said("set_variable", { name: "armed", value: true }),
      said("emit_signal", { signal_name: "breakout" }),
      said("pause_rule", { rule_id: "r-1" }),
      said("enable_rule", { rule_id: "r-1" }),
    ]).toEqual([
      "buy 0.25 at market with a native stop",
      "sell 0.5 at 63,900 with a native stop",
      "buy the profile's size at market with a native stop",
      "tighten the stop to 63,900",
      "tighten the stop to 4 ticks past entry in your favour",
      "tighten the stop to 6 ticks from the price",
      "tighten the stop to 2 × ATR(14) from the close",
      "tighten the stop to 3 ticks beyond the last swing",
      "tighten the stop to …",
      "move the take-profit to 65,000",
      "move the stop to break-even (your average entry) plus 3 ticks",
      "add 50 % to the position, within the profile's caps",
      "add 0.1 to the position, within the profile's caps",
      "flatten the position",
      "flatten the BTCUSDT and ETHUSDT position",
      "reverse the position — flatten, then open the other side with a native stop",
      "cancel the working order",
      "cancel the working take_profit order",
      "cancel every working entry order",
      "halt new orders on this symbol for …",
      "resume new orders on this account (needs the live-arming permission)",
      "reduce leverage to 3×",
      "reduce leverage by 2×",
      "arm the chase limit",
      "start an iceberg slice",
      "start a TWAP",
      "remember armed = 1 for 60 s",
      "remember armed = true",
      "signal breakout to other rules",
      "pause rule",
      "enable rule",
    ]);
    // E36-D05's action phrases, filled by the deck's own instance, byte for byte.
    expect([
      said("move_to_breakeven"),
      said("scale_out", { qty_pct: 33, order_type: "market" }),
      said("flatten_all_positions", { symbols: ["BTCUSDT"] }),
      said("halt_new_orders", { scope: "account", until: "next_utc_day" }),
      said("send_notification", { channel: "push", severity: "high", template: "t" }),
      said("log_journal_tag", { tag: "{tag}" }),
    ]).toEqual(
      ["breakeven", "scale_out", "flatten", "halt", "notify", "tag"].map((k) =>
        deck(`rules.editor.action.phrase.${k}`),
      ),
    );
    const fresh = act("zz_new_action" as Action["type"]);
    expect(ruleSentence(rule({ actions: [fresh] }), { vocabulary: extended() })).toContain(
      ": new action.",
    );
    // One that can place orders (the flag absent, as `22` reads it, or true) says so, with its native stop.
    const NEW = extended().actions.at(-1) as VocabularyAction;
    const unflagged = { ...NEW };
    Reflect.deleteProperty(unflagged, "places_orders");
    const clauseOf = (entry: VocabularyAction): string | undefined =>
      ruleSentence(rule({ actions: [fresh] }), { vocabulary: { ...extended(), actions: [entry] } })
        .split(": ")
        .at(-1);
    expect([clauseOf(unflagged), clauseOf({ ...NEW, places_orders: true })]).toEqual([
      "new action (places orders, with a native stop).",
      "new action (places orders, with a native stop).",
    ]);
  });

  it("says a targets other than the rule scope with the served sentence (G9), and a dry run, inside the action's clause", () => {
    expect([
      actionClause(act("flatten_position", {}, { targets: "originating_account" })),
      actionClause(act("flatten_position", {}, { targets: "all_accounts", dry_run_only: true })),
      actionClause(act("flatten_position", {}, { targets: "scope_accounts", dry_run_only: false })),
    ]).toEqual([
      "flatten the position on the account whose event fired the rule",
      "flatten the position on every account the author can trade — simulated, never sent",
      "flatten the position",
    ]);
  });

  it("closes with the safety line only when an action moves a stop and none holds only_tighten at anything but true (G7)", () => {
    const ends = (actions: SentenceRule["actions"]): boolean =>
      say({ actions }).endsWith(text("rules.editor.stop.tightens"));
    const loose = act("tighten_stop", { mode: "atr", value: 1, only_tighten: false });
    expect([
      ends([act("modify_stop_loss", { mode: "absolute", value: 1 })]),
      ends([act("tighten_stop", { mode: "atr", value: 1, only_tighten: true })]),
      ends([act("move_to_breakeven")]),
      ends([act("place_order", { side: "buy" })]),
      ends([act("modify_take_profit", { mode: "absolute", value: 1 })]),
      ends([act("flatten_all_positions"), act("log_journal_tag", { tag: "x" })]),
      ends([act("move_to_breakeven"), loose]),
      ends([act("tighten_stop", { mode: "atr", value: 1, only_tighten: null })]),
    ]).toEqual([true, true, true, false, false, false, false, false]);
    // No deck string says a stop may loosen (#4137): nothing stands in the line's place.
    expect(say({ actions: [loose] })).toMatch(
      /: tighten the stop to 1 × ATR\(14\) from the close\.$/,
    );
  });
});

describe("node fragments (E37-S02; E37-D05 `rules.graph.aria.node`)", () => {
  it("gives each node type its fragment: the trigger in 15's CMP-147 form, a condition and an action as the sentence says them, a gate's words, a comment's text", () => {
    const named = (type: GraphNode["type"], data: GraphNode["data"]): string =>
      text("rules.graph.aria.node", {
        Type: {
          trigger: "Trigger",
          condition: "Condition",
          action: "Action",
          logicGate: "Logic gate",
          comment: "Comment",
        }[type],
        "sentence fragment": fragmentOf(node(type, data), context()),
      });
    expect([
      named("trigger", { type: "on_bar_close", timeframe: "5m", debounce_ms: 0 }),
      named("trigger", { type: "on_timer", interval_ms: 60_000 }),
      named("trigger", { type: "on_schedule", cron: "0 9 * * 1" }),
      named("trigger", { type: "on_metric_change", metric: "funding_rate" }),
      named("trigger", { type: "on_order_fill" }),
      named("condition", { kind: "comparison", op: "gt", right: { const: 2 } }),
      named("condition", { kind: "temporal", op: "sustained_for", window_ms: 5000 }),
      named("condition", { kind: "arithmetic", op: "sub", operands: [null, { metric: "ema" }] }),
      named("logicGate", { op: "all_of", children: [null, null] }),
      named("logicGate", { op: "n_of", n: 2, children: [null, null, null] }),
      named("action", { type: "move_to_breakeven", params: {}, targets: "scope_accounts" }),
      named("comment", { text: "<b>Not part of the rule</b>" }),
    ]).toEqual([
      "Trigger node: on bar close, 5m",
      "Trigger node: on timer, 60 s",
      "Trigger node: on schedule, 0 9 * * 1 (UTC)",
      "Trigger node: on metric change, Funding rate",
      "Trigger node: on order fill",
      "Condition node: … is above 2",
      "Condition node: … for at least 5 s",
      "Condition node: … minus EMA",
      "Logic gate node: all of",
      "Logic gate node: at least 2 of",
      "Action node: move the stop to break-even (your average entry) plus 2 ticks",
      "Comment node: <b>Not part of the rule</b>",
    ]);
  });

  it("names no action by its id: every served action's fragment is words", () => {
    for (const action of served("owner").actions) {
      const said = fragmentOf(node("action", { type: action.id, params: {} }), context("owner"));
      expect(said, action.id).not.toContain(action.id);
      expect(said, action.id).not.toMatch(/_/);
    }
  });

  it("reads a half-built node as '…' where a value is not set yet, never a {slot}", () => {
    const said = (type: GraphNode["type"], data: GraphNode["data"]): string =>
      fragmentOf(node(type, data), context());
    expect([
      said("trigger", {}),
      said("condition", {}),
      said("condition", { kind: "comparison", left: { metric: "spread_bps" } }),
      said("condition", { kind: "comparison", op: "in_set", left: {}, tolerance: null }),
      said("condition", { kind: "temporal", op: "sustained_for" }),
      said("condition", { kind: "arithmetic", operands: [] }),
      said("condition", { kind: "arithmetic", op: "abs", operands: [] }),
      said("condition", { kind: "arithmetic", op: "zz_op", operands: [{ const: 1 }, null] }),
      said("condition", { children: [] }),
      said("logicGate", {}),
      said("logicGate", { op: "zz_gate" }),
      said("action", {}),
      said("action", { type: "zz_unserved", params: {} }),
      said("action", { type: "move_to_breakeven" }),
      said("comment", { text: "" }),
    ]).toEqual([
      "…",
      "…",
      "Spread (bps) … …",
      "… is one of …",
      "… for at least …",
      "… …",
      "the size of …",
      "zz_op 1 and …",
      "…",
      "…",
      "zz_gate",
      "…",
      "zz_unserved",
      "move the stop to break-even (your average entry) plus 2 ticks",
      "…",
    ]);
    // A metric with no id, and an unavailable one served with no reason: "…" stands in, never a slot.
    const reasonless = served("unrecorded-solusdt");
    Reflect.deleteProperty(signalOf(reasonless, "tape_speed"), "unavailable_reason");
    expect(
      fragmentOf(
        node("condition", { kind: "comparison", op: "changed", left: { metric: "tape_speed" } }),
        {
          vocabulary: reasonless,
        },
      ),
    ).toBe("Tape speed (not available — … · Start recording) changes");
    expect(said("condition", { kind: "comparison", op: "changed", left: { metric: null } })).toBe(
      "… changes",
    );
  });
});

describe("the memo's words (E36-D01 §5.4, §5.6, verbatim)", () => {
  it("each phrase no deck keys stands in the memo as written", () => {
    const memo = readFileSync(resolve(ROOT, "docs/design/research/e36-rules-in-words.md"), "utf8");
    const stands: Record<string, string> = {
      scaleIn: "to the position, within the profile's caps",
    };
    for (const [name, words] of Object.entries(MEMO)) {
      expect(memo, name).toContain(stands[name] ?? words);
    }
  });
});
