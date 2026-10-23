import { describe, expect, expectTypeOf, it } from "vitest";
import type { GraphNode } from "../src/model.js";
import { NODE_PORTS, PORT_COMPAT, PORT_TYPES, canConnect, portTypeOfMetric } from "../src/ports.js";
import { portsOf, type MetricUnit, type MetricValueType, type PortType } from "../src/ports.js";

// Each ordered pair's verdict: a row per output type, a column per input type, in PORT_TYPES order.
const CONNECTS = ["Y---Y-", "-YY---", "-YY---", "---Y--", "------", "------"];
const PAIRS = PORT_TYPES.flatMap((from, i) =>
  PORT_TYPES.map((to, j) => [from, to, CONNECTS[i]?.[j] === "Y"] as const),
);
const WORDS: Partial<Record<PortType, string>> = { boolean: "true or false" }; // else its name
const words = (type: PortType) => new RegExp(`\\b${WORDS[type] ?? type}\\b`);
const SV = expect.objectContaining({ code: "SCHEMA_VIOLATION" });
const of = (type: unknown, data?: unknown) => portsOf({ id: "n1", type, data } as GraphNode);

describe("PORT_COMPAT and canConnect", () => {
  it("hold one 6 x 6 table over the six port types, in order", () => {
    expect(PORT_TYPES).toEqual(["boolean", "number", "price", "side", "action", "trigger"]);
    for (const row of [PORT_COMPAT, ...Object.values(PORT_COMPAT)]) {
      expect(Object.keys(row)).toEqual(PORT_TYPES);
    }
  });

  it.each(PAIRS)("join a %s output to a %s input: %s", (from, to, connects) => {
    const cell = PORT_COMPAT[from][to];
    expect(cell === true).toBe(connects);
    expect(canConnect(from, to)).toEqual(connects ? { ok: true } : { ok: false, reason: cell });
  });

  // OQ9, as the coordinator ruled: E09-D09 §3.1's reason rule (docs/design/E09/E09-D09.md:85).
  it("give each refused pair its own sentence: one, a full stop, 80 characters, no data", () => {
    const reasons = PAIRS.filter(([, , connects]) => !connects).map(([from, to]) => {
      const reason = String(PORT_COMPAT[from][to]);
      // "A <type> can't <capability>.": words alone, so no figure, symbol, name or second sentence.
      const [, subject, capability] = /^(An? [a-z ]+) can't ([a-z ]+)\.$/.exec(reason) ?? [];
      expect(reason.length, reason).toBeLessThanOrEqual(80);
      expect(subject, reason).toMatch(words(from)); // the output's type, in plain words
      expect(capability, reason).toMatch(words(to)); // what the input needs, in plain words
      return reason;
    });
    expect(new Set(reasons).size).toBe(29);
  });

  it("refuse a type that is no port type, and keep the tables frozen", () => {
    expect(() => canConnect("flag" as PortType, "boolean")).toThrow(SV);
    expect(() => canConnect("number", "constructor" as PortType)).toThrow(SV);
    const tables = [PORT_TYPES, PORT_COMPAT, PORT_COMPAT.side, NODE_PORTS, NODE_PORTS.comparison];
    expect([...tables, NODE_PORTS.comparison.inputs].every((t) => Object.isFrozen(t))).toBe(true);
  });
});

describe("portsOf", () => {
  it("give each node kind its output's type and its inputs', in order", () => {
    const seen = Object.entries(NODE_PORTS).map(([name, { type }]) => {
      const { kind, output, inputs } = of(type, type === "condition" ? { kind: name } : {});
      return `${kind}:${String(output)}<${inputs.map((port) => port.join(":")).join(",")}`;
    });
    const head = "trigger:trigger< comment:null< action:null<when:action";
    const gates = "logicGate:boolean<in:boolean comparison:boolean<left:number,right:number";
    const tail = "temporal:boolean<child:boolean arithmetic:number<in:number";
    expect(seen.join(" ")).toBe(`${head} ${gates} ${tail}`);
  });

  it("give a comparison the operands its op takes, as the server counts them (graph.py)", () => {
    const ops = { 1: "is_true is_false changed in_set not_in_set", 2: "gt", 3: "between outside" };
    for (const [n, names] of Object.entries(ops)) {
      for (const op of [...names.split(" "), ...(n === "2" ? [undefined, 5, "constructor"] : [])]) {
        const ports = of("condition", { kind: "comparison", op }).inputs.map(([port]) => port);
        expect(ports, String(op)).toEqual(["left", "right", "right2"].slice(0, Number(n)));
      }
    }
  });

  it("refuse a node of no known kind, a condition of another kind, or a node with no data", () => {
    for (const type of ["gate", "constructor", "condition", undefined]) {
      expect(() => of(type, {}), String(type)).toThrow(SV); // a condition needs its kind in data
    }
    expect(() => of("condition", { kind: "action" })).toThrow(SV);
    expect(() => of("action", null)).toThrow(SV);
    expect(() => portsOf({ id: 7, type: "action", data: {} } as never)).toThrow(SV);
    expect(() => portsOf(null as never)).toThrow(SV);
  });
});

describe("portTypeOfMetric", () => {
  // The units and value types of a metric descriptor (rules/vocabulary/registry.py:14-17).
  const NUMBERS = ["qty", "notional", "ratio", "pct", "bps", "count", "ms", "zscore"] as const;

  it("type a metric by its unit: a price, a side for an enum, true or false, else a number", () => {
    const own = ["price", "enum", "bool"].map((unit) =>
      portTypeOfMetric(unit as MetricUnit, "enum"),
    );
    expect(own).toEqual(["price", "side", "boolean"]); // the unit decides, as build.py:32-38
    for (const unit of NUMBERS) expect(portTypeOfMetric(unit, "number"), unit).toBe("number");
    expect(portTypeOfMetric("price", "series")).toBeUndefined(); // a series is not one value
    for (const unit of ["usd", "constructor"]) {
      expect(portTypeOfMetric(unit as MetricUnit, "number"), unit).toBeUndefined();
    }
    type Own = "price" | "enum" | "bool";
    expectTypeOf<MetricUnit>().toEqualTypeOf<(typeof NUMBERS)[number] | Own>();
    expectTypeOf<MetricValueType>().toEqualTypeOf<"number" | "bool" | "enum" | "series">();
  });
});
