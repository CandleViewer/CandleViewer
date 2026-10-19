import { describe, expect, it, expectTypeOf } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { generated } from "../src/index.js";

type Payload = generated.ws.IndicatorsSymbolBarTypeParam;
type Point = Payload["instances"][number]["points"][number];
type Options = generated.ws.IndicatorOptions;

interface SchemaNode {
  $ref?: string;
  pattern?: string;
  required?: string[];
  additionalProperties?: boolean | SchemaNode;
  properties?: Record<string, SchemaNode>;
  items?: SchemaNode;
  oneOf?: SchemaNode[];
  anyOf?: SchemaNode[];
  $defs?: Record<string, SchemaNode>;
}

const here = dirname(fileURLToPath(import.meta.url));
const { schemas } = JSON.parse(readFileSync(join(here, "..", "ws-schemas.json"), "utf8")) as {
  schemas: Record<string, SchemaNode>;
};
const schemaOf = (name: string): SchemaNode => schemas[`cv://ws/v1/${name}.schema.json`] ?? {};
const keys = (node: SchemaNode | undefined): string => [...(node?.required ?? [])].sort().join();

describe("indicators.{symbol}.{bar_type}.{param} (consumer side, 23-ws-protocol §6.1/§14.10)", () => {
  it("types the payload as the topic map's entry, with closed points", () => {
    type Entry = generated.ws.WsTopicPayloadMap["indicators.{symbol}.{bar_type}.{param}"];
    expectTypeOf<Entry>().toEqualTypeOf<Payload>();
    expectTypeOf<Point["v"][number]>().toEqualTypeOf<string | null>();
    expectTypeOf<Point["amended"]>().toEqualTypeOf<boolean | undefined>();
    expectTypeOf<Point>().not.toHaveProperty("confirm"); // only closed bars are served
  });

  it("reads a value back as the kernel's float64, written without an exponent", () => {
    const plain = new RegExp(schemaOf("common").$defs?.["decimal"]?.pattern ?? "$^");
    expect(plain.test("0.0000001") && !plain.test(String(1e-7))).toBe(true); // never "1e-7"
    expect(Object.is(Number("0.0000001"), 1e-7)).toBe(true);
  });

  it("closes the bundled payload schema, keyed per instance and per point", () => {
    const payload = schemaOf("indicators");
    const instance = payload.properties?.["instances"]?.items;
    const pointNode = instance?.properties?.["points"]?.items;
    expect([payload, instance, pointNode].map((n) => n?.additionalProperties)).toEqual([
      false,
      false,
      false,
    ]);
    expect(keys(payload)).toBe("bar_type,instances,param,symbol");
    expect(keys(instance)).toBe("build_version,indicator,key,outputs,params,points");
    expect(keys(pointNode)).toBe("generation,index,t_ms,v");
    expect(pointNode?.properties?.["v"]?.items?.oneOf).toEqual([
      { $ref: "cv://ws/v1/common.schema.json#/$defs/decimal" },
      { type: "null" },
    ]);
  });

  it("subscribes with the closed indicatorOptions, instances required, and retunes them by ctl", () => {
    expectTypeOf<{ history: number }>().not.toExtend<Options>();
    expectTypeOf<generated.ws.CvWsV1CtlSchemaJson>().toHaveProperty("instances");
    const opts: Options = { instances: [{ indicator: "ema", params: { n: 21 } }], history: 500 };
    expect(opts.instances).toHaveLength(1);
    const sub = schemaOf("sub");
    expect(sub.properties?.["topics"]?.items?.properties?.["opts"]?.anyOf).toEqual([
      { $ref: "#/$defs/options" },
      { $ref: "#/$defs/indicatorOptions" },
    ]);
    expect(sub.$defs?.["indicatorOptions"]).toMatchObject({
      required: ["instances"],
      additionalProperties: false,
    });
    const entry = "cv://ws/v1/common.schema.json#/$defs/indicatorInstance";
    expect(sub.$defs?.["indicatorOptions"]?.properties?.["instances"]?.items?.$ref).toBe(entry);
    expect(schemaOf("ctl").properties?.["instances"]?.items?.$ref).toBe(entry);
    expect(schemaOf("common").$defs?.["indicatorInstance"]?.additionalProperties).toBe(false);
  });
});
