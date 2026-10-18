import { describe, expect, it, expectTypeOf } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { generated } from "../src/index.js";

type Meta = NonNullable<generated.ws.CandleViewerWSEnvelope["meta"]>;
type BarsPayload = generated.ws.BarsSymbolBarTypeParam;

interface SchemaNode {
  $ref?: string;
  type?: string;
  default?: unknown;
  additionalProperties?: boolean;
  properties?: Record<string, SchemaNode>;
  $defs?: Record<string, SchemaNode>;
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

describe("snapshot staleness is meta.stale (consumer side, 23-ws-protocol §7.2/§13)", () => {
  it("types stale as an optional boolean on the envelope's meta", () => {
    expectTypeOf<Meta>().toHaveProperty("stale");
    expectTypeOf<Meta["stale"]>().toEqualTypeOf<boolean | undefined>();
    // Guards the lines above: they would pass vacuously if `Meta` widened to an open record.
    expectTypeOf<Meta>().not.toHaveProperty("not_a_meta_key");
    const healthy: Meta = { reason: "initial" };
    const stale: Meta = { reason: "initial", stale: true };
    expect(healthy.stale).toBeUndefined();
    expect(stale.stale).toBe(true);
  });

  it("closes the bundled snapMeta and types its stale key as a boolean, default false", () => {
    expect(schemaOf("envelope").properties?.["meta"]?.$ref).toBe(
      "cv://ws/v1/common.schema.json#/$defs/snapMeta",
    );
    const snapMeta = schemaOf("common").$defs?.["snapMeta"];
    expect(snapMeta?.additionalProperties).toBe(false);
    expect(snapMeta?.properties?.["stale"]).toMatchObject({ type: "boolean", default: false });
  });

  it("keeps stale out of the bars payload: a binary snapshot's meta is the one carrier", () => {
    expectTypeOf<BarsPayload>().not.toHaveProperty("stale");
    const bars = schemaOf("bars");
    expect(bars.additionalProperties).toBe(false);
    expect(bars.properties).not.toHaveProperty("stale");
  });
});
