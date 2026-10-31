import { randomBytes } from "node:crypto";
import type { Page, Response } from "@playwright/test";
import { same } from "../support/real/cookies";
import { expect, test, type AuditRow } from "../support/real/failureArtefacts";
import { signIn } from "../support/real/signIn";
import { TOTP_STEP_S } from "../support/totp";

// E09-Q02 (#293) PR 3 (#2086): AC4's server half, in BQ-5's wording: a users-class step-up through
// the real SCR-006 elevates for 5 minutes (`auth/step_up.py` GRACE_WINDOW); once the server's clock
// has passed that, the retry gets `403 step_up_required` with a new `challenge_id` and the dialog
// again, the action does not run (no new row, no audit write), and the consumed `challenge_id` is
// refused. Rotation is not asserted (#2101). A challenge id is compared, never printed (`same`).

const ROUTE = "/admin/users/new";
const GRACE_S = 5 * 60;
const MARGIN_S = 60;
const DIALOG = "Confirm with two-factor";
const STEP_UP = "/api/v1/auth/step-up";

const answerTo = (path: string, method: string) => (r: Response) =>
  new URL(r.url()).pathname === path && r.request().method() === method;
const bodyOf = async (r: Response): Promise<Record<string, unknown>> =>
  (await r.json().catch(() => ({}))) as Record<string, unknown>;

/** Fills SCR-123 for `name` and submits it; the answer to its `POST /users`. */
async function invite(page: Page, name: string): Promise<Response> {
  await page.getByLabel("Username").fill(name);
  await page.getByLabel("Email").fill(`${name}@example.test`);
  const [res] = await Promise.all([
    page.waitForResponse(answerTo("/api/v1/users", "POST")),
    page.getByRole("button", { name: "Create invitation" }).click(),
  ]);
  return res;
}

const count = (rows: readonly AuditRow[], action: string, reason?: string): number =>
  rows.filter((r) => r["action"] === action && (reason === undefined || r["reason"] === reason))
    .length;

test("E09-TC-C05 E09-TC-C06 (server half) a users step-up lapses after 5 min: the retry gets a new challenge and SCR-006 again, nothing runs, and the spent challenge_id is refused @clock", async ({
  page,
  lane,
}) => {
  await lane.refreshes(2); // the page load, and the reload that reads the invitations back
  const user = lane.user();
  const first = `up-a-${randomBytes(4).toString("hex")}`;
  const second = `up-b-${randomBytes(4).toString("hex")}`;
  await signIn(page, lane.stack, user);
  await page.goto(ROUTE);
  await expect(page.getByRole("heading", { level: 1, name: "Invite user" })).toBeVisible();

  // C05: the server challenges the invite; the step-up answers it and the held request goes once
  const refused = await invite(page, first);
  const challenge = await bodyOf(refused);
  expect({
    status: refused.status(),
    code: challenge["code"],
    cls: challenge["action_class"],
  }).toEqual({ status: 403, code: "step_up_required", cls: "users" });
  const dialog = page.getByRole("alertdialog", { name: DIALOG });
  await expect(dialog).toBeVisible();
  lane.stack.clock.advance(TOTP_STEP_S); // the sign-in spent this step's code (one use per step)
  await dialog.getByLabel("Password", { exact: true }).fill(lane.stack.password());
  await dialog.getByLabel("Authenticator code").fill(lane.stack.clock.totpAt(user.seed()));
  const [granted, created] = await Promise.all([
    page.waitForResponse(answerTo(STEP_UP, "POST")),
    page.waitForResponse(answerTo("/api/v1/users", "POST")),
    dialog.getByRole("button", { name: "Confirm" }).click(),
  ]);
  const grant = await bodyOf(granted);
  expect({ status: granted.status(), cls: grant["action_class"] }).toEqual({
    status: 200,
    cls: "users",
  });
  const consumed = challenge["challenge_id"] as string | undefined;
  expect(same(grant["challenge_id"] as string | undefined, consumed), "the grant used it").toBe(
    true,
  );
  expect(created.status(), "the held invite, re-sent once").toBe(201);
  await expect(page.getByRole("heading", { name: "Invitation link" })).toBeVisible();

  // C06: past the grace window the retry is challenged again, with a new challenge
  lane.stack.clock.advance(GRACE_S + MARGIN_S);
  const retried = await invite(page, second);
  const again = await bodyOf(retried);
  expect({ status: retried.status(), code: again["code"] }).toEqual({
    status: 403,
    code: "step_up_required",
  });
  expect(same(again["challenge_id"] as string | undefined, consumed), "a new challenge").toBe(
    false,
  );
  await expect(dialog).toBeVisible();

  // The consumed challenge cannot be answered again: SCR-006's step-up goes out naming it instead
  await page.route(`**${STEP_UP}`, (route) =>
    route.continue({
      postData: JSON.stringify({ ...route.request().postDataJSON(), challenge_id: consumed }),
    }),
  );
  await dialog.getByLabel("Password", { exact: true }).fill(lane.stack.password());
  await dialog.getByLabel("Authenticator code").fill(lane.stack.clock.totpAt(user.seed()));
  const [stale] = await Promise.all([
    page.waitForResponse(answerTo(STEP_UP, "POST")),
    dialog.getByRole("button", { name: "Confirm" }).click(),
  ]);
  const errors = (await bodyOf(stale))["errors"] as { rule?: unknown }[] | undefined;
  expect({ status: stale.status(), rules: errors?.map((e) => e.rule) }).toEqual({
    status: 400,
    rules: ["challenge_expired"],
  });
  // the SPA drops the held invite unsent (E09-D06 §2 item 7)
  await expect(page.getByRole("status").filter({ hasText: /^Not sent$/u })).toBeVisible();
  await page.unroute(`**${STEP_UP}`);

  // No new row: the invitations read back from the server hold the first and not the retry
  await page.reload();
  const pending = page.getByRole("region", { name: "Pending invitations" });
  await expect(pending.getByRole("listitem").filter({ hasText: first })).toHaveCount(1);
  await expect(pending.getByRole("listitem").filter({ hasText: second })).toHaveCount(0);
  // No audit write: once the refusal's own record has landed, the first invite's is still the one
  await expect
    .poll(async () => {
      const rows = await lane.auditRows();
      return {
        refused: count(rows, "auth.step_up_failed", "challenge_expired"),
        invited: count(rows, "users.invited"),
      };
    })
    .toEqual({ refused: 1, invited: 1 });
});
