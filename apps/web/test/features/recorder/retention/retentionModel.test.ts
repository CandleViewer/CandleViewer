/**
 * E16-S03 (#485): the retention policy model (E16-D03 §3, §5, §7; D03-C9, D03-D5). Pure: no React,
 * no fetch, no deck strings (keys and parameters only). The K1-K7 rows are D03 §5's reduction-kinds
 * table, run on the `22` examples: BTCUSDT pinned, ETHUSDT not.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  addOverride,
  classify,
  hasChanges,
  invalidCount,
  isAtSeed,
  isDirty,
  load,
  OFFERED_ACTIONS,
  resetToDefault,
  SEED,
  setAction,
  setDays,
  stageRemoval,
  STREAMS,
  symbolsOf,
  toRequest,
  totalHorizon,
  undoRemoval,
  validateDays,
  type Classification,
  type ClassifyContext,
  type Draft,
  type Line,
  type LineKind,
  type OfferedAction,
  type RetentionPolicy,
  type RowKey,
  type StreamKind,
  type TypedConfirm,
} from "../../../../src/features/recorder/retention/retentionModel";
import { POLICIES_DEFAULTS, STORAGE_USAGE, policy } from "./fixtures";

type Step = (draft: Draft) => Draft;
const G = (stream: StreamKind): RowKey => ({ symbol: null, stream });
const O = (symbol: string, stream: StreamKind): RowKey => ({ symbol, stream });
const edit = (draft: Draft, ...steps: Step[]): Draft => steps.reduce((d, step) => step(d), draft);
const days =
  (key: RowKey, n: number): Step =>
  (d) =>
    setDays(d, key, n);
const act =
  (key: RowKey, action: OfferedAction): Step =>
  (d) =>
    setAction(d, key, action);
const add =
  (symbol: string, stream: StreamKind): Step =>
  (d) =>
    addOverride(d, symbol, stream);
const remove =
  (key: RowKey): Step =>
  (d) =>
    stageRemoval(d, key);

/** The `22` example set; the six streams it does not list stand on their seed (BQ-10). */
const BASE = load(POLICIES_DEFAULTS.items);
/** The `22` storage example's symbols: BTCUSDT pinned, ETHUSDT not. */
const CTX: ClassifyContext = { ...symbolsOf(STORAGE_USAGE), applyNow: false };
const NOW: ClassifyContext = { ...CTX, applyNow: true };
const THREE: ClassifyContext = {
  symbols: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"],
  pinned: ["BTCUSDT"],
  applyNow: false,
};

const confirmOf = (c: Classification): TypedConfirm => {
  if (c.kind !== "reduction") throw new Error(`expected a reduction, got ${c.kind}`);
  return c.confirm;
};
const linesOf = (confirm: TypedConfirm) =>
  confirm.lines.map((l) => [l.reductionKind, l.stream, l.symbol, l.scope]);

describe("the seed (21 §7; recorder/retention_defaults.py STREAM_DEFAULTS)", () => {
  it("STREAMS - the contract's StreamKind - eight, in the contract's order, keyed like SEED", () => {
    expect(STREAMS).toEqual([
      "trades",
      "orderbook_delta",
      "orderbook_snapshot",
      "tickers",
      "klines",
      "liquidations",
      "open_interest",
      "funding",
    ]);
    expect(Object.keys(SEED)).toEqual([...STREAMS]);
  });

  it.each([
    ["trades", 30, 730, true],
    ["orderbook_delta", 7, 730, true],
    ["orderbook_snapshot", 30, 730, false],
    ["tickers", 30, 730, true],
    ["klines", 90, null, false],
    ["liquidations", 90, null, true],
    ["open_interest", 90, null, false],
    ["funding", 365, null, false],
  ] as const)("SEED - %s - %i d hot, total %s d, rolls off %s", (stream, hot, total, rolls) => {
    expect(SEED[stream]).toEqual({ hotDays: hot, totalDays: total, rollsOff: rolls });
  });

  it("SEED - its sources - retention_defaults.py, rolloff.py's ROLLOFF_STREAMS and D03's eight seed markers", () => {
    const read = (path: string): string =>
      readFileSync(resolve(import.meta.dirname, "../../../../../..", path), "utf8");
    const defaults = read("services/api/candleviewer/recorder/retention_defaults.py");
    const rolloff = read("services/api/candleviewer/recorder/rolloff.py");
    const d03 = read("docs/design/E16/E16-D03.md");
    // `22`'s `funding` is the recorder's `funding_rates` (`DB_STREAM_ALIASES`).
    const named = (stream: StreamKind): string => (stream === "funding" ? "funding_rates" : stream);
    const tuple = /^ROLLOFF_STREAMS: tuple\[StreamKind, \.\.\.\] = \(([^)]*)\)/m.exec(rolloff);
    const rolling = [...(tuple?.[1] ?? "").matchAll(/StreamKind\.([A-Z_]+)/g)].map(([, member]) =>
      member?.toLowerCase(),
    );
    expect(rolling).toHaveLength(4);
    for (const stream of STREAMS) {
      const row = new RegExp(`^\\s*"${named(stream)}": \\((\\d+), (\\d+|None)\\),$`, "m").exec(
        defaults,
      );
      const marker = new RegExp(`<!-- audit:seed\\.${stream}=(\\d+) -->`).exec(d03);
      const total = row?.[2] === "None" ? null : Number(row?.[2]);
      expect(SEED[stream], stream).toEqual({
        hotDays: Number(row?.[1]),
        totalDays: total,
        rollsOff: rolling.includes(named(stream)),
      });
      expect(Number(marker?.[1]), stream).toBe(SEED[stream].hotDays);
    }
  });

  it.each([
    ["trades", 30, "archive_parquet", 730],
    ["trades", 1000, "archive_parquet", 1000],
    ["trades", 7, "drop", 7],
    ["klines", 90, "archive_parquet", null],
    ["klines", 30, "drop", 30],
  ] as const)("totalHorizon - %s %i d %s - %s", (stream, n, action, total) => {
    expect(totalHorizon(stream, n, action)).toBe(total);
  });
});

describe("validateDays (D03 §7; 22 retain_days 1-3650, whole days)", () => {
  it.each([
    [0, "min"],
    [1, null],
    [3650, null],
    [3651, "max"],
    [4000, "max"],
    [7.5, "int"],
    [-3, "min"],
    [Number.NaN, "int"],
  ] as const)("validateDays - %s - %s", (n, error) => {
    expect(validateDays(n)).toBe(error);
  });

  it("invalidCount - two invalid live fields and an invalid removed row - two", () => {
    const draft = edit(
      BASE,
      days(G("trades"), 0),
      days(O("ETHUSDT", "orderbook_delta"), 7.5),
      add("SOLUSDT", "funding"),
      days(O("SOLUSDT", "funding"), 4000),
      remove(O("SOLUSDT", "funding")),
    );
    expect(invalidCount(draft)).toBe(2);
  });
});

describe("load and the draft (D03 §3, §6; D03-D15; BQ-10)", () => {
  it("load - the 22 defaults example - eight global rows in order, six on their seed, then the override", () => {
    expect(BASE.rows.map((r) => [r.symbol, r.stream, r.days, r.action, r.removed])).toEqual([
      [null, "trades", 30, "archive_parquet", false],
      [null, "orderbook_delta", 7, "archive_parquet", false],
      [null, "orderbook_snapshot", 30, "archive_parquet", false],
      [null, "tickers", 30, "archive_parquet", false],
      [null, "klines", 90, "archive_parquet", false],
      [null, "liquidations", 90, "archive_parquet", false],
      [null, "open_interest", 90, "archive_parquet", false],
      [null, "funding", 365, "archive_parquet", false],
      ["ETHUSDT", "orderbook_delta", 3, "drop", false],
    ]);
    expect([isDirty(BASE), hasChanges(BASE), invalidCount(BASE)]).toEqual([false, false, 0]);
    expect(BASE.rows.map(isAtSeed)).toEqual([
      true,
      true,
      true,
      true,
      true,
      true,
      true,
      true,
      false,
    ]);
  });

  it("load - a duplicate, an unknown stream, downsample and pin, an absent symbol - first kept, skipped, archive_parquet, global", () => {
    const draft = load([
      policy("trades", 12, "drop"),
      policy("trades", 99, "drop"),
      policy("klines", 40, "downsample"),
      { stream: "tickers", retain_days: 15, action: "pin", applies_to_pinned: false },
      // A stream outside the `22` StreamKind, as the wire could carry one.
      JSON.parse(
        '{"stream":"bars","retain_days":5,"action":"drop","symbol":"ETHUSDT","applies_to_pinned":false}',
      ) as RetentionPolicy,
      policy("funding", 20, "drop", "ETHUSDT"),
      policy("funding", 21, "drop", "ETHUSDT"),
    ]);
    expect(draft.rows.map((r) => [r.symbol, r.stream, r.days, r.action])).toEqual([
      [null, "trades", 12, "drop"],
      [null, "orderbook_delta", 7, "archive_parquet"],
      [null, "orderbook_snapshot", 30, "archive_parquet"],
      [null, "tickers", 15, "archive_parquet"],
      [null, "klines", 40, "archive_parquet"],
      [null, "liquidations", 90, "archive_parquet"],
      [null, "open_interest", 90, "archive_parquet"],
      [null, "funding", 365, "archive_parquet"],
      ["ETHUSDT", "funding", 20, "drop"],
    ]);
  });

  const DIRTY: [string, Step[], boolean, boolean][] = [
    ["no edit", [], false, false],
    ["trades 30 to 7", [days(G("trades"), 7)], true, true],
    ["trades 30 to 7 and back", [days(G("trades"), 7), days(G("trades"), 30)], false, false],
    ["an invalid field", [days(G("trades"), 0)], true, true],
    ["a staged removal", [remove(O("ETHUSDT", "orderbook_delta"))], true, true],
    [
      "a removal undone",
      [
        remove(O("ETHUSDT", "orderbook_delta")),
        (d) => undoRemoval(d, O("ETHUSDT", "orderbook_delta")),
      ],
      false,
      false,
    ],
    ["an added override", [add("SOLUSDT", "trades")], true, true],
    [
      "an added override removed",
      [add("SOLUSDT", "trades"), remove(O("SOLUSDT", "trades"))],
      true,
      false,
    ],
    [
      "an edit reset to default",
      [act(G("trades"), "drop"), days(G("trades"), 7), (d) => resetToDefault(d, "trades")],
      false,
      false,
    ],
  ];
  it.each(DIRTY)("isDirty, hasChanges - %s - %s, %s", (_name, steps, dirty, changes) => {
    const draft = edit(BASE, ...steps);
    expect([isDirty(draft), hasChanges(draft)]).toEqual([dirty, changes]);
  });

  it("resetToDefault - a funding row edited - the seed's 365 d Move to Parquet, chip back", () => {
    const edited = edit(BASE, act(G("funding"), "drop"), days(G("funding"), 30));
    const reset = resetToDefault(edited, "funding");
    expect([edited, reset].map((d) => d.rows.filter(isAtSeed).length)).toEqual([7, 8]);
    expect(reset.rows).toEqual(BASE.rows);
  });

  it("addOverride - a new pair - the stream's effective days and Move to Parquet after (D03 §6 row-add)", () => {
    const draft = edit(BASE, days(G("trades"), 45), add("SOLUSDT", "trades"));
    expect(draft.rows.at(-1)).toEqual({
      symbol: "SOLUSDT",
      stream: "trades",
      days: 45,
      action: "archive_parquet",
      removed: false,
    });
    const fromSeed = edit(BASE, days(G("klines"), 0), add("SOLUSDT", "klines"));
    expect(fromSeed.rows.at(-1)?.days).toBe(90); // the global field is invalid: the seed's days
  });

  it("addOverride, stageRemoval, setDays - an existing pair, a global row, an unknown row - the same draft", () => {
    const removed = edit(BASE, remove(O("ETHUSDT", "orderbook_delta")));
    expect(addOverride(BASE, "ETHUSDT", "orderbook_delta")).toBe(BASE);
    expect(addOverride(removed, "ETHUSDT", "orderbook_delta")).toBe(removed);
    expect(stageRemoval(BASE, G("trades"))).toBe(BASE);
    expect(setDays(BASE, O("SOLUSDT", "trades"), 5)).toBe(BASE);
  });

  it("toRequest - the loaded set - all eight defaults with symbol null, then the override", () => {
    expect(toRequest(BASE)).toEqual({
      items: [
        ...STREAMS.map((stream) => ({
          stream,
          retain_days: SEED[stream].hotDays,
          action: "archive_parquet",
          symbol: null,
          applies_to_pinned: false,
        })),
        {
          stream: "orderbook_delta",
          retain_days: 3,
          action: "drop",
          symbol: "ETHUSDT",
          applies_to_pinned: false,
        },
      ],
    });
  });

  it("toRequest - a removal and overrides added out of order - removed row omitted, overrides by symbol then stream", () => {
    const draft = edit(
      BASE,
      add("SOLUSDT", "funding"),
      add("ADAUSDT", "trades"),
      add("SOLUSDT", "trades"),
      remove(O("ETHUSDT", "orderbook_delta")),
    );
    const items = toRequest(draft).items;
    expect(items.slice(0, 8).map((i) => [i.symbol, i.stream])).toEqual(
      STREAMS.map((s) => [null, s]),
    );
    expect(items.slice(8).map((i) => [i.symbol, i.stream, i.retain_days, i.action])).toEqual([
      ["ADAUSDT", "trades", 30, "archive_parquet"],
      ["SOLUSDT", "trades", 30, "archive_parquet"],
      ["SOLUSDT", "funding", 365, "archive_parquet"],
    ]);
  });

  it("toRequest - a hand-built draft without global rows - the eight seeds are sent", () => {
    const items = toRequest({ base: [], rows: [] }).items;
    expect(items.map((i) => [i.symbol, i.stream, i.retain_days, i.action])).toEqual(
      STREAMS.map((s) => [null, s, SEED[s].hotDays, "archive_parquet"]),
    );
  });

  it("symbolsOf - the 22 storage example and an empty report - both symbols with BTCUSDT pinned; none", () => {
    expect(symbolsOf(STORAGE_USAGE)).toEqual({
      symbols: ["BTCUSDT", "ETHUSDT"],
      pinned: ["BTCUSDT"],
    });
    expect(symbolsOf({ symbols: [{ used_bytes: 1 }] })).toEqual({ symbols: [], pinned: [] });
    expect(symbolsOf({})).toEqual({ symbols: [], pinned: [] });
  });

  it("symbolsOf - no report (the 503 before the first sample) - symbols unknown (null), no pin known", () => {
    expect(symbolsOf(null)).toEqual({ symbols: null, pinned: [] });
  });
});

const ETH = ["ETHUSDT"];
const K1 = edit(BASE, act(G("trades"), "drop"), days(G("trades"), 7));
const K7 = edit(load([policy("trades", 1000, "archive_parquet")]), days(G("trades"), 30));
const K4 = edit(
  load([policy("trades", 7, "drop"), policy("trades", 14, "archive_parquet", "ETHUSDT")]),
  remove(O("ETHUSDT", "trades")),
);
const SNAPSHOTS_7 = edit(
  BASE,
  act(G("orderbook_snapshot"), "drop"),
  days(G("orderbook_snapshot"), 7),
);
const M24 = { days: 730, seed: true } as const;

type Expected = Pick<TypedConfirm, "reductionKind" | "word" | "title" | "body" | "timing">;
type KindRow = [
  string,
  Draft,
  ClassifyContext,
  Expected,
  [LineKind, StreamKind, string | null, string[]][],
];

/** D03 §5's reduction kinds; each row's example is the table's, on the `22` fixture. */
const KINDS: KindRow[] = [
  [
    "K1 global trades 30 d Move to Parquet to 7 d Delete after (the worked case)",
    K1,
    CTX,
    {
      reductionKind: "K1",
      word: "trades",
      timing: "next_run",
      title: { key: "retention.confirm.title", params: { stream: "trades", n: 7 } },
      body: { key: "retention.confirm.body", params: { stream: "trades", scope: ETH, n: 7 } },
    },
    [["K1", "trades", null, ETH]],
  ],
  [
    "K2 global trades 7 d Delete after lowered to 3 d",
    edit(load([policy("trades", 7, "drop")]), days(G("trades"), 3)),
    CTX,
    {
      reductionKind: "K2",
      word: "trades",
      timing: "next_run",
      title: { key: "retention.confirm.title", params: { stream: "trades", n: 3 } },
      body: { key: "retention.confirm.body", params: { stream: "trades", scope: ETH, n: 3 } },
    },
    [["K2", "trades", null, ETH]],
  ],
  [
    "K3 an ETHUSDT trades override at 14 d Delete after (F3; its fallback keeps 24 months)",
    edit(
      BASE,
      add("ETHUSDT", "trades"),
      act(O("ETHUSDT", "trades"), "drop"),
      days(O("ETHUSDT", "trades"), 14),
    ),
    CTX,
    {
      reductionKind: "K3",
      word: "ETHUSDT",
      timing: "next_run",
      title: {
        key: "retention.confirm.title_symbol",
        params: { symbol: "ETHUSDT", stream: "trades", n: 14 },
      },
      body: { key: "retention.confirm.body", params: { stream: "trades", scope: ETH, n: 14 } },
    },
    [["K3", "trades", "ETHUSDT", ETH]],
  ],
  [
    "K3 the ETHUSDT order-book deltas override lowered from 3 d to 2 d",
    edit(BASE, days(O("ETHUSDT", "orderbook_delta"), 2)),
    CTX,
    {
      reductionKind: "K3",
      word: "ETHUSDT",
      timing: "next_run",
      title: {
        key: "retention.confirm.title_symbol",
        params: { symbol: "ETHUSDT", stream: "orderbook_delta", n: 2 },
      },
      body: {
        key: "retention.confirm.body",
        params: { stream: "orderbook_delta", scope: ETH, n: 2 },
      },
    },
    [["K3", "orderbook_delta", "ETHUSDT", ETH]],
  ],
  [
    "K4 the ETHUSDT trades 14 d Move-to-Parquet override removed under a 7 d Delete-after rule",
    K4,
    CTX,
    {
      reductionKind: "K4",
      word: "ETHUSDT",
      timing: "next_run",
      title: { key: "retention.remove.title", params: { symbol: "ETHUSDT", stream: "trades" } },
      body: { key: "retention.confirm.body", params: { stream: "trades", scope: ETH, n: 7 } },
    },
    [["K4", "trades", "ETHUSDT", ETH]],
  ],
  [
    "K4 onto a Move-to-Parquet global rule (the body reads the total)",
    edit(
      load([
        policy("trades", 30, "archive_parquet"),
        policy("trades", 1000, "archive_parquet", "ETHUSDT"),
      ]),
      remove(O("ETHUSDT", "trades")),
    ),
    CTX,
    {
      reductionKind: "K4",
      word: "ETHUSDT",
      timing: "next_run",
      title: { key: "retention.remove.title", params: { symbol: "ETHUSDT", stream: "trades" } },
      body: {
        key: "retention.confirm.body_total",
        params: { stream: "trades", scope: ETH, total: M24 },
      },
    },
    [["K4", "trades", "ETHUSDT", ETH]],
  ],
  [
    "K5 trades and order-book deltas both to 7 d Delete after",
    edit(
      load([
        policy("trades", 30, "archive_parquet"),
        policy("orderbook_delta", 7, "archive_parquet"),
      ]),
      act(G("trades"), "drop"),
      days(G("trades"), 7),
      act(G("orderbook_delta"), "drop"),
    ),
    CTX,
    {
      reductionKind: "K5",
      word: "all streams",
      timing: "next_run",
      title: { key: "retention.confirm.title_multi", params: { k: 2 } },
      body: { key: "retention.confirm.body_multi", params: { k: 2 } },
    },
    [
      ["K1", "trades", null, ETH],
      ["K1", "orderbook_delta", null, ETH],
    ],
  ],
  [
    "K5 one stream over three symbols (K1's title, the stream typed)",
    K1,
    THREE,
    {
      reductionKind: "K5",
      word: "trades",
      timing: "next_run",
      title: { key: "retention.confirm.title", params: { stream: "trades", n: 7 } },
      body: {
        key: "retention.confirm.body",
        params: { stream: "trades", scope: ["ETHUSDT", "SOLUSDT", "XRPUSDT"], n: 7 },
      },
    },
    [["K1", "trades", null, ["ETHUSDT", "SOLUSDT", "XRPUSDT"]]],
  ],
  [
    "K5 one stream through two rules (the shortest in the title, one line each)",
    edit(
      K1,
      add("ETHUSDT", "trades"),
      act(O("ETHUSDT", "trades"), "drop"),
      days(O("ETHUSDT", "trades"), 3),
    ),
    { symbols: ["ETHUSDT", "SOLUSDT"], pinned: [], applyNow: false },
    {
      reductionKind: "K5",
      word: "trades",
      timing: "next_run",
      title: { key: "retention.confirm.title", params: { stream: "trades", n: 3 } },
      body: { key: "retention.confirm.body_multi", params: { k: 2 } },
    },
    [
      ["K1", "trades", null, ["SOLUSDT"]],
      ["K3", "trades", "ETHUSDT", ETH],
    ],
  ],
  [
    "K6 trades 1000 d Delete after to 30 d Move to Parquet after (1000 d to 24 months)",
    edit(
      load([policy("trades", 1000, "drop")]),
      act(G("trades"), "archive_parquet"),
      days(G("trades"), 30),
    ),
    CTX,
    {
      reductionKind: "K6",
      word: "trades",
      timing: "next_run",
      title: {
        key: "retention.confirm.title_total_move",
        params: { stream: "trades", total: M24 },
      },
      body: {
        key: "retention.confirm.body_total",
        params: { stream: "trades", scope: ETH, total: M24 },
      },
    },
    [["K6", "trades", null, ETH]],
  ],
  [
    "K6 to an 800 d hot window (800 days, never 24 months)",
    edit(
      load([policy("trades", 1000, "drop")]),
      act(G("trades"), "archive_parquet"),
      days(G("trades"), 800),
    ),
    CTX,
    {
      reductionKind: "K6",
      word: "trades",
      timing: "next_run",
      title: {
        key: "retention.confirm.title_total_move",
        params: { stream: "trades", total: { days: 800, seed: false } },
      },
      body: {
        key: "retention.confirm.body_total",
        params: { stream: "trades", scope: ETH, total: { days: 800, seed: false } },
      },
    },
    [["K6", "trades", null, ETH]],
  ],
  [
    "K6 on the ETHUSDT trades override (the symbol typed)",
    edit(
      load([policy("trades", 30, "archive_parquet"), policy("trades", 1000, "drop", "ETHUSDT")]),
      act(O("ETHUSDT", "trades"), "archive_parquet"),
      days(O("ETHUSDT", "trades"), 30),
    ),
    CTX,
    {
      reductionKind: "K6",
      word: "ETHUSDT",
      timing: "next_run",
      title: {
        key: "retention.confirm.title_total_move",
        params: { stream: "trades", total: M24 },
      },
      body: {
        key: "retention.confirm.body_total",
        params: { stream: "trades", scope: ETH, total: M24 },
      },
    },
    [["K6", "trades", "ETHUSDT", ETH]],
  ],
  [
    "K7 trades 1000 d Move to Parquet after lowered to 30 d (1000 d to 24 months)",
    K7,
    CTX,
    {
      reductionKind: "K7",
      word: "trades",
      timing: "next_run",
      title: { key: "retention.confirm.title_total", params: { stream: "trades", total: M24 } },
      body: {
        key: "retention.confirm.body_total",
        params: { stream: "trades", scope: ETH, total: M24 },
      },
    },
    [["K7", "trades", null, ETH]],
  ],
];

describe("classify - the reduction kinds (D03 §5, D03-D5)", () => {
  it.each(KINDS)("classify - %s - typed confirm", (_name, draft, ctx, expected, lines) => {
    const confirm = confirmOf(classify(draft, ctx));
    const { reductionKind, word, title, body, timing } = confirm;
    expect({ reductionKind, word, title, body, timing }).toEqual(expected);
    expect(linesOf(confirm)).toEqual(lines);
  });

  it("classify - K4 and K1 - the removed rule's lead sentence on K4 only", () => {
    expect(confirmOf(classify(K4, CTX)).lines.map((l) => l.lead)).toEqual([
      { key: "retention.confirm.body_removed", params: { symbol: "ETHUSDT" } },
    ]);
    expect(confirmOf(classify(K1, CTX)).lines.map((l) => l.lead)).toEqual([null]);
  });

  it("classify - the worked K1 - BTCUSDT exempt on trades, the totals before and after", () => {
    const result = classify(K1, CTX);
    expect(result).toMatchObject({ exempt: [{ symbol: "BTCUSDT", streams: ["trades"] }] });
    expect(confirmOf(result).lines).toMatchObject([
      { exempt: ["BTCUSDT"], before: { total: 730 }, after: { total: 7 }, effect: "shrink" },
    ]);
  });

  const BODIES: [string, Draft, ClassifyContext, TypedConfirm["body"], TypedConfirm["timing"]][] = [
    [
      "K1 with Apply now",
      K1,
      NOW,
      { key: "retention.confirm.body_now", params: { stream: "trades", scope: ETH, n: 7 } },
      "now",
    ],
    [
      "order-book snapshots (no roll-off) to 7 d Delete after",
      SNAPSHOTS_7,
      CTX,
      {
        key: "retention.confirm.body_cold",
        params: { stream: "orderbook_snapshot", scope: ETH, n: 7 },
      },
      "next_run",
    ],
    [
      "order-book snapshots to 7 d Delete after with Apply now",
      SNAPSHOTS_7,
      NOW,
      {
        key: "retention.confirm.body_cold_now",
        params: { stream: "orderbook_snapshot", scope: ETH, n: 7 },
      },
      "now",
    ],
    [
      "order-book snapshots 1000 d Move to Parquet after to 30 d (the Parquet copy at the total)",
      edit(
        load([policy("orderbook_snapshot", 1000, "archive_parquet")]),
        days(G("orderbook_snapshot"), 30),
      ),
      CTX,
      {
        key: "retention.confirm.body_cold",
        params: { stream: "orderbook_snapshot", scope: ETH, n: 730 },
      },
      "next_run",
    ],
    [
      "K7 with Apply now (the deck has no body_total_now: the timing carries it)",
      K7,
      NOW,
      { key: "retention.confirm.body_total", params: { stream: "trades", scope: ETH, total: M24 } },
      "now",
    ],
  ];
  it.each(BODIES)("classify - %s - body key and timing", (_name, draft, ctx, body, timing) => {
    const confirm = confirmOf(classify(draft, ctx));
    expect([confirm.body, confirm.timing]).toEqual([body, timing]);
  });

  // D03 §14: `{total}` reads "24 months" when the §7 total is the larger, "{n} days" otherwise.
  it.each([
    [729, { days: 730, seed: true }],
    [730, { days: 730, seed: false }],
    [731, { days: 731, seed: false }],
  ] as const)("classify - K7 1000 d lowered to %i d - total %o", (n, total) => {
    const draft = edit(load([policy("trades", 1000, "archive_parquet")]), days(G("trades"), n));
    expect(confirmOf(classify(draft, CTX)).title).toEqual({
      key: "retention.confirm.title_total",
      params: { stream: "trades", total },
    });
  });
});

describe("classify - not a reduction (D03 §3, D03-C9)", () => {
  it("classify - trades 30 to 7 d kept on Move to Parquet, funding 365 to 400 d - tiering: nothing deleted", () => {
    expect(classify(edit(BASE, days(G("trades"), 7), days(G("funding"), 400)), CTX)).toEqual({
      kind: "tiering",
      lines: [
        {
          stream: "trades",
          symbol: null,
          cause: "edited",
          effect: "tier",
          scope: ETH,
          exempt: ["BTCUSDT"],
          before: { days: 30, action: "archive_parquet", hot: 30, total: 730 },
          after: { days: 7, action: "archive_parquet", hot: 7, total: 730 },
        },
        {
          stream: "funding",
          symbol: null,
          cause: "edited",
          effect: "lengthen",
          scope: ETH,
          exempt: ["BTCUSDT"],
          before: { days: 365, action: "archive_parquet", hot: 365, total: null },
          after: { days: 400, action: "archive_parquet", hot: 400, total: null },
        },
      ],
    });
  });

  it("classify - trades 30 to 90 d - lengthen", () => {
    expect(classify(edit(BASE, days(G("trades"), 90)), CTX)).toMatchObject({
      kind: "lengthen",
      lines: [{ stream: "trades", effect: "lengthen", before: { hot: 30 }, after: { hot: 90 } }],
    });
  });

  it("classify - the ETHUSDT deltas override removed, its fallback longer - lengthen (D03 row-removed)", () => {
    expect(classify(edit(BASE, remove(O("ETHUSDT", "orderbook_delta"))), CTX)).toEqual({
      kind: "lengthen",
      lines: [
        {
          stream: "orderbook_delta",
          symbol: "ETHUSDT",
          cause: "removed",
          effect: "lengthen",
          scope: ETH,
          exempt: [],
          before: { days: 3, action: "drop", hot: 3, total: 3 },
          after: { days: 7, action: "archive_parquet", hot: 7, total: 730 },
        },
      ],
    });
  });

  // `read_policy_row` (`21` §3.6.3): a `drop` row's days are its hot window and its total.
  const SERVED: [
    string,
    Classification["kind"],
    Draft,
    Pick<Line, "effect" | "before" | "after">,
  ][] = [
    [
      "Move to Parquet after 100 d to Delete after 800 d (the window and the total grow)",
      "lengthen",
      edit(
        load([policy("trades", 100, "archive_parquet")]),
        act(G("trades"), "drop"),
        days(G("trades"), 800),
      ),
      {
        effect: "lengthen",
        before: { days: 100, action: "archive_parquet", hot: 100, total: 730 },
        after: { days: 800, action: "drop", hot: 800, total: 800 },
      },
    ],
    [
      "Move to Parquet after 30 d to Delete after 730 d (the window grows to the total)",
      "lengthen",
      edit(BASE, act(G("trades"), "drop"), days(G("trades"), 730)),
      {
        effect: "lengthen",
        before: { days: 30, action: "archive_parquet", hot: 30, total: 730 },
        after: { days: 730, action: "drop", hot: 730, total: 730 },
      },
    ],
    [
      "Delete after 100 d to Move to Parquet after 40 d (the window falls, the total grows)",
      "tiering",
      edit(
        load([policy("trades", 100, "drop")]),
        act(G("trades"), "archive_parquet"),
        days(G("trades"), 40),
      ),
      {
        effect: "tier",
        before: { days: 100, action: "drop", hot: 100, total: 100 },
        after: { days: 40, action: "archive_parquet", hot: 40, total: 730 },
      },
    ],
  ];
  it.each(SERVED)(
    "classify - %s - %s, as the served reader reads a drop row",
    (_n, kind, draft, line) => {
      expect(classify(draft, CTX)).toMatchObject({ kind, lines: [{ stream: "trades", ...line }] });
    },
  );

  it("classify - a reduction beside a tiering change - the reduction; its confirm lists the shrink only", () => {
    const confirm = confirmOf(classify(edit(K1, days(G("tickers"), 7)), CTX));
    expect(linesOf(confirm)).toEqual([["K1", "trades", null, ETH]]);
  });

  const NONE: [string, Draft][] = [
    ["the loaded set", BASE],
    ["trades 30 to 7 and back", edit(BASE, days(G("trades"), 7), days(G("trades"), 30))],
    [
      "a pinned-only change (a BTCUSDT trades override at 3 d Delete after)",
      edit(
        BASE,
        add("BTCUSDT", "trades"),
        act(O("BTCUSDT", "trades"), "drop"),
        days(O("BTCUSDT", "trades"), 3),
      ),
    ],
    [
      "an override for a symbol with no recorded data",
      edit(
        BASE,
        add("SOLUSDT", "trades"),
        act(O("SOLUSDT", "trades"), "drop"),
        days(O("SOLUSDT", "trades"), 3),
      ),
    ],
    ["an invalid field (0 d)", edit(BASE, days(G("trades"), 0))],
  ];
  it.each(NONE)("classify - %s - none", (_name, draft) => {
    expect(classify(draft, CTX)).toEqual({ kind: "none" });
  });

  it("classify - a hand-built draft with no rows - none (every pair on its seed)", () => {
    expect(classify({ base: [], rows: [] }, CTX)).toEqual({ kind: "none" });
  });

  it("classify - a pinned-only change - none, yet a change to send", () => {
    const draft = edit(BASE, add("BTCUSDT", "trades"), act(O("BTCUSDT", "trades"), "drop"));
    expect([classify(draft, CTX).kind, hasChanges(draft)]).toEqual(["none", true]);
  });
});

/** No storage report (`GET /recording/storage` answers 503 before its first sample): `symbolsOf(null)`. */
const NO_REPORT: ClassifyContext = { symbols: null, pinned: [], applyNow: false };

describe("classify - no storage report: which symbols hold data, or are pinned, is unknown", () => {
  it("classify - the worked K1 with no report - a reduction over an unknown scope, never none", () => {
    const { reductionKind, word, title, body } = confirmOf(classify(K1, NO_REPORT));
    expect({ reductionKind, word, title, body }).toEqual({
      reductionKind: "K1",
      word: "trades",
      title: { key: "retention.confirm.title", params: { stream: "trades", n: 7 } },
      body: { key: "retention.confirm.body", params: { stream: "trades", scope: null, n: 7 } },
    });
    expect(linesOf(confirmOf(classify(K1, NO_REPORT)))).toEqual([["K1", "trades", null, null]]);
    // A report that lists no symbol is known: nothing is recorded, so nothing is deleted.
    expect(classify(K1, { symbols: [], pinned: [], applyNow: false })).toEqual({ kind: "none" });
  });

  const OVERRIDES: [string, Draft, [LineKind, StreamKind, string, string[]][]][] = [
    [
      "the ETHUSDT order-book deltas override lowered to 2 d",
      edit(BASE, days(O("ETHUSDT", "orderbook_delta"), 2)),
      [["K3", "orderbook_delta", "ETHUSDT", ETH]],
    ],
    [
      "a BTCUSDT trades override at 3 d Delete after (no pin is known)",
      edit(
        BASE,
        add("BTCUSDT", "trades"),
        act(O("BTCUSDT", "trades"), "drop"),
        days(O("BTCUSDT", "trades"), 3),
      ),
      [["K3", "trades", "BTCUSDT", ["BTCUSDT"]]],
    ],
    [
      "the ETHUSDT trades rule removed onto a 7 d Delete-after rule",
      K4,
      [["K4", "trades", "ETHUSDT", ETH]],
    ],
  ];
  it.each(OVERRIDES)(
    "classify - %s with no report - a reduction over its symbol",
    (_n, draft, lines) => {
      expect(linesOf(confirmOf(classify(draft, NO_REPORT)))).toEqual(lines);
    },
  );

  it("classify - trades and order-book deltas shrink with no report - K5, every line over an unknown scope", () => {
    const draft = edit(K1, act(G("orderbook_delta"), "drop"));
    const confirm = confirmOf(classify(draft, NO_REPORT));
    expect([confirm.reductionKind, confirm.word]).toEqual(["K5", "all streams"]);
    expect(linesOf(confirm)).toEqual([
      ["K1", "trades", null, null],
      ["K1", "orderbook_delta", null, null],
    ]);
  });

  it("classify - trades 30 to 90 d, and no edit, with no report - lengthen over an unknown scope; none", () => {
    expect(classify(edit(BASE, days(G("trades"), 90)), NO_REPORT)).toMatchObject({
      kind: "lengthen",
      lines: [{ stream: "trades", symbol: null, scope: null, exempt: [] }],
    });
    expect(classify(BASE, NO_REPORT)).toEqual({ kind: "none" });
  });
});

/**
 * The invariants over a deterministic grid (no randomness): one row before and after an edit, over
 * seven day counts (the bounds, the hot seeds and the §7 total's edges) and both offered actions, on
 * the trades and klines global rows (a finite and an infinite §7 total) and on an ETHUSDT and a
 * BTCUSDT (pinned) trades override that may be absent (842 cases). The reference reads a row as `read_policy_row` does (`21` §3.6.3): its days are
 * the hot window, its total the days for `drop` and max(the days, the §7 total) for
 * `archive_parquet`.
 */
describe("classify, toRequest - the invariants over a deterministic grid (D03 §3; 21 §3.6.3)", () => {
  type State = readonly [n: number, action: OfferedAction];
  interface Case {
    readonly name: string;
    readonly symbol: string | null;
    readonly stream: StreamKind;
    readonly from: State | null;
    readonly to: State | null;
    readonly draft: Draft;
    readonly undone: Draft;
  }
  const STATES = [1, 7, 30, 729, 730, 731, 3650].flatMap((n) =>
    OFFERED_ACTIONS.map((action): State => [n, action]),
  );
  const SEEDED: State = [SEED.trades.hotDays, "archive_parquet"];
  const CASES: Case[] = [];
  for (const stream of ["trades", "klines"] as const) {
    for (const from of STATES) {
      for (const to of STATES) {
        const draft = edit(
          load([policy(stream, ...from)]),
          act(G(stream), to[1]),
          days(G(stream), to[0]),
        );
        const undone = edit(draft, act(G(stream), from[1]), days(G(stream), from[0]));
        CASES.push({
          name: `${stream} ${from} -> ${to}`,
          symbol: null,
          stream,
          from,
          to,
          draft,
          undone,
        });
      }
    }
  }
  for (const symbol of ["ETHUSDT", "BTCUSDT"]) {
    const key = O(symbol, "trades");
    for (const from of [null, ...STATES]) {
      for (const to of [null, ...STATES]) {
        const base = load(from === null ? [] : [policy("trades", ...from, symbol)]);
        const set = (state: State): Step[] => [act(key, state[1]), days(key, state[0])];
        const draft =
          to === null
            ? edit(base, remove(key))
            : edit(base, ...(from === null ? [add(symbol, "trades")] : []), ...set(to));
        const undone =
          to === null
            ? undoRemoval(draft, key)
            : edit(draft, ...(from === null ? [remove(key)] : set(from)));
        const name = `${symbol} trades ${from} -> ${to}`;
        CASES.push({ name, symbol, stream: "trades", from, to, draft, undone });
      }
    }
  }
  /** The served reading of the edited pair, before or after (no row: the global trades seed). */
  const served = (stream: StreamKind, state: State | null) => {
    const [n, action] = state ?? SEEDED;
    const total = SEED[stream].totalDays;
    return {
      hot: n,
      total: action === "drop" ? n : total === null ? Number.POSITIVE_INFINITY : Math.max(n, total),
    };
  };
  const expected = ({ stream, from, to }: Case): Classification["kind"] => {
    const [a, b] = [served(stream, from), served(stream, to)];
    if (b.total < a.total) return "reduction";
    if (b.hot < a.hot) return "tiering";
    return b.total > a.total || b.hot > a.hot ? "lengthen" : "none";
  };
  const results = new Map<Case, Classification>();
  const classified = (c: Case): Classification => {
    const result = results.get(c) ?? classify(c.draft, CTX);
    results.set(c, result);
    return result;
  };
  const linesIn = (c: Classification): readonly Line[] =>
    c.kind === "reduction" ? c.confirm.lines : c.kind === "none" ? [] : c.lines;
  const failing = (check: (c: Case) => boolean): string[] =>
    CASES.filter((c) => !check(c)).map((c) => c.name);

  it("the grid - 842 cases", () => {
    expect(CASES).toHaveLength(2 * 14 * 14 + 2 * 15 * 15);
  });

  it("classify - every case - a reduction iff a non-pinned pair's total shrinks, else the served reading", () => {
    expect(
      failing((c) => classified(c).kind === (c.symbol === "BTCUSDT" ? "none" : expected(c))),
    ).toEqual([]);
  });

  it("classify - every case with no report - a reduction iff the pair's total shrinks, pinned or not", () => {
    expect(
      failing(
        (c) =>
          (classify(c.draft, NO_REPORT).kind === "reduction") === (expected(c) === "reduction"),
      ),
    ).toEqual([]);
  });

  it("classify - every case - no line's scope holds a pinned symbol; every exempt row is pinned", () => {
    expect(
      failing((c) => {
        const result = classified(c);
        const exempt = result.kind === "reduction" ? result.exempt.map((row) => row.symbol) : [];
        const scopes = linesIn(result).flatMap((line) => line.scope ?? []);
        return !scopes.includes("BTCUSDT") && exempt.every((symbol) => symbol === "BTCUSDT");
      }),
    ).toEqual([]);
  });

  it("toRequest - every case - the eight global rows first in the contract's order, no key twice", () => {
    expect(
      failing((c) => {
        const items = toRequest(c.draft).items;
        const keys = items.map((item) => `${item.symbol ?? ""}/${item.stream}`);
        const globals = items.slice(0, 8).map((item) => `${item.symbol ?? ""}/${item.stream}`);
        return (
          new Set(keys).size === keys.length &&
          globals.join() === STREAMS.map((s) => `/${s}`).join()
        );
      }),
    ).toEqual([]);
  });

  it("classify, hasChanges - every edit undone - none, and nothing to send", () => {
    expect(
      failing((c) => classify(c.undone, CTX).kind === "none" && !hasChanges(c.undone)),
    ).toEqual([]);
  });
});
