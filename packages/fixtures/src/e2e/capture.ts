import { expect, type Page } from "@playwright/test";

// E10-Q02 capture conventions for the screenshot corpus (consumer: E49 design QA and the
// visual-regression baseline): a frozen clock, no motion, fixed viewports, seeded stubs. A capture
// is taken twice and must be byte-identical, so "deterministic" is checked, not claimed.

/** The instant every capture shows (the stubs' own `server_time` day). */
export const FROZEN_AT = new Date("2026-09-14T10:31:00.000Z");

/** The fixed viewport set: the desktop reference and the narrow shell breakpoint. */
export const VIEWPORTS = [
  { name: "1440x900", width: 1440, height: 900 },
  { name: "1024x768", width: 1024, height: 768 },
] as const;

/** Freezes the page clock and turns motion off before the first navigation. */
export async function prepareCapture(page: Page): Promise<void> {
  await page.clock.install({ time: FROZEN_AT });
  await page.clock.pauseAt(FROZEN_AT);
  await page.emulateMedia({ reducedMotion: "reduce" });
}

/** Two full-page captures of the settled page, asserted identical; returns the first. */
export async function captureTwice(page: Page): Promise<Buffer> {
  const shot = () => page.screenshot({ fullPage: true, animations: "disabled", caret: "hide" });
  const first = await shot();
  const second = await shot();
  expect(Buffer.compare(first, second), "two captures of one surface differ").toBe(0);
  return first;
}
