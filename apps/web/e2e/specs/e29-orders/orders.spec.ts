import { expect, test, type Page } from "@playwright/test";
import type { generated } from "@candleviewer/protocol";
import { stubSession } from "../../support/api";
import { seriousAxe } from "../../support/axe";
import { goldenOrders, stubOrders, type OrdersAnswers } from "../../support/orders";
import { goldenPositions, POSITIONS_FIXTURE, stubPositions } from "../../support/positions";
import { installWsHarness, type WsHarness } from "../../support/wsHarness";

// E29-S02 (#912) PR2: SCR-063's Working-orders tab on R-130 `/positions`, web. One test per scenario this
// PR covers ("Conditional orders are separated", "Cancel that lost the race", through the protective
// take-profit's confirm (D02 §8.2), "Cancel-all partial failure", Retry failed sending the retryable
// account alone), the native stop's T2 Cancel with the proof that no stop row is sent (C-2.6), axe
// and the keyboard path. The real web client runs against the fake gateway (wsHarness) and stubbed REST (the
// shipped mappers' goldens, `support/orders.ts`). CI-only: this host has no Playwright browser.

type Orders = generated.ws.Orders;
type Positions = generated.ws.Positions;
type Role = "owner" | "manager" | "viewer";
const { sub1: SUB1, sub2: SUB2 } = POSITIONS_FIXTURE;
const TP = "0e000000-0000-4000-8000-000000000001";
const ENTRY = "0e000000-0000-4000-8000-000000000002";
const ETH = "0e000000-0000-4000-8000-000000000003";
const COND = "0e000000-0000-4000-8000-000000000004";
const STOP = "0e000000-0000-4000-8000-000000000005";

const snapshot = (): Orders => goldenOrders<Orders>("ws_orders_snapshot.json");
const deltaOf = (name: string): Orders => {
  const found = goldenOrders<{ case: string; body: Orders }[]>("ws_orders_deltas.json").find(
    (d) => d.case === name,
  );
  if (found === undefined) throw new Error(`no delta case ${name}`);
  return found.body;
};

/** Signs `role` in, opens `/positions`, reads the book, then the Working-orders tab with `book`. */
async function openOrders(
  page: Page,
  options: { readonly role?: Role; readonly book?: Orders; readonly answers?: OrdersAnswers } = {},
): Promise<{
  readonly harness: WsHarness;
  readonly orders: Awaited<ReturnType<typeof stubOrders>>;
}> {
  const role = options.role ?? "owner";
  await stubSession(page, { role });
  await stubPositions(page, { role });
  const orders = await stubOrders(page, options.answers);
  const harness = await installWsHarness(page);
  await page.goto("/positions");
  await expect(page.getByRole("heading", { level: 1, name: "Positions and orders" })).toBeVisible();
  await expect.poll(() => harness.privateSubs().some((s) => s.ch === "positions")).toBe(true);
  harness.sendPositions(goldenPositions<Positions>("ws_positions_snapshot.json"));
  await page.getByRole("tab", { name: "Working orders" }).click();
  await expect.poll(() => harness.privateSubs().some((s) => s.ch === "orders")).toBe(true);
  harness.sendOrders(options.book ?? snapshot());
  await expect(grid(page).locator('[aria-level="3"]').first()).toBeVisible();
  return { harness, orders };
}

const grid = (page: Page) => page.getByRole("treegrid", { name: "Working orders" });
const orderRow = (page: Page, id: string) => grid(page).locator(`tr[data-key="${id}"]`);
const cancelOf = (page: Page, id: string) =>
  orderRow(page, id).getByRole("button", { name: /Cancel/ });

test.describe("SCR-063 Working orders (E29-S02)", () => {
  test("Conditional orders are separated", async ({ page }) => {
    await openOrders(page);
    await expect(grid(page).locator('[aria-level="1"]')).toHaveText([
      "Working · 5",
      "Conditional — not triggered · 2",
    ]);
    await expect(orderRow(page, COND)).toHaveAttribute("aria-level", "3");
    await expect(orderRow(page, STOP).getByRole("gridcell").nth(8)).toHaveText(
      "Mark falls to 63,950",
    );
  });

  test("Cancel that lost the race", async ({ page }) => {
    const { harness, orders } = await openOrders(page);
    // D02 §6.2's take-profit is a protective one: it asks first, and Keep sends nothing
    await cancelOf(page, TP).click();
    const confirm = page.getByRole("alertdialog", {
      name: "Cancel the take-profit at 64,800 for Main BTCUSDT?",
    });
    await confirm.getByRole("button", { name: "Keep take-profit" }).click();
    await expect(confirm).toBeHidden();
    expect(orders.writes()).toEqual([]);
    await cancelOf(page, TP).click();
    await confirm.getByRole("button", { name: "Cancel take-profit" }).click();
    await expect.poll(() => orders.writes().map((w) => w.path)).toEqual([`/api/v1/orders/${TP}`]);
    expect(orders.writes()[0]).toMatchObject({ method: "DELETE", arm: false });
    expect(orders.writes()[0]?.key).toMatch(/^[0-9a-f-]{36}$/);
    harness.sendOrders(deltaOf("cancel_request"));
    await expect(orderRow(page, TP)).toContainText("Cancelling");
    harness.sendOrders(deltaOf("cancel_lost_race"));
    await expect(orderRow(page, TP)).toContainText("Filled");
    await expect(page.getByText(/already filled/i)).toHaveCount(0);
    await expect(page.getByText(/^Not cancelled/)).toHaveCount(0);
  });

  test("Cancel-all partial failure", async ({ page }) => {
    // the entries only, placed: Cancel all in view is one cancelAllOrders for Sub-1 and Sub-2
    const keep = new Set([ENTRY, COND, ETH]);
    const open = goldenOrders<{ items: { id: string }[] }>("rest_list_orders_open.json").items;
    const failing = (n: number) =>
      n === 1
        ? {
            status: 200,
            body: {
              results: [
                {
                  exchange_account_id: SUB1,
                  ok: false,
                  affected: 1,
                  error: {
                    code: "timeout",
                    message: "x",
                    exchange_ret_code: null,
                    retryable: true,
                  },
                },
                {
                  exchange_account_id: SUB2,
                  ok: false,
                  affected: 0,
                  error: {
                    code: "exchange_unavailable",
                    message: "x",
                    exchange_ret_code: null,
                    retryable: false,
                  },
                },
              ],
              requested: 2,
              succeeded: 0,
            },
          }
        : { status: 200, body: { results: [], requested: 0, succeeded: 0 } };
    const { orders } = await openOrders(page, {
      book: { orders: snapshot().orders.filter((o) => keep.has(o.id)) },
      answers: { open: open.filter((o) => keep.has(o.id)), cancelAll: (_, n) => failing(n) },
    });
    await page.getByRole("button", { name: "Cancel all in view…" }).click();
    const dialog = page.getByRole("alertdialog", { name: "Cancel 3 orders?" });
    await expect(dialog).toContainText("2 orders on Sub-1 · LIVE");
    await dialog.getByRole("textbox").fill("CANCEL");
    await dialog.getByRole("button", { name: "Cancel 3 orders" }).click();
    const result = page.getByRole("dialog", { name: "Cancel results" });
    await expect(result.getByRole("listitem")).toHaveText([
      "Sub-1 · LIVE: cancelled 1, then Bybit stopped answering — try again",
      "Sub-2 · LIVE: not confirmed — check its orders on Bybit",
    ]);
    expect(orders.writes()).toEqual([
      expect.objectContaining({
        method: "POST",
        path: "/api/v1/orders/cancel-all",
        arm: false,
        body: {
          exchange_account_ids: [SUB1, SUB2],
          symbol: null,
          intents: [],
          exclude_reduce_only: true,
        },
      }),
    ]);
    await result.getByRole("button", { name: "Retry failed" }).click();
    await expect.poll(() => orders.writes().length).toBe(2);
    expect(orders.writes()[1]?.key).not.toBe(orders.writes()[0]?.key);
    // Sub-2's exchange_unavailable is not retryable: that order is never sent again (22)
    expect(orders.writes()[1]?.body).toMatchObject({ exchange_account_ids: [SUB1] });
  });

  test("a native stop's Cancel is disabled with its reason, and no stop row is ever sent", async ({
    page,
  }) => {
    const { orders } = await openOrders(page);
    const stop = cancelOf(page, STOP);
    await expect(stop).toHaveAttribute("aria-disabled", "true");
    await expect(stop).toHaveAccessibleDescription(
      "Every position keeps a native stop — you can move it, not delete it.",
    );
    await stop.click({ force: true }); // aria-disabled: Playwright's actionability would wait
    expect(orders.writes()).toEqual([]);
    await page.getByRole("button", { name: "Cancel all in view…" }).click();
    const dialog = page.getByRole("alertdialog", { name: "Cancel 4 orders?" });
    await expect(dialog).toContainText(
      "1 native-stop order is not included: every position keeps a native stop.",
    );
    await dialog.getByRole("textbox").fill("CANCEL");
    await dialog.getByRole("button", { name: "Cancel 4 orders" }).click();
    await expect(page.getByRole("dialog", { name: "Cancel results" })).toBeVisible();
    const paths = orders.writes().map((w) => w.path);
    expect(paths).toHaveLength(4);
    expect(paths).not.toContain(`/api/v1/orders/${STOP}`);
    expect(orders.writes().every((w) => !w.arm)).toBe(true);
  });

  test("has no serious or critical axe violation, populated and with the dialog open", async ({
    page,
  }) => {
    await openOrders(page);
    expect(await seriousAxe(page)).toEqual([]);
    await page.getByRole("button", { name: "Cancel all in view…" }).click();
    await expect(page.getByRole("alertdialog")).toBeVisible();
    expect(await seriousAxe(page)).toEqual([]);
  });

  test("the keyboard path: the toolbar in order, the grid's one stop, Space selects", async ({
    page,
  }) => {
    await openOrders(page);
    await page.getByRole("tab", { name: "Working orders" }).focus();
    for (const control of [
      page.getByRole("button", { name: "Filter" }),
      page.getByRole("button", { name: "Cancel all in view…" }),
    ]) {
      await page.keyboard.press("Tab");
      await expect(control).toBeFocused();
    }
    await page.keyboard.press("Tab");
    await expect(grid(page).getByRole("rowheader", { name: "Working · 5" })).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Space");
    await expect(page.locator('[data-part="SelectionBar"]')).toContainText("1 selected");
    await expect(page.getByRole("button", { name: "Cancel selected" })).toBeVisible();
  });
});
