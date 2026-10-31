import type { Page } from "@playwright/test";
import { assertNoClientSecrets } from "../support/api";
import { expect, test, type Lane } from "../support/real/failureArtefacts";
import { signIn } from "../support/real/signIn";
import { tapWebSocket, type WsTap } from "../support/real/wsTap";
import { TOTP_STEP_S } from "../support/totp";

// E09-Q02 (#293) PR 3 (#2086): AC3 on the real stack, in BQ-4's wording, with D01 and D02: one
// user signed in on two devices, each a browser context of its own (its own cookie jar and shared
// worker): the stub lane's two-context case (`support/contexts.ts`) against the real API. B's
// socket is tapped (`support/real/wsTap.ts`): when A ends B's session, the hub sends
// `bye{session_revoked, reconnect:false}` and closes 4401 (`23` §4.4, §9.5), and B's next REST
// call lands on SCR-001.
// The replay guard accepts a TOTP step once (`mfa_service.py`), so B's code is the next step's:
// the server clock moves one step on between the two sign-ins.

const PROFILE = "/settings/profile";
const SIGN_IN = "Sign in to CandleViewer";
const SESSIONS = "Signed-in sessions";

interface Devices {
  readonly a: Page;
  readonly b: Page;
  readonly tap: WsTap;
}

/** The test's user on A and on B, B's socket live and tapped. A's sessions list is not read yet. */
async function twoDevices(page: Page, lane: Lane): Promise<Devices> {
  const user = lane.user();
  const b = await (await lane.newContext()).newPage();
  const tap = await tapWebSocket(b);
  await signIn(page, lane.stack, user);
  lane.stack.clock.advance(TOTP_STEP_S);
  await signIn(b, lane.stack, user);
  await b.goto("/terminal/last"); // B boots first, so A's list holds B's live session
  await expect(b.getByRole("button", { name: /^Connection: Live/u })).toBeVisible({
    timeout: 20_000,
  });
  expect(
    tap.frames.some((f) => f["t"] === "auth_ok"),
    "B's socket authenticated",
  ).toBe(true);
  return { a: page, b, tap };
}

/** The hub ended B's socket: `bye session_revoked` as its last frame, then the 4401 close. */
async function byeThen4401(tap: WsTap): Promise<void> {
  await expect.poll(() => tap.closes.map((c) => c.code)).toEqual([4401]);
  expect(tap.frames.at(-1)).toMatchObject({
    t: "bye",
    p: { code: 4401, reason: "session_revoked", reconnect: false },
  });
}

/** B's next REST call is refused, and the SPA routes it to SCR-001. */
async function nextCallSignsOut(b: Page, tap: WsTap): Promise<void> {
  await b.getByRole("link", { name: "Settings" }).click();
  await expect(b).toHaveURL(/\/login\?next=%2Fsettings%2Fprofile$/u);
  await expect(b.getByRole("heading", { name: SIGN_IN })).toBeVisible();
  expect(tap.connections(), "B opened no second socket").toBe(1);
}

test("E09-TC-D01 E09-TC-D02 A lists both sessions with no token in the page, then revokes B's: the row goes, A stays, B gets bye then 4401 and its next call lands on SCR-001 @clock", async ({
  page,
  lane,
}) => {
  await lane.refreshes(4); // each device's page load, B's refused call, B's SCR-001 page load
  const { a, b, tap } = await twoDevices(page, lane);
  const [listed] = await Promise.all([
    a.waitForRequest((r) => new URL(r.url()).pathname === "/api/v1/auth/sessions"),
    a.goto(PROFILE),
  ]);
  const table = a.getByRole("table", { name: SESSIONS });
  await expect(table.getByRole("row")).toHaveCount(3); // the header and the two devices
  await expect(table.getByRole("rowheader", { name: /This session/u })).toBeVisible();
  // D01: the list was read with a bearer, and none of it is in the page (compared, never printed)
  const bearer = ((await listed.headerValue("authorization")) ?? "").replace(/^Bearer /u, "");
  expect(bearer.length, "the list was read with a bearer").toBeGreaterThan(20);
  expect((await a.content()).includes(bearer), "the bearer is not in the page").toBe(false);
  await assertNoClientSecrets(a, [bearer]);

  // D02: revoke B's row (the button that is not this session's)
  await table.getByRole("button", { name: /^Revoke (?!.*\(this session\))/u }).click();
  const confirm = a.getByRole("alertdialog", { name: "Revoke session?" });
  await confirm.getByRole("button", { name: "Revoke", exact: true }).click();
  await expect(table.getByRole("row")).toHaveCount(2); // the header and this session
  await expect(a).toHaveURL(/\/settings\/profile$/u);
  await byeThen4401(tap);
  await nextCallSignsOut(b, tap);
  await expect(table.getByRole("rowheader", { name: /This session/u })).toBeVisible(); // A stays
  await expect
    .poll(async () =>
      (await lane.auditRows()).filter(
        (r) => r["action"] === "auth.session_revoked" && r["reason"] === "user_revoked",
      ),
    )
    .toHaveLength(1);
});

test("E09-TC-D03 sign out everywhere from A: B's tapped socket gets bye session_revoked then 4401, and B's next call lands on SCR-001 @clock", async ({
  page,
  lane,
}) => {
  await lane.refreshes(4); // each device's page load, B's refused call, B's SCR-001 page load
  const { a, b, tap } = await twoDevices(page, lane);
  await a.goto(PROFILE);
  const table = a.getByRole("table", { name: SESSIONS });
  await expect(table.getByRole("row")).toHaveCount(3);
  await a.getByRole("button", { name: "Sign out everywhere" }).click();
  const confirm = a.getByRole("alertdialog", { name: "Sign out everywhere?" });
  await confirm.getByRole("button", { name: "Sign out everywhere" }).click();
  await expect(a).toHaveURL(/\/login\?next=%2Fsettings%2Fprofile$/u);
  await expect(a.getByRole("heading", { name: SIGN_IN })).toBeVisible();
  await byeThen4401(tap);
  await nextCallSignsOut(b, tap);
});
