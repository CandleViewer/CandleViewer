/**
 * E29-S02 PR3a (#912) P3-BQ-8: a rejection is never lost on a tab switch. The real `PositionsPanel`
 * (SCR-063) with the real orders feed and writes behind a fake `fetch` and fake topic handles: an
 * amend pressed while the Working-orders tab shows, the Positions tab chosen, the venue's `502` and
 * its rejection step arriving meanwhile. The session's feed and amend store run on, the rejection is
 * said once (RT-06), and the tab's return finds it with the same subscription. A press is judged on
 * the session's orders store row, never the caller's object (N1).
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { PreferencesProvider } from "../../../../src/features/a11y-preferences/PreferencesContext";
import {
  clearAnnouncements,
  REGION_BUDGET_MS,
  ShellAnnouncer,
} from "../../../../src/features/app-shell/announcer";
import { positionsApi } from "../../../../src/features/positions/api";
import { ordersApi } from "../../../../src/features/positions/orders/api";
import {
  createAmendStore,
  type AmendStore,
} from "../../../../src/features/positions/orders/amendStore";
import { mapOrder } from "../../../../src/features/positions/orders/model/orderRow";
import { resetPanelState } from "../../../../src/features/positions/panelState";
import { PositionsPanel } from "../../../../src/features/positions/PositionsPanel";
import type { PositionsDeps } from "../../../../src/features/positions/positionsSession";
import { COMMIT_INTERVAL_MS } from "../../../../src/features/positions/wsPositions";
import { resetShellState, setShellState, type Me } from "../../../../src/shell/bootstrap/store";
import { golden as positionsGolden } from "../support/fakes";
import {
  delta,
  deltaBody,
  directory,
  ETH,
  exchangeAccounts,
  fakeClient,
  fakeRaf,
  restOpen,
  snap,
  snapshotBody,
  wsItem,
  type FakeClient,
} from "./support/orders";

const TICK = COMMIT_INTERVAL_MS + 16;
const USER = "11111111-2222-4333-8444-555555555555";
const FULL = ["positions:read", "positions:write", "orders:read", "orders:write", "accounts:read"];
/** A whole SCR-063 mount under the build host's load (`orders.integration.test.tsx`'s bound, doubled). */
const SCREEN = { timeout: 60_000 };

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

let ws: FakeClient;
let patches: { readonly path: string; readonly arm: string | null }[];
let replies: ((res: Response) => void)[];

/** SCR-063's reads, and the amend's PATCH held until the test answers it. */
function serve() {
  const positions = positionsGolden<{ items: unknown[] }>("rest_list_positions.json").items;
  const page = { next_cursor: null, has_more: false };
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname === "/api/v1/exchange-accounts")
      return json(200, { items: exchangeAccounts(), meta: page });
    if (url.pathname === "/api/v1/positions")
      return json(200, { items: positions, aggregates: [] });
    if (url.pathname === "/api/v1/orders") return json(200, { items: restOpen(), meta: page });
    if (init?.method === "PATCH") {
      patches.push({ path: url.pathname, arm: new Headers(init.headers).get("X-Arm-Token") });
      return new Promise<Response>((resolve) => replies.push(resolve));
    }
    return json(404, {});
  });
}

async function settle(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/** Every message the shell's regions take from now on, in order. */
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

/** The panel on R-130, the book read, then the Working-orders tab live; the session's amend store. */
async function openOrders(): Promise<AmendStore> {
  setShellState({
    me: {
      role: "owner",
      permissions: FULL,
      user: { id: USER },
      accounts: exchangeAccounts().map((a) => ({ exchange_account_id: a.id, mode: "trade" })),
    } as Me,
    environment: "live",
  });
  vi.stubGlobal("fetch", serve());
  let made: AmendStore | null = null;
  const clocks = { ...fakeRaf, now: () => Date.now(), performance: null };
  const deps: PositionsDeps = {
    client: ws.client,
    feed: { api: positionsApi, ...clocks },
    orders: {
      feed: { api: ordersApi, ...clocks },
      wall: () => Date.now(),
      arm: { token: () => "arm-token-1" },
      createAmends: (options) => {
        made = createAmendStore(options);
        return made;
      },
    },
  };
  const router = createMemoryRouter(
    [{ path: "/positions", element: <PositionsPanel deps={deps} /> }],
    { initialEntries: ["/positions"] },
  );
  render(
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
  ws.live("orders")[0]?.push(snap(snapshotBody()));
  await settle(TICK);
  if (made === null) throw new Error("the session made no amend store");
  return made;
}

beforeEach(() => {
  vi.useFakeTimers();
  Element.prototype.scrollIntoView = vi.fn();
  ws = fakeClient();
  patches = [];
  replies = [];
  resetPanelState();
  resetShellState();
  clearAnnouncements();
  localStorage.clear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  resetShellState();
  clearAnnouncements();
});

describe("P3-BQ-8: the amends run for the session, not the tab", () => {
  it(
    "a rejection landing while the Positions tab shows is said once and kept for the tab's return",
    SCREEN,
    async () => {
      const amends = await openOrders();
      const handle = ws.live("orders")[0];
      const eth = mapOrder(wsItem(snapshotBody(), ETH), "ws", directory());
      // N1: the caller's object is stale (2,400); the press judges the session store's row (2,500)
      const stale = eth === null ? null : { ...eth, price: "2400" };
      expect(stale === null ? null : amends.press(stale, "price", "2495.00")).toEqual({
        kind: "sent",
        seq: 1,
      });
      await settle(TICK);
      expect(patches).toEqual([{ path: `/api/v1/orders/${ETH}`, arm: "arm-token-1" }]);
      const said = heard();
      fireEvent.click(screen.getByRole("tab", { name: "Positions" }));
      await settle(TICK);
      expect(screen.queryByRole("treegrid", { name: "Working orders", hidden: true })).toBeNull();
      handle?.push(delta(deltaBody("amend_request")));
      await settle(TICK);
      replies[0]?.(json(502, { code: "exchange_error", exchange: { ret_code: 110007 } }));
      await settle(TICK);
      handle?.push(delta(deltaBody("amend_rejected")));
      await settle(REGION_BUDGET_MS + TICK);
      const amendLines = (): string[] => said().filter((text) => text.startsWith("Amend"));
      expect(amendLines()).toEqual([
        "Amend rejected. Your order is unchanged: the price is still 2,500.",
      ]);
      expect(amends.getSnapshot().mutations.get(ETH)).toMatchObject({
        phase: "rejected",
        prior: "2500",
      });
      fireEvent.click(screen.getByRole("tab", { name: "Working orders" }));
      await settle(REGION_BUDGET_MS + TICK);
      expect(ws.live("orders")).toEqual([handle]);
      expect(amends.getSnapshot().mutations.get(ETH)).toMatchObject({
        phase: "rejected",
        said: "rejected",
      });
      expect(amendLines()).toHaveLength(1);
    },
  );

  it(
    "the venue's accept step lands while another tab shows: applied, said once, the row at 2,495 on return",
    SCREEN,
    async () => {
      const amends = await openOrders();
      const handle = ws.live("orders")[0];
      const eth = mapOrder(wsItem(snapshotBody(), ETH), "ws", directory());
      if (eth !== null) amends.press(eth, "price", "2495.00");
      await settle(TICK);
      const said = heard();
      fireEvent.click(screen.getByRole("tab", { name: "Positions" }));
      await settle(TICK);
      handle?.push(delta(deltaBody("amend_request")));
      await settle(TICK);
      replies[0]?.(json(202, { id: ETH, lifecycle_state: "submitted" }));
      await settle(TICK);
      handle?.push(delta(deltaBody("amend_accepted")));
      await settle(REGION_BUDGET_MS + TICK);
      expect(said().filter((text) => text.startsWith("Amend"))).toEqual([
        "Amend confirmed: price 2,495.",
      ]);
      expect(amends.getSnapshot().mutations.has(ETH)).toBe(false);
      fireEvent.click(screen.getByRole("tab", { name: "Working orders" }));
      await settle(TICK);
      const row = document.querySelector<HTMLElement>(`tr[data-key="${ETH}"]`);
      expect(row?.textContent).toContain("2,495");
      expect(row?.textContent).not.toContain("2,500");
    },
  );
});
