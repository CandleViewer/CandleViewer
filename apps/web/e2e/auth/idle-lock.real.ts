import { randomBytes } from "node:crypto";
import type { Page, Response } from "@playwright/test";
import { ABSOLUTE_LIFETIME_MS, IDLE_TIMEOUT_S } from "../support/contexts";
import { sessionByCookie } from "../support/real/cookies";
import { expect, test, type Lane } from "../support/real/failureArtefacts";
import { answerTo, signIn } from "../support/real/signIn";

// E09-Q02 (#293) PR 3 (#2086): AC2 and the absolute lifetime on the server's own clock. The API
// reads its auth time as UTC plus the offset `lane.stack.clock` writes (`support/serverClock.ts`),
// so a spec moves it on and waits for nothing; the browser's clock is never touched. Each step
// passes its limit by a minute (plan rows C02 to C04), never its edge. The access token lives
// 12 min, so a call after either jump is refused, and the refresh it makes says why:
// `session_idle_locked` past the idle timeout; past the lifetime the session is gone (`22` "Idle
// lock": a locked one still reads as locked by its cookie, a gone one is `401`).
// The route is SCR-123: its form is the typed state, and its submit is the gated call.

const ROUTE = "/admin/users/new";
const NEXT = /\/login\?next=%2Fadmin%2Fusers%2Fnew$/u;
const SIGN_IN = "Sign in to CandleViewer";
const MARGIN_S = 60;
const LIFETIME_S = ABSOLUTE_LIFETIME_MS / 1_000;
const REFRESH = "/api/v1/auth/refresh";

const codeOf = async (r: Response): Promise<unknown> =>
  ((await r.json().catch(() => ({}))) as { code?: unknown }).code;

/** A fixture user signed in on SCR-123 with a username typed; the shell has read its session. */
async function typedOnInvite(page: Page, lane: Lane): Promise<string> {
  await signIn(page, lane.stack, lane.user());
  // the lock host's first read: once answered, nothing but a call of the test's reads the session
  await Promise.all([
    page.waitForResponse(answerTo("/api/v1/auth/session", "GET")),
    page.goto(ROUTE),
  ]);
  await expect(page.getByRole("heading", { level: 1, name: "Invite user" })).toBeVisible();
  const name = `idle-${randomBytes(4).toString("hex")}`;
  await page.getByLabel("Username").fill(name);
  return name;
}

test("E09-TC-C02 (server half) past the idle timeout a gated call opens SCR-005 over the route; unlock returns to it, typed state and focus kept @clock", async ({
  page,
  lane,
}) => {
  await lane.refreshes(3); // the page load, the locked call's refresh, the refresh after unlock
  const typed = await typedOnInvite(page, lane);
  const username = page.getByLabel("Username");
  lane.stack.clock.advance(IDLE_TIMEOUT_S + MARGIN_S); // no extend, no unlock: nothing is activity
  const [locked] = await Promise.all([
    page.waitForResponse(answerTo(REFRESH, "POST")),
    username.press("Enter"), // the user is back and submits
  ]);
  expect({ status: locked.status(), code: await codeOf(locked) }).toEqual({
    status: 401,
    code: "session_idle_locked",
  });
  const lock = page.getByRole("alertdialog", { name: "Session locked" });
  await expect(lock).toBeVisible();
  await expect(page).toHaveURL(/\/admin\/users\/new$/u);
  await expect(lock.getByLabel("Password")).toBeFocused();

  await lock.getByLabel("Password").fill(lane.stack.password());
  const [unlocked, refreshed] = await Promise.all([
    page.waitForResponse(answerTo("/api/v1/auth/unlock", "POST")),
    // 22 "Idle lock": the client unlocks, then refreshes
    page.waitForResponse(answerTo(REFRESH, "POST")),
    page.keyboard.press("Enter"),
  ]);
  expect(unlocked.status()).toBe(200);
  expect(refreshed.status(), "the unlocked session refreshes again").toBe(200);
  await expect(lock).toBeHidden();
  await expect(page).toHaveURL(/\/admin\/users\/new$/u);
  await expect(username).toHaveValue(typed);
  await expect(username).toBeFocused(); // E09-D06 §6: back to the element that had focus
});

test("E09-TC-C03 (server half) the 12 h lifetime lapsing while SCR-005 is up: unlock shows the expiry card, whose Sign in is SCR-001 @clock", async ({
  page,
  lane,
}) => {
  await lane.refreshes(3); // the page load, the locked call's refresh, SCR-001's page load
  await typedOnInvite(page, lane);
  lane.stack.clock.advance(IDLE_TIMEOUT_S + MARGIN_S);
  await page.getByLabel("Username").press("Enter");
  const lock = page.getByRole("alertdialog", { name: "Session locked" });
  await expect(lock).toBeVisible();
  lane.stack.clock.advance(LIFETIME_S); // the screen sat locked past the absolute lifetime

  await lock.getByLabel("Password").fill(lane.stack.password());
  const [refused] = await Promise.all([
    page.waitForResponse(answerTo("/api/v1/auth/unlock", "POST")),
    page.keyboard.press("Enter"),
  ]);
  const body = (await refused.json().catch(() => ({}))) as Record<string, unknown>;
  expect({ status: refused.status(), code: body["code"], why: body["revoked_reason"] }).toEqual({
    status: 401,
    code: "session_revoked",
    why: "expired",
  });
  const expired = page.getByRole("alertdialog", { name: "Session expired" });
  await expect(expired).toBeVisible();
  await expect(lock).toHaveCount(0);
  await expect(expired.getByRole("button", { name: "Sign in" })).toBeFocused();
  await expired.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(NEXT);
  await expect(page.getByRole("heading", { name: SIGN_IN })).toBeVisible();
});

test("E09-TC-C04 (server half) a gated action 12 h + 1 min after sign-in is refused 401 and ends at SCR-001, never SCR-006 @clock", async ({
  page,
  lane,
}) => {
  await lane.refreshes(3); // the page load, the refused call's refresh, SCR-001's page load
  const challenges: number[] = [];
  page.on("response", (r) => {
    if (r.status() === 403 && new URL(r.url()).pathname === "/api/v1/users") challenges.push(403);
  });
  const name = await typedOnInvite(page, lane);
  await page.getByLabel("Email").fill(`${name}@example.test`);
  lane.stack.clock.advance(LIFETIME_S + MARGIN_S);
  const [create, refreshed] = await Promise.all([
    page.waitForResponse(answerTo("/api/v1/users", "POST")),
    page.waitForResponse(answerTo(REFRESH, "POST")),
    page.getByRole("button", { name: "Create invitation" }).click(),
  ]);
  expect(create.status(), "the lapsed session is refused before any step-up gate").toBe(401);
  // its body is not read: the SPA leaves for SCR-001 on it, and the navigation drops the body
  expect(refreshed.status(), "the refresh finds no session to renew").toBe(401);
  await expect(page).toHaveURL(NEXT);
  await expect(page.getByRole("heading", { name: SIGN_IN })).toBeVisible();
  expect(challenges, "no step-up challenge revives a session past its lifetime").toEqual([]);
  // gone, not locked: the cookie that still identifies a locked session identifies nothing now
  expect(await sessionByCookie(page)).toEqual({ status: 401, code: "unauthenticated" });
});
