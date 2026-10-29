// E10-S04 (#306): SR-023's post-run `system` notice on the E08-Q05 WS harness, against the REAL web
// client. The fake gateway pushes it after a socket's FIRST `auth_ok` only, never after a re-auth
// (23 15.9): one SCR-153 (CMP-092) warning row, announced assertively once; a re-auth in place
// repeats nothing; a reconnect's notice re-asserts it.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
// eslint-disable-next-line no-restricted-imports -- `ajv/dist/2020` is Ajv's documented entry point for draft 2020-12 (it has no `exports` map)
import { Ajv2020 } from "ajv/dist/2020.js";
import { AXE_GATE_TAGS } from "../a11y/tags";
import { stubSession } from "../support/api";
import { installWsHarness, type Frame, type WsHarness } from "../support/wsHarness";

/** services/api/candleviewer/auth/break_glass_notice.py `notices()`: one frame for every role. */
const NOTICE = {
  kind: "notice",
  severity: "critical",
  message: "Break-glass recovery was used on this server; the Owner must review it.",
  reason: "auth.break_glass_used",
} as const;
const STILL_WORKS = "Order entry unaffected.";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../../../..");
const { schemas } = JSON.parse(
  readFileSync(join(ROOT, "packages/protocol/ws-schemas.json"), "utf8"),
) as { schemas: Record<string, object> };
const ajv = new Ajv2020({ strict: false, validateFormats: false, allErrors: true });
for (const [id, schema] of Object.entries(schemas)) ajv.addSchema(schema, id);

/** Ajv errors of a `system` data frame against 23's envelope and `system.schema.json`. */
const schemaErrors = (frame: Frame): string[] =>
  [["envelope", frame] as const, ["system", frame["p"]] as const].flatMap(([name, value]) => {
    const validate = ajv.getSchema(`cv://ws/v1/${name}.schema.json`);
    if (validate === undefined) return [`no schema ${name}`];
    return validate(value)
      ? []
      : (validate.errors ?? []).map((e) => `${name} ${e.instancePath} ${e.message}`);
  });

const notices = (h: WsHarness): Frame[] =>
  h.sent.filter((f) => (f["p"] as { reason?: unknown } | undefined)?.reason === NOTICE.reason);
const dismiss = (page: Page) => page.getByRole("button", { name: `Dismiss ${NOTICE.message}` });
/** The shell announcer's assertive region (`p[data-seq]`), where CMP-092's assertive words go. */
const alert = (page: Page) => page.locator('[aria-live="assertive"] > p');

async function signedIn(page: Page, tokenTtlMs = 600_000): Promise<WsHarness> {
  await stubSession(page, { role: "manager" }); // any role: the frame names no user (15.9)
  const harness = await installWsHarness(page, undefined, {
    firstAuthSystem: [NOTICE],
    tokenTtlMs,
  });
  await page.goto("/terminal");
  await expect.poll(() => harness.authenticated()).toBe(1);
  return harness;
}

test("SR-023: the first auth_ok's notice shows once and assertively; a re-auth repeats nothing", async ({
  page,
}) => {
  const harness = await signedIn(page, 61_000); // the client re-auths in place 5 s on (4.1)
  expect(harness.sent.slice(0, 4).map((f) => f.t)).toEqual(["welcome", "auth_ok", "snap", "d"]);
  const [frame, ...more] = notices(harness);
  expect(more).toEqual([]);
  expect(frame).toMatchObject({ t: "d", ch: "system", s: 2, e: "j", p: NOTICE });
  expect(frame === undefined ? ["no notice"] : schemaErrors(frame)).toEqual([]);

  await expect(dismiss(page)).toHaveCount(1);
  const row = page.locator('[data-severity="warning"]');
  for (const part of ["Warning", NOTICE.message, STILL_WORKS])
    await expect(row).toContainText(part);
  await expect(page.getByText(/new orders off/iu)).toHaveCount(0); // order entry untouched
  await expect(alert(page)).toHaveText(`${NOTICE.message} ${STILL_WORKS}`);
  // The default dark theme only: the light theme's pass waits for the G-row ruling on the severity
  // word's contrast there (`warning.strong` on `.subtle`, 4.11:1, as every CMP-092 tone).
  const res = await new AxeBuilder({ page })
    .withTags([...AXE_GATE_TAGS])
    .include('[data-severity="warning"]')
    .analyze();
  const serious = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => v.id)).toEqual([]);

  // Marks the announced node: a second announcement would replace it (a new React key).
  await alert(page).evaluate((el) => el.setAttribute("data-e2e-said", "1"));
  await expect.poll(() => harness.reauthenticated(), { timeout: 15_000 }).toBeGreaterThan(0);
  expect(notices(harness)).toHaveLength(1);
  await expect(dismiss(page)).toHaveCount(1);
  await expect(alert(page)).toHaveAttribute("data-e2e-said", "1");
});

test("SR-023: a keyboard dismissal holds until a reconnect's notice re-asserts the row", async ({
  page,
}) => {
  const harness = await signedIn(page);
  await dismiss(page).focus();
  await page.keyboard.press("Enter");
  await expect(dismiss(page)).toHaveCount(0);
  // E10-D04 T-19: no banner follows, so the TopBar's search trigger, never the canvas
  await expect(page.getByRole("button", { name: /^Search commands/ })).toBeFocused();

  const anchor = page
    .getByRole("navigation", { name: "Primary" })
    .getByRole("link", { name: "Journal", exact: true });
  await anchor.focus();
  harness.kill();
  harness.restore();
  await expect.poll(() => harness.authenticated(), { timeout: 15_000 }).toBe(2);
  expect(notices(harness)).toHaveLength(2);
  await expect(dismiss(page)).toHaveCount(1);
  // its turn in the shell announcer comes 5 s after CMP-077's "Disconnected" sentence (E17-D02 §11)
  await expect(alert(page)).toHaveText(`${NOTICE.message} ${STILL_WORKS}`, { timeout: 15_000 });
  await expect(anchor).toBeFocused(); // the notice never takes focus
});
