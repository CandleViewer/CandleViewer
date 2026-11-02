// E17-Q04 (#569): the automated half of the E17 accessibility check, in each transport state the build can force:
// axe-core with zero violations of ANY impact (AC 4), keyboard operation of the region, reduced motion, 200% reflow.
// The manual half (NVDA, VoiceOver, the focus-order walk) is the pack's section E, owner-run; nothing here claims a
// screen-reader result. Each check has one owner in the pack's section D (`Q04 automated` or `D04 manual`).
// Dark theme, the default; the light theme's pass is a D04 row.
import { expect, test, type Locator, type Page } from "@playwright/test";
import type { WsHarness } from "../support/wsHarness";
import {
  BYE_FATAL,
  BYE_SESSION_ENDED,
  KILL_ENGAGED,
  PACK,
  SHUTDOWN_NOTICE,
  chip,
  chipSettled,
  covers,
  openWorkspace,
  patient,
  region,
  retryNow,
  strictAxe,
} from "./support";

interface Forced {
  readonly state: string;
  readonly row: string;
  readonly hold?: boolean;
  readonly drive: (harness: WsHarness) => void;
  readonly ready: (page: Page, harness: WsHarness) => Promise<void>;
}

const regionSays = (text: string) => async (page: Page) =>
  void (await patient(region(page)).toContainText(text));
const reasonIs = (reason: string) => async (page: Page) =>
  void (await patient(region(page)).toHaveAttribute("data-reason", reason));

// E17-D01's six states, as far as the build can force them (Stale cannot be: no topic consumer is mounted, ledger
// rows 10 to 12), then the variants of Disconnected and Read-only that draw their own region.
const FORCED: readonly Forced[] = [
  {
    state: "Live",
    row: "D02-row-2",
    drive: () => undefined,
    ready: async (page) => void (await patient(chip(page)).toHaveAttribute("data-status", "live")),
  },
  {
    state: "Disconnected",
    row: "D02-row-3",
    drive: (h) => h.kill(),
    ready: regionSays("Disconnected — reconnecting"),
  },
  {
    state: "Resyncing",
    row: "D02-row-9",
    drive: (h) => {
      h.hold("resync");
      h.desync();
    },
    ready: reasonIs("R6-system-unknown"),
  },
  {
    state: "Delayed",
    row: "D02-row-5",
    drive: (h) => h.sendSystem({ kind: "connection_quality", class: "saturated", queue_pct: 70 }),
    ready: async (page, h) => {
      await patient.poll(() => h.sent.at(-1)?.["p"]).toMatchObject({ class: "saturated" });
      await patient(chip(page)).toHaveAttribute("data-status", "live");
    },
  },
  {
    state: "Read-only (kill switch)",
    row: "D02-row-17",
    drive: (h) => h.sendSystem(KILL_ENGAGED),
    ready: reasonIs("R2-kill-switch"),
  },
  {
    state: "Read-only (shutdown notice)",
    row: "D02-row-8",
    drive: (h) => h.sendSystem(SHUTDOWN_NOTICE),
    ready: reasonIs("R1-shutdown"),
  },
  {
    state: "Disconnected (first connect)",
    row: "D02-row-1",
    hold: true,
    drive: () => undefined,
    ready: async (page) =>
      void (await patient(chip(page)).toHaveAttribute("aria-label", "Connection: Connecting…")),
  },
  {
    state: "Disconnected (retry stopped)",
    row: "D02-row-6",
    drive: (h) => h.closeWith({ code: BYE_FATAL.code, reason: BYE_FATAL.reason, bye: BYE_FATAL }),
    ready: regionSays("Offline — retry stopped"),
  },
  {
    state: "Disconnected (session ended)",
    row: "D02-row-21",
    drive: (h) =>
      h.closeWith({
        code: BYE_SESSION_ENDED.code,
        reason: BYE_SESSION_ENDED.reason,
        bye: BYE_SESSION_ENDED,
      }),
    ready: regionSays("Session ended"),
  },
];

for (const forced of FORCED) {
  test(`Q04-X01 axe: zero violations of any impact, ${forced.state} ${PACK}`, async ({ page }) => {
    covers("C-14.1", forced.row, "AC-4");
    const harness = await openWorkspace(page, forced.hold === true ? { hold: true } : {});
    forced.drive(harness);
    await forced.ready(page, harness);
    await chipSettled(page);
    expect(await strictAxe(page)).toEqual([]);
  });
}

/** Presses Tab until `target` has focus; a bound, not a wait. Fails with the count, so a reordered shell is a finding. */
async function tabTo(page: Page, target: Locator, presses = 80): Promise<void> {
  for (let i = 0; i < presses; i += 1) {
    if (await target.evaluate((el) => el === document.activeElement)) return;
    await page.keyboard.press("Tab");
  }
  throw new Error(`"Retry now" was not reached by ${presses} Tab presses`);
}

for (const key of ["Enter", "Space"] as const) {
  test(`Q04-X02 keyboard: Retry now by Tab and ${key}; a state change never moves focus ${PACK}`, async ({
    page,
  }) => {
    covers("C-14.1", "D02-row-6", "AC-4");
    const harness = await openWorkspace(page);
    const anchor = chip(page);
    await anchor.focus();
    harness.closeWith({ code: BYE_FATAL.code, reason: BYE_FATAL.reason, bye: BYE_FATAL });
    await patient(retryNow(page)).toBeVisible();
    await expect(anchor).toBeFocused(); // the region draws without taking focus
    // A non-modal region (E17-D02 section 6): no dialog, no modal flag, no trap.
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(region(page)).not.toHaveAttribute("aria-modal", /.*/);
    await tabTo(page, retryNow(page));
    const before = harness.connections();
    await page.keyboard.press(key);
    await patient.poll(() => harness.authenticated()).toBe(2); // the stopped retry comes back only by this press
    expect(harness.connections()).toBe(before + 1);
    await patient(chip(page)).toHaveAttribute("data-status", "live");
    await expect(region(page)).toHaveCount(0);
  });
}

test(`Q04-X03 reduced motion: the chip changes state with no cross-fade ${PACK}`, async ({
  page,
}) => {
  covers("C-14.1", "D02-row-3", "AC-4");
  await page.emulateMedia({ reducedMotion: "reduce" });
  const harness = await openWorkspace(page);
  harness.kill();
  await patient(chip(page)).toHaveAttribute("data-status", "reconnecting");
  const fade = chip(page).locator("[data-fade]"); // the cross-fade wrapper has no role or label to query
  await expect(fade).toHaveCSS("transition-property", "none");
  await expect(fade).toHaveCSS("opacity", "1");
});

test(`Q04-X04 full motion, the control: the same change does fade ${PACK}`, async ({ page }) => {
  covers("C-14.1", "D02-row-3", "AC-4");
  const harness = await openWorkspace(page);
  harness.kill();
  await patient(chip(page)).toHaveAttribute("data-status", "reconnecting");
  await chipSettled(page);
  // the cross-fade wrapper has no role or label to query
  await expect(chip(page).locator("[data-fade]")).toHaveCSS("transition-property", "opacity");
});

test(`Q04-X05 200% zoom: the offline region reflows at 640 px, Retry now in view ${PACK}`, async ({
  page,
}) => {
  covers("C-14.1", "D02-row-6", "AC-4");
  await page.setViewportSize({ width: 640, height: 400 }); // a 1280 x 800 reference at 200%
  const harness = await openWorkspace(page);
  harness.closeWith({ code: BYE_FATAL.code, reason: BYE_FATAL.reason, bye: BYE_FATAL });
  await patient(retryNow(page)).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  const box = await retryNow(page).boundingBox();
  expect(box).not.toBeNull();
  expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(640);
  await expect(chip(page)).toBeVisible();
});
