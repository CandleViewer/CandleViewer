import { describe, expect, it, expectTypeOf } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { generated } from "../src/index.js";

type Payload = generated.ws.CvWsV1PermissionChangeSchemaJson;
type Envelope = generated.ws.CandleViewerWSEnvelope;

interface SchemaNode {
  enum?: string[];
  required?: string[];
  additionalProperties?: boolean;
  properties?: Record<string, SchemaNode>;
  items?: SchemaNode & { "x-db-enum"?: string };
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

describe("permission_change frame (consumer side, 23-ws-protocol §9.5/§13.4)", () => {
  it("types the frame type as a member of the closed envelope union and the payload", () => {
    expectTypeOf<"permission_change">().toExtend<Envelope["t"]>();
    // Guards the line above: it would pass vacuously if `Envelope["t"]` widened to `string`.
    expectTypeOf<"not_a_frame_type">().not.toExtend<Envelope["t"]>();
    expectTypeOf<Payload>().toHaveProperty("user_id").toEqualTypeOf<string>();
    expectTypeOf<Payload>().toHaveProperty("permissions").toEqualTypeOf<string[]>();
    expectTypeOf<Payload>().toHaveProperty("account_scope").toEqualTypeOf<string[]>();
    expectTypeOf<Payload["roles"][number]>().toEqualTypeOf<"owner" | "manager" | "viewer">();
    const viewer: Payload = { user_id: "u", roles: ["viewer"], permissions: [], account_scope: [] };
    expect(viewer.account_scope).toEqual([]);
  });

  it("lists permission_change in the envelope `t` enum of the bundled schema", () => {
    expect(schemaOf("envelope").properties?.["t"]?.enum).toContain("permission_change");
  });

  it("closes the bundled payload schema: four required keys, no extras, roles from role_name", () => {
    const schema = schemaOf("permission_change");
    expect([...(schema.required ?? [])].sort()).toEqual([
      "account_scope",
      "permissions",
      "roles",
      "user_id",
    ]);
    expect(schema.additionalProperties).toBe(false);
    const roleItems = schema.properties?.["roles"]?.items;
    expect(roleItems?.enum).toEqual(["owner", "manager", "viewer"]);
    expect(roleItems?.["x-db-enum"]).toBe("role_name");
  });
});
