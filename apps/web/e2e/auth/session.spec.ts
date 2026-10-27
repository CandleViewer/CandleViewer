import { test, expect } from "@playwright/test";
import {
  assertNoClientSecrets,
  json,
  stubSession,
  stubSessionsList,
  watchForLeaks,
} from "../support/api";
import { installWsHarness } from "../support/wsHarness";

// E09-Q02 (#293) session.spec. Covered here: the unauthenticated redirect, cookie-stripped/401
// handling, the bootstrap session read, SCR-005 idle lock -> unlock (#1640 S2) and SCR-112 sign out
// everywhere -> SCR-001, with the server's 4401 close honoured (#1640 S3). @electron tagged.

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
  // Registered after stubSession, so these answer first, as the server does (22 "Idle lock"): a locked
  // session's refresh is refused and mints nothing; /me knows a locked session only by its bearer, and
  // without a bearer (a reload) it answers unauthenticated, never session_idle_locked.
  await page.route("**/api/v1/auth/refresh", (r) =>
    locked ? r.fulfill(lockedProblem) : r.fallback(),
  );
  const meCalls: { auth: string | undefined; locked: boolean }[] = [];
  await page.route("**/api/v1/me", (r) => {
    const auth = r.request().headers()["authorization"];
    meCalls.push({ auth, locked });
    if (auth === undefined) return r.fulfill(json({ status: 401, code: "unauthenticated" }, 401));
    return locked ? r.fulfill(lockedProblem) : r.fallback();
  });
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
  // no /me while locked (the refresh's lock is what showed SCR-005); the app booted on a bearer
  expect(meCalls.filter((call) => call.locked)).toEqual([]);
  expect(meCalls.at(-1)?.auth).toMatch(/^Bearer /u);
  await expect(page.getByText("pw-lock-1")).toHaveCount(0);
  const typed = await page
    .locator("input[type=password]")
    .evaluateAll((inputs) => inputs.map((i) => (i as HTMLInputElement).value));
  expect(typed.filter((v) => v !== "")).toEqual([]);
  await assertNoClientSecrets(page, ["pw-lock-1"]);
  await guard.flush();
});

// What this proves: the confirm sends `{all_sessions: true}` once, and the tab reaches SCR-001 through
// `endSession()` on the 204, not through the socket. The server's `bye session_revoked` + 4401 close
// (sent before the 204, as the hub does) is honoured: the client never re-authenticates on it. A
// revocation from another device (4401 alone, no in-tab logout) does not reach SCR-001 yet; the WS
// client stops on it as a fatal close (`connectionRegion.ts`, G12), so that is not asserted here.
test("#1640 SCR-112 sign out everywhere: logout all, SCR-001, the 4401 close honoured", async ({
  page,
}) => {
  await stubSession(page, { role: "owner" });
  const harness = await installWsHarness(page);
  let revoked = false;
  await stubSessionsList(page);
  // services/api/candleviewer/api/sessions.py: after the logout the cleared cookie refreshes
  // nothing (`_unauthorized("refresh_token_invalid")`)
  await page.route("**/api/v1/auth/refresh", (r) =>
    revoked
      ? r.fulfill(
          json(
            {
              type: "about:blank",
              title: "Unauthorized",
              status: 401,
              detail: "refresh_token_invalid",
            },
            401,
          ),
        )
      : r.fallback(),
  );
  const logouts: unknown[] = [];
  await page.route("**/api/v1/auth/logout", (r) => {
    logouts.push(r.request().postDataJSON());
    revoked = true;
    harness.revokeSession(); // the hub closes the session's sockets before the 204 (23 4.3)
    return r.fulfill({ status: 204 });
  });

  await page.goto("/settings/profile");
  await expect.poll(() => harness.authenticated()).toBe(1);
  const table = page.getByRole("table", { name: "Signed-in sessions" });
  await expect(table.getByRole("rowheader", { name: /This session/u })).toBeVisible();
  await page.getByRole("button", { name: "Sign out everywhere" }).click();
  const confirm = page.getByRole("alertdialog", { name: "Sign out everywhere?" });
  await expect(confirm.getByRole("button", { name: "Cancel" })).toBeFocused();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL(/\/login\?next=%2Fsettings%2Fprofile$/u);
  await expect(page.getByRole("heading", { name: "Sign in to CandleViewer" })).toBeVisible();
  expect(logouts).toEqual([{ all_sessions: true }]);
  expect(harness.sent.at(-1)).toMatchObject({ t: "bye", p: { code: 4401, reconnect: false } });
  expect(harness.authenticated()).toBe(1); // bye.reconnect false: never re-authenticated
});
