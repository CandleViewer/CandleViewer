import { randomBytes } from "node:crypto";
import { expect, test } from "../support/real/failureArtefacts";
import { completeMfa, submitPassword } from "../support/real/signIn";

// E09-Q02 (#293) PR 3 (#2086): A08's server half, in BQ-7's wording: five wrong passwords lock the
// account for 15 minutes on the server's clock (`auth/login_service.py` LOCKOUT_THRESHOLD and
// LOCKOUT_DURATION), the right password is still refused while it lasts, and once the clock has
// moved past it the sign-in completes. Every refusal is the one `401` and the one string (SR-014).
// The per-address login throttle (20 failures a minute, `auth/throttle.py`) runs on the monotonic
// clock, which no spec moves: this is the lane's only spec that fails a sign-in, 6 times.

const LOCKOUT_THRESHOLD = 5;
const LOCKOUT_S = 15 * 60;
const MARGIN_S = 60;
const REFUSED = "Couldn't sign you in. Check your details and try again.";

test("E09-TC-A08 (server half) five wrong passwords lock the account: the right one is refused until the server clock passes 15 min, then the sign-in completes @clock", async ({
  page,
  lane,
}) => {
  const user = lane.user();
  const wrong = randomBytes(16).toString("hex"); // unrelated to the real password
  await page.goto("/login");
  for (let attempt = 1; attempt <= LOCKOUT_THRESHOLD; attempt += 1) {
    expect((await submitPassword(page, user, wrong)).status, `wrong password ${attempt}`).toBe(401);
    await expect(page.getByRole("alert")).toHaveText(REFUSED);
  }
  const locked = await submitPassword(page, user, lane.stack.password());
  expect({ status: locked.status, mfa: locked.mfaRequired }).toEqual({ status: 401, mfa: false });
  await expect(page.getByRole("alert")).toHaveText(REFUSED);

  lane.stack.clock.advance(LOCKOUT_S + MARGIN_S);
  const step = await submitPassword(page, user, lane.stack.password());
  expect({ status: step.status, mfa: step.mfaRequired }).toEqual({ status: 200, mfa: true });
  await expect(page.getByRole("heading", { name: "Two-factor code" })).toBeVisible();
  const mfa = await completeMfa(page, step.mfaToken(), lane.stack.clock.totpAt(user.seed()));
  expect(mfa.authenticated, "the sign-in completes").toBe(true);
  expect(mfa.session).toMatchObject({ status: 200, username: user.username });
});
