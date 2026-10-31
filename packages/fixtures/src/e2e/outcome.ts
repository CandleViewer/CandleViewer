import { expect, type Page } from "@playwright/test";
import { classify, type Outcome } from "./routes";

/** Consecutive identical reads before a landing counts as settled. */
const SETTLED_READS = 3;

/**
 * Asserts the landing of `requested` classifies as `expected` and holds: the first matching read is
 * not enough, since a loading heading or a late guard redirect could match `render` and then turn
 * into a denial. The poll passes only after SETTLED_READS identical reads in a row (on Playwright's
 * poll intervals; no fixed sleep). `networkidle` is no settle signal here: the shell keeps polling.
 */
export async function expectSettledOutcome(
  page: Page,
  requested: string,
  expected: Outcome | undefined,
  message?: string,
): Promise<void> {
  const h1 = page.getByRole("heading", { level: 1 }).first();
  let last: Outcome | undefined;
  let streak = 0;
  const read = async (): Promise<string> => {
    const now = classify(requested, new URL(page.url()).pathname, (await h1.textContent()) ?? "");
    streak = now === last ? streak + 1 : 1;
    last = now;
    return streak >= SETTLED_READS ? now : `${now} (not settled yet)`;
  };
  await expect.poll(read, message === undefined ? {} : { message }).toBe(expected);
}
