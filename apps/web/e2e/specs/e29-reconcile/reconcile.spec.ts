// E29-S07 (#1028) the reconciliation UX on the shipped bundle and the fixture gateway (feeds E29-Q04's chaos pack):
// the five Gherkin scenarios, each by its name, driven by the harness's `kill` / `restore` / `sendSystem` and REST
// stubs for the session's accounts, the digest (#5584's `getReconciliationDigest`), the window's fills and the
// reassurance read. No network: every call the client makes here is answered by a route below.
import { expect, test, type Page } from "@playwright/test";
import { json, stubSession } from "../../support/api";
import { startWsHarness, type WsHarness } from "../../support/wsHarness";
import { FAST_HEARTBEAT, assertive, patient, region } from "../../e17/support";

const A = "a1000000-0000-4000-8000-00000000000a";
const B = "a1000000-0000-4000-8000-00000000000b";
const ORDER = "c1000000-0000-4000-8000-000000000001";

interface Stubs {
  /** Every open position's `native_stop_present` for the reassurance read (default true). */
  readonly stopsConfirmed?: boolean;
  /** `sl_repaired` symbols in the reconnect pass's digest. */
  readonly repaired?: readonly string[];
}

/** The session's two accounts, and the reads the reconciliation surfaces make (22 shapes). */
async function stubReconcile(page: Page, stubs: Stubs = {}): Promise<void> {
  await page.route("**/api/v1/me", (r) =>
    r.fulfill(
      json({
        role: "owner",
        permissions: [],
        session: { environment: "demo", elevated_until: null },
        accounts: [
          { exchange_account_id: A, label: "Sub-1", environment: "demo", mode: "trade" },
          { exchange_account_id: B, label: "Sub-2", environment: "demo", mode: "trade" },
        ],
      }),
    ),
  );
  await page.route(
    (url) => url.pathname === "/api/v1/positions",
    (r) =>
      r.fulfill(
        json({
          items: [
            {
              id: "p-1",
              exchange_account_id: A,
              symbol: "BTCUSDT",
              size: "0.250",
              is_paper: false,
              native_stop_present: stubs.stopsConfirmed ?? true,
              tpsl_mode: "Full",
            },
          ],
        }),
      ),
  );
  await page.route("**/api/v1/exchange-accounts/*/reconciliation/latest", (r) => {
    const id = new URL(r.request().url()).pathname.split("/")[4] ?? "";
    if (id !== A) return r.fulfill(json({ code: "not_found" }, 404));
    const now = new Date().toISOString();
    return r.fulfill(
      json({
        exchange_account_id: A,
        pass_id: "b1000000-0000-4000-8000-000000000001",
        trigger: "reconnect",
        result: "corrected",
        confirmed_at: now,
        gap_window: { from: now, to: now },
        counts: { corrected: 1, sl_repaired: stubs.repaired?.length ?? 0 },
        abandoned: [],
        anomalies: [],
        corrected: ["link-1"],
        foreign_stops: [],
        held: [],
        newly_unknown: [],
        position_drift: [],
        resolved_from_history: [],
        sl_repaired: stubs.repaired ?? [],
        sl_restore_refused: [],
        sl_restored: [],
        sl_tighter: [],
        unpaired: [],
        unprotected: [],
        untracked: [],
      }),
    );
  });
  await page.route(
    (url) => url.pathname === "/api/v1/executions",
    (r) =>
      r.fulfill(
        json({
          items: [{ exchange_account_id: A, order_id: ORDER, exec_type: "Trade", is_paper: false }],
          meta: { has_more: false },
        }),
      ),
  );
  await page.route(`**/api/v1/orders/${ORDER}`, (r) =>
    r.fulfill(json({ id: ORDER, exchange_account_id: A, state: "filled" })),
  );
}

async function open(page: Page, stubs: Stubs = {}): Promise<WsHarness> {
  await stubSession(page, { role: "owner" });
  await stubReconcile(page, stubs); // registered after: these answer first
  const harness = await startWsHarness(page, FAST_HEARTBEAT);
  // the reassurance verdict is in before a test drops the link (a11y m1): its first read answered
  const isRead = (url: string): boolean => new URL(url).pathname === "/api/v1/positions";
  const reads = { asked: 0, answered: 0 };
  page.on("request", (r) => void (isRead(r.url()) && (reads.asked += 1)));
  page.on("response", (r) => void (isRead(r.url()) && (reads.answered += 1)));
  const read = page.waitForResponse((r) => isRead(r.url()));
  await page.goto("/terminal");
  await patient.poll(() => harness.authenticated()).toBe(1);
  await read;
  // The `positions` snap on `sub` may move the account while that read is on the wire; its retry
  // then goes out as soon as the first answer lands (two reads at most). Wait for that possible
  // retry (an event wait, bounded; absent when the snap came after the answer), then for every
  // read to be answered, so a test's kill never aborts the verdict it asserts.
  await page.waitForResponse((r) => isRead(r.url()), { timeout: 2_000 }).catch(() => undefined);
  await patient.poll(() => reads.asked - reads.answered).toBe(0);
  return harness;
}

async function dropAndRestore(page: Page, harness: WsHarness): Promise<void> {
  harness.kill();
  await patient(region(page)).toHaveAttribute("data-state", /reconnecting|long-outage/);
  harness.restore();
  await patient.poll(() => harness.authenticated()).toBe(2);
}

const stale = (id: string) => ({
  kind: "account_notice",
  severity: "critical",
  reason: "oms.account_stale",
  message: "An account could not be reconciled; new orders are locked until the owner resolves it.",
  exchange_account_ids: [id],
  changed_at_ms: 1_789_133_300_000,
});

test("E29-S07 Reconnect with a correction: the summary lists the fill with a link to its row", async ({
  page,
}) => {
  const harness = await open(page);
  await dropAndRestore(page, harness);
  const recovered = region(page);
  await patient(recovered).toHaveAttribute("data-state", "recovered");
  await expect(recovered).toContainText("Reconnected");
  await expect(recovered).toContainText("While you were offline: 1 order filled.");
  await expect(recovered.getByRole("link", { name: "1 order filled" })).toHaveAttribute(
    "href",
    `/positions/order/${ORDER}`,
  );
  await expect(recovered).toContainText("Sub-1: 1 change — review them in Positions.");
  await patient(assertive(page).last()).toHaveText("Reconnected. 1 order filled while offline.");
});

test("E29-S07 Trading is blocked while blind: the region says new orders are off, and why, in text", async ({
  page,
}) => {
  const harness = await open(page);
  harness.kill();
  await patient(region(page)).toContainText("New orders off; cancel and close remain available");
  // `order.blocked_offline` is the guard's page-local event (BQ-8): its unit test asserts it, as no
  // new-exposure control is mounted on this route before E30-S01 and E31-S01.
});

test("E29-S07 Repeated reconciliation failure: a locked account drops the stops claim", async ({
  page,
}) => {
  const harness = await open(page);
  harness.sendSystem(stale(A));
  harness.kill();
  const blind = region(page);
  await patient(blind).toContainText("App-managed rules are paused.");
  await expect(blind).not.toContainText("Exchange-side stops still protect open positions");
});

test("E29-S07 The reassurance must be true: every stop confirmed and synced, the claim stands", async ({
  page,
}) => {
  const harness = await open(page);
  harness.kill();
  await patient(region(page)).toContainText(
    "Exchange-side stops still protect open positions; app-managed rules are paused.",
  );
});

test("E29-S07 The reassurance must be true: a position without a confirmed stop drops the claim; the repaired stop is named", async ({
  page,
}) => {
  const harness = await open(page, { stopsConfirmed: false, repaired: ["BTCUSDT"] });
  harness.kill();
  await patient(region(page)).toContainText("App-managed rules are paused.");
  await expect(region(page)).not.toContainText("Exchange-side stops still protect");
  harness.restore();
  await patient.poll(() => harness.authenticated()).toBe(2);
  await patient(region(page)).toContainText(
    "Sub-1: 2 changes, including 1 stop attached automatically — review them in Positions.",
  );
});

test("E29-S07 The overlay never hides the book: the region is non-modal and outside the workspace", async ({
  page,
}) => {
  const harness = await open(page);
  harness.kill();
  const blind = region(page);
  await patient(blind).toBeVisible();
  await expect(page.locator('[aria-modal="true"]')).toHaveCount(0);
  const box = await blind.boundingBox();
  const main = await page.getByRole("main").boundingBox();
  expect(box).not.toBeNull();
  expect(main).not.toBeNull();
  // the banner slot pushes the workspace down; it never overlays it
  expect((box?.y ?? 0) + (box?.height ?? 0)).toBeLessThanOrEqual(main?.y ?? 0);
});
