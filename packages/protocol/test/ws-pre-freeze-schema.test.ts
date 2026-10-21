import { describe, expect, it, expectTypeOf } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { generated } from "../src/index.js";

// E17-T07 (#572): the tightenings of 23-ws-protocol.md section 13 that had to land before cv.v1
// froze, because a later one is breaking (C-6.3). The Python twin, which validates real frames
// against these schemas, is services/api/tests/contract/ws/test_ws_schema_tightenings.py.

interface SchemaNode {
  $ref?: string;
  type?: string;
  minimum?: number;
  required?: string[];
  properties?: Record<string, SchemaNode>;
  $defs?: Record<string, SchemaNode>;
  items?: SchemaNode;
  allOf?: { if: SchemaNode; then: SchemaNode }[];
}

const here = dirname(fileURLToPath(import.meta.url));
const bundle = JSON.parse(readFileSync(join(here, "..", "ws-schemas.json"), "utf8")) as {
  schemas: Record<string, SchemaNode>;
};

function schemaOf(name: string): SchemaNode {
  const schema = bundle.schemas[`cv://ws/v1/${name}.schema.json`];
  if (schema === undefined) {
    throw new Error(`ws-schemas.json has no ${name} schema`);
  }
  return schema;
}

/** The `then` of the envelope clause that applies when `t` is `type`. */
function whenType(type: string): SchemaNode {
  const clause = schemaOf("envelope").allOf?.find(
    (c) => (c.if.properties?.["t"] as { const?: string } | undefined)?.const === type,
  );
  if (clause === undefined) {
    throw new Error(`the envelope has no clause for t: ${type}`);
  }
  return clause.then;
}

describe("the pre-freeze tightenings of 23-ws-protocol section 13", () => {
  it("requires s on every snap and an integer s on every d", () => {
    expect(whenType("snap").required).toContain("s");
    expect(whenType("d").required).toContain("s");
    expect(whenType("d").properties?.["s"]).toEqual({ type: "integer" });
  });

  it("types a sub_ok result's sub_id as the subId definition", () => {
    const result = schemaOf("sub_ok").properties?.["results"]?.items;
    expect(result?.properties?.["sub_id"]?.$ref).toBe("cv://ws/v1/common.schema.json#/$defs/subId");
  });

  it("requires every limit a welcome carries, max_symbols_per_connection included", () => {
    const limits = schemaOf("welcome").properties?.["limits"];
    expect(limits?.required).toContain("max_symbols_per_connection");
    expect([...(limits?.required ?? [])].sort()).toEqual(
      Object.keys(limits?.properties ?? {}).sort(),
    );
    type Limits = generated.ws.CvWsV1WelcomeSchemaJson["limits"];
    expectTypeOf<Limits["max_symbols_per_connection"]>().toEqualTypeOf<number>();
  });
});

describe("the option bounds of 23-ws-protocol section 13.5 and 13.6 (#572, set before the freeze)", () => {
  const options = schemaOf("sub").$defs?.["options"]?.properties;
  const indicatorOptions = schemaOf("sub").$defs?.["indicatorOptions"]?.properties;

  it("types from_seq as a whole number, never null, on both option sets", () => {
    for (const set of [options, indicatorOptions]) {
      expect(set?.["from_seq"]).toEqual({ type: "integer", minimum: 0 });
    }
  });

  it("bounds the list options as the registry does", () => {
    expect(options?.["metrics"]).toMatchObject({
      minItems: 1,
      maxItems: 12,
      items: { minLength: 1, maxLength: 64 },
    });
    expect(options?.["symbols"]).toMatchObject({ minItems: 1, maxItems: 40 });
    expect(options?.["status"]).toMatchObject({
      maxItems: 16,
      items: { minLength: 1, maxLength: 64 },
    });
    expect(options?.["rule_ids"]).toMatchObject({ maxItems: 100 });
    expect(schemaOf("ctl").properties?.["metrics"]).toMatchObject({ minItems: 1, maxItems: 12 });
  });
});
