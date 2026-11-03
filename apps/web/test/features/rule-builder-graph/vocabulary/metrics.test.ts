import { describe, expect, it } from "vitest";
import {
  categoryOf,
  metricOptions,
  operatorsFor,
  type MetricCategory,
} from "../../../../src/features/rule-builder-graph/model/vocabulary/metrics.js";
import type { VocabularySignal } from "../../../../src/features/rule-builder-graph/model/vocabulary/types.js";
import { extended, served } from "./fixtures.js";

/** The 13 signals the registry marks estimated (`confidence != "exact"`), as served. */
const ESTIMATED = [
  "absorption",
  "adl_risk_proxy",
  "cvd_divergence",
  "delta_divergence",
  "exhaustion",
  "hurst",
  "iceberg_executed_volume",
  "iceberg_present_at_level",
  "in_stop_hunt_zone",
  "market_regime",
  "queue_position_estimate",
  "stop_run_detected",
  "trade_cluster",
];
const SOLUSDT = { method: "POST", path: "/api/v1/recording/symbols", body: { symbol: "SOLUSDT" } };

describe("metric options over the server-written vocabulary (E37-S02)", () => {
  it("Gherkin 'The whole vocabulary is reachable on canvas': every served signal is an option with its display name, unit and description; a new one shows with no client change", () => {
    const vocabulary = served("manager");
    const options = metricOptions(vocabulary);
    expect(options).toHaveLength(105);
    expect(options.map((o) => o.id)).toEqual(vocabulary.signals.map((s) => s.id));
    vocabulary.signals.forEach((s, i) =>
      expect(options[i], s.id).toMatchObject({
        label: s.display_name,
        unit: s.unit,
        description: s.description,
      }),
    );
    expect(metricOptions(extended()).at(-1)).toEqual({
      id: "zz_new_metric",
      label: "New metric",
      unit: "ratio",
      description: "A metric no client table names",
      category: "position",
      estimated: true,
      available: true,
      unavailableReason: undefined,
      missingInputs: [],
      recorderAction: undefined,
    });
  });

  it("puts each signal in E36-D01 R2's category by its served scope and inputs: 13, 41, 16, 11, 13, 8 and 3", () => {
    const counts: Partial<Record<MetricCategory, number>> = {};
    for (const o of metricOptions(served("owner")))
      counts[o.category] = (counts[o.category] ?? 0) + 1;
    expect(counts).toEqual({
      price: 13,
      orderflow: 41,
      book: 16,
      derivatives: 11,
      position: 13,
      account: 8,
      replay: 3,
    });
    const by = new Map(metricOptions(served("owner")).map((o) => [o.id, o.category]));
    expect(
      ["atr", "cvd", "spread_bps", "funding_rate", "queue_position_estimate", "drawdown_pct"].map(
        (id) => by.get(id),
      ),
    ).toEqual(["price", "orderflow", "book", "derivatives", "position", "account"]);
    expect(by.get("replay_speed")).toBe("replay");
  });

  it("reads a bare signal: no scope is a symbol's (by its inputs), no display name its id (P1)", () => {
    const bare = (dependencies?: string[]): VocabularySignal => ({
      id: "x",
      type: "number",
      estimated: false,
      available: true,
      requires_recording: false,
      ...(dependencies === undefined ? {} : { dependencies }),
    });
    expect([bare(["liquidations"]), bare(["positions"]), bare()].map(categoryOf)).toEqual([
      "derivatives",
      "price",
      "price",
    ]);
    // Served with no display name, unit or description, it still shows: by its id (P1), with no unit.
    expect(metricOptions({ ...served("manager"), signals: [bare()] })).toEqual([
      expect.objectContaining({ id: "x", label: "x", unit: undefined, description: "" }),
    ]);
  });

  it("Gherkin 'Estimated metrics are badged as text': the served flag alone marks an option estimated, 13 of 105, distance_to_liquidity_cluster exact", () => {
    const options = metricOptions(served("manager"));
    expect(
      options
        .filter((o) => o.estimated)
        .map((o) => o.id)
        .sort(),
    ).toEqual(ESTIMATED);
    expect(options.find((o) => o.id === "distance_to_liquidity_cluster")?.estimated).toBe(false);
    expect(metricOptions(extended()).filter((o) => o.estimated)).toHaveLength(14);
  });

  it("Gherkin 'Unavailable metric is explained, not hidden': on the unrecorded fixture every signal stays an option, each unavailable one naming SOLUSDT, its missing inputs and the recorder action", () => {
    const options = metricOptions(served("unrecorded-solusdt"));
    expect(options).toHaveLength(105);
    const unavailable = options.filter((o) => !o.available);
    expect(unavailable).toHaveLength(63);
    for (const o of unavailable) {
      expect(o.unavailableReason, o.id).toBe("SOLUSDT is not on the recorded-symbol list");
      expect(o.missingInputs.length, o.id).toBeGreaterThan(0);
      expect(o.recorderAction, o.id).toEqual(SOLUSDT);
    }
    const tape = options.find((o) => o.id === "tape_speed");
    expect([tape?.available, tape?.missingInputs]).toEqual([false, ["trades"]]);
    expect(options.find((o) => o.id === "atr")).toMatchObject({
      available: true,
      unavailableReason: undefined,
      missingInputs: [],
      recorderAction: undefined,
    });
  });
});

describe("the operators a metric can take (E37-S02)", () => {
  const { operators } = served("manager");
  const ids = (unit: string | undefined): string[] =>
    operatorsFor({ unit }, operators).map((o) => o.id);

  it("offers the served operators whose operand units include the metric's, each with its arity and E36-D05 verb", () => {
    expect(ids("bool")).toEqual(["eq", "neq", "changed", "is_true", "is_false"]);
    expect(ids("enum")).toEqual(["eq", "neq", "changed", "in_set", "not_in_set"]);
    expect(ids("price")).toEqual([
      "gt",
      "gte",
      "lt",
      "lte",
      "crosses_above",
      "crosses_below",
      "eq",
      "neq",
      "between",
      "outside",
      "changed",
    ]);
    const price = operatorsFor({ unit: "price" }, operators);
    expect(price.find((o) => o.id === "between")).toEqual({
      id: "between",
      arity: 3,
      verb: "is between {a} and {b}",
    });
    expect(price.find((o) => o.id === "gte")?.verb).toBe("is at least");
    expect(ids(undefined)).toEqual([]);
  });

  it("an operator with no keyed verb reads by its id, so a new one shows with no client change", () => {
    expect(operatorsFor({ unit: "bool" }, operators).at(-1)).toEqual({
      id: "is_false",
      arity: 1,
      verb: "is_false",
    });
    expect(operatorsFor({ unit: "ratio" }, extended().operators).at(-1)).toEqual({
      id: "zz_new_op",
      arity: 2,
      verb: "zz_new_op",
    });
    // The generated shape makes id, arity and operand_types optional: an entry without them is skipped or read
    // with a value's arity.
    expect(
      operatorsFor({ unit: "ratio" }, [{}, { id: "w" }, { id: "x", operand_types: ["ratio"] }]),
    ).toEqual([{ id: "x", arity: 2, verb: "x" }]);
  });
});
