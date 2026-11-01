import { expect, test, type Page } from "@playwright/test";
import type { generated } from "@candleviewer/protocol";
import { stubSession } from "../../support/api";
import { seriousAxe } from "../../support/axe";
import { goldenPositions, POSITIONS_FIXTURE, stubPositions } from "../../support/positions";
import { installWsHarness, type WsHarness } from "../../support/wsHarness";

// E29-S01 (#911) SCR-063 on R-130 `/positions`, web: one test per Gherkin scenario of the ticket, plus
// axe and the keyboard path. The real web client runs against the fake gateway (wsHarness, `23`'s
// private-topic narrowing) and stubbed REST (`support/positions.ts`: the shipped mappers' goldens,
// BQ-22). Scenario "Manager scope is enforced server-side" is the stub lane's half (BQ-13): the
// enforcement and its audit row are E29-T07's and E29-T13's server tests.

type Positions = generated.ws.Positions;
type Role = "owner" | "manager" | "viewer";
const { main: MAIN, sub2: SUB2 } = POSITIONS_FIXTURE;

interface Opened {
  readonly harness: WsHarness;
  readonly stubs: Awaited<ReturnType<typeof stubPositions>>;
}

/** Signs `role` in on stubs, opens `/positions{search}` and waits for its `positions` subscription. */
async function openPositions(
  page: Page,
  role: Role,
  options: { readonly scope?: readonly string[]; readonly search?: string } = {},
): Promise<Opened> {
  await stubSession(page, { role });
  const stubs = await stubPositions(page, { role, ...(options.scope && { scope: options.scope }) });
  const harness = await installWsHarness(page, undefined, {
    ...(options.scope && { accountScope: options.scope }),
  });
  await page.goto(`/positions${options.search ?? ""}`);
  await expect(page.getByRole("heading", { level: 1, name: "Positions and orders" })).toBeVisible();
  await expect.poll(() => harness.privateSubs().some((s) => s.ch === "positions")).toBe(true);
  return { harness, stubs };
}

const grid = (page: Page) => page.getByRole("treegrid", { name: "Positions" });
const positionRow = (page: Page, name: string) =>
  grid(page).getByRole("row", { name, exact: true });
/** A position row's name, "BTCUSDT · Long · 0.25 BTC · Main" (N-02); a group header's starts with its label. */
const POSITION = /^[A-Z0-9]+USDT · /;

test.describe("SCR-063 Positions (E29-S01)", () => {
  test("Rows render the whole book", async ({ page }) => {
    const { harness } = await openPositions(page, "owner");
    harness.sendPositions(goldenPositions<Positions>("ws_positions_snapshot.json"));
    const main = positionRow(page, "BTCUSDT · Long · 0.25 BTC · Main");
    await expect(main).toBeVisible();
    // account, symbol, side as text, qty, entry, mark, uPnL, R, rPnL today, liq price and
    // distance, leverage, margin mode
    await expect(main.getByRole("gridcell")).toHaveText([
      "Main",
      "▲ Long",
      "0.25 BTC",
      "63,980",
      "64,012",
      /\+8/,
      /\+0\.32/,
      /—/,
      "57,901.9",
      "9.5",
      "10×",
      "Isolated",
    ]);
    await expect(main.getByRole("rowheader")).toHaveText("BTCUSDT");
    await expect(grid(page).getByRole("row", { name: POSITION })).toHaveCount(5);
    await expect(grid(page).getByRole("rowheader", { name: /^LIVE total/ })).toContainText(
      "LIVE total · 5 open · Exposure",
    );
  });

  test("Grouping by trade group", async ({ page }) => {
    const { harness } = await openPositions(page, "owner");
    harness.sendPositions(goldenPositions<Positions>("ws_positions_contract_fields.json"));
    await expect(positionRow(page, "BTCUSDT · Long · 0.25 BTC · Main")).toBeVisible();
    await page.getByRole("combobox", { name: "Group by" }).click();
    await page.getByRole("option", { name: "Trade group" }).click();
    const group = grid(page).getByRole("row", { name: /^Trade group …0001/ });
    await expect(group).toHaveAttribute("aria-expanded", "true");
    await expect(group.getByRole("rowheader")).toContainText(
      "Trade group …0001 · 2 positions · net 0.35 BTC · uPnL",
    );
    await expect(
      grid(page)
        .locator('[aria-level="2"]')
        .evaluateAll((rows) => rows.slice(0, 2).map((r) => r.getAttribute("aria-label"))),
    ).resolves.toEqual(["BTCUSDT · Long · 0.25 BTC · Main", "BTCUSDT · Long · 0.1 BTC · Sub-1"]);
  });

  test("Liquidation proximity is not colour-only", async ({ page }) => {
    const { harness } = await openPositions(page, "owner");
    harness.sendPositions(goldenPositions<Positions>("ws_positions_snapshot.json"));
    const eth = positionRow(page, "ETHUSDT · Short · 1.5 ETH · Sub-1");
    await expect(eth).toContainText("! Near 1.2");
    await expect(eth).toHaveAccessibleDescription(
      "Near liquidation: 27 % of the entry buffer left, 1.2 % from liquidation",
    );
    const sol = positionRow(page, "SOLUSDT · Long · 20 SOL · Sub-2");
    await expect(sol).toContainText("!! Critical 0.5");
    await expect(sol).toHaveAccessibleDescription(
      "Critical — near liquidation: 0.5 % from liquidation",
    );
  });

  test("Manager scope is enforced server-side", async ({ page }) => {
    // a manager granted only B opens a link crafted to filter to A
    const { harness, stubs } = await openPositions(page, "manager", {
      scope: [SUB2],
      search: `?account=${MAIN}`,
    });
    // the subscription names B only, as the directory the server scoped lists it (and no B20 topic)
    expect(harness.privateSubs().filter((s) => s.ch === "positions")).toEqual([
      { ch: "positions", named: [SUB2], kept: [SUB2] },
    ]);
    expect(harness.privateSubs().filter((s) => s.ch.startsWith("machines."))).toEqual([]);
    const snapshot = goldenPositions<Positions>("ws_positions_snapshot.json");
    harness.sendPositions({
      positions: snapshot.positions.filter((p) => p.exchange_account_id === SUB2),
    });
    await expect(
      page.getByRole("heading", { level: 2, name: "No rows match 1 filters" }),
    ).toBeVisible();
    await expect(grid(page).getByRole("row", { name: POSITION })).toHaveCount(0);
    await page.getByRole("button", { name: "Clear filters" }).click();
    await expect(grid(page).getByRole("row", { name: POSITION })).toHaveCount(2);
    await page.getByRole("button", { name: "Filter" }).click();
    await expect(page.getByRole("listbox", { name: "Filter" }).getByRole("option")).toHaveText([
      "Sub-2",
    ]);
    await page.keyboard.press("Escape");
    // a request crafted to filter to A is refused whole, with no rows (the server's audited 403)
    const crafted = await page.evaluate(async (account) => {
      const res = await fetch(`/api/v1/positions?exchange_account_ids=${account}`);
      return { status: res.status, body: (await res.json()) as { code?: string; items?: unknown } };
    }, MAIN);
    expect(crafted).toEqual({
      status: 403,
      body: expect.objectContaining({ code: "account_scope_denied" }) as unknown,
    });
    expect(crafted.body.items).toBeUndefined();
    expect(stubs.refusals()).toBe(1);
  });

  test("Live update latency", async ({ page }) => {
    const { harness } = await openPositions(page, "owner");
    const snapshot = goldenPositions<Positions>("ws_positions_snapshot.json");
    harness.sendPositions(snapshot);
    const main = positionRow(page, "BTCUSDT · Long · 0.25 BTC · Main");
    await expect(main.getByRole("gridcell").nth(4)).toHaveText("64,012");
    const [update] = goldenPositions<{ case: string; body: Positions }[]>(
      "ws_positions_deltas.json",
    );
    harness.sendPositions(update?.body ?? { positions: [] });
    await expect(main.getByRole("gridcell").nth(4)).toHaveText("64,112");
    // the in-page measure of an applied frame (BQ-21: G-W2 owns its transport); the 200 ms bound is
    // proven on fake timers in the unit suite, as wall-clock gates are off on shared runners
    const measures = await page.evaluate(() =>
      performance
        .getEntriesByName("ws_frame_apply_seconds")
        .map((m) => (m as PerformanceMeasure).detail as { topic?: string }),
    );
    expect(measures.some((d) => d.topic === "positions")).toBe(true);
  });

  test("Empty state", async ({ page }) => {
    const { harness } = await openPositions(page, "owner");
    harness.sendPositions({ positions: [] });
    await expect(page.getByRole("heading", { level: 2, name: "No open positions" })).toBeVisible();
    await expect(page.getByText("Positions you open on any account appear here.")).toBeVisible();
    await expect(page.getByRole("alert")).toHaveCount(0);
    await expect(page.getByText(/Could not load/)).toHaveCount(0);
  });

  test("has no serious or critical axe violation, populated, as the Viewer", async ({ page }) => {
    const { harness } = await openPositions(page, "viewer");
    harness.sendPositions(goldenPositions<Positions>("ws_positions_snapshot.json"));
    await expect(grid(page).getByRole("row", { name: POSITION })).toHaveCount(5);
    await expect(page.getByText("Your role can't change positions.")).toBeVisible();
    expect(await seriousAxe(page)).toEqual([]);
  });

  test("the keyboard path: from the tab, the toolbar in order, then the grid's one stop and its keys", async ({
    page,
  }) => {
    const { harness } = await openPositions(page, "owner");
    harness.sendPositions(goldenPositions<Positions>("ws_positions_snapshot.json"));
    await expect(grid(page).getByRole("row", { name: POSITION })).toHaveCount(5);
    await page.getByRole("tab", { name: "Positions" }).focus();
    for (const control of [
      page.getByRole("combobox", { name: "Group by" }),
      page.getByRole("button", { name: "Filter" }),
      page.getByRole("button", { name: "Columns" }),
      page.getByRole("button", { name: "Export CSV" }),
    ]) {
      await page.keyboard.press("Tab");
      await expect(control).toBeFocused();
    }
    await page.keyboard.press("Tab");
    const header = grid(page).getByRole("rowheader", { name: /^Main · LIVE/ });
    await expect(header).toBeFocused();
    await page.keyboard.press("ArrowLeft");
    await expect(grid(page).getByRole("row", { name: /^Main · LIVE/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    await page.keyboard.press("ArrowRight");
    await expect(grid(page).getByRole("row", { name: /^Main · LIVE/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    await page.keyboard.press("ArrowDown");
    await expect(
      positionRow(page, "BTCUSDT · Long · 0.25 BTC · Main").getByRole("gridcell").first(),
    ).toBeFocused();
  });
});
