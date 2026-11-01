// E17-Q04 (#569): one smoke per command of the dev-only fault channel (E17-T04 S5e, `faultChannel.ts`) on a build made
// with `CV_ALLOW_FAULT_INJECTION=1` (`playwright.fault.config.ts`): the channel E17-D04 forces states with works, and
// what it injects reaches the same chrome the fixture gateway's specs read. The fixture gateway still answers the
// socket; the command goes to the shared worker over the tab's own port, as the `fault` port message (`messages.ts`).
import { expect, test, type Page } from "@playwright/test";
import type { WsHarness } from "../support/wsHarness";
import {
  FAST_HEARTBEAT,
  PACK,
  SAID,
  assertive,
  chip,
  covers,
  openWorkspace,
  patient,
  region,
  settle,
} from "./support";

/** Keeps each `SharedWorker`'s port (after the harness's own wrapper), so a test can post a `fault` on it. */
async function keepPorts(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const Wrapped = window.SharedWorker;
    const ports: MessagePort[] = [];
    Object.assign(window, { cvE2eFaultPorts: ports });
    window.SharedWorker = function (url: string | URL, opts?: string | WorkerOptions) {
      const worker = new Wrapped(url, opts);
      ports.push(worker.port);
      return worker;
    } as unknown as typeof SharedWorker;
  });
}

async function fault(page: Page, command: Readonly<Record<string, unknown>>): Promise<void> {
  await page.evaluate((c) => {
    const ports = (window as unknown as { cvE2eFaultPorts: MessagePort[] }).cvE2eFaultPorts;
    for (const port of ports) port.postMessage({ t: "fault", command: c });
  }, command);
}

async function open(page: Page): Promise<WsHarness> {
  await keepPorts(page);
  return openWorkspace(page, { heartbeat: FAST_HEARTBEAT });
}

test(`Q04-F01 fault close 4400: Offline — retry stopped ${PACK}`, async ({ page }) => {
  covers("C7", "D02-row-6", "AC-2");
  await open(page);
  await fault(page, { kind: "close", code: 4400 });
  await patient(chip(page)).toHaveAttribute("data-status", "offline");
  await patient(assertive(page)).toHaveText(SAID.retryStopped);
});

test(`Q04-F02 fault drop: the next system delta never arrives, so the client resyncs ${PACK}`, async ({
  page,
}) => {
  covers("C2", "D02-row-9", "US-MKT-006#Gap detection");
  const harness = await open(page);
  await fault(page, { kind: "drop", ch: "system" });
  await settle(harness); // the command is in before the deltas
  harness.sendSystem({ kind: "health", health: "healthy" });
  harness.sendSystem({ kind: "health", health: "healthy" });
  await patient
    .poll(() => harness.frames.map((f) => f.frame).find((f) => f.t === "resync"))
    .toMatchObject({ ch: "system", p: { reason: "sequence_gap" } });
});

test(`Q04-F03 fault delay: what the server says reaches the chrome late, in order ${PACK}`, async ({
  page,
}) => {
  covers("C12", "D02-row-17", "AC-2");
  const harness = await open(page);
  await fault(page, { kind: "delay", ms: 1_500 });
  await settle(harness);
  const sentAt = Date.now();
  harness.sendSystem({
    kind: "kill_switch",
    kill_switch: { engaged: true, scope: "global", exchange_account_ids: [] },
  });
  await patient(region(page)).toHaveAttribute("data-reason", "R2-kill-switch");
  expect(Date.now() - sentAt).toBeGreaterThanOrEqual(1_400); // a floor only: never a ceiling on a real clock
});

test(`Q04-F04 fault quality: a saturated class is taken, numbered without a gap ${PACK}`, async ({
  page,
}) => {
  covers("C4", "D02-row-5", "AC-2");
  const harness = await open(page);
  await fault(page, { kind: "quality", class: "saturated" });
  await settle(harness);
  // The injected frame took a number: the gateway's next real delta still applies, with no gap.
  harness.sendSystem({
    kind: "kill_switch",
    kill_switch: { engaged: true, scope: "global", exchange_account_ids: [] },
  });
  await patient(region(page)).toHaveAttribute("data-reason", "R2-kill-switch");
  expect(harness.frames.some((f) => f.frame.t === "resync")).toBe(false);
});

test(`Q04-F05 fault shutdown: order entry off, said once ${PACK}`, async ({ page }) => {
  covers("C12", "D02-row-8", "AC-1");
  await open(page);
  await fault(page, { kind: "shutdown", closingInMs: 5_000, downtimeMs: 20_000 });
  await patient(region(page)).toHaveAttribute("data-reason", "R1-shutdown");
  await patient(assertive(page)).toHaveText(SAID.shutdown);
});

test(`Q04-F06 fault killSwitch: order entry off, said once ${PACK}`, async ({ page }) => {
  covers("C12", "D02-row-17", "AC-1");
  await open(page);
  await fault(page, { kind: "killSwitch", engaged: true });
  await patient(region(page)).toHaveAttribute("data-reason", "R2-kill-switch");
  await patient(assertive(page)).toHaveText(SAID.killSwitch);
});

test(`Q04-F07 fault revoke on system: the kill switch reads unknown, order entry off ${PACK}`, async ({
  page,
}) => {
  covers("C12", "D02-row-15", "D02-row-18", "WS-E06");
  await open(page);
  await fault(page, { kind: "revoke", ch: "system", reason: "permission_removed" });
  await patient(region(page)).toHaveAttribute("data-reason", "R6-system-unknown");
  await patient(assertive(page)).toHaveText(SAID.systemUnknown);
});

test(`Q04-F08 fault staleSnap on system: a stale snapshot leaves the kill switch unknown ${PACK}`, async ({
  page,
}) => {
  covers("C21", "D02-row-12", "D02-row-18", "WS-E06");
  await open(page);
  await fault(page, { kind: "staleSnap", ch: "system" });
  // A stale `system` is not trusted (WS-E06): the switch reads unknown, never "not killed".
  await patient(region(page)).toHaveAttribute("data-reason", "R6-system-unknown");
  await patient(assertive(page)).toHaveText(SAID.systemUnknown);
  await expect(chip(page)).toHaveAttribute("data-status", "live");
});
