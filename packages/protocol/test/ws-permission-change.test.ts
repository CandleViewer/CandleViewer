import { describe, expect, it, expectTypeOf } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { generated } from "../src/index.js";

type Payload = generated.ws.CvWsV1PermissionChangeSchemaJson;
type Envelope = generated.ws.CandleViewerWSEnvelope;

const here = dirname(fileURLToPath(import.meta.url));
const bundle = JSON.parse(readFileSync(join(here, "..", "ws-schemas.json"), "utf8")) as {
  schemas: Record<string, { required?: string[]; additionalProperties?: boolean }>;
};

describe("permission_change frame (consumer side, 23-ws-protocol §9.5/§13.4)", () => {
  it("types the payload with the four required keys", () => {
    expectTypeOf<Payload>().toHaveProperty("user_id").toEqualTypeOf<string>();
    expectTypeOf<Payload>().toHaveProperty("permissions").toEqualTypeOf<string[]>();
    expectTypeOf<Payload>().toHaveProperty("account_scope").toEqualTypeOf<string[]>();
    expectTypeOf<Payload["roles"][number]>().toEqualTypeOf<"owner" | "manager" | "viewer">();
    expectTypeOf<Envelope["t"]>().toExtend<string>();
    const viewer: Payload = { user_id: "u", roles: ["viewer"], permissions: [], account_scope: [] };
    expect(viewer.account_scope).toEqual([]);
  });

  it("exposes the schema in the bundle as closed with all keys required", () => {
    const s = bundle.schemas["cv://ws/v1/permission_change.schema.json"];
    expect(s).toBeDefined();
    expect(s?.required).toEqual(["user_id", "roles", "permissions", "account_scope"]);
    expect(s?.additionalProperties).toBe(false);
  });

  it("exposes the generated ws namespace", () => {
    expect(generated.ws).toBeDefined();
  });
});
