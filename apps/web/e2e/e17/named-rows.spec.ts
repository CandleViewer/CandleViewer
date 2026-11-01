// E17-Q04 (#569), web shell: the two rows 23-ws-protocol.md section 16.4 names (C8 hidden tab, C12 kill switch and
// shutdown notice). A browser tab is hidden through the page's own visibility API, as a background tab reports it;
// the Electron copy hides the window itself (`apps/desktop/e2e/e17-named-rows.spec.ts`).
import { expect, test, type Page } from "@playwright/test";
import {
  hiddenTabRestoredWithoutSnapshot,
  killSwitchFrameShowsOrderEntryOff,
  shutdownNoticeShowsOrderEntryOff,
} from "./namedRows";
import {
  FAST_HEARTBEAT,
  KILL_ENGAGED,
  PACK,
  chip,
  covers,
  openWorkspace,
  patient,
  region,
} from "./support";

/** What a hidden tab reports: `visibilityState` and `hidden`, then the event the WS client listens for. */
async function setVisibility(page: Page, hidden: boolean): Promise<void> {
  await page.evaluate((h) => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => (h ? "hidden" : "visible"),
    });
    Object.defineProperty(document, "hidden", { configurable: true, get: () => h });
    document.dispatchEvent(new Event("visibilitychange"));
  }, hidden);
}

test(`Q04-N01 C8: a hidden then restored tab sends only heartbeats, no new snapshot ${PACK}`, async ({
  page,
}) => {
  covers("C8", "D02-row-2", "AC-1");
  const harness = await openWorkspace(page, { heartbeat: FAST_HEARTBEAT });
  await hiddenTabRestoredWithoutSnapshot({
    page,
    harness,
    hide: () => setVisibility(page, true),
    show: () => setVisibility(page, false),
  });
});

test(`Q04-N02 C12: a kill_switch frame turns order entry off, said once, no REST call ${PACK}`, async ({
  page,
}) => {
  covers("C12", "D02-row-17", "WS-E06", "AC-1");
  const harness = await openWorkspace(page, { heartbeat: FAST_HEARTBEAT });
  await killSwitchFrameShowsOrderEntryOff({ page, harness });
});

test(`Q04-N03 C12: a shutdown_notice turns order entry off, said once ${PACK}`, async ({
  page,
}) => {
  covers("C12", "D02-row-8", "AC-1");
  const harness = await openWorkspace(page, { heartbeat: FAST_HEARTBEAT });
  await shutdownNoticeShowsOrderEntryOff({ page, harness });
});

test(`Q04-N04 C12 after a reconnect: the kill switch is what auth_ok says, never the old mirror ${PACK}`, async ({
  page,
}) => {
  covers("C12", "D02-row-16", "WS-E06", "AC-3");
  const harness = await openWorkspace(page);
  harness.sendSystem(KILL_ENGAGED);
  await patient(region(page)).toHaveAttribute("data-reason", "R2-kill-switch"); // M-N04-1
  harness.kill();
  // Disconnected outranks the switch, which is unknown, not "not killed", while the link is down.
  await patient(region(page)).toHaveAttribute("data-reason", "disconnected"); // M-N04-2
  harness.restore();
  await patient.poll(() => harness.authenticated()).toBe(2);
  // This gateway's `auth_ok` says disengaged (released during the outage): the region goes, R2 is not kept.
  await patient(region(page)).toHaveCount(0); // M-N04-3
  await expect(chip(page)).toHaveAttribute("data-status", "live"); // M-N04-4
});
