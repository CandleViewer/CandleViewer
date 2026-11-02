import { expect, test, type Page } from "@playwright/test";
import { stubSession, stubSessionsList } from "../support/api";
import { stubRecorder } from "../support/recorder";
import { REFRESH_INVALID } from "../support/contexts";
import type { A11yScreen } from "./screens";

/**
 * The bound on one step of one screen (its <main>, its h1, a capture beyond its own window): far
 * under the 300 s test timeout, so a screen that never settles fails by name instead of holding the
 * whole sweep until the timeout (#5151).
 */
export const STEP_TIMEOUT_MS = 10_000;
/**
 * Screens visited before `sweep` projects the pace. The first (cold) screen is left out of the
 * per-screen rate, so one slow cold start on a slow runner is not read as a trend.
 */
const PACE_SAMPLE = 5;

/** Per-screen data stubs, so the collectors audit the populated state, not an error. */
const SCREEN_STUBS: Readonly<Record<string, (page: Page) => Promise<void>>> = {
  "R-201": stubSessionsList, // SCR-112 sessions: the table with the current session marked
  "R-340": async (page) => void (await stubRecorder(page)), // SCR-140: a fresh install's empty state
};

/**
 * Opens one screen for a collector and waits until it has rendered. A signed-in screen enters
 * through the app's own bootstrap with /api/v1/me answered at the network layer, and the call fails
 * unless the route guard let it in and its h1 rendered: a bounce to /login renders a <main> of its
 * own, so waiting for any <main> would pass on the wrong page (#3470).
 */
export async function openScreen(page: Page, s: A11yScreen): Promise<void> {
  // Stubs are per screen: one left behind by a signed-in screen would sign the next public one in.
  await page.unrouteAll({ behavior: "ignoreErrors" });
  // A bare screen is a signed-out visitor: the page-load refresh gets the server's one 401, as
  // `contexts.ts` answers it. Unanswered, `vite preview` 404s it, the access-token client keeps its
  // refresh-sent mark (a 404 may follow a rotation) and every later load in the context waits out
  // ORPHAN_WAIT_MS before its first paint, on Date.now(), which a fixed clock never moves (#5151).
  if (s.signedIn) await stubSession(page, { role: s.signedIn.role });
  else await page.route("**/api/v1/auth/refresh", (r) => r.fulfill(REFRESH_INVALID));
  await SCREEN_STUBS[s.id]?.(page);
  await page.goto(s.path);
  await expect(
    page.getByRole("main").first(),
    `${s.id} (${s.path}): no <main> rendered within ${STEP_TIMEOUT_MS / 1000} s`,
  ).toBeVisible({ timeout: STEP_TIMEOUT_MS });
  if (!s.signedIn) return;
  const landed = new URL(page.url()).pathname;
  if (landed !== s.path) {
    throw new Error(
      `${s.id}: opened ${s.path} but landed on ${landed}; the session stub did not hold`,
    );
  }
  // expect gives up after its 5 s default; waitFor has no default timeout, so a missing h1 would
  // hold until the 300 s test timeout.
  await expect(
    page.getByRole("heading", { level: 1, name: s.signedIn.heading, exact: true }),
    `${s.id}: its h1 did not render`,
  ).toBeVisible();
  if (s.id === "R-201") {
    const table = page.getByRole("table"); // the list state, not loading
    await expect(table, `${s.id}: its table did not render`).toBeVisible({
      timeout: STEP_TIMEOUT_MS,
    });
  }
}

/** `work`, or an error naming `what` once `ms` pass: for a wait that takes no timeout of its own. */
export async function bounded<T>(what: string, ms: number, work: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${what}: not done within ${ms / 1000} s`)), ms);
  });
  try {
    return await Promise.race([work, deadline]);
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Visits `screens` in order for one collector. A failing screen is named in the error, and a
 * sweep whose pace would overrun the test timeout stops as soon as that is clear, naming its
 * slowest screen, instead of timing out on whichever screen is open at 300 s (#5151).
 */
export async function sweep(
  collector: string,
  screens: readonly A11yScreen[],
  visit: (s: A11yScreen) => Promise<void>,
): Promise<void> {
  const budgetMs = test.info().timeout; // 0: no timeout, so no pace to keep
  const start = Date.now();
  let slowest = { id: "", ms: 0 };
  let firstMs = 0; // the cold start, kept out of the projected rate
  for (const [i, s] of screens.entries()) {
    const began = Date.now();
    try {
      await visit(s);
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      throw new Error(`${collector}: ${s.id} (${s.path}) failed: ${reason}`, { cause: error });
    }
    const ms = Date.now() - began;
    if (i === 0) firstMs = ms;
    if (ms > slowest.ms) slowest = { id: s.id, ms };
    const done = i + 1;
    const spentMs = Date.now() - start;
    // What is spent, plus the screens left at the warm rate (every screen after the first).
    const warmRateMs = (spentMs - firstMs) / Math.max(done - 1, 1);
    const projectedMs = spentMs + warmRateMs * (screens.length - done);
    if (budgetMs > 0 && done >= PACE_SAMPLE && done < screens.length && projectedMs > budgetMs) {
      const s1 = (n: number): string => (n / 1000).toFixed(1);
      throw new Error(
        `${collector}: ${done}/${screens.length} screens took ${s1(spentMs)} s, a pace that` +
          ` overruns the ${s1(budgetMs)} s test timeout (projected ${s1(projectedMs)} s;` +
          ` slowest ${slowest.id} at ${s1(slowest.ms)} s)`,
      );
    }
  }
}
