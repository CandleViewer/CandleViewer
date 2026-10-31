import { randomBytes } from "node:crypto";
import { watchForLeaks } from "../support/api";
import {
  CSRF_COOKIE,
  REFRESH_COOKIE,
  REFRESH_PATH,
  expires,
  jarFlags,
  plantRefresh,
  refreshByCookie,
  requiredValue,
  same,
  sessionByCookie,
  tamperOneByte,
  valueOf,
} from "../support/real/cookies";
import { expect, test } from "../support/real/failureArtefacts";
import { completeMfa, signIn, submitPassword } from "../support/real/signIn";

// E09-Q02 (#293) PR 2 (#2490): AC1, the cold start on the seeded stack, against the real API and the
// browser's own cookie jar. The cookie checks are #293's BQ-3 wording of record: no `Set-Cookie` after
// the password step; after MFA exactly `cv_refresh` (HttpOnly, Secure, Strict, `Path=/api/v1/auth`)
// and `__Host-cv_csrf` (Secure, Strict, not HttpOnly); a planted `cv_refresh` replaced, never adopted;
// a refresh rotating both; a one-byte tamper getting `401`. MFA is completed by in-page `fetch` until
// SCR-002's OTP form lands (#2711, BQ-2). Each test signs in a fixture user of its own. Values are
// compared as booleans (`same`), never printed: a failure shows flags, statuses and codes only.
// The per-address refresh budget is 10 a minute (`api/sessions.py`): each test declares how often
// it presents `cv_refresh` to `POST /auth/refresh`, the page loads that carry one included
// (`lane.refreshes`, held to the count by the fixture). These tests present it 8 times in all.

const SIGN_IN = "Sign in to CandleViewer";
const SHELL = /R-101/u;

function originOf(baseURL: string | undefined): string {
  if (baseURL === undefined) throw new Error("the lane's config sets baseURL");
  return baseURL;
}

/** The jar after MFA, without values: exactly these two cookies, host-only on the lane's host. */
const afterMfa = (origin: string) => {
  const domain = new URL(origin).hostname;
  return [
    { name: CSRF_COOKIE, domain, path: "/", secure: true, httpOnly: false, sameSite: "Strict" },
    {
      name: REFRESH_COOKIE,
      domain,
      path: REFRESH_PATH,
      secure: true,
      httpOnly: true,
      sameSite: "Strict",
    },
  ];
};

test("E09-TC-A01 the password step answers mfa_required, sets no cookie, and SCR-001 moves on to the second factor", async ({
  page,
  context,
  lane,
}) => {
  const user = lane.user();
  const guard = watchForLeaks(page, [lane.stack.password(), user.seed()]);
  await page.goto("/login");
  const step = await submitPassword(page, user, lane.stack.password());
  expect(step.status).toBe(200);
  expect(step.mfaRequired).toBe(true);
  expect(step.methods).toContain("totp");
  expect(step.setCookies, "no Set-Cookie after the password step").toBe(0);
  await expect(page.getByRole("heading", { name: "Two-factor code" })).toBeVisible();
  expect(await jarFlags(context)).toEqual([]);
  await guard.flush();
});

test("E09-TC-A02 (server half) MFA sets exactly cv_refresh and __Host-cv_csrf with their flags, and no refresh token in the body", async ({
  page,
  context,
  lane,
  baseURL,
}) => {
  const { mfa } = await signIn(page, lane.stack, lane.user());
  expect(mfa.status).toBe(200);
  expect([...mfa.cookiesSet].sort()).toEqual([CSRF_COOKIE, REFRESH_COOKIE]);
  expect(mfa.tokenType).toBe("Bearer");
  expect(mfa.refreshInBody, "the refresh token lives in the cookie only (ADR-0020)").toBe(false);
  expect(await jarFlags(context)).toEqual(afterMfa(originOf(baseURL)));
});

test("E09-TC-C01 GET /auth/session gives the user and permissions, the cold start boots the shell, and no secret reaches a body", async ({
  page,
  context,
  lane,
}) => {
  await lane.refreshes(2); // the page load into the shell, then the refresh read after it
  const user = lane.user();
  const secrets = [lane.stack.password(), user.seed()];
  const signingIn = watchForLeaks(page, secrets);
  const { mfa } = await signIn(page, lane.stack, user);
  expect(mfa.session.status).toBe(200);
  expect(mfa.session.username).toBe(user.username);
  expect(mfa.session.permissions).toBeGreaterThan(0);
  expect(mfa.session.echoesToken, "GET /auth/session does not echo the bearer").toBe(false);
  expect(mfa.me).toEqual({ status: 200, echoesToken: false });
  await signingIn.flush(); // before the navigation below drops this page's bodies
  const cookie = await requiredValue(context, REFRESH_COOKIE);
  const booting = watchForLeaks(page, [...secrets, cookie]);

  await page.goto("/terminal/last"); // the page load refreshes by cookie, then reads /me
  await expect(page).toHaveURL(/\/terminal\/last$/u);
  await expect(page.getByRole("heading", { name: SHELL })).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  // the SharedWorker's socket, through the preview's proxy: hello, auth, the system snapshot
  await expect(page.getByRole("button", { name: /^Connection: Live/u })).toBeVisible({
    timeout: 20_000,
  });
  const rotated = await requiredValue(context, REFRESH_COOKIE);
  expect(same(rotated, cookie), "the page load's refresh rotated cv_refresh").toBe(false);
  // `booting` forbids the cookie from before the boot, which no body echoes. The value a leaking
  // body would carry is the one a refresh issues next, unknown until it runs: so read a refresh's
  // answer after the boot (a 200 with a bundle, so the `false` is not a 401's empty body).
  expect(await refreshByCookie(page)).toEqual({
    status: 200,
    code: null,
    bundle: true,
    refreshInBody: false,
  });
  await booting.flush();
});

test("E09-TC-C07 a refresh rotates both cookies; the spent cv_refresh is refused and ends the family", async ({
  page,
  context,
  lane,
  baseURL,
}) => {
  await lane.refreshes(2); // the rotation, then the spent cookie's replay
  const origin = originOf(baseURL);
  await signIn(page, lane.stack, lane.user());
  const spent = await requiredValue(context, REFRESH_COOKIE);
  const csrf = await requiredValue(context, CSRF_COOKIE);

  expect(await refreshByCookie(page)).toEqual({
    status: 200,
    code: null,
    bundle: true,
    refreshInBody: false,
  });
  const successor = await requiredValue(context, REFRESH_COOKIE);
  expect(same(successor, spent), "cv_refresh rotated").toBe(false);
  const csrfSuccessor = await requiredValue(context, CSRF_COOKIE);
  expect(same(csrfSuccessor, csrf), "__Host-cv_csrf rotated").toBe(false);
  expect(await jarFlags(context)).toEqual(afterMfa(origin));

  // `22` authRefresh: a token presented after its rotation is reuse; it revokes the whole family
  await plantRefresh(context, origin, spent);
  expect(await refreshByCookie(page)).toMatchObject({ status: 401, code: "refresh_token_invalid" });
  await plantRefresh(context, origin, successor);
  expect(await sessionByCookie(page)).toEqual({ status: 401, code: "unauthenticated" });
});

test("E09-TC-C09 a planted cv_refresh is replaced at sign-in, never adopted", async ({
  page,
  context,
  lane,
  baseURL,
}) => {
  await lane.refreshes(2); // SCR-001's page load with the planted cookie, then that cookie again
  const origin = originOf(baseURL);
  const user = lane.user();
  const planted = randomBytes(32).toString("hex");
  await plantRefresh(context, origin, planted); // before SCR-001 loads: its page load presents it
  await page.goto("/login");
  const step = await submitPassword(page, user, lane.stack.password());
  expect(step.mfaRequired, "the password step asks for the second factor").toBe(true);
  await expect(page.getByRole("heading", { name: "Two-factor code" })).toBeVisible();
  // The planted value is still the jar's cv_refresh when MFA is completed: neither the page load's
  // failed refresh nor the password step clears it. So the value after MFA is a replacement.
  expect(
    same(await valueOf(context, REFRESH_COOKIE), planted),
    "the planted cv_refresh was in the jar when MFA completed",
  ).toBe(true);
  const mfa = await completeMfa(page, step.mfaToken(), lane.stack.clock.totpAt(user.seed()));
  expect(mfa.authenticated, "MFA by in-page fetch authenticated the session").toBe(true);
  const issued = await requiredValue(context, REFRESH_COOKIE);
  expect(same(issued, planted), "MFA replaced the planted cv_refresh").toBe(false);
  expect(await jarFlags(context)).toEqual(afterMfa(origin));
  // the server resolves no session from the planted value, before or after the sign-in
  await plantRefresh(context, origin, planted);
  expect(await sessionByCookie(page)).toEqual({ status: 401, code: "unauthenticated" });
  expect(await refreshByCookie(page)).toMatchObject({ status: 401, code: "refresh_token_invalid" });
  await plantRefresh(context, origin, issued); // the issued one is the session's (positive control)
  expect(await sessionByCookie(page)).toEqual({ status: 200, code: null });
});

test("E09-TC-C09 a stripped or one-byte-tampered cv_refresh gets 401 and resolves no session", async ({
  page,
  context,
  lane,
  baseURL,
}) => {
  await lane.refreshes(1); // the tampered cookie (the stripped jar presents none)
  const origin = originOf(baseURL);
  await signIn(page, lane.stack, lane.user());
  const issued = await requiredValue(context, REFRESH_COOKIE);
  expect(await sessionByCookie(page)).toEqual({ status: 200, code: null }); // positive control

  await plantRefresh(context, origin, tamperOneByte(issued));
  expect(await sessionByCookie(page)).toEqual({ status: 401, code: "unauthenticated" });
  expect(await refreshByCookie(page)).toMatchObject({ status: 401, code: "refresh_token_invalid" });

  await context.clearCookies({ name: REFRESH_COOKIE });
  expect(await sessionByCookie(page)).toEqual({ status: 401, code: "unauthenticated" });
  expect(await refreshByCookie(page)).toMatchObject({ status: 401, code: "refresh_token_invalid" });

  // the 401s were the tamper's and the strip's: the untouched value still identifies the session
  await plantRefresh(context, origin, issued);
  expect(await sessionByCookie(page)).toEqual({ status: 200, code: null });
});

test("E09-TC-C09 Sign out expires both cookies, and the ended session's cookie gets 401", async ({
  page,
  context,
  lane,
  baseURL,
}) => {
  await lane.refreshes(1); // the page load (the logout expires the cookie SCR-001's would send)
  await signIn(page, lane.stack, lane.user());
  await page.goto("/terminal/last");
  await expect(page.getByRole("heading", { name: SHELL })).toBeVisible();
  const ended = await requiredValue(context, REFRESH_COOKIE); // the boot refresh's successor

  const logout = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/v1/auth/logout");
  await page.getByRole("button", { name: "Sign out" }).click();
  const res = await logout;
  expect(res.status()).toBe(204);
  const headers = await res.headersArray();
  expect(expires(headers, REFRESH_COOKIE), "the logout expires cv_refresh").toBe(true);
  expect(expires(headers, CSRF_COOKIE), "the logout expires __Host-cv_csrf").toBe(true);
  await expect(page).toHaveURL(/\/login\?next=/u);
  await expect(page.getByRole("heading", { name: SIGN_IN })).toBeVisible();
  expect(await jarFlags(context)).toEqual([]);

  await plantRefresh(context, originOf(baseURL), ended);
  expect(await sessionByCookie(page)).toEqual({ status: 401, code: "unauthenticated" });
});

test("E09-TC-C09 a deep link with no session lands on SCR-001 with next, from the real API's 401", async ({
  page,
  context,
}) => {
  // The boot's refresh has no cv_refresh to present: the real API's 401 is what sends the SPA to
  // SCR-001. Awaited with the `goto`, so it cannot be missed, nor left pending if `goto` throws.
  const [res] = await Promise.all([
    page.waitForResponse((r) => new URL(r.url()).pathname === "/api/v1/auth/refresh"),
    page.goto("/positions"),
  ]);
  expect(res.status()).toBe(401);
  const body = (await res.json().catch(() => ({}))) as { code?: unknown };
  expect(body.code).toBe("refresh_token_invalid");
  await expect(page).toHaveURL(/\/login\?next=%2Fpositions$/u);
  await expect(page.getByRole("heading", { name: SIGN_IN })).toBeVisible();
  expect(await jarFlags(context)).toEqual([]);
});
