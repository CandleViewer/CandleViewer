import { describe, expect, it } from "vitest";
import {
  paramFields,
  withFixedValues,
  type ParamField,
} from "../../../../src/features/rule-builder-graph/model/vocabulary/paramFields.js";
import type {
  RuleVocabulary,
  VocabularyAction,
} from "../../../../src/features/rule-builder-graph/model/vocabulary/types.js";
import { extended, served, type Persona } from "./fixtures.js";

const PERSONAS: readonly Persona[] = ["owner", "manager", "no-orders-write", "unrecorded-solusdt"];

const actionOf = (vocabulary: RuleVocabulary, id: string): VocabularyAction => {
  const action = vocabulary.actions.find((a) => a.id === id);
  if (action === undefined) throw new Error(`${id} is not served`);
  return action;
};

/** A field as the inspector reads it: name, kind, required, and the served values that are set. */
const brief = (field: ParamField): Record<string, unknown> =>
  Object.fromEntries(
    Object.entries(field).filter(
      ([key, value]) =>
        key === "name" ||
        key === "kind" ||
        (value !== undefined && value !== false && !(Array.isArray(value) && value.length === 0)),
    ),
  );

const fieldsOf = (id: string): Record<string, unknown>[] =>
  paramFields(actionOf(served("owner"), id)).map(brief);

describe("parameter fields over the served params_schema (E37-S02)", () => {
  it("Gherkin 'The whole vocabulary is reachable on canvas': every served parameter is a field, in the order served, with its kind, requirement and served values; a new parameter needs no client change", () => {
    for (const action of served("owner").actions) {
      const properties = action.params_schema?.["properties"] as Record<string, unknown>;
      expect(
        paramFields(action).map((f) => f.name),
        action.id,
      ).toEqual(Object.keys(properties));
    }
    expect(fieldsOf("place_order")).toEqual([
      { name: "algo", kind: "group" },
      { name: "order_type", kind: "choice", required: true, options: ["market", "limit"] },
      { name: "price", kind: "number" },
      { name: "profile", kind: "text" },
      { name: "qty", kind: "number", exclusiveMinimum: 0 },
      { name: "qty_mode", kind: "text", required: true },
      { name: "side", kind: "choice", required: true, options: ["buy", "sell"] },
      { name: "stop_loss", kind: "nativeStop" },
      { name: "take_profits", kind: "list" },
    ]);
    expect(fieldsOf("scale_out")).toEqual([
      { name: "order_type", kind: "choice", required: true, options: ["market", "limit"] },
      { name: "qty", kind: "number", exclusiveMinimum: 0 },
      { name: "qty_pct", kind: "number", exclusiveMinimum: 0, maximum: 100 },
    ]);
    expect([
      ...fieldsOf("move_to_breakeven"),
      ...fieldsOf("flatten_position"),
      ...fieldsOf("set_variable"),
      ...fieldsOf("halt_new_orders"),
    ]).toEqual([
      { name: "offset_ticks", kind: "integer", initial: 2 },
      { name: "symbols", kind: "list", items: "text" },
      { name: "name", kind: "text", required: true },
      { name: "ttl_ms", kind: "integer" },
      { name: "value", kind: "value", required: true },
      { name: "scope", kind: "text", required: true },
      {
        name: "until",
        kind: "choice",
        required: true,
        options: ["next_utc_day", "duration_ms", "manual"],
      },
    ]);
    expect(fieldsOf("reverse_position")).toEqual([]);
    const fresh: VocabularyAction = {
      ...actionOf(extended(), "zz_new_action"),
      params_schema: {
        type: "object",
        properties: { zz_window: { type: "integer", minimum: 1 }, zz_mode: { enum: ["a", 2, {}] } },
        required: ["zz_window"],
      },
    };
    expect(paramFields(fresh).map(brief)).toEqual([
      { name: "zz_window", kind: "integer", required: true, minimum: 1 },
      { name: "zz_mode", kind: "choice", options: ["a", 2] },
    ]);
  });

  it("rules never loosen a stop: only_tighten is a fixed field at true wherever it is served, never a control that offers false", () => {
    for (const persona of PERSONAS) {
      for (const action of served(persona).actions) {
        const field = paramFields(action).find((f) => f.name === "only_tighten");
        if (field !== undefined) {
          expect(brief(field), `${persona} ${action.id}`).toEqual({
            name: "only_tighten",
            kind: "fixed",
            initial: true,
          });
        }
      }
    }
    const holders = served("owner").actions.filter((a) =>
      paramFields(a).some((f) => f.kind === "fixed"),
    );
    expect(holders.map((a) => a.id)).toEqual([
      "modify_stop_loss",
      "modify_take_profit",
      "tighten_stop",
    ]);
  });

  it("a write never carries only_tighten: false: it takes true, an absent one stays absent, and every other parameter is kept as given", () => {
    const stop = actionOf(served("owner"), "modify_stop_loss");
    const given = { mode: "atr", value: 2, only_tighten: false };
    expect(withFixedValues(stop, given)).toEqual({ mode: "atr", value: 2, only_tighten: true });
    expect(given.only_tighten).toBe(false); // the caller's object is not changed
    expect(withFixedValues(stop, { mode: "atr", value: 2 })).toEqual({ mode: "atr", value: 2 });
    expect(withFixedValues(stop, { only_tighten: true })).toEqual({ only_tighten: true });
    const halt = actionOf(served("owner"), "halt_new_orders");
    expect(withFixedValues(halt, { scope: "account", until: "manual" })).toEqual({
      scope: "account",
      until: "manual",
    });
  });

  it("place_order's stop_loss is its native stop field, on no other action; on an action that places no orders it is its schema's kind", () => {
    for (const action of served("owner").actions) {
      const stops = paramFields(action).filter((f) => f.kind === "nativeStop");
      expect(
        stops.map((f) => f.name),
        action.id,
      ).toEqual(action.id === "place_order" ? ["stop_loss"] : []);
    }
    const order = actionOf(served("owner"), "place_order");
    const stopOf = (action: VocabularyAction) =>
      paramFields(action).find((f) => f.name === "stop_loss")?.kind;
    expect([stopOf(order), stopOf({ ...order, places_orders: false })]).toEqual([
      "nativeStop",
      "group",
    ]);
  });

  it("reads a bare or malformed schema as no field, and a bare property as a free value", () => {
    const halt = actionOf(served("owner"), "halt_new_orders");
    const unschemed = { ...halt };
    Reflect.deleteProperty(unschemed, "params_schema");
    expect(paramFields(unschemed)).toEqual([]);
    expect(paramFields({ ...halt, params_schema: { properties: ["scope"] } })).toEqual([]);
    expect(
      paramFields({
        ...halt,
        params_schema: { properties: { x: true, y: { type: "date" } }, required: "x" },
      }).map(brief),
    ).toEqual([
      { name: "x", kind: "value" },
      { name: "y", kind: "value" },
    ]);
  });
});
