// #5345 (E08-D14 FS-1, DF-1): the CMP-076 chip on the E08-Q05 WS harness, against the REAL web client. The fake gateway
// pushes a `system` `exchange_state` with the exchange's public feed down after the socket's first `auth_ok` (23 §15.9):
// the chip reads "Stale — exchange feed down" (E17-D02 §2 row 13), never "Live", and the one polite announcement is
// CMP-092's row (§6 routing row 8). A reconnect whose first `auth_ok` brings the feed back returns the chip to "Live"
// (row 16). The harness sends no mid-session `system` frame (#5340 adds one), so the recovery goes through a reconnect.
// A saturated `connection_quality` reads Delayed (row 5). Each fill is scanned by axe with colour contrast on, once the
// chip's cross-fade has ended (no shipped route consumes a public topic yet, so the age fills are a probe's to scan).
import { stubSession } from "../support/api";
import { seriousAxe } from "../support/axe";
import { installWsHarness } from "../support/wsHarness";
import { expect, test } from "../support/pack";

const DOWN = { kind: "exchange_state", public_ws: "disconnected", private_ws: "connected" };
const BACK = { kind: "exchange_state", public_ws: "connected", private_ws: "connected" };
const SATURATED = {
  kind: "connection_quality",
  class: "saturated",
  queue_pct: 72,
  rtt_ms: 640,
  applied: { throttle_multiplier: 4, forced_coalesce: true, degraded_topics: [] },
};
const ROW = "Exchange feed down — the server is restoring the connection.";

test("FS-1: the exchange's public feed down reads on the chip, and its recovery reads Live @ga-regression @ga-area-shell", async ({
  page,
}) => {
  // Two sockets, a reconnect backoff and two contrast-on axe scans: about 21 s on a loaded host,
  // of the 30 s default.
  test.setTimeout(60_000);
  await stubSession(page, { role: "owner" });
  // Read at each socket's first `auth_ok`: what the next socket hears is swapped below.
  const pushes: Record<string, unknown>[] = [DOWN];
  const harness = await installWsHarness(page, undefined, { firstAuthSystem: pushes });
  await page.goto("/terminal");
  await expect.poll(() => harness.authenticated()).toBe(1);

  const chip = page.getByRole("banner").getByRole("button", { name: /^Connection: / });
  const faded = chip.locator("[data-fade]");
  await expect(chip).toHaveAttribute("data-status", "stale");
  await expect(chip).toHaveText(/Stale — exchange feed down/);
  await expect(chip).toHaveAccessibleName(/^Connection: Stale — exchange feed down/);
  // One polite announcement names it, CMP-092's (§11 row 5); the chip writes none of its own.
  const polite = page.locator('[aria-live="polite"]');
  await expect(polite.filter({ hasText: ROW })).toHaveCount(1);
  await expect(polite.filter({ hasText: /Price feed/ })).toHaveCount(0);
  await expect(faded).toHaveCSS("opacity", "1");
  expect(await seriousAxe(page)).toEqual([]); // colour contrast included: a real browser

  pushes.splice(0, pushes.length, BACK);
  harness.kill();
  await expect(chip).toHaveAccessibleName(/^Connection: Reconnecting/);
  await expect(chip).toHaveAttribute("data-status", "reconnecting");
  await expect(faded).toHaveCSS("opacity", "1");
  expect(await seriousAxe(page)).toEqual([]); // the danger fill
  harness.restore();
  await expect.poll(() => harness.authenticated(), { timeout: 15_000 }).toBe(2);
  await expect(chip).toHaveAccessibleName(/^Connection: Live/);
  await expect(chip).toHaveAttribute("data-status", "live");
  await expect(polite.filter({ hasText: ROW })).toHaveCount(0); // the row has gone with its condition
});

test("row 5: a saturated link reads Delayed, and its fill passes axe with colour contrast on @ga-regression @ga-area-shell", async ({
  page,
}) => {
  await stubSession(page, { role: "owner" });
  const harness = await installWsHarness(page, undefined, { firstAuthSystem: [SATURATED] });
  await page.goto("/terminal");
  await expect.poll(() => harness.authenticated()).toBe(1);

  const chip = page.getByRole("banner").getByRole("button", { name: /^Connection: / });
  await expect(chip).toHaveAttribute("data-status", "delayed");
  await expect(chip).toHaveAccessibleName(/^Connection: Reduced rate/);
  await expect(chip.locator("[data-fade]")).toHaveCSS("opacity", "1");
  expect(await seriousAxe(page)).toEqual([]);
});
