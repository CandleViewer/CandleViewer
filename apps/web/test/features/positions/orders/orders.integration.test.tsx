/**
 * E29-S02 PR2 (#912) integration: the real `PositionsPanel` (SCR-063) on its Working-orders tab, with
 * the real `ordersApi`, `ordersWrites` and `positionsApi` behind a fake `fetch` and fake topic
 * handles (#911 BQ-19: no MSW, no new dependency), read through the accessibility tree. The rows,
 * the sections, a row's Cancel (sent once, no arm token, a toast), the lost race (BQ-3), the native
 * stop's T2 Cancel and the proof that no stop row is ever sent (C-2.6), Cancel-all partial failure on
 * 3 of 5 accounts with Retry failed, Cancel selected, the Viewer's notice, the kill switch's
 * carve-out, focus never on `body`, axe, and teardown.
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
import { ordersApi } from "../../../../src/features/positions/orders/api";
import { LINGER_MS } from "../../../../src/features/positions/orders/ordersStore";
import { resetPanelState } from "../../../../src/features/positions/panelState";
import { PositionsPanel } from "../../../../src/features/positions/PositionsPanel";
import type { PositionsDeps } from "../../../../src/features/positions/positionsSession";
import { COMMIT_INTERVAL_MS } from "../../../../src/features/positions/wsPositions";
import { resetShellState, setShellState, type Me } from "../../../../src/shell/bootstrap/store";
import { THEME_ANALYTICS_EVENT } from "../../../../src/shell/bootstrap/themeStore";
import { golden as positionsGolden } from "../support/fakes";
import {
  delta,
  deltaBody,
  ENTRY,
  exchangeAccounts,
  fakeClient,
  fakeRaf,
  golden,
  MAIN,
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
}

interface Served {
  readonly accounts?: readonly ExchangeAccount[];
  readonly orders?: readonly unknown[];
  readonly cancel?: (id: string) => Response;
  readonly cancelAll?: (body: unknown, n: number) => Response;
}

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

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
      return (
        o.cancelAll?.(JSON.parse(String(init?.body)), cancelAlls) ?? json(200, { results: [] })
      );
    }
    const id = /^\/api\/v1\/orders\/([0-9a-f-]{36})$/.exec(url.pathname)?.[1];
    if (id !== undefined && method === "DELETE")
      return o.cancel?.(id) ?? json(202, { id, lifecycle_state: "cancel_pending" });
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
        mode: "trade",
      })),
    } as Me,
    environment: "live",
  });
  vi.stubGlobal("fetch", serve(o));
  const clocks = { ...fakeRaf, now: () => Date.now(), performance: null };
  const deps: PositionsDeps = {
    client: ws.client,
    feed: { api: positionsApi, ...clocks },
    orders: { feed: { api: ordersApi, ...clocks }, wall: () => Date.now() },
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
  ws.live("positions")[0]?.push(snap(positionsGolden("ws_positions_snapshot.json")));
  await settle(TICK);
  fireEvent.click(screen.getByRole("tab", { name: "Working orders" }));
  await settle(TICK);
  ws.live("orders")[0]?.push(snap(o.body ?? snapshotBody()));
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

/** A frame for one order: the snapshot's item with `patch` and a later stamp. */
const moved = (id: string, patch: Record<string, unknown>, at: number): OrdersBody =>
  ({ orders: [{ ...wsItem(snapshotBody(), id), ...patch, updated_at_ms: at }] }) as OrdersBody;

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
      fireEvent.click(cancelOf(TP));
      await settle(TICK);
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
      fireEvent.click(cancelOf(TP));
      await settle(TICK);
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
});

describe("Cancel-all partial failure", () => {
  /** Five accounts, one placed entry each: Cancel all in view is one cancelAllOrders. */
  const five = (): Served & { body: OrdersBody } => {
    const base = exchangeAccounts()[0];
    if (base === undefined) throw new Error("no account golden");
    const accounts = [
      ...exchangeAccounts(),
      { ...base, id: SUB3, label: "Sub-3" },
      { ...base, id: SUB4, label: "Sub-4" },
    ];
    const ids = [MAIN, SUB1, SUB2, SUB3, SUB4];
    const entry = wsItem(snapshotBody(), ENTRY);
    const rest = restOpen().find((r) => r.id === ENTRY);
    const id = (i: number) => `0e000000-0000-4000-8000-0000000002${String(i).padStart(2, "0")}`;
    return {
      accounts,
      body: {
        orders: ids.map((a, i) => ({ ...entry, id: id(i), exchange_account_id: a })),
      } as OrdersBody,
      orders: ids.map((a, i) => ({ ...rest, id: id(i), exchange_account_id: a })),
    };
  };

  it(
    "3 of 5 accounts: a per-account list with each failing account's reason; Retry failed names those alone",
    SCREEN,
    async () => {
      const answer = golden("rest_cancel_all_partial.json");
      await openOrders({
        ...five(),
        cancelAll: (_, n) =>
          n === 1
            ? json(200, answer)
            : json(200, {
                results: [SUB2, SUB4].map((a) => ({
                  exchange_account_id: a,
                  ok: true,
                  affected: 1,
                  error: null,
                })),
                requested: 2,
                succeeded: 2,
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
        "Sub-2 · LIVE: Bybit did not answer — nothing cancelled",
        "Cancelled 3 on Sub-3 · LIVE",
        "Sub-4 · LIVE: cancelled 1, then Bybit stopped answering — the rest are still open",
      ]);
      expect(result).not.toHaveTextContent(/connectivity|deadline/i);
      expect(document.activeElement).toBe(within(result).getByRole("button", { name: "Close" }));
      fireEvent.click(within(result).getByRole("button", { name: "Retry failed" }));
      await settle(TICK);
      expect(sent).toHaveLength(2);
      expect(sent[1]?.body).toMatchObject({ exchange_account_ids: [SUB2, SUB4] });
      expect(seen.map((e) => [e["retry"], e["orders"], e["accounts"]])).toEqual([
        [false, 5, 5],
        [true, 2, 2],
      ]);
      expect(sent[1]?.key).not.toBe(sent[0]?.key); // a new request, a new key (BQ-8)
      expect(
        within(screen.getByRole("dialog", { name: "Cancel results" }))
          .getAllByRole("listitem")
          .map((li) => li.textContent),
      ).toEqual(["Cancelled 1 on Sub-2 · LIVE", "Cancelled 1 on Sub-4 · LIVE"]);
      fireEvent.click(screen.getByRole("button", { name: "Close" }));
      await settle(TICK);
      expect(document.activeElement).toBe(opener);
    },
  );
});

describe("Cancel selected (D02 §8.3, D-3)", () => {
  it("the selection bar counts and says it; one cancelOrder per selected row", SCREEN, async () => {
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
    fireEvent.click(within(dialog).getByRole("button", { name: "Keep orders" }));
    await settle(TICK);
    expect(sent).toEqual([]);
  });
});

describe("T2 and the carve-out (D02 §10.3–§10.4)", () => {
  it(
    "a Viewer's Cancel and bulk buttons point at the panel's one orders:write line",
    SCREEN,
    async () => {
      await openOrders({ permissions: ["positions:read", "orders:read", "accounts:read"] });
      for (const button of [
        cancelOf(ENTRY),
        screen.getByRole("button", { name: /Cancel all in view/ }),
      ]) {
        expect(button).toHaveAttribute("aria-disabled", "true");
        expect(button).toHaveAccessibleDescription("Your role can't place orders.");
      }
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

describe("axe and teardown", () => {
  it("no serious or critical axe finding on the tab, the dialog open or not", SCREEN, async () => {
    await openOrders();
    const tab = screen.getByRole("group", { name: "Working orders" });
    vi.useRealTimers();
    const serious = async (el: Element): Promise<string[]> =>
      (await axe.run(el, { rules: { "color-contrast": { enabled: false } } })).violations
        .filter((v) => v.impact === "serious" || v.impact === "critical")
        .map((v) => v.id);
    expect(await serious(tab)).toEqual([]);
  });

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
});
