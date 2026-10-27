import { test, expect } from "@playwright/test";
import { assertNoClientSecrets, json, stubSession, watchForLeaks } from "../support/api";

// E09-Q02 (#293) session.spec. SCR-111/112 (sessions list, sign-out everywhere) are not built yet
// (#1640 S3). Covered here: the unauthenticated redirect, cookie-stripped/401 handling, the
// bootstrap session read, and SCR-005 idle lock -> unlock (#1640 S2). @electron tagged.

test("E09-TC-C09 unauthenticated deep link redirects to /login preserving next @electron", async ({
  page,
}) => {
  await page.route("**/api/v1/me", (r) => r.fulfill(json({}, 401)));
  await page.goto("/positions");
  await expect(page).toHaveURL(/\/login\?next=%2Fpositions$/u);
  await expect(page.getByRole("heading", { name: "Sign in to CandleViewer" })).toBeVisible();
});

test("E09-TC-C01 authenticated bootstrap reads /me once and renders the shell @electron", async ({
  page,
}) => {
  let meCalls = 0;
  await stubSession(page, { role: "owner" });
  await page.route("**/api/v1/me", (r) => {
    meCalls += 1;
    return r.fulfill(
      json({
        role: "owner",
        permissions: [],
        session: { environment: "demo", elevated_until: null },
      }),
    );
  });
  await page.goto("/terminal/last");
  await expect(page).toHaveURL(/\/terminal\/last$/u);
  expect(meCalls).toBe(1);
});

test("E09-TC-C09 session cookie is never readable by page script (HttpOnly contract)", async ({
  page,
  context,
}) => {
  await context.addCookies([
    {
      name: "cv_session",
      value: "opaque-test-value",
      url: "http://127.0.0.1:4173",
      httpOnly: true,
      sameSite: "Strict",
    },
  ]);
  await stubSession(page, { role: "owner" });
  await page.goto("/terminal/last");
  expect(await page.evaluate(() => document.cookie)).not.toContain("cv_session");
  const [cookie] = await context.cookies();
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.sameSite).toBe("Strict");
});

test("E09-TC-C01 sign-in leaves no password or challenge in storage, URL or DOM (SR-012)", async ({
  page,
}) => {
  const guard = watchForLeaks(page, ["pw-a1"]);
  await page.route("**/api/v1/auth/login", (r) =>
    r.fulfill(json({ status: "mfa_required", mfa_token: "ch-1", methods: ["totp"] })),
  );
  await page.goto("/login");
  await page.getByLabel("Username or email").fill("ann");
  await page.getByLabel("Password", { exact: true }).fill("pw-a1");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Two-factor code" })).toBeVisible();
  await assertNoClientSecrets(page, ["pw-a1", "ch-1"]);
  await expect(page.getByText("pw-a1")).toHaveCount(0);
  await guard.flush();
});

test("#1640 a reload into an idle-locked session shows SCR-005, not /login; unlock boots the app", async ({
  page,
}) => {
  const guard = watchForLeaks(page, ["pw-lock-1"]);
  let locked = true;
  const lockedProblem = json({ status: 401, code: "session_idle_locked" }, 401);
  const session = () => ({
    server_time: new Date().toISOString(),
    step_up_expires_at: null,
    session: {
      id: "5b1f0c3e-7d2a-4c11-9e8f-0a1b2c3d4e5f",
      issued_at: new Date(Date.now() - 3_600_000).toISOString(),
      expires_at: new Date(Date.now() + 3_600_000).toISOString(),
      idle_deadline: new Date(Date.now() + (locked ? -1_000 : 900_000)).toISOString(),
      idle_timeout_s: 900,
      locked,
    },
  });
  await stubSession(page, { role: "owner" });
  // registered after stubSession, so these answer first while the session is locked
  await page.route("**/api/v1/auth/refresh", (r) =>
    locked ? r.fulfill(lockedProblem) : r.fallback(),
  );
  await page.route("**/api/v1/me", (r) => (locked ? r.fulfill(lockedProblem) : r.fallback()));
  await page.route("**/api/v1/auth/session", (r) => r.fulfill(json(session())));
  const unlocks: unknown[] = [];
  await page.route("**/api/v1/auth/unlock", (r) => {
    unlocks.push(r.request().postDataJSON());
    locked = false;
    return r.fulfill(json(session()));
  });

  await page.goto("/terminal/last");
  const lock = page.getByRole("alertdialog", { name: "Session locked" });
  await expect(lock).toBeVisible();
  await expect(page).toHaveURL(/\/terminal\/last$/u); // not routed to /login
  await expect(page.getByLabel("Password")).toBeFocused();
  await page.keyboard.press("Escape"); // Esc does not dismiss SCR-005
  await expect(lock).toBeVisible();
  await page.keyboard.type("pw-lock-1");
  await page.keyboard.press("Enter");
  await expect(lock).toBeHidden();
  await expect(page.getByRole("heading", { name: /R-101/u })).toBeVisible(); // the app booted
  await expect(page).toHaveURL(/\/terminal\/last$/u);
  expect(unlocks).toEqual([{ password: "pw-lock-1" }]); // the password only, once
  await assertNoClientSecrets(page, ["pw-lock-1"]);
  await guard.flush();
});
