/**
 * E29-S02 PR2 (#912) integration: the real `PositionsPanel` (SCR-063) on its Working-orders tab, with
 * the real `ordersApi`, `ordersWrites` and `positionsApi` behind a fake `fetch` and fake topic
 * handles (#911 BQ-19: no MSW, no new dependency), read through the accessibility tree. The rows,
 * the sections, a row's Cancel (sent once, no arm token, a toast, busy until its row shows it), the
 * protective take-profit's confirm, the lost race (BQ-3), the native stop's T2 Cancel and the proof
 * that no stop row is ever sent, even one whose position opens while the dialog is up (C-2.6),
 * Cancel-all partial failure on 3 of 5 accounts with Retry failed, Cancel selected, the S-22
 * refusals, the Viewer's notice, the kill switch's carve-out, the window past 50 rows, the bodies,
 * focus never on `body`, axe, and teardown.
 */
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeAll, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { PreferencesProvider } from "../../../../src/features/a11y-preferences/PreferencesContext";
import {
  clearAnnouncements,
  REGION_BUDGET_MS,
  ShellAnnouncer,
} from "../../../../src/features/app-shell/announcer";
import { positionsApi, type ExchangeAccount } from "../../../../src/features/positions/api";
import { ordersApi, type OrdersWrites } from "../../../../src/features/positions/orders/api";
import type * as ViewModule from "../../../../src/features/positions/orders/view";
import { LINGER_MS } from "../../../../src/features/positions/orders/ordersStore";
import { BUSY_BOUND_MS } from "../../../../src/features/positions/orders/WorkingOrdersTab";
import { resetPanelState, updatePanelState } from "../../../../src/features/positions/panelState";
import { PositionsPanel } from "../../../../src/features/positions/PositionsPanel";
import type { PositionsDeps } from "../../../../src/features/positions/positionsSession";
import { COMMIT_INTERVAL_MS } from "../../../../src/features/positions/wsPositions";
import { resetShellState, setShellState, type Me } from "../../../../src/shell/bootstrap/store";
import { THEME_ANALYTICS_EVENT } from "../../../../src/shell/bootstrap/themeStore";
import { repoFile } from "../../../lib/ws/support/schemaHarness";
import { golden as positionsGolden } from "../support/fakes";
import {
  COND,
  delta,
  HELD,
  deltaBody,
  ENTRY,
  ETH,
  exchangeAccounts,
  fakeClient,
  fakeRaf,
  golden,
  MAIN,
  reset,
  restOpen,
  snap,
  snapshotBody,
  STOP,
  SUB1,
  SUB2,
  SUB3,
  SUB4,
  TP,
  wsItem,
  type FakeClient,
  type OrdersBody,
} from "./support/orders";

/** How often the tab rebuilt its rows in view (code m5: a mark tick must not). */
const rebuilt = vi.hoisted(() => ({ count: 0 }));
vi.mock("../../../../src/features/positions/orders/view", async (importOriginal) => {
  const real = await importOriginal<typeof ViewModule>();
  return {
    ...real,
    rowsInView: (...args: Parameters<typeof real.rowsInView>) => {
      rebuilt.count += 1;
      return real.rowsInView(...args);
    },
  };
});

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as {
  run: (
    el: Element,
    o?: object,
  ) => Promise<{ violations: { id: string; impact?: string | null }[] }>;
};

const TICK = COMMIT_INTERVAL_MS + 16;
const USER = "11111111-2222-4333-8444-555555555555";
const FULL = ["positions:read", "positions:write", "orders:read", "orders:write", "accounts:read"];
/** Four minutes after ENTRY's `created_at` (D02 §6.2's "4 m"). */
const NOW = Date.parse("2026-10-31T14:02:11Z");
/** The screen tests' measured bound (`positions.integration.test.tsx`: a whole SCR-063 mount under load). */
const SCREEN = { timeout: 30_000 };

interface Sent {
  readonly method: string;
  readonly path: string;
  readonly key: string | null;
  readonly arm: boolean;
  readonly body: unknown;
  /** Its signal had not aborted when it was sent: a browser sends nothing on an aborted one. */
  readonly live: boolean;
}

interface Served {
  readonly accounts?: readonly ExchangeAccount[];
  readonly orders?: readonly unknown[];
  readonly cancel?: (id: string) => Response | Promise<Response>;
  readonly cancelAll?: (body: unknown, n: number) => Response;
}

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/**
 * A write's answer as a browser's `fetch` gives it: refused unsent when its signal has already
 * aborted, and cut off by an abort while it waits (`AbortError` both ways).
 */
function asFetch(
  answer: Response | Promise<Response>,
  signal: AbortSignal | null | undefined,
): Promise<Response> {
  const aborted = (): DOMException => new DOMException("The operation was aborted.", "AbortError");
  if (signal == null) return Promise.resolve(answer);
  if (signal.aborted) return Promise.reject(aborted());
  return new Promise((resolve, reject) => {
    signal.addEventListener("abort", () => reject(aborted()), { once: true });
    void Promise.resolve(answer).then(resolve, reject);
  });
}

let ws: FakeClient;
let sent: Sent[];
let alive = false;

/** The server as SCR-063 reads it, and the cancel writes: every write is recorded with its headers. */
function serve(o: Served = {}) {
  const accounts = o.accounts ?? exchangeAccounts();
  const positions = positionsGolden<{ items: unknown[] }>("rest_list_positions.json").items;
  let cancelAlls = 0;
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = new URL(String(input), "http://localhost");
    const method = init?.method ?? "GET";
    const headers = new Headers(init?.headers);
    if (method !== "GET") {
      sent.push({
        method,
        path: url.pathname,
        key: headers.get("Idempotency-Key"),
        arm: headers.has("X-Arm-Token"),
        body: typeof init?.body === "string" ? JSON.parse(init.body) : null,
        live: init?.signal?.aborted !== true,
      });
    }
    if (url.pathname === "/api/v1/exchange-accounts")
      return json(200, { items: accounts, meta: { next_cursor: null, has_more: false } });
    if (url.pathname === "/api/v1/positions")
      return json(200, { items: positions, aggregates: [] });
    if (url.pathname === "/api/v1/orders")
      return json(200, {
        items: o.orders ?? restOpen(),
        meta: { next_cursor: null, has_more: false },
      });
    if (url.pathname === "/api/v1/orders/cancel-all" && method === "POST") {
      cancelAlls += 1;
      return asFetch(
        o.cancelAll?.(JSON.parse(String(init?.body)), cancelAlls) ?? json(200, { results: [] }),
        init?.signal,
      );
    }
    const id = /^\/api\/v1\/orders\/([0-9a-f-]{36})$/.exec(url.pathname)?.[1];
    if (id !== undefined && method === "DELETE")
      return asFetch(
        o.cancel?.(id) ?? json(202, { id, lifecycle_state: "cancel_pending" }),
        init?.signal,
      );
    return json(404, {});
  });
}

async function settle(ms = 0): Promise<void> {
  if (!alive) throw new Error("the test has ended");
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

interface OpenOptions extends Served {
  readonly permissions?: readonly string[];
  readonly body?: OrdersBody;
  /** The positions book's snapshot (default the golden's five). */
  readonly book?: unknown;
  /** The session's grants by account (default every account `trade`). */
  readonly modes?: Readonly<Record<string, "read" | "trade">>;
  readonly writes?: OrdersWrites;
  /** Leave the orders topic without its snapshot (the loading and failed bodies). */
  readonly noSnapshot?: boolean;
}

/** The panel on R-130, its positions book read, then the Working-orders tab with `body` as its snapshot. */
async function openOrders(o: OpenOptions = {}): Promise<{ unmount: () => void }> {
  setShellState({
    me: {
      role: "owner",
      permissions: [...(o.permissions ?? FULL)],
      user: { id: USER },
      accounts: (o.accounts ?? exchangeAccounts()).map((a) => ({
        exchange_account_id: a.id,
        mode: o.modes?.[a.id] ?? "trade",
      })),
    } as Me,
    environment: "live",
  });
  vi.stubGlobal("fetch", serve(o));
  const clocks = { ...fakeRaf, now: () => Date.now(), performance: null };
  const deps: PositionsDeps = {
    client: ws.client,
    feed: { api: positionsApi, ...clocks },
    orders: {
      feed: { api: ordersApi, ...clocks },
      wall: () => Date.now(),
      ...(o.writes === undefined ? {} : { writes: o.writes }),
    },
  };
  const router = createMemoryRouter(
    [{ path: "/positions", element: <PositionsPanel deps={deps} /> }],
    { initialEntries: ["/positions"] },
  );
  const view = render(
    <PreferencesProvider>
      <RouterProvider router={router} />
      <ShellAnnouncer />
    </PreferencesProvider>,
  );
  await settle(TICK);
  ws.live("positions")[0]?.push(snap(o.book ?? positionsGolden("ws_positions_snapshot.json")));
  await settle(TICK);
  fireEvent.click(screen.getByRole("tab", { name: "Working orders" }));
  await settle(TICK);
  if (o.noSnapshot !== true) ws.live("orders")[0]?.push(snap(o.body ?? snapshotBody()));
  await settle(TICK);
  return { unmount: view.unmount };
}

const grid = (): HTMLElement =>
  screen.getByRole("treegrid", { name: "Working orders", hidden: true });
function orderRow(id: string): HTMLElement {
  const row = grid().querySelector<HTMLElement>(`tr[data-key="${id}"]`);
  if (row === null) throw new Error(`no row for ${id}`);
  return row;
}
const cancelOf = (id: string): HTMLElement =>
  within(orderRow(id)).getByRole("button", { name: /Cancel/, hidden: true });
const region = (politeness: "polite" | "assertive"): string =>
  document.querySelector(`[data-cv-inert-exempt][aria-live="${politeness}"]`)?.textContent ?? "";
/** A sentence on screen (a toast, the selection bar), not the shell region that also says it. */
const onScreen = (text: string): HTMLElement | undefined =>
  screen.getAllByText(text).find((el) => el.closest("[data-cv-inert-exempt]") === null);
/** The `cv:analytics` events from now on, for the test's life. */
function analytics(): Readonly<Record<string, unknown>>[] {
  const seen: Readonly<Record<string, unknown>>[] = [];
  const listen = (event: Event): void => {
    seen.push((event as CustomEvent<Readonly<Record<string, unknown>>>).detail);
  };
  window.addEventListener(THEME_ANALYTICS_EVENT, listen);
  onTestFinished(() => window.removeEventListener(THEME_ANALYTICS_EVENT, listen));
  return seen;
}
const deletes = (): string[] =>
  sent.filter((s) => s.method === "DELETE").map((s) => s.path.slice("/api/v1/orders/".length));
/**
 * Focus sits on an element still in the document and shown, never `body` (D05 §5.4 G-BODY): jsdom
 * leaves focus on a control a closed dialog hides, where a browser drops it to `body`.
 */
const focusHeld = (): void => {
  const active = document.activeElement;
  expect(active).not.toBe(document.body);
  expect(active?.isConnected).toBe(true);
  expect(active?.closest("[hidden], [inert]")).toBeNull();
};
/** The golden snapshot's positions, and the one under the Sub-2 stop (D02 §6.2). */
const positionsBook = (): { positions: { id: string; updated_at_ms: number }[] } =>
  positionsGolden("ws_positions_snapshot.json");
const STOP_POSITION = "0d000000-0000-4000-8000-000000000005";
/** Types LIVE's word into the bulk confirm and confirms it (D01 D7). */
async function confirmBulk(name: string): Promise<void> {
  const dialog = screen.getByRole("alertdialog");
  fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "CANCEL" } });
  await settle(500);
  fireEvent.click(within(dialog).getByRole("button", { name }));
  await settle(TICK);
}
/** The protective take-profit's confirm (D02 §8.2): its title, then its own Cancel. */
const TP_TITLE = "Cancel the take-profit at 64,800 for Main BTCUSDT?";
async function confirmTakeProfit(): Promise<void> {
  fireEvent.click(cancelOf(TP));
  await settle(500);
  const dialog = screen.getByRole("alertdialog", { name: TP_TITLE });
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancel take-profit" }));
  await settle(TICK);
}

/** A frame for one order: the snapshot's item with `patch` and a later stamp. */
const moved = (id: string, patch: Record<string, unknown>, at: number): OrdersBody =>
  ({ orders: [{ ...wsItem(snapshotBody(), id), ...patch, updated_at_ms: at }] }) as OrdersBody;

/**
 * `n` placed entries, ENTRY's frame and REST row under ids `0e000000-…-000000000{series}{nn}`, each
 * on `accounts` in turn (ENTRY's own Sub-1 by default): every long or many-account view (code n8).
 */
function placed(
  n: number,
  series: number,
  accounts: readonly string[] = [SUB1],
): Served & { body: OrdersBody } {
  const entry = wsItem(snapshotBody(), ENTRY);
  const rest = restOpen().find((r) => r.id === ENTRY);
  const id = (i: number) =>
    `0e000000-0000-4000-8000-000000000${series}${String(i).padStart(2, "0")}`;
  const on = (i: number) => accounts[i % accounts.length] ?? SUB1;
  const each = <T,>(row: T) =>
    Array.from({ length: n }, (_, i) => ({ ...row, id: id(i), exchange_account_id: on(i) }));
  return { body: { orders: each(entry) } as OrdersBody, orders: each(rest) };
}

/** DELETEs the test answers itself (`answer`, a 202 `cancel_pending` each; all of them, or `ids`). */
function heldCancels(): {
  readonly cancel: (id: string) => Promise<Response>;
  readonly waiting: () => string[];
  readonly answer: (...ids: string[]) => void;
} {
  const waiting = new Map<string, (res: Response) => void>();
  return {
    cancel: (id) => new Promise<Response>((resolve) => waiting.set(id, resolve)),
    waiting: () => [...waiting.keys()],
    answer: (...ids) => {
      for (const id of ids.length === 0 ? [...waiting.keys()] : ids) {
        waiting.get(id)?.(json(202, { id, lifecycle_state: "cancel_pending" }));
        waiting.delete(id);
      }
    },
  };
}

/**
 * Whether a timer runs out at `at` and is not set again: the pending count changes across that
 * millisecond (the frame loops set their next one as they fire, and nothing else is due then).
 */
async function timerEndsAt(at: number): Promise<boolean> {
  await settle(at - 1 - Date.now());
  const pending = vi.getTimerCount();
  await settle(1);
  return vi.getTimerCount() !== pending;
}

/** Every message the shell's regions take from now on, in order (`ShellAnnouncer`: a node each). */
function heard(): () => string[] {
  const said: string[] = [];
  const take = (records: readonly MutationRecord[]): void => {
    for (const record of records)
      for (const node of record.addedNodes)
        if (node instanceof HTMLElement) said.push(node.textContent ?? "");
  };
  const observer = new MutationObserver(take);
  for (const region of document.querySelectorAll("[data-cv-inert-exempt][aria-live]"))
    observer.observe(region, { childList: true });
  onTestFinished(() => observer.disconnect());
  return () => {
    take(observer.takeRecords());
    return said;
  };
}

beforeAll(async () => {
  // the panel's first render in a worker compiles its whole tree: paid once, under the screen bound
  vi.useFakeTimers();
  ws = fakeClient();
  sent = [];
  alive = true;
  (await openOrders()).unmount();
  alive = false;
  vi.unstubAllGlobals();
  vi.useRealTimers();
}, SCREEN.timeout);

beforeEach(() => {
  alive = true;
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
  Element.prototype.scrollIntoView = vi.fn();
  ws = fakeClient();
  sent = [];
  resetPanelState();
  resetShellState();
  clearAnnouncements();
  localStorage.clear();
});
afterEach(() => {
  alive = false;
  vi.unstubAllGlobals();
  vi.useRealTimers();
  resetShellState();
  clearAnnouncements();
});

describe("Rows carry the full order vocabulary; Conditional orders are separated", () => {
  it("sections at level 1, account groups at level 2, the orders at level 3", SCREEN, async () => {
    await openOrders();
    const rows = within(grid()).getAllByRole("row", { hidden: true });
    const sections = rows.filter((r) => r.getAttribute("aria-level") === "1");
    expect(sections.map((r) => r.textContent)).toEqual([
      "Working · 5",
      "Conditional — not triggered · 2",
    ]);
    const entry = orderRow(ENTRY);
    expect(entry).toHaveAttribute("aria-level", "3");
    expect(
      within(entry)
        .getAllByRole("gridcell", { hidden: true })
        .slice(1, -1)
        .map((c) => c.textContent),
    ).toEqual([
      "Sub-1",
      "▲ Buy",
      "Limit · Entry",
      "0.15 BTC",
      "0.05",
      "63,950",
      "63,950",
      "—",
      "GTC",
      "—",
      "4 m",
      "#7c1e",
      "Partial 0.05/0.15",
    ]);
    expect(within(entry).getByRole("rowheader", { hidden: true })).toHaveTextContent("BTCUSDT");
  });
});

describe("a row's Cancel (D02 §8.2)", () => {
  it(
    "sends one DELETE, its own key and no arm token; busy, then a toast names the order",
    SCREEN,
    async () => {
      await openOrders();
      const seen = analytics();
      fireEvent.click(cancelOf(ENTRY));
      expect(seen).toEqual([{ name: "order.cancel_attempted", via: "row" }]);
      expect(cancelOf(ENTRY)).toHaveAttribute("aria-busy", "true");
      expect(cancelOf(ENTRY)).toHaveTextContent("Cancelling…");
      await settle(TICK);
      expect(sent).toEqual([
        expect.objectContaining({ method: "DELETE", path: `/api/v1/orders/${ENTRY}`, arm: false }),
      ]);
      expect(sent[0]?.key).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
      );
      expect(onScreen("Cancel sent: BTCUSDT Buy 0.15 at 63,950 on Sub-1.")).toBeVisible();
    },
  );

  it(
    "Cancel that lost the race: Cancelling, then Filled, no error and no 'already filled'",
    SCREEN,
    async () => {
      await openOrders();
      await confirmTakeProfit(); // D02 §8.2's example row: a protective take-profit asks first
      expect(deletes()).toEqual([TP]);
      const handle = ws.live("orders")[0];
      handle?.push(delta(deltaBody("cancel_request")));
      await settle(TICK);
      expect(orderRow(TP)).toHaveTextContent("Cancelling");
      expect(cancelOf(TP)).toHaveAttribute("aria-busy", "true");
      handle?.push(delta(deltaBody("cancel_lost_race")));
      await settle(TICK);
      expect(orderRow(TP)).toHaveTextContent("Filled");
      expect(cancelOf(TP)).toBeDisabled(); // nothing left to cancel
      expect(document.body.textContent?.toLowerCase()).not.toContain("already filled");
      expect(screen.queryByText(/^Not cancelled/)).toBeNull();
      await settle(LINGER_MS + TICK);
      expect(grid().querySelector(`tr[data-key="${TP}"]`)).toBeNull();
    },
  );

  it(
    "the 110001 path: Unknown — checking until reconciliation says Filled (BQ-3)",
    SCREEN,
    async () => {
      await openOrders({ cancel: (id) => json(202, { id, lifecycle_state: "unknown" }) });
      await confirmTakeProfit();
      expect(deletes()).toEqual([TP]);
      ws.live("orders")[0]?.push(delta(deltaBody("cancel_110001")));
      await settle(TICK);
      expect(orderRow(TP)).toHaveTextContent("Unknown — checking");
      expect(cancelOf(TP)).toHaveAccessibleDescription(
        "We could not confirm this order with Bybit; checking.",
      );
      ws.live("orders")[0]?.push(delta(deltaBody("reconcile_filled")));
      await settle(TICK);
      expect(orderRow(TP)).toHaveTextContent("Filled");
    },
  );

  it("a refusal keeps the row and says so; the server's words never show", SCREEN, async () => {
    await openOrders({
      cancel: () => json(502, { code: "exchange_error", detail: "Bybit 110001 order not exists" }),
    });
    fireEvent.click(cancelOf(ENTRY));
    await settle(TICK);
    expect(onScreen("Not cancelled: BTCUSDT Buy 0.15 on Sub-1.")).toBeVisible();
    expect(document.body.textContent).not.toMatch(/110001|not exists|exchange_error/);
    expect(cancelOf(ENTRY)).not.toHaveAttribute("aria-busy");
  });

  it(
    "busy holds until the row shows the cancel; a second press sends nothing (design m5)",
    SCREEN,
    async () => {
      await openOrders();
      fireEvent.click(cancelOf(ENTRY));
      await settle(TICK); // the 202 is in, no frame yet
      expect(cancelOf(ENTRY)).toHaveAttribute("aria-busy", "true");
      expect(cancelOf(ENTRY)).toHaveTextContent("Cancelling…");
      expect(cancelOf(ENTRY).querySelector(".cv-button__icon")).not.toBeNull(); // the ⟳ leads it
      fireEvent.click(cancelOf(ENTRY));
      await settle(TICK);
      expect(deletes()).toEqual([ENTRY]);
      // the frame moves the row: busy by its own state now, then ended
      ws.live("orders")[0]?.push(
        delta(moved(ENTRY, { lifecycle_state: "cancel_pending" }, 1_793_455_340_000)),
      );
      await settle(TICK);
      expect(cancelOf(ENTRY)).toHaveAttribute("aria-busy", "true");
      ws.live("orders")[0]?.push(
        delta(
          moved(ENTRY, { lifecycle_state: "cancelled", state: "cancelled" }, 1_793_455_341_000),
        ),
      );
      await settle(TICK);
      expect(cancelOf(ENTRY)).toBeDisabled();
      expect(deletes()).toEqual([ENTRY]);
    },
  );

  it(
    "busy holds through a fill; it ends at the 202's state, the order's end or unknown (n6)",
    SCREEN,
    async () => {
      await openOrders(); // each DELETE answers 202 with the order cancel_pending
      const push = (id: string, lifecycle: string, at: number): void =>
        ws.live("orders")[0]?.push(delta(moved(id, { lifecycle_state: lifecycle }, at)));
      const pressed = Date.now(); // its 202 comes at once: the bound counts from here
      fireEvent.click(cancelOf(ETH)); // submitted
      await settle(TICK);
      // a fill moves it, but not to the 202's state: busy holds, and a press sends nothing
      push(ETH, "partially_filled", 1_793_455_340_000);
      await settle(TICK);
      expect(cancelOf(ETH)).toHaveAttribute("aria-busy", "true");
      fireEvent.click(cancelOf(ETH));
      await settle(TICK);
      expect(deletes()).toEqual([ETH]);
      await settle(pressed + BUSY_BOUND_MS - 3 * TICK - Date.now());
      expect(cancelOf(ETH)).toHaveAttribute("aria-busy", "true"); // to the bound's last frames
      // it reaches cancel_pending (busy by its own state), then the venue refuses: free again,
      // still before the bound, so it is the 202's state that let it go
      push(ETH, "cancel_pending", 1_793_455_341_000);
      await settle(TICK);
      push(ETH, "partially_filled", 1_793_455_342_000);
      await settle(TICK);
      expect(Date.now()).toBeLessThan(pressed + BUSY_BOUND_MS);
      expect(cancelOf(ETH)).not.toHaveAttribute("aria-busy");
      expect(cancelOf(ETH)).not.toHaveAttribute("aria-disabled");
      // one parked unknown is let go too: its own reason shows, not busy
      fireEvent.click(cancelOf(COND));
      await settle(TICK);
      push(COND, "unknown", 1_793_455_343_000);
      await settle(TICK);
      expect(cancelOf(COND)).not.toHaveAttribute("aria-busy");
      expect(cancelOf(COND)).toHaveAccessibleDescription(
        "We could not confirm this order with Bybit; checking.",
      );
    },
  );

  it(
    "a row that moved on before its 202 was read is busy to the bound, then cancellable (R2-m1)",
    SCREEN,
    async () => {
      const held = heldCancels();
      await openOrders({ cancel: held.cancel });
      const push = (lifecycle: string, at: number): void =>
        ws.live("orders")[0]?.push(delta(moved(ETH, { lifecycle_state: lifecycle }, at)));
      fireEvent.click(cancelOf(ETH)); // submitted, its DELETE held
      await settle(TICK);
      // the cancel's step, then a fill (INV-B1-d), both before the 202 is read, in one commit
      push("cancel_pending", 1_793_455_340_000);
      push("partially_filled", 1_793_455_341_000);
      await settle(TICK);
      const answered = Date.now();
      held.answer(); // 202 cancel_pending: a state the row has already left
      await settle(TICK);
      push("partially_filled", 1_793_455_342_000);
      await settle(answered + BUSY_BOUND_MS - 1 - Date.now());
      expect(cancelOf(ETH)).toHaveAttribute("aria-busy", "true"); // n6's hold, to the bound
      fireEvent.click(cancelOf(ETH));
      await settle(1);
      expect(cancelOf(ETH)).not.toHaveAttribute("aria-busy"); // let go at the bound
      expect(deletes()).toEqual([ETH]); // the press while busy sent nothing
      fireEvent.click(cancelOf(ETH));
      await settle(TICK);
      expect(deletes()).toEqual([ETH, ETH]); // cancellable again
    },
  );

  it(
    "a row that reaches its 202's state is let go there, before the bound, timer and all (R2-m1)",
    SCREEN,
    async () => {
      const held = heldCancels();
      await openOrders({ cancel: held.cancel });
      const push = (lifecycle: string, at: number): void =>
        ws.live("orders")[0]?.push(delta(moved(ETH, { lifecycle_state: lifecycle }, at)));
      fireEvent.click(cancelOf(ETH));
      await settle(TICK);
      const answered = Date.now();
      held.answer();
      await settle(TICK);
      push("cancel_pending", 1_793_455_340_000); // the 202's state: busy by its own state now
      await settle(TICK);
      push("partially_filled", 1_793_455_341_000); // the venue refused it
      await settle(TICK);
      expect(cancelOf(ETH)).not.toHaveAttribute("aria-busy");
      expect(await timerEndsAt(answered + BUSY_BOUND_MS)).toBe(false); // its timer went with it
    },
  );

  it("a market order's sent toast names no price (code n5)", SCREEN, async () => {
    const body = snapshotBody();
    const market = {
      orders: body.orders.map((o) =>
        o.id === ENTRY ? { ...o, order_type: "market", price: null } : o,
      ),
    } as OrdersBody;
    await openOrders({ body: market });
    fireEvent.click(cancelOf(ENTRY));
    await settle(TICK);
    expect(onScreen("Cancel sent: BTCUSDT Buy 0.15 on Sub-1.")).toBeVisible();
  });

  it(
    "no answer after the re-sends: Cancel not confirmed, and the row is free again",
    SCREEN,
    async () => {
      await openOrders({
        cancel: () => {
          throw new TypeError("Failed to fetch");
        },
      });
      fireEvent.click(cancelOf(ENTRY));
      await settle(2 * 1_000 + TICK); // two re-sends, a second apart (BQ-8)
      expect(sent.filter((s) => s.method === "DELETE")).toHaveLength(3);
      expect(new Set(sent.map((s) => s.key)).size).toBe(1);
      expect(onScreen("Cancel not confirmed: BTCUSDT Buy 0.15 on Sub-1.")).toBeVisible();
      expect(cancelOf(ENTRY)).not.toHaveAttribute("aria-busy");
    },
  );

  it("a write that throws is no answer, never a Cancel left busy (code m9)", SCREEN, async () => {
    const throwing: OrdersWrites = {
      cancelOrder: () => Promise.reject(new Error("crypto.randomUUID needs a secure context")),
      cancelAllOrders: () => Promise.reject(new Error("crypto.randomUUID needs a secure context")),
    };
    await openOrders({ writes: throwing });
    fireEvent.click(cancelOf(ENTRY));
    await settle(TICK);
    expect(onScreen("Cancel not confirmed: BTCUSDT Buy 0.15 on Sub-1.")).toBeVisible();
    expect(cancelOf(ENTRY)).not.toHaveAttribute("aria-busy");
    fireEvent.click(screen.getByRole("button", { name: "Cancel all in view…" }));
    await settle(500);
    await confirmBulk("Cancel 4 orders");
    const result = screen.getByRole("dialog", { name: "Cancel results" });
    expect(within(result).getAllByRole("listitem")[0]).toHaveTextContent(
      "Main · LIVE: not confirmed — check its orders on Bybit",
    );
  });

  it("the row menu (Shift+F10) repeats Cancel and sends it (m18)", SCREEN, async () => {
    await openOrders();
    const cell = within(orderRow(ENTRY)).getByRole("rowheader", { hidden: true });
    act(() => cell.focus());
    fireEvent.keyDown(cell, { key: "F10", shiftKey: true });
    await settle(TICK);
    const menu = screen.getByRole("menu", {
      name: "Actions for BTCUSDT Buy 0.15 BTC at 63,950 on Sub-1",
    });
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Cancel" }));
    await settle(TICK);
    expect(deletes()).toEqual([ENTRY]);
  });

  it(
    "an ended row's Cancel hands focus to its cell, never to body (D05 §5.4)",
    SCREEN,
    async () => {
      await openOrders();
      const button = cancelOf(ENTRY);
      button.focus();
      ws.live("orders")[0]?.push(
        delta(
          moved(ENTRY, { lifecycle_state: "cancelled", state: "cancelled" }, 1_793_455_340_000),
        ),
      );
      await settle(TICK);
      expect(cancelOf(ENTRY)).toBeDisabled();
      expect(document.activeElement).toBe(cancelOf(ENTRY).closest("td"));
    },
  );
});

describe("a protective take-profit asks first (D01 D7, D02 §8.2; design M2)", () => {
  it("Keep take-profit sends nothing; Cancel take-profit sends one DELETE", SCREEN, async () => {
    await openOrders();
    const button = cancelOf(TP);
    act(() => button.focus());
    fireEvent.click(button);
    await settle(500);
    const dialog = screen.getByRole("alertdialog", { name: TP_TITLE });
    expect(sent).toEqual([]); // nothing before the answer
    fireEvent.click(within(dialog).getByRole("button", { name: "Keep take-profit" }));
    await settle(TICK);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(sent).toEqual([]);
    expect(document.activeElement).toBe(cancelOf(TP)); // back to its opener
    await confirmTakeProfit();
    expect(deletes()).toEqual([TP]);
    expect(sent[0]?.arm).toBe(false);
    expect(onScreen("Cancel sent: BTCUSDT Sell 0.25 at 64,800 on Main.")).toBeVisible();
  });

  it(
    "its Confirm reads the row again: one that ended meanwhile sends nothing (code m7)",
    SCREEN,
    async () => {
      await openOrders();
      fireEvent.click(cancelOf(TP));
      await settle(500);
      ws.live("orders")[0]?.push(delta(deltaBody("cancel_lost_race")));
      await settle(TICK);
      const dialog = screen.getByRole("alertdialog", { name: TP_TITLE });
      fireEvent.click(within(dialog).getByRole("button", { name: "Cancel take-profit" }));
      await settle(TICK);
      expect(sent).toEqual([]);
      focusHeld();
    },
  );
});

describe("the S-22 refusals (design m17)", () => {
  it(
    "403 account_scope_denied: that account's rows stay T2 with rbac.account, its header the notice",
    SCREEN,
    async () => {
      await openOrders({
        cancel: () => json(403, { code: "account_scope_denied", detail: "no grant" }),
      });
      fireEvent.click(cancelOf(ENTRY));
      await settle(TICK);
      expect(onScreen("Not cancelled: BTCUSDT Buy 0.15 on Sub-1.")).toBeVisible();
      expect(onScreen("This account isn't assigned to you.")).toBeVisible();
      for (const id of [ENTRY, COND]) {
        const button = cancelOf(id);
        expect(button).toHaveAttribute("aria-disabled", "true");
        expect(button).toHaveAccessibleDescription("This account isn't assigned to you.");
        const notice = document.getElementById(button.getAttribute("aria-describedby") ?? "");
        expect(notice?.closest('[data-part="GroupRow"]')).not.toBeNull();
      }
      expect(cancelOf(ETH)).not.toHaveAttribute("aria-disabled"); // Sub-2 is still assigned
      fireEvent.click(cancelOf(ENTRY));
      await settle(TICK);
      expect(deletes()).toEqual([ENTRY]); // the T2 press sent nothing more
    },
  );

  it("403 view_as_read_only gives its reason", SCREEN, async () => {
    await openOrders({ cancel: () => json(403, { code: "view_as_read_only" }) });
    fireEvent.click(cancelOf(ENTRY));
    await settle(TICK);
    expect(onScreen("Read-only while viewing as another user.")).toBeVisible();
  });
});

describe("the native stop (C-2.6, BQ-5)", () => {
  it(
    "its Cancel is T2 with sl.note; a press sends nothing and says the reason once",
    SCREEN,
    async () => {
      await openOrders();
      const seen = analytics();
      const stop = cancelOf(STOP);
      expect(stop).toHaveAttribute("aria-disabled", "true");
      expect(stop).not.toBeDisabled();
      expect(stop).toHaveAccessibleDescription(
        "Every position keeps a native stop — you can move it, not delete it.",
      );
      fireEvent.click(stop);
      await settle(REGION_BUDGET_MS + TICK);
      expect(sent).toEqual([]);
      expect(seen).toEqual([]); // a T2 press reports nothing
      expect(region("polite")).toContain("Every position keeps a native stop");
    },
  );

  it(
    "Cancel all in view sends every order but the stop, and the dialog says it is left out",
    SCREEN,
    async () => {
      await openOrders();
      fireEvent.click(screen.getByRole("button", { name: "Cancel all in view…" }));
      await settle(500);
      const dialog = screen.getByRole("alertdialog");
      expect(dialog).toHaveTextContent(
        "1 native-stop order is not included: every position keeps a native stop.",
      );
      expect(dialog).toHaveTextContent("2 orders are not included: they can't be cancelled now.");
      fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "CANCEL" } });
      await settle(500);
      fireEvent.click(within(dialog).getByRole("button", { name: "Cancel 4 orders" }));
      await settle(TICK);
      expect(deletes().sort()).toEqual(
        [
          TP,
          ENTRY,
          "0e000000-0000-4000-8000-000000000004",
          "0e000000-0000-4000-8000-000000000003",
        ].sort(),
      );
      expect(deletes()).not.toContain(STOP);
      expect(sent.every((s) => !s.arm)).toBe(true);
      expect(new Set(sent.map((s) => s.key)).size).toBe(4); // one key per request
      const result = screen.getByRole("dialog", { name: "Cancel results" });
      expect(result).toHaveTextContent("Cancelled 1 on Main · LIVE");
      expect(result).toHaveTextContent("Cancelled 2 on Sub-1 · LIVE");
    },
  );

  it(
    "a stop whose position opens between the press and Confirm is never sent; the result names it (M1)",
    SCREEN,
    async () => {
      await openOrders();
      const positions = ws.live("positions")[0];
      // the stop's position goes flat: an orphan stop cancels like any order (D01 D7)
      positions?.push(delta({ positions: [], removed: [STOP_POSITION] }));
      await settle(TICK);
      expect(cancelOf(STOP)).not.toHaveAttribute("aria-disabled");
      fireEvent.click(screen.getByRole("button", { name: "Cancel all in view…" }));
      await settle(500);
      expect(screen.getByRole("alertdialog", { name: "Cancel 5 orders?" })).toHaveTextContent(
        "BTCUSDT Sell 0.08 BTC on Sub-2 · LIVE",
      );
      // an entry fills while the dialog is up: the stop's position opens again
      const reopened = positionsBook().positions.find((p) => p.id === STOP_POSITION);
      if (reopened === undefined) throw new Error("no stop position golden");
      positions?.push(
        delta({ positions: [{ ...reopened, updated_at_ms: reopened.updated_at_ms + 10 }] }),
      );
      await settle(TICK);
      await confirmBulk("Cancel 5 orders");
      expect(deletes()).not.toContain(STOP);
      expect(deletes().sort()).toEqual([TP, ENTRY, ETH, COND].sort());
      const result = screen.getByRole("dialog", { name: "Cancel results" });
      expect(result).toHaveTextContent(
        "1 native-stop order is not included: every position keeps a native stop.",
      );
    },
  );
});

describe("Cancel-all partial failure", () => {
  /** Five accounts, one placed entry each: Cancel all in view is one cancelAllOrders. */
  const five = (): Served & { body: OrdersBody } => {
    const base = exchangeAccounts()[0];
    if (base === undefined) throw new Error("no account golden");
    const more = [
      { ...base, id: SUB3, label: "Sub-3" },
      { ...base, id: SUB4, label: "Sub-4" },
    ];
    return {
      accounts: [...exchangeAccounts(), ...more],
      ...placed(5, 2, [MAIN, SUB1, SUB2, SUB3, SUB4]),
    };
  };

  it(
    "3 of 5 accounts: a per-account list with each failing account's reason; Retry failed sends the retryable one alone",
    SCREEN,
    async () => {
      const answer = golden("rest_cancel_all_partial.json");
      await openOrders({
        ...five(),
        // 22's answer to the retry: the order whose cancel timed out is never sent again and
        // ends cancelled by its own send, so nothing more is affected (code m3)
        cancelAll: (_, n) =>
          n === 1
            ? json(200, answer)
            : json(200, {
                results: [{ exchange_account_id: SUB4, ok: true, affected: 0, error: null }],
                requested: 1,
                succeeded: 1,
              }),
      });
      const seen = analytics();
      const opener = screen.getByRole("button", { name: "Cancel all in view…" });
      opener.focus(); // as a browser's click does
      fireEvent.click(opener);
      await settle(500);
      const dialog = screen.getByRole("alertdialog", { name: "Cancel 5 orders?" });
      for (const label of ["Main", "Sub-1", "Sub-2", "Sub-3", "Sub-4"])
        expect(dialog).toHaveTextContent(`1 order on ${label} · LIVE`);
      expect(sent).toEqual([]); // nothing before Confirm
      fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "CANCEL" } });
      await settle(500);
      fireEvent.click(within(dialog).getByRole("button", { name: "Cancel 5 orders" }));
      await settle(TICK);
      expect(sent).toHaveLength(1);
      expect(sent[0]).toMatchObject({
        method: "POST",
        path: "/api/v1/orders/cancel-all",
        arm: false,
        body: {
          exchange_account_ids: [MAIN, SUB1, SUB2, SUB3, SUB4],
          symbol: null,
          intents: [],
          exclude_reduce_only: true,
        },
      });
      const result = screen.getByRole("dialog", { name: "Cancel results" });
      const lines = within(result)
        .getAllByRole("listitem")
        .map((li) => li.textContent);
      expect(lines).toEqual([
        "Cancelled 4 on Main · LIVE",
        "Cancelled 2 on Sub-1 · LIVE",
        "Sub-2 · LIVE: not confirmed — check its orders on Bybit",
        "Cancelled 3 on Sub-3 · LIVE",
        "Sub-4 · LIVE: cancelled 1, then Bybit stopped answering — try again",
      ]);
      expect(result).not.toHaveTextContent(/connectivity|deadline/i);
      expect(document.activeElement).toBe(within(result).getByRole("button", { name: "Close" }));
      fireEvent.click(within(result).getByRole("button", { name: "Retry failed" }));
      await settle(TICK);
      expect(sent).toHaveLength(2);
      // exchange_unavailable is retryable false: that order unknown, never sent again (22)
      expect(sent[1]?.body).toMatchObject({ exchange_account_ids: [SUB4] });
      expect(seen.map((e) => [e["retry"], e["orders"], e["accounts"]])).toEqual([
        [false, 5, 5],
        [true, 1, 1],
      ]);
      expect(sent[1]?.key).not.toBe(sent[0]?.key); // a new request, a new key (BQ-8)
      expect(
        within(screen.getByRole("dialog", { name: "Cancel results" }))
          .getAllByRole("listitem")
          .map((li) => li.textContent),
      ).toEqual(["Cancelled 0 on Sub-4 · LIVE"]);
      fireEvent.click(screen.getByRole("button", { name: "Close" }));
      await settle(TICK);
      expect(document.activeElement).toBe(opener);
    },
  );

  it(
    "once sent, the dismissing button reads Close: it closes the view and cancels nothing; the result comes as a toast (design m12, m1)",
    SCREEN,
    async () => {
      let answer: (res: Response) => void = () => undefined;
      await openOrders({
        ...five(),
        cancelAll: () =>
          new Promise<Response>((resolve) => {
            answer = resolve;
          }) as never,
      });
      fireEvent.click(screen.getByRole("button", { name: "Cancel all in view…" }));
      await settle(500);
      await confirmBulk("Cancel 5 orders");
      const confirm = screen.getByRole("alertdialog");
      expect(confirm).toHaveAttribute("aria-busy", "true");
      // it keeps nothing back once sent, so it says what it does (m1); Esc does the same (N-M1)
      expect(within(confirm).queryByRole("button", { name: "Keep orders" })).toBeNull();
      fireEvent.click(within(confirm).getByRole("button", { name: "Close" }));
      await settle(TICK);
      expect(screen.queryByRole("alertdialog")).toBeNull();
      focusHeld();
      answer(json(200, golden("rest_cancel_all_partial.json")));
      await settle(TICK);
      expect(screen.queryByRole("dialog", { name: "Cancel results" })).toBeNull();
      expect(onScreen("Cancel results")).toBeVisible();
      expect(
        screen.getByText(/Sub-2 · LIVE: not confirmed — check its orders on Bybit/, {
          ignore: "[data-cv-inert-exempt] *",
        }),
      ).toBeVisible();
      expect(sent).toHaveLength(1); // closing sent nothing more and cancelled nothing
    },
  );

  it(
    "Close while Retry failed runs: the late result is dropped, never re-opened (code m8)",
    SCREEN,
    async () => {
      let answer: (res: Response) => void = () => undefined;
      await openOrders({
        ...five(),
        cancelAll: (_, n) =>
          n === 1
            ? json(200, golden("rest_cancel_all_partial.json"))
            : (new Promise<Response>((resolve) => {
                answer = resolve;
              }) as never),
      });
      fireEvent.click(screen.getByRole("button", { name: "Cancel all in view…" }));
      await settle(500);
      await confirmBulk("Cancel 5 orders");
      const result = screen.getByRole("dialog", { name: "Cancel results" });
      fireEvent.click(within(result).getByRole("button", { name: "Retry failed" }));
      await settle(TICK);
      fireEvent.click(within(result).getByRole("button", { name: "Close" }));
      await settle(TICK);
      expect(screen.queryByRole("dialog", { name: "Cancel results" })).toBeNull();
      answer(
        json(200, { results: [{ exchange_account_id: SUB4, ok: true, affected: 0, error: null }] }),
      );
      await settle(TICK);
      expect(screen.queryByRole("dialog", { name: "Cancel results" })).toBeNull();
      focusHeld();
    },
  );
});

describe("Cancel selected (D02 §8.3, D-3)", () => {
  it("the selection bar counts and says it; Keep orders sends nothing", SCREEN, async () => {
    await openOrders();
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Select BTCUSDT Buy 0.15 BTC at 63,950 on Sub-1",
        hidden: true,
      }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Select ETHUSDT Buy 1 ETH at 2,500 on Sub-2",
        hidden: true,
      }),
    );
    await settle(REGION_BUDGET_MS + TICK);
    expect(onScreen("2 selected")).toBeVisible();
    expect(region("polite")).toContain("2 selected");
    fireEvent.click(screen.getByRole("button", { name: "Cancel selected" }));
    await settle(500);
    const dialog = screen.getByRole("alertdialog", { name: "Cancel 2 orders?" });
    expect(dialog).toHaveTextContent("BTCUSDT Buy 0.15 BTC on Sub-1 · LIVE");
    expect(
      screen.getByText("2 selected", { selector: '[data-part="SelectionBar"] span' }),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Keep orders" }));
    await settle(TICK);
    expect(sent).toEqual([]);
  });

  it(
    "Confirm sends one cancelOrder per selected row; after the result's Close focus is held (M2)",
    SCREEN,
    async () => {
      await openOrders();
      for (const name of [
        "Select BTCUSDT Buy 0.15 BTC at 63,950 on Sub-1",
        "Select ETHUSDT Buy 1 ETH at 2,500 on Sub-2",
      ])
        fireEvent.click(screen.getByRole("checkbox", { name, hidden: true }));
      await settle(TICK);
      const opener = screen.getByRole("button", { name: "Cancel selected" });
      act(() => opener.focus());
      fireEvent.click(opener);
      await settle(500);
      await confirmBulk("Cancel 2 orders");
      expect(deletes().sort()).toEqual([ENTRY, ETH].sort());
      expect(screen.queryByRole("button", { name: "Cancel selected" })).toBeNull(); // the bar left
      const result = screen.getByRole("dialog", { name: "Cancel results" });
      fireEvent.click(within(result).getByRole("button", { name: "Close" }));
      await settle(TICK);
      focusHeld();
      expect(grid().contains(document.activeElement)).toBe(true); // the grid's roving stop
    },
  );

  it(
    "Cancel all in view that empties the view: after Close focus is held (M2)",
    SCREEN,
    async () => {
      const keep = new Set([ENTRY, COND, ETH]);
      await openOrders({
        body: { orders: snapshotBody().orders.filter((o) => keep.has(o.id)) } as OrdersBody,
        orders: restOpen().filter((o) => keep.has(o.id)),
      });
      const opener = screen.getByRole("button", { name: "Cancel all in view…" });
      act(() => opener.focus()); // as a browser's click does: the opener is this button
      fireEvent.click(opener);
      await settle(500);
      await confirmBulk("Cancel 3 orders");
      ws.live("orders")[0]?.push(
        delta({
          orders: [ENTRY, COND, ETH].map((id, i) => ({
            ...wsItem(snapshotBody(), id),
            lifecycle_state: "cancelled",
            state: "cancelled",
            updated_at_ms: 1_793_455_350_000 + i,
          })),
        } as OrdersBody),
      );
      await settle(LINGER_MS + TICK);
      expect(opener.isConnected).toBe(false); // the opener left with the emptied view
      fireEvent.click(screen.getByRole("button", { name: "Close" }));
      await settle(TICK);
      focusHeld();
      expect(
        screen.getByRole("group", { name: "Working orders" }).contains(document.activeElement),
      ).toBe(true);
    },
  );

  it("a press with nothing to send opens no dialog and says why (m18)", SCREEN, async () => {
    await openOrders();
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Select BTCUSDT Sell 0.08 BTC on Sub-2", hidden: true }),
    );
    await settle(TICK);
    fireEvent.click(screen.getByRole("button", { name: "Cancel selected" }));
    await settle(500);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(
      onScreen("1 native-stop order is not included: every position keeps a native stop."),
    ).toBeVisible();
    expect(sent).toEqual([]);
  });

  it(
    "Ctrl+A selects every order in view, Space one; Clear selection keeps focus and says 0 (n5)",
    SCREEN,
    async () => {
      await openOrders();
      const cell = within(orderRow(ENTRY)).getByRole("rowheader", { hidden: true });
      act(() => cell.focus());
      fireEvent.keyDown(cell, { key: "a", ctrlKey: true });
      await settle(TICK);
      expect(onScreen("7 selected")).toBeVisible();
      fireEvent.keyDown(cell, { key: " " });
      await settle(TICK);
      expect(onScreen("6 selected")).toBeVisible();
      expect(orderRow(ENTRY)).toHaveAttribute("aria-selected", "false");
      const clear = screen.getByRole("button", { name: "Clear selection" });
      act(() => clear.focus());
      fireEvent.click(clear);
      await settle(REGION_BUDGET_MS + TICK);
      expect(screen.queryByRole("button", { name: "Clear selection" })).toBeNull();
      focusHeld();
      expect(region("polite")).toContain("0 selected");
    },
  );
});

describe("T2 and the carve-out (D02 §10.3–§10.4)", () => {
  it(
    "a Viewer's Cancel and bulk buttons point at the panel's one orders:write line",
    SCREEN,
    async () => {
      await openOrders({ permissions: ["positions:read", "orders:read", "accounts:read"] });
      const line = screen.getByText("Your role can't place orders.", { selector: "p" });
      expect(line.id).not.toBe("");
      for (const button of [
        cancelOf(ENTRY),
        screen.getByRole("button", { name: /Cancel all in view/ }),
      ]) {
        expect(button).toHaveAttribute("aria-disabled", "true");
        expect(button).toHaveAccessibleDescription("Your role can't place orders.");
        expect(button).toHaveAttribute("aria-describedby", line.id); // the one notice (m18)
      }
      // the row menu's Cancel points at it too, no second line of its own (design M1)
      const cell = within(orderRow(ENTRY)).getByRole("rowheader", { hidden: true });
      act(() => cell.focus());
      fireEvent.keyDown(cell, { key: "F10", shiftKey: true });
      await settle(TICK);
      const item = within(screen.getByRole("menu")).getByRole("menuitem", { name: "Cancel" });
      expect(item).toHaveAttribute("aria-disabled", "true");
      expect(item).toHaveAttribute("aria-describedby", line.id);
      expect(item.closest(".cv-menu__row")?.querySelector(".cv-menu__second")).toBeNull();
      fireEvent.keyDown(item, { key: "Escape" });
      await settle(TICK);
      // selecting sends nothing and stays enabled
      expect(
        screen.getByRole("checkbox", {
          name: "Select BTCUSDT Buy 0.15 BTC at 63,950 on Sub-1",
          hidden: true,
        }),
      ).not.toHaveAttribute("aria-disabled");
      fireEvent.click(cancelOf(ENTRY));
      await settle(TICK);
      expect(sent).toEqual([]);
    },
  );

  it(
    "offline with REST unreachable: one notice, every cancel pointing at it (D02:397)",
    SCREEN,
    async () => {
      await openOrders();
      ws.setLink({ kind: "offline", cause: "backend_unreachable" });
      await settle(TICK);
      expect(screen.getByText("Cannot reach server")).toBeVisible();
      for (const button of [
        cancelOf(ENTRY),
        screen.getByRole("button", { name: /Cancel all in view/ }),
      ]) {
        expect(button).toHaveAttribute("aria-disabled", "true");
        expect(button).toHaveAccessibleDescription("Cannot reach server");
      }
      // the socket's own fatal close leaves REST reachable: the cancels stay sendable
      ws.setLink({ kind: "offline", cause: "fatal", closeCode: 4400 });
      await settle(TICK);
      expect(cancelOf(ENTRY)).not.toHaveAttribute("aria-disabled");
    },
  );

  it(
    "a read-only grant: one header notice per section, the row menu pointing at it, and the bulk buttons' reason beside them (m1, m3, n4)",
    SCREEN,
    async () => {
      const modes = { [MAIN]: "read", [SUB1]: "read", [SUB2]: "read" } as const;
      await openOrders({ modes });
      // Sub-1 heads a group in each section: two notices, two ids (no duplicate id, m1)
      const working = cancelOf(ENTRY).getAttribute("aria-describedby");
      const conditional = cancelOf(COND).getAttribute("aria-describedby");
      expect(working).not.toBe(conditional);
      for (const id of [working, conditional]) {
        const notice = document.getElementById(id ?? "");
        expect(notice).toHaveTextContent("You can view this account, not trade it.");
        expect(notice?.closest('[data-part="GroupRow"]')).not.toBeNull();
      }
      // the row menu's Cancel points at the same header notice, no second line of its own (n4)
      const cell = within(orderRow(ENTRY)).getByRole("rowheader", { hidden: true });
      act(() => cell.focus());
      fireEvent.keyDown(cell, { key: "F10", shiftKey: true });
      await settle(TICK);
      const item = within(screen.getByRole("menu")).getByRole("menuitem", { name: "Cancel" });
      expect(item).toHaveAttribute("aria-disabled", "true");
      expect(working).not.toBeNull();
      expect(item.getAttribute("aria-describedby")).toBe(working);
      expect(item.closest(".cv-menu__row")?.querySelector(".cv-menu__second")).toBeNull();
      fireEvent.keyDown(item, { key: "Escape" });
      await settle(TICK);
      // every account in view read-only: "Cancel all in view…" takes the reason, drawn beside it
      const all = screen.getByRole("button", { name: /Cancel all in view/ });
      expect(all).toHaveAttribute("aria-disabled", "true");
      const reason = document.getElementById(all.getAttribute("aria-describedby") ?? "");
      expect(reason).toHaveAttribute("data-part", "BulkReason");
      expect(reason).toHaveTextContent("You can view this account, not trade it.");
      fireEvent.click(all);
      await settle(TICK);
      expect(screen.queryByRole("alertdialog")).toBeNull();
    },
  );

  it("the kill switch never gates a cancel (C-2.6)", SCREEN, async () => {
    await openOrders();
    ws.setState({ killSwitch: { state: "engaged", scope: "global", exchangeAccountIds: [] } });
    await settle(TICK);
    expect(cancelOf(ENTRY)).not.toHaveAttribute("aria-disabled");
    fireEvent.click(cancelOf(ENTRY));
    await settle(TICK);
    expect(deletes()).toEqual([ENTRY]);
  });
});

describe("the window past 50 rows (G-01; code M3)", () => {
  /** `n` placed entries on Sub-1, one account group: a section, a group, then the orders. */
  const many = (n: number): Served & { body: OrdersBody } => placed(n, 3);
  /** Lays the region out: 24 px rows under a 24 px header, `view` px tall, scrolled to `top`. */
  function layout(view: number): (top: number) => void {
    const box = grid().closest<HTMLElement>(".cv-table__region");
    if (box === null) throw new Error("no region");
    let top = 0;
    Object.defineProperty(box, "clientHeight", { configurable: true, get: () => view });
    Object.defineProperty(box, "scrollTop", { configurable: true, get: () => top });
    const rects = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockImplementation(function (this: HTMLElement) {
        const y = this.tagName === "TBODY" ? 24 - top : 0;
        const height = this.tagName === "TR" || this.tagName === "THEAD" ? 24 : 0;
        return { top: y, bottom: y + height, height, width: 0, left: 0, right: 0 } as DOMRect;
      });
    onTestFinished(() => rects.mockRestore());
    return (to) => {
      top = to;
      fireEvent.scroll(box);
    };
  }
  const drawnKeys = (): string[] =>
    [...grid().querySelectorAll("tbody tr[aria-rowindex]")].map(
      (r) => r.getAttribute("data-key") ?? r.getAttribute("aria-level") ?? "",
    );

  it(
    "60 orders: a first window, every row counted, the window moving with the scroll, the focused row kept",
    SCREEN,
    async () => {
      await openOrders(many(60));
      const table = grid();
      expect(table).toHaveAttribute("aria-rowcount", "63"); // the header, a section, a group, 60
      expect(drawnKeys()).toHaveLength(40); // the first window and its overscan
      const last = "0e000000-0000-4000-8000-000000000359";
      expect(table.querySelector(`tr[data-key="${last}"]`)).toBeNull();
      const focused = "0e000000-0000-4000-8000-000000000302";
      const cell = within(orderRow(focused)).getByRole("rowheader", { hidden: true });
      act(() => cell.focus());
      const scrollTo = layout(480);
      scrollTo(45 * 24);
      await settle(TICK);
      expect(table.querySelector(`tr[data-key="${last}"]`)).not.toBeNull(); // the window moved
      const kept = table.querySelector<HTMLElement>(`tr[data-key="${focused}"]`);
      expect(kept).not.toBeNull(); // G-01: the focused row stays drawn outside the window
      expect(kept).toHaveAttribute("aria-rowindex", "6"); // entry 4: the header row is 1
      expect(drawnKeys().length).toBeLessThan(63);
    },
  );

  it(
    "a read-only account's header stays drawn while its rows are (design m1)",
    SCREEN,
    async () => {
      await openOrders({ ...many(60), modes: { [SUB1]: "read" } });
      const scrollTo = layout(480);
      scrollTo(45 * 24);
      await settle(TICK);
      const last = cancelOf("0e000000-0000-4000-8000-000000000359");
      const notice = document.getElementById(last.getAttribute("aria-describedby") ?? "");
      expect(notice).not.toBeNull();
      expect(notice?.closest('[data-part="GroupRow"]')).not.toBeNull();
    },
  );
});

describe("the bodies (m18, design m15)", () => {
  it("loading: one busy group per account, as the Positions tab draws S-01", SCREEN, async () => {
    await openOrders({ noSnapshot: true, orders: [] }); // no row from REST either: S-01
    const loading = document.querySelector('[data-part="Loading"]');
    expect(loading).not.toBeNull();
    const groups = within(loading as HTMLElement).getAllByRole("group");
    expect(groups.map((g) => g.getAttribute("aria-busy"))).toEqual(["true", "true", "true"]);
    expect(groups[1]).toHaveAccessibleName("Loading Sub-1 · LIVE…");
  });

  it("empty: S-03's title and cause", SCREEN, async () => {
    await openOrders({ body: { orders: [] } as unknown as OrdersBody, orders: [] });
    expect(screen.getByRole("heading", { name: "No working orders" })).toBeVisible();
    expect(screen.getByText("Orders you place on any account appear here.")).toBeVisible();
  });

  it("no accounts", SCREEN, async () => {
    await openOrders({ accounts: [], orders: [] });
    expect(
      screen.getByRole("heading", {
        name: "No accounts to show. None is assigned to you, or your access to them is frozen.",
      }),
    ).toBeVisible();
  });

  it(
    "refused before any snapshot: could not load, and Retry keeps focus on the tab",
    SCREEN,
    async () => {
      await openOrders({ noSnapshot: true });
      ws.live("orders")[0]?.push(reset("revoked"));
      await settle(TICK);
      expect(screen.getByText("Could not load Sub-1 · LIVE")).toBeVisible();
      fireEvent.click(screen.getByRole("button", { name: "Retry" }));
      await settle(TICK);
      expect(document.activeElement).toBe(screen.getByRole("group", { name: "Working orders" }));
    },
  );

  it("revoked after a snapshot: the withdrawn lines, then Retry", SCREEN, async () => {
    await openOrders();
    ws.live("orders")[0]?.push(reset("revoked"));
    await settle(TICK);
    const failed = document.querySelector('[data-part="SnapshotFailed"]');
    expect(failed).not.toBeNull();
    expect(within(failed as HTMLElement).getByRole("button", { name: "Retry" })).toBeVisible();
    expect(screen.queryByRole("treegrid", { hidden: true })).toBeNull();
  });
});

describe("the toolbar, the tree and the toasts", () => {
  it(
    "the Side chip reads Buy, seen and spoken, and keeps the buy orders alone (the orchestrator's ruling)",
    SCREEN,
    async () => {
      await openOrders();
      act(() => updatePanelState({ chips: [{ kind: "side", value: "long" }] }));
      await settle(TICK);
      expect(screen.getByText("Side: Buy")).toBeVisible();
      expect(screen.queryByText("Side: Long")).toBeNull();
      expect(screen.getByRole("button", { name: "Remove filter Side: Buy" })).toBeVisible();
      const keys = [...grid().querySelectorAll("tr[data-key]")].map((r) =>
        r.getAttribute("data-key"),
      );
      expect(keys.sort()).toEqual([ENTRY, ETH, COND, HELD].sort()); // the buy orders, no sell
    },
  );

  it("a section collapses and expands from its header", SCREEN, async () => {
    await openOrders();
    const header = within(grid()).getByRole("rowheader", { name: "Working · 5", hidden: true });
    const row = header.closest("tr");
    expect(row).toHaveAttribute("aria-expanded", "true");
    act(() => header.focus());
    fireEvent.keyDown(header, { key: "ArrowLeft" });
    await settle(TICK);
    expect(row).toHaveAttribute("aria-expanded", "false");
    expect(grid().querySelector(`tr[data-key="${ENTRY}"]`)).toBeNull();
    fireEvent.keyDown(header, { key: "ArrowRight" });
    await settle(TICK);
    expect(orderRow(ENTRY)).toBeInTheDocument();
  });

  it(
    "the tab's one toast region has its own name, and a failure stays until dismissed (design m9, n5)",
    SCREEN,
    async () => {
      await openOrders({ cancel: () => json(502, { code: "exchange_error" }) });
      fireEvent.click(cancelOf(ENTRY));
      await settle(TICK);
      const stack = screen.getByRole("region", { name: "Order notifications" });
      expect(within(stack).getByText("Not cancelled: BTCUSDT Buy 0.15 on Sub-1.")).toBeVisible();
      await settle(20_000);
      expect(within(stack).getByText("Not cancelled: BTCUSDT Buy 0.15 on Sub-1.")).toBeVisible();
      // its corner is not the shell's: CMP-045 portals the region to the body, out of the tab, so
      // the stylesheet finds it by the tab's own toast ids, never by its PROPOSED label (n5)
      expect(stack.parentElement).toBe(document.body);
      const corner = '.cv-toast-region:has([data-toast-id^="orders-toast-"])';
      expect(stack.matches(corner)).toBe(true);
      const css = repoFile("apps/web/src/features/positions/positions.css");
      expect(css).toContain(`${corner} {`);
    },
  );

  it("a mark tick does not rebuild the orders in view (code m5)", SCREEN, async () => {
    await openOrders();
    const before = rebuilt.count;
    const main = positionsBook().positions[0] as { updated_at_ms: number };
    ws.live("positions")[0]?.push(
      delta({
        positions: [{ ...main, mark_price: "64100", updated_at_ms: main.updated_at_ms + 10 }],
      }),
    );
    await settle(TICK);
    expect(rebuilt.count).toBe(before);
  });
});

describe("the bulk dialog's restatement, the busy look and the bar (design n1, m4, n6)", () => {
  it(
    "past ten rows in view it restates the chips, and lists the rows while no chip is set (D02 §8.3)",
    SCREEN,
    async () => {
      await openOrders(placed(12, 4)); // twelve on Sub-1, all of them cancel-all's to select
      fireEvent.click(screen.getByRole("button", { name: "Cancel all in view…" }));
      await settle(500);
      const listed = document.querySelector(".cv-orders-bulk__targets");
      expect(listed?.querySelectorAll("li")).toHaveLength(12); // no chip: the list, never nothing
      fireEvent.click(
        within(screen.getByRole("alertdialog")).getByRole("button", { name: "Keep orders" }),
      );
      await settle(TICK);
      act(() => updatePanelState({ chips: [{ kind: "symbol", value: "BTCUSDT" }] }));
      await settle(TICK);
      fireEvent.click(screen.getByRole("button", { name: "Cancel all in view…" }));
      await settle(500);
      const dialog = screen.getByRole("alertdialog");
      expect(dialog.querySelector(".cv-orders-bulk__targets")).toBeNull();
      expect(dialog).toHaveTextContent("Symbol: BTCUSDT");
    },
  );

  it("the selection bar draws its dots, hidden from the reader", SCREEN, async () => {
    await openOrders();
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Select BTCUSDT Buy 0.15 BTC at 63,950 on Sub-1",
        hidden: true,
      }),
    );
    await settle(TICK);
    const bar = document.querySelector<HTMLElement>('[data-part="SelectionBar"]');
    const dots = [...(bar?.querySelectorAll('[aria-hidden="true"]') ?? [])].filter(
      (node) => node.textContent === "·",
    );
    expect(dots).toHaveLength(2);
    expect(bar).toHaveTextContent("1 selected·Cancel selected·Clear selection");
  });

  it("a busy Cancel keeps its label beside a static ⟳ (CMP-057's look, D02:345)", () => {
    // jsdom draws no CSS: the rule itself is pinned, whitespace aside
    const css = repoFile("apps/web/src/features/positions/positions.css").replace(/\s+/g, " ");
    const busy = '.cv-orders .cv-button[aria-busy="true"]';
    expect(css).toContain(
      `${busy}:not([data-side]) > :is(.cv-button__label, .cv-button__icon) { opacity: 1; }`,
    );
    expect(css).toContain(`${busy} > .cv-spinner { display: none; }`);
  });
});

describe("a sent cancel outlives the tab (D02 §8.3, never silently dropped; N-M1)", () => {
  it(
    "Esc while a bulk sends, then the Positions tab: every target still goes out live, and its result is said once",
    SCREEN,
    async () => {
      const extra = placed(2, 5); // two more entries on Sub-1: six targets, four in flight at a time
      const held = heldCancels();
      await openOrders({
        body: { orders: [...snapshotBody().orders, ...extra.body.orders] } as OrdersBody,
        orders: [...restOpen(), ...(extra.orders ?? [])],
        cancel: held.cancel,
      });
      const said = heard();
      fireEvent.click(screen.getByRole("button", { name: "Cancel all in view…" }));
      await settle(500);
      await confirmBulk("Cancel 6 orders");
      expect(held.waiting()).toHaveLength(4); // MAX_IN_FLIGHT: two wait their turn
      fireEvent.keyDown(screen.getByRole("alertdialog"), { key: "Escape" });
      await settle(TICK);
      fireEvent.click(screen.getByRole("tab", { name: "Positions" }));
      await settle(TICK);
      expect(screen.queryByRole("group", { name: "Working orders", hidden: true })).toBeNull();
      held.answer(); // the first four answer: the last two go out, the tab gone
      await settle(TICK);
      expect(held.waiting()).toHaveLength(2);
      held.answer();
      await settle(REGION_BUDGET_MS + TICK);
      const ids = ["0e000000-0000-4000-8000-000000000500", "0e000000-0000-4000-8000-000000000501"];
      expect(deletes().sort()).toEqual([TP, ENTRY, ETH, COND, ...ids].sort());
      expect(sent.map((s) => s.live)).toEqual([true, true, true, true, true, true]);
      expect(said().filter((text) => text.startsWith("Cancel results"))).toEqual([
        "Cancel results. Cancelled 1 on Main · LIVE. Cancelled 4 on Sub-1 · LIVE. Cancelled 1 on Sub-2 · LIVE. 1 native-stop order is not included: every position keeps a native stop. 2 orders are not included: they can't be cancelled now.",
      ]);
    },
  );

  it(
    "a row's cancel sent before the tab goes is answered after it, and its toast's words said once",
    SCREEN,
    async () => {
      const held = heldCancels();
      await openOrders({ cancel: held.cancel });
      const said = heard();
      fireEvent.click(cancelOf(ENTRY));
      await settle(TICK);
      expect(held.waiting()).toEqual([ENTRY]);
      fireEvent.click(screen.getByRole("tab", { name: "Positions" }));
      await settle(TICK);
      held.answer();
      await settle(REGION_BUDGET_MS + TICK);
      expect(sent.map((s) => s.live)).toEqual([true]);
      expect(said().filter((text) => text.startsWith("Cancel"))).toEqual([
        "Cancel sent: BTCUSDT Buy 0.15 at 63,950 on Sub-1.",
      ]);
    },
  );

  it(
    "a second bulk confirmed while a closed first still runs: each answer is told (n3)",
    SCREEN,
    async () => {
      const held = heldCancels();
      await openOrders({ cancel: held.cancel });
      const cancelSelected = async (name: string): Promise<void> => {
        fireEvent.click(screen.getByRole("checkbox", { name, hidden: true }));
        await settle(TICK);
        fireEvent.click(screen.getByRole("button", { name: "Cancel selected" }));
        await settle(500);
        await confirmBulk("Cancel 1 order");
      };
      await cancelSelected("Select BTCUSDT Buy 0.15 BTC at 63,950 on Sub-1");
      fireEvent.keyDown(screen.getByRole("alertdialog"), { key: "Escape" }); // it runs on, closed
      await settle(TICK);
      await cancelSelected("Select ETHUSDT Buy 1 ETH at 2,500 on Sub-2");
      held.answer(ETH); // the second answers first: its dialog shows it
      await settle(TICK);
      const result = screen.getByRole("dialog", { name: "Cancel results" });
      expect(
        within(result)
          .getAllByRole("listitem")
          .map((li) => li.textContent),
      ).toEqual(["Cancelled 1 on Sub-2 · LIVE"]);
      held.answer(ENTRY); // then the closed first: its own toast, never dropped
      await settle(TICK);
      expect(onScreen("Cancelled 1 on Sub-1 · LIVE.")).toBeVisible();
      expect(deletes()).toEqual([ENTRY, ETH]);
    },
  );
});

describe("axe and teardown", () => {
  it(
    "no serious or critical axe finding on the tab, then with the bulk dialog open",
    SCREEN,
    async () => {
      await openOrders();
      const tab = screen.getByRole("group", { name: "Working orders" });
      fireEvent.click(screen.getByRole("button", { name: "Cancel all in view…" }));
      await settle(500);
      const dialog = screen.getByRole("alertdialog");
      vi.useRealTimers();
      const serious = async (el: Element): Promise<string[]> =>
        (await axe.run(el, { rules: { "color-contrast": { enabled: false } } })).violations
          .filter((v) => v.impact === "serious" || v.impact === "critical")
          .map((v) => v.id);
      expect(await serious(dialog)).toEqual([]);
      expect(await serious(tab)).toEqual([]);
    },
  );

  it(
    "leaving the tab releases the orders subscription; the positions feed runs on",
    SCREEN,
    async () => {
      await openOrders();
      expect(ws.live("orders")).toHaveLength(1);
      fireEvent.click(screen.getByRole("tab", { name: "Positions" }));
      await settle(TICK);
      expect(ws.live("orders")).toEqual([]);
      expect(ws.live("positions")).toHaveLength(1);
    },
  );

  it(
    "leaving the tab clears a busy row's bound: nothing runs for it after (R2-m1)",
    SCREEN,
    async () => {
      const held = heldCancels();
      await openOrders({ cancel: held.cancel });
      fireEvent.click(cancelOf(ETH));
      await settle(TICK);
      const answered = Date.now();
      held.answer(); // taken, the row still submitted: busy, its bound set
      await settle(TICK);
      expect(cancelOf(ETH)).toHaveAttribute("aria-busy", "true");
      fireEvent.click(screen.getByRole("tab", { name: "Positions" }));
      await settle(TICK);
      expect(screen.queryByRole("group", { name: "Working orders", hidden: true })).toBeNull();
      expect(await timerEndsAt(answered + BUSY_BOUND_MS)).toBe(false);
    },
  );
});
