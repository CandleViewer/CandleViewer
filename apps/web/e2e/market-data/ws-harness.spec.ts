// E08-Q05 (#282) slice 1: the e2e WS harness against the REAL web client: handshake (23 4.2, 4.3), lost transport and
// reconnect (4.4, 9.2), silent server and heartbeat watchdog (9.1), sequence gap and resync (7.5, 12.3). Every frame both
// ways is checked against 23's schemas. No UI renders the connection state yet (CMP-076/077/078), so this reads the wire.
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
// eslint-disable-next-line no-restricted-imports -- `ajv/dist/2020` is Ajv's documented entry point for draft 2020-12 (it has no `exports` map)
import { Ajv2020 } from "ajv/dist/2020.js";
import { stubSession } from "../support/api";
import * as H from "../support/wsHarness";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../../../..");
const { schemas } = JSON.parse(
  readFileSync(join(ROOT, "packages/protocol/ws-schemas.json"), "utf8"),
) as { schemas: Record<string, object> };
// As test/lib/ws/support/schemaHarness.ts: strict mode rejects the schemas' `x-db-enum` and if/then `required`.
const ajv = new Ajv2020({ strict: false, validateFormats: false, allErrors: true });
for (const [id, schema] of Object.entries(schemas)) ajv.addSchema(schema, id);

/** Ajv errors of a frame against `envelope` and its payload schema (data frames: the topic family's). */
function schemaErrors(frame: H.Frame): string[] {
  const family = String(frame["ch"]).split(".")[0];
  const name =
    { snap: family, d: family, ping: "heartbeat", pong: "heartbeat" }[frame.t] ?? frame.t;
  return [["envelope", frame] as const, [name, frame["p"]] as const].flatMap(([schema, value]) => {
    const validate = ajv.getSchema(`cv://ws/v1/${schema}.schema.json`);
    if (validate === undefined) return [`no schema ${schema}`];
    return validate(value)
      ? []
      : (validate.errors ?? []).map((e) => `${frame.t} ${e.instancePath} ${e.message}`);
  });
}

const types = (h: H.WsHarness, conn?: number): string[] =>
  h.frames.filter((f) => conn === undefined || f.conn === conn).map((f) => f.frame.t);

async function signedIn(page: Page, heartbeat?: H.Heartbeat): Promise<H.WsHarness> {
  await stubSession(page, { role: "owner" });
  const harness = await H.installWsHarness(page, heartbeat);
  await page.goto("/terminal");
  await expect.poll(() => harness.authenticated()).toBe(1);
  return harness;
}

test("connects and authenticates; every frame is a 23 frame", async ({ page }) => {
  const harness = await signedIn(page);
  expect(types(harness, 1).slice(0, 2)).toEqual(["hello", "auth"]); // 4.2: hello first, then auth
  const auth = harness.frames[1]?.frame;
  expect(auth?.["p"]).toEqual({ access_token: expect.stringMatching(/^x{20,}$/) }); // masked in the log
  expect(harness.sent.map((f) => f.t)).toEqual(["welcome", "auth_ok", "snap"]);
  expect(harness.sent.flatMap(schemaErrors)).toEqual([]);
  expect(harness.frames.map((f) => f.frame).flatMap(schemaErrors)).toEqual([]);
});

test("kill: the client retries; restore: it re-authenticates", async ({ page }) => {
  const harness = await signedIn(page);
  harness.kill();
  await expect.poll(() => harness.connections(), { timeout: 10_000 }).toBeGreaterThan(2); // retries refused while down (9.2)
  expect(harness.authenticated()).toBe(1);
  harness.restore();
  await expect.poll(() => harness.authenticated(), { timeout: 15_000 }).toBe(2);
  expect(types(harness, harness.connections())).toEqual(["hello", "auth"]); // a new session, no resumption (9.3)
});

test("stall: the heartbeat watchdog closes the silent socket", async ({ page }) => {
  // 13.3 floors: ping every 1 s, give up after 5 s of silence (9.1).
  const harness = await signedIn(page, { interval_ms: 1_000, timeout_ms: 5_000 });
  harness.stall();
  await expect
    .poll(() => harness.clientCloses, { timeout: 15_000 })
    .toContainEqual({ code: 4000, reason: "heartbeat_timeout" });
  expect(types(harness, 1)).toContain("ping"); // pings went unanswered
  harness.resume();
  await expect.poll(() => harness.authenticated(), { timeout: 15_000 }).toBe(2);
});

test("desync: a sequence gap makes the client resync", async ({ page }) => {
  const harness = await signedIn(page);
  harness.desync();
  await expect
    .poll(() => harness.frames.map((f) => f.frame).find((f) => f.t === "resync"))
    .toMatchObject({ ch: "system", p: { last_seq: 1, reason: "sequence_gap" } });
  await expect
    .poll(() => harness.sent.at(-1))
    .toMatchObject({ t: "snap", ch: "system", s: 4, meta: { reason: "client_resync" } });
  expect(harness.sent.flatMap(schemaErrors)).toEqual([]);
});

test("fixture tickers translate into valid 23 ticker payloads", () => {
  const rows = H.fixtureTickers();
  expect(rows).toHaveLength(20);
  expect(rows[0]).toMatchObject({ symbol: "BTCUSDT", last_price: "82751.20" }); // the snapshot line
  const errors = rows.flatMap((row) =>
    schemaErrors({ t: "d", ch: "ticker.BTCUSDT", s: 1, ts: 1, p: { tickers: [row] } }),
  );
  expect(errors).toEqual([]);
});

test("the production build carries no harness code", () => {
  const dir = join(ROOT, "apps/web/dist/assets");
  const bundles = readdirSync(dir).filter((f) => f.endsWith(".js"));
  expect(bundles.length).toBeGreaterThan(0);
  for (const file of bundles)
    expect(readFileSync(join(dir, file), "utf8")).not.toContain(H.WS_HARNESS_MARKER);
});
