// Test-only Ajv harness (D11): every schema of packages/protocol/ws-schemas.json, compiled once.
// S4's fake gateway reuses `validateClientFrame` to check each frame the engine sends.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
// eslint-disable-next-line no-restricted-imports -- `ajv/dist/2020` is Ajv's documented entry point for draft 2020-12 (it has no `exports` map)
import { Ajv2020 } from "ajv/dist/2020.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../../../../../..");
export const repoFile = (rel: string): string => readFileSync(join(ROOT, rel), "utf8");

const { schemas } = JSON.parse(repoFile("packages/protocol/ws-schemas.json")) as {
  schemas: Record<string, object>;
};

// The schemas are authored in 23-ws-protocol.md and gated there (`ws_message_schemas`). Strict
// mode rejects their `x-db-enum` annotation and if/then `required`, and `format: uuid` is not asserted.
const ajv = new Ajv2020({ strict: false, validateFormats: false, allErrors: true });
for (const [id, schema] of Object.entries(schemas)) ajv.addSchema(schema, id);

const CLIENT_TYPES = new Set(["hello", "auth", "sub", "unsub", "ctl", "resync", "ping", "pong"]);

function errorsOf(name: string, data: unknown): string[] {
  const validate = ajv.getSchema(`cv://ws/v1/${name}.schema.json`);
  if (validate === undefined) throw new Error(`no such WS schema: ${name}`);
  return validate(data) ? [] : (validate.errors ?? []).map((e) => `${e.instancePath} ${e.message}`);
}

/** Ajv errors for a client frame against `envelope` and its payload schema; `[]` means valid. */
export function validateClientFrame(
  frame: { readonly t: string } & Readonly<Record<string, unknown>>,
) {
  if (!CLIENT_TYPES.has(frame.t)) return [`${frame.t} is not a client frame`];
  const payload = frame.t === "ping" || frame.t === "pong" ? "heartbeat" : frame.t;
  return [...errorsOf("envelope", frame), ...errorsOf(payload, frame["p"])];
}
