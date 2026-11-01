// E17-Q04 (#569): the two rows 23-ws-protocol.md section 16.4 names (C8, C12) as one body each, run by the web spec
// `named-rows.spec.ts`. The shells differ in how a window is hidden, not in what must follow; the Electron copy is
// `apps/desktop/e2e/e17-named-rows.spec.ts`. Every assertion here has its mutation line in the pack.
import { expect, type Page } from "@playwright/test";
import type { WsHarness } from "../support/wsHarness";
import {
  KILL_ENGAGED,
  SAID,
  SHUTDOWN_NOTICE,
  assertive,
  chip,
  markAnnounced,
  patient,
  region,
  settle,
  stillTheSameAnnouncement,
  watchPolls,
} from "./support";

export interface Open {
  readonly page: Page;
  readonly harness: WsHarness;
}
export interface Hidable extends Open {
  /** Makes the host's `document.visibilityState` "hidden" (a tab, or a hidden window) and returns when it is. */
  readonly hide: () => Promise<void>;
  readonly show: () => Promise<void>;
}

const snaps = (h: WsHarness): number => h.sent.filter((f) => f.t === "snap").length;
/** What the client sent from frame `from` on, heartbeats left out. */
const traffic = (h: WsHarness, from: number): string[] =>
  h.frames
    .slice(from)
    .map((f) => f.frame.t)
    .filter((t) => t !== "ping" && t !== "pong");

/**
 * C8 (23 section 5.4; 16.4 "Hidden tab drops throttles; restored tab does not re-snapshot"), the restore half: after
 * hide then show, the client sent nothing but heartbeats, the gateway sent no new `snap`, the socket is the same one,
 * and the chrome never left Live. The throttle half needs a mounted consumer of a topic (ledger row C8-a).
 */
export async function hiddenTabRestoredWithoutSnapshot({
  page,
  harness,
  hide,
  show,
}: Hidable): Promise<void> {
  await settle(harness); // the first connect's frames are in
  const framesBefore = harness.frames.length;
  const snapsBefore = snaps(harness);
  const connectionsBefore = harness.connections();
  await hide();
  await settle(harness);
  await show();
  await settle(harness);
  expect(traffic(harness, framesBefore)).toEqual([]); // M-N01-1
  expect(snaps(harness)).toBe(snapsBefore); // M-N01-2
  expect(harness.connections()).toBe(connectionsBefore); // M-N01-3
  await expect(chip(page)).toHaveAttribute("data-status", "live"); // M-N01-4
  await expect(region(page)).toHaveCount(0); // M-N01-5
}

/**
 * C12 (23 section 4.2: "disable order entry on this frame alone"; 16.4 "Kill-switch frame disables the order ticket
 * without a REST round-trip"), the half the build can show: the `kill_switch` frame alone puts the region in R2 and
 * says so once, and no request that could poll the kill switch leaves the page. The order ticket half waits for an
 * order ticket (ledger row C12-a).
 */
export async function killSwitchFrameShowsOrderEntryOff({ page, harness }: Open): Promise<void> {
  const polls = watchPolls(page);
  harness.sendSystem(KILL_ENGAGED);
  await patient(region(page)).toHaveAttribute("data-reason", "R2-kill-switch"); // M-N02-1
  await expect(region(page)).toHaveAttribute("data-state", "read-only"); // M-N02-2
  await expect(region(page)).toContainText("Order entry off — trading frozen by the owner."); // M-N02-3
  await patient(assertive(page)).toHaveText(SAID.killSwitch); // M-N02-4
  await expect(chip(page)).toHaveAttribute("data-status", "live"); // M-N02-5
  await markAnnounced(page);
  await settle(harness);
  await stillTheSameAnnouncement(page); // M-N02-6
  expect(polls).toEqual([]); // M-N02-7
}

/**
 * C12's second clause ("and on `shutdown_notice`"; 23 section 4.4): the notice puts the region in R1 and says so once;
 * the chip stays as it was until the close. The countdown is not built (ledger row P-8).
 */
export async function shutdownNoticeShowsOrderEntryOff({ page, harness }: Open): Promise<void> {
  const polls = watchPolls(page);
  harness.sendSystem(SHUTDOWN_NOTICE);
  await patient(region(page)).toHaveAttribute("data-reason", "R1-shutdown"); // M-N03-1
  await expect(region(page)).toHaveAttribute("data-state", "read-only"); // M-N03-2
  await patient(assertive(page)).toHaveText(SAID.shutdown); // M-N03-3
  await expect(chip(page)).toHaveAttribute("data-status", "live"); // M-N03-4
  await markAnnounced(page);
  await settle(harness);
  await stillTheSameAnnouncement(page); // M-N03-5
  expect(polls).toEqual([]); // M-N03-6
}
