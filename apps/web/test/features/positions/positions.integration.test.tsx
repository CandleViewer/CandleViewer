/**
 * E29-S01 (#911) integration: the real `PositionsPanel` (SCR-063) with the real `positionsApi` behind
 * a fake `fetch` and fake topic handles (BQ-19: no MSW, no new dependency), read through the
 * accessibility tree. Three accounts, grouping (account, trade group), filter and clear, the empty
 * state, a failed snapshot and Retry, the Viewer, the account states and the locks as far as no B20
 * allows, the kill switch, the deep links and per-user persistence, CSV export, the announcements,
 * and the client half of manager scope (BQ-13: the server refuses a filter naming an account
 * outside the grants, audited; its tests are E29-T07's), run as a manager granted only B.
 */
import { act, configure, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type Mock,
} from "vitest";
import type { generated } from "@candleviewer/protocol";
import { PreferencesProvider } from "../../../src/features/a11y-preferences/PreferencesContext";
import { clearAnnouncements, ShellAnnouncer } from "../../../src/features/app-shell/announcer";
import { positionsApi } from "../../../src/features/positions/api";
import {
  PANEL_STORAGE_KEY,
  resetPanelState,
  updateChips,
} from "../../../src/features/positions/panelState";
import { PositionsPanel } from "../../../src/features/positions/PositionsPanel";
import type { PositionsDeps } from "../../../src/features/positions/PositionsTab";
import {
  COMMIT_INTERVAL_MS,
  SNAPSHOT_BUDGET_MS,
} from "../../../src/features/positions/wsPositions";
import { resetShellState, setShellState, type Me } from "../../../src/shell/bootstrap/store";
import {
  delta,
  fakeClient,
  fakeRaf,
  golden,
  MAIN,
  snap,
  SUB1,
  SUB2,
  type FakeClient,
} from "./support/fakes";

type Positions = generated.ws.Positions;
type SystemUpdate = generated.ws.System;
const TICK = COMMIT_INTERVAL_MS + 16;
const USER = "11111111-2222-4333-8444-555555555555";
const FULL = ["positions:read", "positions:write", "orders:read", "orders:write", "accounts:read"];
const snapshot = golden<Positions>("ws_positions_snapshot.json");

/** `fetch` as the server answers each read: the goldens, and the audited 403 for an account out of scope. */
function fakeFetch(scope: readonly string[] = [MAIN, SUB1, SUB2]) {
  const accounts = golden<{ items: { id: string }[] }>("rest_list_exchange_accounts.json");
  const positions = golden<{ items: { exchange_account_id: string }[] }>(
    "rest_list_positions.json",
  );
  return vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
    const url = new URL(String(input), "http://localhost");
    const json = (status: number, body: unknown): Response =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    if (url.pathname === "/api/v1/exchange-accounts") {
      const items = accounts.items.filter((a) => scope.includes(a.id));
      return json(200, {
        items,
        meta: { next_cursor: null, has_more: false, count: items.length },
      });
    }
    if (url.pathname === "/api/v1/positions") {
      const named = url.searchParams.getAll("exchange_account_ids");
      if (named.some((id) => !scope.includes(id))) {
        return json(403, {
          type: "https://candleviewer.local/errors/account_scope_denied",
          title: "x",
          status: 403,
          code: "account_scope_denied",
        });
      }
      const wanted = named.length > 0 ? named : scope;
      return json(200, {
        items: positions.items.filter((p) => wanted.includes(p.exchange_account_id)),
        aggregates: [],
      });
    }
    return json(404, {});
  });
}

interface OpenOptions {
  readonly role?: "owner" | "manager" | "viewer";
  readonly permissions?: readonly string[];
  readonly scope?: readonly string[];
  readonly grants?: readonly { readonly id: string; readonly mode: "read" | "trade" }[];
  readonly path?: string;
}

let ws: FakeClient;
let saveFile: Mock<(name: string, text: string) => void>;
let fetchMock: ReturnType<typeof fakeFetch>;

/**
 * Each test mounts the whole SCR-063 screen (tabs, toolbar, CMP-114 over CMP-049) in jsdom. Measured on the build
 * host with this file alone, at a load of about 34 on 8 cores: 0.6 to 6.7 s a test; with the feature's other files in
 * parallel workers, at 29 to 40: up to 8.9 s, past Vitest's 5 s default. The ceiling is the one the hotkey editor's
 * screen tests take (`keymap-editor-axe.test.tsx`).
 */
const SCREEN = { timeout: 30_000 };

/** False once the test has ended: a test that timed out stops at its next step, never in the next test's. */
let alive = false;

/** Advances the fake clock, flushing the promises between timers (a REST answer, a re-read). */
async function settle(ms = 0): Promise<void> {
  if (!alive) throw new Error("the test has ended");
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/**
 * A long idle stretch (S-02's budget, a region's 5 s): the timers alone, run in one go. Each await of
 * `settle` costs a real macrotask per timer, and the feed's 10 Hz tick sets two timers per 100 ms.
 */
function idle(ms: number): void {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

/** The panel as R-130 mounts it, for `role`, under the app's preferences and the shell's announcer. */
async function open(o: OpenOptions = {}): Promise<{ unmount: () => void }> {
  const role = o.role ?? "owner";
  const scope = o.scope ?? [MAIN, SUB1, SUB2];
  setShellState({
    me: {
      role,
      permissions: [...(o.permissions ?? FULL)],
      user: { id: USER },
      accounts: (o.grants ?? scope.map((id) => ({ id, mode: "trade" as const }))).map((g) => ({
        exchange_account_id: g.id,
        mode: g.mode,
      })),
    } as Me,
    environment: "live",
  });
  fetchMock = fakeFetch(scope);
  vi.stubGlobal("fetch", fetchMock);
  const deps: PositionsDeps = {
    client: ws.client,
    feed: { api: positionsApi, ...fakeRaf, now: () => Date.now(), performance: null },
    saveFile,
  };
  const router = createMemoryRouter(
    [{ path: "/positions", element: <PositionsPanel deps={deps} /> }],
    { initialEntries: [o.path ?? "/positions"] },
  );
  const view = render(
    <PreferencesProvider>
      <RouterProvider router={router} />
      <ShellAnnouncer />
    </PreferencesProvider>,
  );
  await settle(TICK);
  return { unmount: view.unmount };
}

const grid = (): HTMLElement => screen.getByRole("treegrid", { name: "Positions" });
/** The grid's rows; a position row's name is its `aria-label` (N-02), read without walking every row's content. */
const gridRows = (): HTMLElement[] => within(grid()).getAllByRole("row");
function positionRow(name: string): HTMLElement {
  const row = gridRows().find((r) => r.getAttribute("aria-label") === name);
  if (row === undefined) throw new Error(`no position row named ${name}`);
  return row;
}
const positionNames = (): (string | null)[] =>
  gridRows()
    .filter((r) => r.getAttribute("aria-level") === "2")
    .map((r) => r.getAttribute("aria-label"));
const totalsRow = (): HTMLElement | undefined =>
  gridRows().find((r) => r.dataset["part"] === "TotalsRow");
const groupRow = (label: string): HTMLElement | undefined =>
  gridRows().find(
    (r) =>
      r.dataset["part"] === "GroupHeaderRow" &&
      (within(r).getByRole("rowheader").textContent ?? "").startsWith(label),
  );
const headers = (): string[] =>
  within(grid())
    .getAllByRole("row")
    .filter((r) => r.getAttribute("aria-level") === "1" && r.dataset["part"] === "GroupHeaderRow")
    .map((r) => within(r).getByRole("rowheader").textContent ?? "");
const positionsHandle = () => ws.live("positions")[0];
/** The shell announcer's region (its two are the page's only inert-exempt live regions). */
const region = (politeness: "polite" | "assertive"): string =>
  document.querySelector(`[data-cv-inert-exempt][aria-live="${politeness}"]`)?.textContent ?? "";

/**
 * The first render of the panel's whole tree in a worker compiles each component it reaches: 4.6 s
 * cold at a load of about 34 on the build host, against well under 1 s warm. It is paid here once,
 * inside the default hook timeout, not by whichever test runs first.
 */
beforeAll(async () => {
  // Role queries skip RTL's "is it accessible" walk (a computed style up every ancestor of every
  // element: 2 s for one `getByRole` of this page at that load); a test asserts visibility itself.
  configure({ defaultHidden: true });
  vi.useFakeTimers();
  Element.prototype.scrollIntoView = vi.fn();
  ws = fakeClient();
  saveFile = vi.fn();
  alive = true;
  const warm = await open();
  warm.unmount();
  alive = false;
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

afterAll(() => {
  configure({ defaultHidden: false });
});

beforeEach(() => {
  alive = true;
  vi.useFakeTimers();
  // jsdom lays nothing out: CMP-009 keeps its active option in view through this
  Element.prototype.scrollIntoView = vi.fn();
  ws = fakeClient();
  saveFile = vi.fn();
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

describe("Rows render the whole book: three accounts", () => {
  it(
    "REST paints first, the WS snapshot replaces it; each row's columns; a TOTAL row aggregates",
    SCREEN,
    async () => {
      await open();
      expect(screen.getByRole("heading", { level: 1, name: "Positions and orders" })).toBeVisible();
      expect(headers().map((h) => h.split(" · ").slice(0, 2).join(" · "))).toEqual([
        "Main · LIVE",
        "Sub-1 · LIVE",
        "Sub-2 · LIVE",
      ]);
      expect(positionRow("BTCUSDT · Long · 0.250 BTC · Main")).toBeVisible();
      positionsHandle()?.push(snap(snapshot));
      await settle(TICK);
      const row = positionRow("BTCUSDT · Long · 0.25 BTC · Main");
      // account, symbol, side as text, qty, entry, mark, uPnL, R, rPnL today, liq price, liq dist., lev, margin
      expect(
        within(row)
          .getAllByRole("gridcell")
          .map((c) => c.textContent),
      ).toEqual([
        "Main",
        "▲ Long",
        "0.25 BTC",
        "63,980",
        "64,012",
        expect.stringContaining("+8"),
        expect.stringContaining("+0.32"),
        expect.stringContaining("—"),
        "57,901.9",
        "9.5",
        "10×",
        "Isolated",
      ]);
      expect(within(row).getByRole("rowheader", { name: "BTCUSDT" })).toBeVisible();
      const total = totalsRow();
      expect(within(total ?? grid()).getByRole("rowheader")).toHaveTextContent(
        "LIVE total · 5 open · Exposure",
      );
      expect(gridRows().filter((r) => r.dataset["part"] === "TotalsRow")).toHaveLength(1);
    },
  );

  it(
    "Live update latency: a position event on the WS positions topic updates the row within 200 ms",
    SCREEN,
    async () => {
      await open();
      positionsHandle()?.push(snap(snapshot));
      await settle(TICK);
      positionsHandle()?.push(
        delta(golden<{ case: string; body: Positions }[]>("ws_positions_deltas.json")[0]?.body),
      );
      await settle(TICK); // one 100 ms tick and one 16 ms frame: 116 ms < 200 ms
      const row = positionRow("BTCUSDT · Long · 0.25 BTC · Main");
      expect(within(row).getAllByRole("gridcell")[4]).toHaveTextContent("64,112");
    },
  );
});

describe("Grouping by trade group", () => {
  it("group rows aggregate size and PnL and expand to per-account rows", SCREEN, async () => {
    await open();
    positionsHandle()?.push(snap(golden("ws_positions_contract_fields.json")));
    await settle(TICK);
    const analytics = vi.fn();
    window.addEventListener("cv:analytics", analytics);
    fireEvent.click(screen.getByRole("combobox", { name: "Group by" }));
    fireEvent.click(screen.getByRole("option", { name: "Trade group" }));
    await settle(TICK);
    window.removeEventListener("cv:analytics", analytics);
    expect(headers()[0]).toMatch(/^Trade group …0001 · 2 positions · net 0\.35 BTC · uPnL/);
    expect(groupRow("Trade group …0001")).toHaveAttribute("aria-expanded", "true");
    expect(positionNames().slice(0, 2)).toEqual([
      "BTCUSDT · Long · 0.25 BTC · Main",
      "BTCUSDT · Long · 0.1 BTC · Sub-1",
    ]);
    expect(headers().at(-1)).toMatch(/^No trade group · 3 positions/);
    expect((analytics.mock.calls[0]?.[0] as CustomEvent).detail).toEqual({
      name: "blotter.grouped",
      by: "trade_group",
    });
  });
});

describe("Liquidation proximity is not colour-only", () => {
  it(
    "the row shows the glyph, the word and the distance, its name the tier sentence",
    SCREEN,
    async () => {
      await open();
      positionsHandle()?.push(snap(snapshot));
      await settle(TICK);
      const eth = positionRow("ETHUSDT · Short · 1.5 ETH · Sub-1");
      expect(eth).toHaveTextContent("! Near 1.2");
      expect(eth).toHaveAccessibleDescription(
        "Near liquidation: 27 % of the entry buffer left, 1.2 % from liquidation",
      );
      const sol = positionRow("SOLUSDT · Long · 20 SOL · Sub-2");
      expect(sol).toHaveTextContent("!! Critical 0.5");
      expect(sol).toHaveAccessibleDescription(
        "Critical — near liquidation: 0.5 % from liquidation",
      );
    },
  );

  it(
    "a crossing into Near is said politely once (RT-12), into Critical assertively (RT-05)",
    SCREEN,
    async () => {
      await open();
      positionsHandle()?.push(snap(snapshot));
      await settle(TICK);
      const main = snapshot.positions[0] as Positions["positions"][number];
      // mark falls toward liquidation: a 9.5 % row crosses into Critical within 1 %
      positionsHandle()?.push(
        delta({
          positions: [{ ...main, mark_price: "58400", updated_at_ms: main.updated_at_ms + 10 }],
        }),
      );
      await settle(TICK);
      expect(region("assertive")).toBe(
        "BTCUSDT Long on Main: Critical — near liquidation: 8 % of the entry buffer left, 0.9 % from liquidation",
      );
    },
  );
});

describe("filter and clear", () => {
  it(
    "the account filter narrows to Sub-1's rows and a removable chip; removing it restores the book",
    SCREEN,
    async () => {
      await open();
      positionsHandle()?.push(snap(snapshot));
      await settle(TICK);
      fireEvent.click(screen.getByRole("button", { name: "Filter" }));
      fireEvent.click(screen.getByRole("option", { name: "Sub-1" }));
      await settle(TICK);
      expect(headers().map((h) => h.split(" · ")[0])).toEqual(["Sub-1"]);
      expect(totalsRow()).toHaveTextContent("LIVE total · 2 open");
      const group = screen.getByRole("group", { name: "Active filters" });
      fireEvent.click(within(group).getByRole("button", { name: "Remove filter Account: Sub-1" }));
      await settle(TICK);
      expect(headers()).toHaveLength(3);
    },
  );

  it(
    "chips that leave no row are filter-empty, restated, and Clear filters restores the book",
    SCREEN,
    async () => {
      await open({ path: `/positions?account=${SUB1}` });
      positionsHandle()?.push(snap(snapshot));
      await settle(TICK);
      act(() => updateChips({ type: "add", chip: { kind: "symbol", value: "SOLUSDT" } }));
      await settle(TICK);
      expect(
        screen.getByRole("heading", { level: 2, name: "No rows match 2 filters" }),
      ).toBeVisible();
      expect(screen.getByText("Account: Sub-1 · Symbol: SOLUSDT")).toBeVisible();
      fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
      await settle(TICK);
      expect(headers()).toHaveLength(3);
      expect(screen.queryByRole("group", { name: "Active filters" })?.textContent).toBe("Filter");
    },
  );
});

describe("Empty state", () => {
  it(
    "no open positions: the explicit empty state, title and cause only, and no error",
    SCREEN,
    async () => {
      await open();
      positionsHandle()?.push(snap({ positions: [] } satisfies Positions));
      await settle(TICK);
      expect(screen.getByRole("heading", { level: 2, name: "No open positions" })).toBeVisible();
      expect(screen.getByText("Positions you open on any account appear here.")).toBeVisible();
      expect(screen.queryByRole("alert")).toBeNull();
      expect(
        within(screen.getByRole("tabpanel", { hidden: false })).queryByText(/Could not load/),
      ).toBeNull();
      expect(totalsRow()).toBeUndefined();
    },
  );
});

describe("a failed snapshot (S-02)", () => {
  it(
    "no snapshot within the 5 s budget: Could not load per account, said once; Retry re-subscribes",
    SCREEN,
    async () => {
      await open();
      idle(SNAPSHOT_BUDGET_MS);
      expect(screen.getByText("Could not load Main · LIVE")).toBeVisible();
      expect(screen.getByText("Could not load Sub-2 · LIVE")).toBeVisible();
      expect(region("polite")).toBe(
        "Could not load Main · LIVE Could not load Sub-1 · LIVE Could not load Sub-2 · LIVE",
      );
      fireEvent.click(screen.getByRole("button", { name: "Retry" }));
      positionsHandle()?.push(snap(snapshot));
      await settle(TICK);
      expect(
        within(screen.getByRole("tabpanel", { hidden: false })).queryByText(/Could not load/),
      ).toBeNull();
      expect(positionRow("BTCUSDT · Long · 0.25 BTC · Main")).toBeVisible();
    },
  );
});

describe("the Viewer (S-22)", () => {
  it(
    "one panel-header notice of its two permission lines, in the DOM at mount; every read stays enabled",
    SCREEN,
    async () => {
      await open({
        role: "viewer",
        permissions: ["positions:read", "orders:read", "accounts:read"],
      });
      positionsHandle()?.push(snap(snapshot));
      await settle(TICK);
      const lines = ["Your role can't change positions.", "Your role can't place orders."];
      for (const line of lines) expect(screen.getByText(line)).toHaveAttribute("id");
      expect(positionNames()).toHaveLength(5);
      // a read or a view choice is never T2 (E29-D04 §4.2): nothing in the panel is aria-disabled
      expect(document.querySelectorAll('[aria-disabled="true"]')).toHaveLength(0);
      expect(screen.getByRole("button", { name: "Export CSV" })).toBeEnabled();
      expect(screen.getByRole("button", { name: "Filter" })).toBeEnabled();
    },
  );

  it("an owner with every write sees no read-only notice", SCREEN, async () => {
    await open();
    expect(screen.queryByText("Your role can't place orders.")).toBeNull();
  });
});

const notice = (
  reason: string,
  ids: [string, ...string[]],
  severity: SystemUpdate["severity"] = "warning",
) =>
  ({
    kind: "account_notice",
    severity,
    reason,
    message: "role-neutral",
    exchange_account_ids: ids,
  }) satisfies SystemUpdate;

describe("the account states and the locks (BQ-14; no B20 subscription)", () => {
  it(
    "reconciling: the header's 'checking', one slot line with live off, said politely once",
    SCREEN,
    async () => {
      await open();
      positionsHandle()?.push(snap(snapshot));
      await settle(TICK);
      act(() =>
        setShellState({
          systemByKind: { account_notice: golden("ws_system_account_notice.json") },
        }),
      );
      await settle(TICK);
      expect(groupRow("Sub-1 · LIVE")).toHaveTextContent("checking");
      const slot = screen.getByText(/^Sub-1 · LIVE — Reconciling with the exchange…/);
      expect(slot.closest('[role="status"], [role="alert"]')).toBeNull();
      expect(region("polite")).toBe(
        "Reconciling Sub-1 with Bybit. Closing, cancelling and tightening stops still work.",
      );
    },
  );

  it("desync: 'Verifying' and its line; synced ends it and is said once", SCREEN, async () => {
    await open();
    positionsHandle()?.push(snap(snapshot));
    await settle(TICK);
    act(() =>
      setShellState({ systemByKind: { account_notice: notice("oms.account_desync", [SUB1]) } }),
    );
    await settle(TICK);
    expect(groupRow("Sub-1 · LIVE")).toHaveTextContent("Verifying");
    expect(screen.getByText(/^Sub-1 · LIVE — Position data is being verified/)).toBeVisible();
    act(() =>
      setShellState({
        systemByKind: { account_notice: notice("oms.account_synced", [SUB1], "info") },
      }),
    );
    idle(5_000 + TICK); // the synced line waits out the region's 5 s after the desync one
    expect(screen.queryByText(/Position data is being verified/)).toBeNull();
    expect(region("polite")).toBe("Sub-1 reconciled with Bybit.");
  });

  it(
    "the locked chip as far as no B20 allows: the stale lock and the kill-switch lock on the header",
    SCREEN,
    async () => {
      await open();
      positionsHandle()?.push(snap(snapshot));
      await settle(TICK);
      act(() =>
        setShellState({
          systemByKind: { account_notice: notice("oms.account_stale", [SUB2], "critical") },
        }),
      );
      await settle(TICK);
      expect(groupRow("Sub-2 · LIVE")).toHaveTextContent(/Stale — locked since \d\d:\d\d:\d\d UTC/);
      expect(
        screen.getByText(/^Sub-2 · LIVE is stale — CandleViewer could not reconcile/),
      ).toBeVisible();
      expect(region("assertive")).toBe(
        "Sub-2 is locked for new orders: reconciliation with Bybit failed for 2 minutes. Closing, cancelling and tightening stops still work.",
      );
      // under a kill switch that covers Sub-1, Sub-1's stale notice is the kill-switch lock
      act(() => {
        ws.setState({ killSwitch: { state: "engaged", scope: "global", exchangeAccountIds: [] } });
        setShellState({
          systemByKind: {
            kill_switch: {
              kind: "kill_switch",
              kill_switch: { engaged: true, scope: "global", engaged_at_ms: 1_793_455_331_000 },
            } as SystemUpdate,
            account_notice: notice("oms.account_stale", [SUB1], "critical"),
          },
        });
      });
      await settle(TICK);
      expect(groupRow("Sub-1 · LIVE")).toHaveTextContent("Locked — kill switch");
      expect(
        screen.getByText("Kill switch active — engaged by the owner at 14:02:11 UTC"),
      ).toBeVisible();
      expect(ws.subs.filter((ch) => ch.startsWith("machines."))).toEqual([]);
      expect(screen.queryByText(/daily loss limit/)).toBeNull(); // S-21's chip waits for B20
    },
  );

  it("a Manager sees S-20's two lines under the kill switch", SCREEN, async () => {
    await open({ role: "manager" });
    act(() => {
      ws.setState({ killSwitch: { state: "engaged", scope: "global", exchangeAccountIds: [] } });
    });
    await settle(TICK);
    expect(screen.getByText(/^Kill switch active since — UTC$/)).toBeVisible();
    expect(screen.getByText("Ask the owner to close or release.")).toBeVisible();
  });
});

describe("Manager scope is enforced server-side (the client half; BQ-13)", () => {
  it(
    "a manager granted only B subscribes to B and holds B's rows only; a filter naming A is answered account_scope_denied, with no rows",
    SCREEN,
    async () => {
      await open({ role: "manager", scope: [SUB2], grants: [{ id: SUB2, mode: "trade" }] });
      expect(ws.live("positions")[0]?.spec.opts).toEqual({ exchange_account_ids: [SUB2] });
      expect(headers().map((h) => h.split(" · ")[0])).toEqual(["Sub-2"]);
      fireEvent.click(screen.getByRole("button", { name: "Filter" }));
      expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Sub-2"]);
      fireEvent.keyDown(screen.getByRole("listbox"), { key: "Escape" });
      // the refusal carries no rows (its audit row and the server's own no-rows are E29-T07's tests)
      expect(await positionsApi.listPositions({ accountIds: [MAIN] })).toEqual({
        kind: "account_scope_denied",
      });
      positionsHandle()?.push(
        snap({ positions: snapshot.positions.filter((p) => p.exchange_account_id === SUB2) }),
      );
      await settle(TICK);
      expect(positionNames()).toEqual([
        "BTCUSDT · Long · 0.08 BTC · Sub-2",
        "SOLUSDT · Long · 20 SOL · Sub-2",
      ]);
    },
  );

  it("a crafted deep link naming A shows none of A's rows", SCREEN, async () => {
    await open({
      role: "manager",
      scope: [SUB2],
      grants: [{ id: SUB2, mode: "trade" }],
      path: `/positions?account=${MAIN}`,
    });
    positionsHandle()?.push(
      snap({ positions: snapshot.positions.filter((p) => p.exchange_account_id === SUB2) }),
    );
    await settle(TICK);
    expect(
      screen.getByRole("heading", { level: 2, name: "No rows match 1 filters" }),
    ).toBeVisible();
    expect(positionNames()).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    await settle(TICK);
    expect(positionNames()).toHaveLength(2);
  });

  it(
    "a read-only grant reads its rbac.account_read_only notice once, in that account's header",
    SCREEN,
    async () => {
      await open({
        role: "manager",
        scope: [SUB1, SUB2],
        grants: [
          { id: SUB1, mode: "read" },
          { id: SUB2, mode: "trade" },
        ],
      });
      positionsHandle()?.push(
        snap({ positions: snapshot.positions.filter((p) => p.exchange_account_id !== MAIN) }),
      );
      await settle(TICK);
      const notices = screen.getAllByText("You can view this account, not trade it.");
      expect(notices).toHaveLength(1);
      expect(notices[0]?.closest("tr")).toBe(groupRow("Sub-1 · LIVE"));
      expect(notices[0]).toHaveAttribute("id");
    },
  );
});

describe("deep links and per-user persistence (BQ-16)", () => {
  it("?groupBy=symbol&account= set the view without storing it", SCREEN, async () => {
    await open({ path: `/positions?groupBy=symbol&account=${SUB1}` });
    positionsHandle()?.push(snap(snapshot));
    await settle(TICK);
    expect(screen.getByRole("combobox", { name: "Group by" })).toHaveTextContent("Symbol");
    expect(screen.getByRole("button", { name: "Remove filter Account: Sub-1" })).toBeVisible();
    expect(headers().map((h) => h.split(" · ")[0])).toEqual(["BTCUSDT", "ETHUSDT"]);
    expect(localStorage.getItem(`${PANEL_STORAGE_KEY}:${USER}`)).toBeNull();
  });

  it(
    "a choice is stored for the user and restored on the next mount; the tab too",
    SCREEN,
    async () => {
      const first = await open();
      fireEvent.click(screen.getByRole("combobox", { name: "Group by" }));
      fireEvent.click(screen.getByRole("option", { name: "Symbol" }));
      fireEvent.click(screen.getByRole("tab", { name: "Fills" }));
      await settle(TICK);
      expect(
        screen.getByRole("heading", { level: 2, name: "Fills are not available yet" }),
      ).toBeVisible();
      first.unmount();
      resetPanelState();
      await open();
      expect(screen.getByRole("tab", { name: "Fills", selected: true })).toBeVisible();
      fireEvent.click(screen.getByRole("tab", { name: "Positions" }));
      await settle(TICK);
      expect(screen.getByRole("combobox", { name: "Group by" })).toHaveTextContent("Symbol");
    },
  );
});

describe("the five tabs (BQ-15)", () => {
  it.each([
    [
      "Working orders",
      "Working orders are not available yet",
      "Open orders across accounts will be listed here.",
    ],
    ["Fills", "Fills are not available yet", "Fills across accounts will be listed here."],
    [
      "Trade groups",
      "Trade groups are not available yet",
      "Grouped orders across accounts will be listed here.",
    ],
    ["Algos", "Algos are not available yet", "Running algorithms will be listed here."],
  ])("%s is a placeholder with its title and cause", SCREEN, async (tab, title, cause) => {
    await open();
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual([
      "Positions",
      "Working orders",
      "Fills",
      "Trade groups",
      "Algos",
    ]);
    fireEvent.click(screen.getByRole("tab", { name: tab }));
    await settle(TICK);
    expect(screen.getByRole("heading", { level: 2, name: title })).toBeVisible();
    expect(screen.getByText(cause)).toBeVisible();
  });
});

describe("CSV export (D-21, BQ-17)", () => {
  it(
    "writes the rows in view in the visible column order, sends no request and reports nothing",
    SCREEN,
    async () => {
      await open({ path: `/positions?account=${SUB1}` });
      positionsHandle()?.push(snap(snapshot));
      await settle(TICK);
      const calls = fetchMock.mock.calls.length;
      const analytics = vi.fn();
      window.addEventListener("cv:analytics", analytics);
      fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
      window.removeEventListener("cv:analytics", analytics);
      expect(saveFile).toHaveBeenCalledTimes(1);
      const [name, text] = saveFile.mock.calls[0] as [string, string];
      expect(name).toMatch(/^candleviewer-positions-\d{8}T\d{6}Z\.csv$/);
      const lines = text.split("\r\n");
      expect(lines[0]).toBe(
        "Account,Symbol,Side,Size,Entry (USDT),Mark (USDT),uPnL (USDT),R,rPnL today (USDT),Liq price (USDT),Liq dist. %,Lev,Margin",
      );
      expect(lines.slice(1, -1).map((l) => l.split(",").slice(0, 2).join(","))).toEqual([
        "Sub-1,BTCUSDT",
        "Sub-1,ETHUSDT",
      ]);
      expect(fetchMock.mock.calls.length).toBe(calls); // no audit request, no export endpoint
      expect(analytics).not.toHaveBeenCalled();
    },
  );
});

describe("RT-16: the focused row's changed values", () => {
  it(
    "a sign change of the focused row's uPnL is said politely, through the ambient writer",
    SCREEN,
    async () => {
      await open();
      positionsHandle()?.push(snap(snapshot));
      await settle(TICK);
      const row = positionRow("BTCUSDT · Long · 0.25 BTC · Main");
      act(() => (within(row).getByRole("rowheader") as HTMLElement).focus());
      const main = snapshot.positions[0] as Positions["positions"][number];
      positionsHandle()?.push(
        delta({
          positions: [{ ...main, unrealised_pnl: "-4", updated_at_ms: main.updated_at_ms + 10 }],
        }),
      );
      await settle(TICK); // the tick that applies it; its effect sets the writer's timer as the act ends
      await settle(16); // the writer's timer
      expect(region("polite")).toBe("BTCUSDT Long on Main: uPnL loss 4 USDT, R profit 0.32 R");
    },
  );
});
