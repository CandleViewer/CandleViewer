// E17-Q04 (#569): the transport states a trader can be in, forced one at a time on the fixture gateway against the REAL
// web client and shell. Each test names what it guards (`covers`: the C-rule, the E17-D02 row, the story or AC), which
// the audit tool matches against the pack's ledger (`qa/plans/e17-regression-pack.md`).
// Driver: the harness (`wsHarness.ts`: `kill`, `restore`, `closeWith`, `desync`, `hold`, `sendSystem`, `sendErr`) on the
// shipped bundle; the dev-only fault channel has its own flagged-build smoke (`fault-channel.flagged.ts`).
// Time: a test that moves the page's clock fakes it before the load (`openWorkspace({ clock: true })`); the worker keeps the
// real one (the first test shows it), so the worker's retries run on real, short, event-bounded waits and the gateway's
// counter supplies the server's times. Written for `--retries=0`. What the build cannot show yet is a ledger row in the
// pack, never a skipped test here.
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import {
  BYE_FATAL,
  BYE_SESSION_ENDED,
  BYE_SLOW_CONSUMER,
  FAST_HEARTBEAT,
  PACK,
  SAID,
  assertive,
  chip,
  covers,
  lastDataAgeSeconds,
  markAnnounced,
  openWorkspace,
  patient,
  region,
  retryNow,
  sentTypes,
  settle,
  signIn,
  statusWord,
  stillTheSameAnnouncement,
  systemSnaps,
} from "./support";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../../../..");
const ageNow = async (page: Parameters<typeof region>[0]): Promise<number> =>
  lastDataAgeSeconds(await region(page).textContent());

test(`Q04-S01 the page's clock moves the page, not the shared worker ${PACK}`, async ({ page }) => {
  covers("BQ-09");
  const harness = await openWorkspace(page, { clock: true, heartbeat: FAST_HEARTBEAT });
  await page.clock.fastForward(60_000);
  const pageNow = await page.evaluate(() => Date.now());
  await settle(harness);
  const ping = harness.frames.filter((f) => f.frame.t === "ping").at(-1)?.frame;
  const workerNow = Number((ping?.["p"] as { client_ms?: unknown } | undefined)?.client_ms);
  // The worker's `ping` carries its own clock: 60 s behind the page's, so the specs move the page alone.
  expect(pageNow - workerNow).toBeGreaterThan(50_000);
});

test(`Q04-S02 the suite runs on the shipped bundle, which has no fault channel ${PACK}`, () => {
  covers("BQ-02");
  const dir = join(ROOT, "apps/web/dist/assets");
  const bundles = readdirSync(dir).filter((f) => f.endsWith(".js"));
  expect(bundles.length).toBeGreaterThan(0);
  for (const file of bundles)
    expect(readFileSync(join(dir, file), "utf8")).not.toContain("cv-ws-fault-injection");
});

test(`Q04-T01 first connect reads Connecting… with no region and no announcement ${PACK}`, async ({
  page,
}) => {
  covers("C7", "D02-row-1", "US-MKT-005#Reconnect");
  const harness = await openWorkspace(page, { hold: true });
  await patient(chip(page)).toHaveAttribute("data-status", "reconnecting");
  await expect(chip(page)).toHaveAttribute("aria-label", "Connection: Connecting…");
  await expect(statusWord(page)).toHaveText("Connection: connecting");
  await expect(region(page)).toHaveCount(0); // a session start is not an outage (D02 section 11 row 15)
  await expect(assertive(page)).toHaveCount(0);
  harness.release("hello");
  await patient.poll(() => harness.authenticated()).toBe(1);
  await patient(chip(page)).toHaveAttribute("data-status", "live");
  await expect(statusWord(page)).toHaveText("Connection: live");
});

test(`Q04-T02 live: no region, no announcement, one socket ${PACK}`, async ({ page }) => {
  covers("C7", "D02-row-2", "US-MKT-005#Subscribed");
  const harness = await openWorkspace(page, { heartbeat: FAST_HEARTBEAT });
  await expect(chip(page)).toHaveAttribute("data-status", "live");
  await settle(harness);
  await expect(region(page)).toHaveCount(0);
  await expect(assertive(page)).toHaveCount(0);
  expect(harness.connections()).toBe(1);
});

test(`Q04-T03 a lost transport shows Disconnected and the last good time, said once ${PACK}`, async ({
  page,
}) => {
  covers("C7", "D02-row-3", "US-MKT-003#Feed interrupted", "AC-2");
  const harness = await openWorkspace(page, { clock: true });
  harness.kill();
  await patient(chip(page)).toHaveAttribute("data-status", "reconnecting");
  await expect(chip(page)).toHaveAttribute(
    "aria-label",
    /^Connection: Reconnecting.*\d\d:\d\d:\d\d UTC$/,
  );
  await expect(statusWord(page)).toHaveText("Connection: reconnecting");
  await patient(region(page)).toContainText("Disconnected — reconnecting");
  await expect(region(page)).toContainText("New orders off");
  await expect(region(page)).toContainText(/Last data \d\d:\d\d ago/);
  await expect(retryNow(page)).toBeVisible();
  await expect(signIn(page)).toHaveCount(0);
  await patient(assertive(page)).toHaveText(SAID.disconnected);
  // The age moves and the attempts cycle, and nothing more is said (D02 section 11 row 1: once per episode).
  await markAnnounced(page);
  const before = await ageNow(page);
  await page.clock.fastForward(4_000);
  await patient.poll(() => ageNow(page)).toBeGreaterThanOrEqual(before + 4);
  await stillTheSameAnnouncement(page);
});

test(`Q04-T04 reconnect: Live on a new session with a fresh snapshot; the episode ends ${PACK}`, async ({
  page,
}) => {
  covers("C7", "D02-row-16", "US-MKT-005#Reconnect", "AC-3");
  const harness = await openWorkspace(page);
  const before = systemSnaps(harness).length;
  harness.kill();
  await patient(region(page)).toBeVisible();
  await patient(assertive(page)).toHaveText(SAID.disconnected);
  harness.restore();
  await patient.poll(() => harness.authenticated()).toBe(2);
  await patient(chip(page)).toHaveAttribute("data-status", "live");
  await patient(region(page)).toHaveCount(0);
  await expect(assertive(page)).toHaveCount(0); // no alert outlives the outage
  await expect(statusWord(page)).toHaveText("Connection: live");
  expect(sentTypes(harness, harness.connections())).toEqual(["hello", "auth"]); // no resumption (23 section 9.3)
  expect(systemSnaps(harness)).toHaveLength(before + 1);
  expect(systemSnaps(harness).at(-1)).toMatchObject({ s: 1 }); // a new session counts from 1
});

test(`Q04-T05 a 60 s outage on the page's clock, then Live with nothing older than it ${PACK}`, async ({
  page,
}) => {
  covers("C7", "D02-row-20", "US-MKT-005#Reconnect", "AC-3");
  const harness = await openWorkspace(page, { clock: true });
  const lastBefore = Number(systemSnaps(harness).at(-1)?.["ts"]);
  harness.kill();
  await patient(region(page)).toBeVisible();
  const start = await ageNow(page);
  await page.clock.fastForward(60_000);
  await patient.poll(() => ageNow(page)).toBeGreaterThanOrEqual(start + 60);
  harness.restore();
  await patient.poll(() => harness.authenticated()).toBe(2);
  await patient(chip(page)).toHaveAttribute("data-status", "live");
  await patient(region(page)).toHaveCount(0);
  // The gateway's counter: the new session's snapshot is newer than anything sent before the outage.
  expect(Number(systemSnaps(harness).at(-1)?.["ts"])).toBeGreaterThan(lastBefore);
});

test(`Q04-T06 the T4 steps: the age line turns at 30 s, the region escalates at 5 min ${PACK}`, async ({
  page,
}) => {
  covers("C7", "D02-row-20", "AC-2");
  const harness = await openWorkspace(page, { clock: true });
  harness.kill();
  await patient(region(page)).toHaveAttribute("data-state", "reconnecting");
  const ink = (): Promise<string> =>
    region(page)
      .locator("p")
      .nth(1)
      .evaluate((el) => getComputedStyle(el).color);
  const quiet = await ink();
  await page.clock.fastForward(12_000); // past T4 10 s: the region's text and ink do not change
  await patient.poll(() => ageNow(page)).toBeGreaterThanOrEqual(12);
  expect(await ink()).toBe(quiet);
  await page.clock.fastForward(25_000); // past T4 30 s
  await patient.poll(ink).not.toBe(quiet);
  await expect(region(page)).toHaveAttribute("data-state", "reconnecting");
  await page.clock.fastForward(270_000); // past T4 5 min
  await patient(region(page)).toHaveAttribute("data-state", "long-outage");
  await expect(region(page)).toContainText(/Disconnected for 0[5-9]:\d\d — escalated/);
});

test(`Q04-T07 a fatal close: Offline — retry stopped, said once, never retried ${PACK}`, async ({
  page,
}) => {
  covers("C7", "D02-row-6", "US-MKT-005#Reconnect");
  const harness = await openWorkspace(page, { heartbeat: FAST_HEARTBEAT });
  harness.closeWith({ code: BYE_FATAL.code, reason: BYE_FATAL.reason, bye: BYE_FATAL });
  await patient(chip(page)).toHaveAttribute("data-status", "offline");
  await expect(chip(page)).toHaveAttribute("aria-label", /^Connection: Offline — retry stopped/);
  await expect(statusWord(page)).toHaveText("Connection: offline");
  await expect(region(page)).toContainText("Offline — retry stopped");
  await expect(region(page)).toContainText("Can't connect — repeated protocol errors.");
  await expect(retryNow(page)).toBeVisible();
  await expect(signIn(page)).toHaveCount(0);
  await patient(assertive(page)).toHaveText(SAID.retryStopped);
  // Only `Retry now` brings it back: one handshake, and none of its own. `settle` spans two real pings, longer than
  // the ladder's first two rows, so a retry the client scheduled itself would be a third socket by then.
  await retryNow(page).click();
  await patient.poll(() => harness.authenticated()).toBe(2);
  await settle(harness);
  expect(harness.connections()).toBe(2); // 23 section 9.2: 4400 is never retried by the client itself
});

test(`Q04-T08 session ended: Sign in, no Retry now, said once ${PACK}`, async ({ page }) => {
  covers("C7", "D02-row-21", "AC-2");
  const harness = await openWorkspace(page);
  harness.closeWith({
    code: BYE_SESSION_ENDED.code,
    reason: BYE_SESSION_ENDED.reason,
    bye: BYE_SESSION_ENDED,
  });
  await patient(region(page)).toContainText("Session ended");
  await expect(signIn(page)).toBeVisible();
  await expect(retryNow(page)).toHaveCount(0); // 4403: the client refuses a manual retry, so none is drawn
  await expect(chip(page)).toHaveAttribute("data-status", "offline");
  await patient(assertive(page)).toHaveText(SAID.sessionEnded);
});

test(`Q04-T09 a sequence gap is a resync on the same socket; the chrome stays Live ${PACK}`, async ({
  page,
}) => {
  covers("C2", "D02-row-9", "US-MKT-006#Gap detection", "US-MKT-007#Sequence break");
  const harness = await openWorkspace(page, { heartbeat: FAST_HEARTBEAT });
  harness.desync();
  await patient
    .poll(() => harness.frames.map((f) => f.frame).find((f) => f.t === "resync"))
    .toMatchObject({ ch: "system", p: { reason: "sequence_gap" } });
  await patient
    .poll(() => harness.sent.at(-1))
    .toMatchObject({ t: "snap", ch: "system", meta: { reason: "client_resync" } });
  await settle(harness);
  await expect(chip(page)).toHaveAttribute("data-status", "live");
  await expect(region(page)).toHaveCount(0);
  expect(harness.connections()).toBe(1); // a resync is a new snapshot, never a new socket
});

test(`Q04-T10 while system resyncs the kill switch reads unknown: order entry off ${PACK}`, async ({
  page,
}) => {
  covers("C12", "D02-row-18", "WS-E06", "AC-2");
  const harness = await openWorkspace(page, { heartbeat: FAST_HEARTBEAT });
  harness.hold("resync");
  harness.desync();
  await patient(region(page)).toHaveAttribute("data-reason", "R6-system-unknown");
  await expect(region(page)).toHaveAttribute("data-state", "read-only");
  await expect(region(page)).toContainText("Order entry off — kill-switch status unknown");
  await patient(assertive(page)).toHaveText(SAID.systemUnknown);
  await expect(chip(page)).toHaveAttribute("data-status", "live"); // read-only is never a chip state
  harness.release("resync");
  await patient(region(page)).toHaveCount(0);
  expect(harness.connections()).toBe(1);
});

test(`Q04-T11 a lagging quality class has no treatment ${PACK}`, async ({ page }) => {
  covers("C4", "D02-row-4", "AC-2");
  const harness = await openWorkspace(page, { heartbeat: FAST_HEARTBEAT });
  harness.sendSystem({ kind: "connection_quality", class: "lagging", rtt_ms: 240, queue_pct: 40 });
  await settle(harness);
  await expect(chip(page)).toHaveAttribute("data-status", "live");
  await expect(region(page)).toHaveCount(0);
  await expect(assertive(page)).toHaveCount(0);
});

// 23 section 10.3: fatal -> modal; transient -> badge; client bug and capacity -> toast (E17-T05 `errorMapping.ts`).
const ERR_TREATMENTS = [
  { code: "forbidden", shows: "Session error (forbidden). Sign in again or contact an owner." },
  { code: "degraded_data", shows: "Data may be stale (degraded_data)" },
  {
    code: "frame_malformed",
    shows: "Unexpected client error (frame_malformed). Please report a bug.",
  },
  {
    code: "subscription_limit",
    shows: "Server capacity reached (subscription_limit). Try fewer panes.",
  },
] as const;
for (const { code, shows } of ERR_TREATMENTS) {
  test(`Q04-T12 err ${code} shows its 10.3 treatment and changes no transport state ${PACK}`, async ({
    page,
  }) => {
    covers("§10.3", "D02-row-23", "AC-2");
    const errors: string[] = [];
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
    const harness = await openWorkspace(page);
    harness.sendErr(code);
    await patient(page.getByText(shows)).toBeVisible();
    await expect(chip(page)).toHaveAttribute("data-status", "live");
    await expect(region(page)).toHaveCount(0);
    // A client-bug code reaches the console, never swallowed; the others leave it alone.
    expect(errors.some((e) => e.includes("[ws] client-bug error"))).toBe(
      code === "frame_malformed",
    );
  });
}

test(`Q04-T13 a slow-consumer close is Disconnected, then Live again on its own ${PACK}`, async ({
  page,
}) => {
  covers("C7", "D02-row-3", "US-MKT-005#Reconnect");
  const harness = await openWorkspace(page);
  harness.closeWith({
    code: BYE_SLOW_CONSUMER.code,
    reason: BYE_SLOW_CONSUMER.reason,
    bye: BYE_SLOW_CONSUMER,
  });
  await patient(region(page)).toContainText("Disconnected — reconnecting"); // reconnect: true is a retry
  await patient(assertive(page)).toHaveText(SAID.disconnected);
  await patient.poll(() => harness.authenticated()).toBe(2);
  await patient(chip(page)).toHaveAttribute("data-status", "live");
  await patient(region(page)).toHaveCount(0);
});

// SCR-153's CMP-092 rows that the `system` stream drives (`degradedIssues.ts`): what a trader sees when the server or
// the exchange is impaired while the transport itself stays Live (E17-D02 section 6, routing rows 6, 8 and 9).
/** CMP-092's own polite region (`DegradedBanner.tsx`), pre-rendered empty, beside the shell announcer's. */
const politeSays = (page: Parameters<typeof region>[0], text: string) =>
  page.locator('[aria-live="polite"]', { hasText: text });

test(`Q04-T14 the exchange's public feed down: a warning row, said politely; the chip stays Live ${PACK}`, async ({
  page,
}) => {
  covers("§15.9", "D02-row-13", "US-MKT-003#Feed interrupted");
  const harness = await openWorkspace(page);
  harness.sendSystem({ kind: "exchange_state", public_ws: "disconnected" });
  const said = "Exchange feed down — the server is restoring the connection.";
  await patient(page.getByText(said, { exact: true }).first()).toBeVisible();
  await patient(politeSays(page, said)).toHaveCount(1);
  await expect(chip(page)).toHaveAttribute("data-status", "live");
  harness.sendSystem({ kind: "exchange_state", public_ws: "connected" });
  await patient(page.getByText(said, { exact: true })).toHaveCount(0);
});

test(`Q04-T15 maintenance and the store down: blocking rows, new orders off, said assertively ${PACK}`, async ({
  page,
}) => {
  covers("§15.9", "D02-row-22", "AC-2");
  const harness = await openWorkspace(page);
  harness.sendSystem({
    kind: "notice",
    severity: "warning",
    reason: "maintenance.enabled",
    message: "maintenance",
  });
  await patient(assertive(page)).toContainText("Maintenance mode — new orders off.");
  harness.sendSystem({
    kind: "health",
    health: "degraded",
    components: [{ name: "postgres", state: "down" }],
  });
  await patient(page.getByText("Database unavailable — new orders off").first()).toBeVisible();
  await expect(chip(page)).toHaveAttribute("data-status", "live");
  await expect(region(page)).toHaveCount(0); // a CMP-092 row, never the connection region (one reason, one surface)
});

test(`Q04-T16 the private feed reconnecting: a row for 10 s, then the region's R5 ${PACK}`, async ({
  page,
}) => {
  covers("§15.9", "D02-row-24", "D02-row-17", "AC-2");
  const harness = await openWorkspace(page, { clock: true });
  harness.sendSystem({ kind: "exchange_state", private_ws: "resyncing" });
  const row = "Position data is being verified — actions temporarily limited.";
  await patient(page.getByText(row, { exact: true }).first()).toBeVisible();
  await expect(region(page)).toHaveCount(0);
  await page.clock.fastForward(11_000); // past the 10 s hand-over (E17-D02 section 6 row 9)
  await patient(region(page)).toHaveAttribute("data-reason", "R5-private-down");
  await expect(region(page)).toContainText("Order entry off — private feed down");
  await expect(page.getByText(row, { exact: true })).toHaveCount(0); // one surface at a time
});
