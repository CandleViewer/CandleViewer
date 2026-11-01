import { test, expect, type Locator, type Page } from "@playwright/test";
import { stubSession } from "../support/api";
import { seriousAxe } from "../support/axe";
import { recorderFrame, stubRecorder } from "../support/recorder";
import { installWsHarness } from "../support/wsHarness";

// E16-S01 (#484) recorder.spec: SCR-140 at R-340 /admin/recorder, reached by a deep link (#5309's lens, C-5309-12),
// on the ticket's critical path (its test plan, E16-Q02's): add a symbol, see it record through the `recorder` topic,
// keep it forever, stop it with its confirmation, and the empty state after its removal. The API is stubbed at the
// network layer and the WS gateway is the harness: no backend, no network (C-13.5).

/** The admin area's lazy chunk, SCR-140's too: Vite names a dynamic import's chunk after its module. */
const ADMIN_CHUNK = /\/AdminArea-[^/]+\.js$/u;
/** `22`'s example clock: the first-recorded time the re-read list carries once the row records. */
const STARTED_AT = "2026-09-14T10:31:05Z";

const band = (page: Page) => page.getByRole("region", { name: "Admin area" });

/** Every path the page asks for from now on: its scripts and its `/api/v1/` calls. */
function watchPaths(page: Page): () => string[] {
  const paths: string[] = [];
  page.on("request", (request) => paths.push(new URL(request.url()).pathname));
  return () => paths;
}

/**
 * CMP-044 ignores a press that begins inside its 400 ms guard, which re-arms when Confirm becomes available (E30-D03
 * D3 (2)): press until the dialog closes on the server's answer, an event wait instead of a sleep. A press while the
 * first is in flight finds Confirm busy and does nothing (its single fire). An answer slower than the 500 ms look
 * closes the dialog during a later round, which then finds it gone: the press that landed is enough.
 */
async function confirmed(dialog: Locator, name: string): Promise<void> {
  await expect(async () => {
    if (await dialog.isHidden()) return;
    await dialog.getByRole("button", { name, exact: true }).click({ timeout: 1_000 });
    await expect(dialog).toBeHidden({ timeout: 500 });
  }).toPass({ timeout: 10_000 });
}

test("E16-S01 an owner records a symbol, keeps it forever and stops it on /admin/recorder", async ({
  page,
}) => {
  const paths = watchPaths(page);
  await stubSession(page, { role: "owner" });
  const ws = await installWsHarness(page);
  const api = await stubRecorder(page);
  await page.goto("/admin/recorder");

  // A fresh install: nothing is recorded by default, and the page says so with one primary action (AC1).
  await expect(band(page)).toHaveText("◆ Admin area · Recorder and retention");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Recorder");
  await expect(
    page.getByRole("heading", { level: 2, name: "Nothing is recorded yet" }),
  ).toBeVisible();
  await expect(page.getByText(/^Nothing is recorded by default\./u)).toBeVisible();
  expect(paths().some((p) => ADMIN_CHUNK.test(p))).toBe(true); // the watcher sees the chunk
  expect(await seriousAxe(page)).toEqual([]);

  // Add BTCUSDT (AC2): the server's row lands starting.
  await page.getByRole("button", { name: "Record a symbol" }).first().click();
  const add = page.getByRole("dialog", { name: "Record a symbol" });
  await add.getByRole("combobox", { name: "Symbol" }).fill("BTCUSDT");
  await add.getByRole("button", { name: "Start recording" }).click();
  await expect(add).toBeHidden();
  const symbol = page.getByRole("button", { name: "BTCUSDT", exact: true });
  const row = page.getByRole("row").filter({ has: symbol });
  await expect(row).toContainText("Starting · initial book snapshot");

  // The page subscribed to `recorder` (23 §6.2.2). The topic reports the row starting, then recording, which the
  // row shows within 5 s; leaving `starting` re-reads the list (BQ-7), which carries the first-recorded time.
  const subscribed = (): boolean =>
    ws.frames.some(
      ({ frame }) => frame.t === "sub" && JSON.stringify(frame["p"]).includes('"recorder"'),
    );
  await expect.poll(subscribed).toBe(true);
  ws.sendData("recorder", recorderFrame(api.rows));
  api.record("BTCUSDT", STARTED_AT);
  ws.sendData("recorder", recorderFrame(api.rows));
  await expect(row).toContainText("Recording", { timeout: 5_000 });
  expect(await seriousAxe(page)).toEqual([]);

  // FM-07: the row's detail, opened from its symbol, states when it started; Esc returns focus to the symbol.
  await symbol.click();
  const detail = page.getByRole("dialog", { name: "BTCUSDT recording" });
  const started = detail
    .locator("dt", { hasText: /^Started$/u })
    .locator("xpath=following-sibling::dd[1]");
  await expect(started).toHaveText("2026-09-14 10:31 UTC", { timeout: 10_000 });
  expect(await seriousAxe(page)).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(detail).toBeHidden();
  await expect(symbol).toBeFocused();

  // Keep it forever (D02 §6.4): the typed confirm, then the pin.
  await row.getByRole("switch", { name: "Keep BTCUSDT data forever" }).click();
  const keep = page.getByRole("alertdialog", { name: "Keep BTCUSDT data forever?" });
  await expect(keep.getByRole("button", { name: "Cancel" })).toBeFocused();
  await keep.getByRole("textbox", { name: "Type BTCUSDT to confirm" }).fill("BTCUSDT");
  await confirmed(keep, "Keep BTCUSDT data forever");
  ws.sendData("recorder", recorderFrame(api.rows));
  await expect(row.getByRole("switch", { name: "Keep BTCUSDT data forever" })).toBeChecked();

  // Stop it (AC5): the confirmation states the consequence, Keep recording the default; then the empty state.
  await row.getByRole("button", { name: "Stop recording BTCUSDT" }).click();
  const stop = page.getByRole("alertdialog", { name: "Stop recording BTCUSDT?" });
  await expect(stop).toContainText("Existing data is kept per the retention policy");
  await expect(stop.getByRole("button", { name: "Keep recording" })).toBeFocused();
  await confirmed(stop, "Stop recording");
  ws.sendData("recorder", recorderFrame([]));
  await expect(
    page.getByRole("heading", { level: 2, name: "Nothing is recorded yet" }),
  ).toBeVisible();
});

for (const role of ["manager", "viewer"] as const) {
  test(`E16-S01 a ${role}'s deep link to /admin/recorder is the 404: no admin code, no recording read`, async ({
    page,
  }) => {
    const paths = watchPaths(page);
    await stubSession(page, { role });
    await page.goto("/admin/recorder");
    await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    await expect(band(page)).toHaveCount(0);
    expect(paths()).toContain("/api/v1/me"); // positive control: the watcher sees the SPA's reads
    expect(paths().filter((p) => ADMIN_CHUNK.test(p))).toEqual([]);
    expect(paths().filter((p) => p.startsWith("/api/v1/recording"))).toEqual([]);
  });
}
