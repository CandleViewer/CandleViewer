import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { AXE_GATE_TAGS } from "../a11y/tags";
import { assertNoClientSecrets, json, stubSession, watchForLeaks } from "../support/api";
import { seriousAxe } from "../support/axe";
import { OTP_SEED, totp } from "../support/totp";

// E09-Q02 (#293) stepup.spec, revised for #2725: there is no client-side `/admin` step-up
// pre-emption any more. Step-up answers the server's own `403 step_up_required` challenge, per
// action, and its credentials are only ever posted with that challenge's `challenge_id`. The
// browser clock is controlled with page.clock (no sleeps); the API is stubbed at the network layer.
const T0 = new Date("2026-03-01T10:00:00Z");
const MIN = 60_000;
const CHALLENGE_ID = "0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d";
const SUMMARY = "Invite user 'annie' as viewer";

interface Wire {
  readonly stepUps: string[];
  readonly creates: string[];
}

/** An owner on SCR-123 whose first invite is refused with a step-up challenge. */
async function inviteWithChallenge(
  page: Page,
  stepUp: { status: number; body: unknown },
): Promise<Wire> {
  const wire: Wire = { stepUps: [], creates: [] };
  await page.clock.install({ time: T0 });
  // A stale elevation in /me changes nothing: the client no longer reads it.
  await stubSession(page, {
    role: "owner",
    elevatedUntil: () => new Date(T0.getTime() - 45 * MIN).toISOString(),
  });
  await page.route("**/api/v1/users/invites", (r) => r.fulfill(json({ items: [] })));
  await page.route("**/api/v1/users", (r) => {
    wire.creates.push(r.request().headers()["idempotency-key"] ?? "");
    return wire.creates.length === 1
      ? r.fulfill(
          json(
            {
              type: "https://candleviewer.local/errors/step_up_required",
              title: "A dangerous action needs a live step-up elevation for its action class",
              status: 403,
              code: "step_up_required",
              action_class: "users",
              challenge_id: CHALLENGE_ID,
              challenge_expires_at: new Date(T0.getTime() + 5 * MIN).toISOString(),
              action_summary: SUMMARY,
              target: null,
            },
            403,
          ),
        )
      : r.fulfill(
          json(
            {
              id: "u1",
              username: "annie",
              invite_url: "/invite/e2e-link",
              invite_expires_at: "2026-03-04T10:00:00Z",
            },
            201,
          ),
        );
  });
  await page.route("**/api/v1/auth/step-up", (r) => {
    wire.stepUps.push(r.request().postData() ?? "");
    return r.fulfill(json(stepUp.body, stepUp.status));
  });
  await page.goto("/admin/users/new");
  await page.getByLabel("Username").fill("annie");
  await page.getByRole("button", { name: "Create invitation" }).click();
  return wire;
}

const GRANTED = { status: 200, body: { elevated_until: T0.toISOString(), action_class: "users" } };

test("E09-TC-C04 a stale elevation never pre-empts /admin: the page renders, no step-up is sent", async ({
  page,
}) => {
  await page.clock.install({ time: T0 });
  const stepUps: string[] = [];
  await page.route("**/api/v1/auth/step-up", (r) => {
    stepUps.push(r.request().postData() ?? "");
    return r.fulfill(json({}, 500));
  });
  await stubSession(page, {
    role: "owner",
    elevatedUntil: () => new Date(T0.getTime() - 45 * MIN).toISOString(),
  });
  await page.goto("/admin/users");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(page.getByLabel("Authenticator code")).toHaveCount(0);
  expect(stepUps).toEqual([]);
});

test("E09-TC-C05 the step-up answers the server's challenge and the held invite is re-sent once", async ({
  page,
}) => {
  const guard = watchForLeaks(page, ["step-up-marker-x"]);
  const wire = await inviteWithChallenge(page, GRANTED);
  const dialog = page.getByRole("alertdialog", { name: "Confirm with two-factor" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAccessibleDescription(SUMMARY);
  await expect(page.getByLabel("Password", { exact: true })).toBeFocused();
  const axe = await new AxeBuilder({ page }).withTags([...AXE_GATE_TAGS]).analyze();
  expect(
    axe.violations
      .filter((v) => v.impact === "serious" || v.impact === "critical")
      .map((v) => `${v.id}: ${v.help}`),
  ).toEqual([]);
  const code = totp(OTP_SEED, T0.getTime());
  await page.getByLabel("Password", { exact: true }).fill("e2e-step-up-pw");
  await page.getByLabel("Authenticator code").fill(code);
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByLabel("Invite link")).toHaveValue(/\/invite\/e2e-link$/u);
  expect(wire.stepUps.map((b) => JSON.parse(b) as unknown)).toEqual([
    { password: "e2e-step-up-pw", code, challenge_id: CHALLENGE_ID },
  ]);
  expect(wire.creates).toHaveLength(2);
  expect(wire.creates[0]).toMatch(/^[0-9a-f-]{36}$/u);
  expect(wire.creates[1]).toBe(wire.creates[0]);
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await assertNoClientSecrets(page, [code, "step-up-marker-x"]);
  await guard.flush();
});

test("E09-TC-C06 at challenge_expires_at the held invite is dropped: Not sent (fake clock)", async ({
  page,
}) => {
  const wire = await inviteWithChallenge(page, GRANTED);
  await expect(page.getByRole("alertdialog")).toBeVisible();
  await page.clock.runFor(5 * MIN);
  // The shell has other polite live regions (the SCR-015 toast host, the theme announcer).
  await expect(page.getByRole("status").filter({ hasText: /^Not sent$/u })).toBeVisible();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  expect(wire.stepUps).toEqual([]);
  expect(wire.creates).toHaveLength(1);
});

test("E09-TC-C05 rejected code keeps the dialog open with an accessible error", async ({
  page,
}) => {
  const wire = await inviteWithChallenge(page, { status: 401, body: { code: "mfa_invalid" } });
  await page.getByLabel("Password", { exact: true }).fill("pw-a1");
  await page.getByLabel("Authenticator code").fill("000000");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alert")).toHaveText("Incorrect code.");
  await expect(page.getByRole("alertdialog", { name: "Confirm with two-factor" })).toBeVisible();
  await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");
  expect(wire.stepUps).toHaveLength(1);
  expect(JSON.parse(wire.stepUps[0] ?? "{}")).toMatchObject({ challenge_id: CHALLENGE_ID });
  expect(wire.creates).toHaveLength(1);
});

test("E09-TC-C05 non-owner is denied (404) rather than offered step-up", async ({ page }) => {
  await page.clock.install({ time: T0 });
  await stubSession(page, { role: "manager" });
  await page.goto("/admin/users");
  await expect(page.getByRole("heading", { name: "Not found" })).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
});

// ---- SCR-006's exits and keyboard (E09-D06 5, 6): Esc and Cancel drop the held request unsent, the third
// refused code does too, and Tab never leaves the dialog.
const DIALOG = { name: "Confirm with two-factor" };
const NOT_SENT = (page: Page) => page.getByRole("status").filter({ hasText: /^Not sent$/u });
const CLOSERS: readonly (readonly [string, (page: Page) => Promise<void>])[] = [
  ["Cancel", (page) => page.getByRole("button", { name: "Cancel" }).click()],
  ["Esc", (page) => page.keyboard.press("Escape")],
];

for (const [name, close] of CLOSERS) {
  test(`E09-TC-C05 ${name} drops the held invite unsent: Not sent, no step-up sent, focus back on the form`, async ({
    page,
  }) => {
    const wire = await inviteWithChallenge(page, GRANTED);
    await expect(page.getByRole("alertdialog", DIALOG)).toBeVisible();
    await close(page);
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
    await expect(NOT_SENT(page)).toBeVisible();
    await expect(page.getByRole("button", { name: "Create invitation" })).toBeFocused();
    expect(wire.stepUps).toEqual([]);
    expect(wire.creates).toHaveLength(1); // the held invite is never re-sent
  });
}

test("E09-TC-C05 the third refused code drops the held invite unsent: three step-ups sent, Not sent, no re-send", async ({
  page,
}) => {
  const wire = await inviteWithChallenge(page, { status: 401, body: { code: "mfa_invalid" } });
  const password = page.getByLabel("Password", { exact: true });
  const code = page.getByLabel("Authenticator code");
  const refused = async (n: number): Promise<void> => {
    await password.fill(`pw-${n}`);
    await code.fill("000000");
    await page.keyboard.press("Enter");
    await expect.poll(() => wire.stepUps.length).toBe(n);
  };
  // each refusal keeps the dialog, shows an alert, clears the fields and refocuses the password
  await refused(1);
  await expect(password).toHaveValue("");
  await refused(2);
  await expect(password).toHaveValue("");
  await expect(password).toBeFocused();
  await expect(page.getByRole("alertdialog", DIALOG)).toBeVisible();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(code).toHaveAttribute("aria-invalid", "true");
  expect(await seriousAxe(page)).toEqual([]);
  await refused(3);
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(NOT_SENT(page)).toBeVisible();
  const bodies = wire.stepUps.map((body) => JSON.parse(body) as { challenge_id?: string });
  expect(bodies.map((body) => body.challenge_id)).toEqual([
    CHALLENGE_ID,
    CHALLENGE_ID,
    CHALLENGE_ID,
  ]);
  expect(wire.creates).toHaveLength(1);
});

test("E09-TC-C05 keyboard-only: Tab and Shift+Tab cycle inside the dialog and never reach the form behind it", async ({
  page,
}) => {
  await inviteWithChallenge(page, GRANTED);
  const dialog = page.getByRole("alertdialog", DIALOG);
  const password = dialog.getByLabel("Password", { exact: true });
  const code = dialog.getByLabel("Authenticator code");
  const cancel = dialog.getByRole("button", { name: "Cancel" });
  const confirm = dialog.getByRole("button", { name: "Confirm" });
  await expect(password).toBeFocused();
  await page.keyboard.type("pw-trap");
  await page.keyboard.press("Tab");
  await expect(code).toBeFocused();
  await page.keyboard.type("123456"); // a valid code enables Confirm, the last stop
  for (const next of [cancel, confirm, password, code]) {
    await page.keyboard.press("Tab");
    await expect(next).toBeFocused();
  }
  await page.keyboard.press("Shift+Tab");
  await expect(password).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(confirm).toBeFocused();
});
