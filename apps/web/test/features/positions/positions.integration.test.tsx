/**
 * E29-S01 (#911) integration: the real `PositionsPanel` (SCR-063) with the real `positionsApi` behind
 * a fake `fetch` and fake topic handles (BQ-19: no MSW, no new dependency), read through the
 * accessibility tree. Three accounts, grouping (account, trade group), filter and clear with their
 * results said, the empty state only for a book read, loading while nothing is read and a load's
 * result said once, a failed snapshot and Retry, an account withdrawn and served again, a
 * narrowing's reload left unsaid, the Viewer and the notices under the toolbar, the
 * account states and the locks as far as no B20 allows, a tab switch that keeps them, the kill
 * switch, the deep links and per-user persistence, CSV export, the announcements (StrictMode
 * included), focus never left on `body`, and the client half of manager scope (BQ-13: the server
 * refuses a filter naming an account outside the grants, audited; its tests are E29-T07's), run as a
 * manager granted only B.
 */
import { StrictMode, useLayoutEffect, useRef, type JSX, type ReactNode } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import type { generated } from "@candleviewer/protocol";
import { PreferencesProvider } from "../../../src/features/a11y-preferences/PreferencesContext";
import { clearAnnouncements, ShellAnnouncer } from "../../../src/features/app-shell/announcer";
import { InShellProvider } from "../../../src/features/app-shell/ScreenRoot";
import { positionsApi } from "../../../src/features/positions/api";
import {
  PANEL_STORAGE_KEY,
  resetPanelState,
  updateChips,
} from "../../../src/features/positions/panelState";
import { PositionsPanel } from "../../../src/features/positions/PositionsPanel";
import type { PositionsDeps } from "../../../src/features/positions/positionsSession";
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
  reset,
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

/**
 * `fetch` as the server answers each read: the goldens, and the audited 403 for an account out of scope;
 * with `hangPositions`, `/positions` never answers (no request carries a timeout).
 */
function fakeFetch(scope: readonly string[] = [MAIN, SUB1, SUB2], hangPositions = false) {
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
      if (hangPositions) return new Promise<Response>(() => undefined);
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
  /** Under StrictMode, as `main.tsx` mounts the app (dev: effects run twice on mount). */
  readonly strict?: boolean;
  /** In a `main` holding focus as the panel mounts: the route's focus move, made before a lazy chunk renders. */
  readonly focusedMain?: boolean;
  /** `/positions` never answers; the directory does. */
  readonly hangPositions?: boolean;
}

/**
 * The shell's one `main` (its screens render inside it, `InShellProvider`) as `useRouteFocus` leaves it on a
 * first visit: focused before the panel's effects run.
 */
function FocusedMain({ children }: { readonly children: ReactNode }): JSX.Element {
  const main = useRef<HTMLElement>(null);
  useLayoutEffect(() => main.current?.focus(), []);
  return (
    <main ref={main} tabIndex={-1}>
      <InShellProvider>{children}</InShellProvider>
    </main>
  );
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
  fetchMock = fakeFetch(scope, o.hangPositions === true);
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
  const routed = <RouterProvider router={router} />;
  const tree = (
    <PreferencesProvider>
      {o.focusedMain === true ? <FocusedMain>{routed}</FocusedMain> : routed}
      <ShellAnnouncer />
    </PreferencesProvider>
  );
  const view = render(o.strict === true ? <StrictMode>{tree}</StrictMode> : tree);
  await settle(TICK);
  return { unmount: view.unmount };
}

/**
 * The grid's queries skip RTL's "is it accessible" walk (a computed style up every ancestor of every row: 2 s
 * for one query of this page at a load of about 34, `hidden: true`); a test asserts a row's visibility itself.
 */
const grid = (): HTMLElement => screen.getByRole("treegrid", { name: "Positions", hidden: true });
/** The grid's rows; a position row's name is its `aria-label` (N-02), read without walking every row's content. */
const gridRows = (): HTMLElement[] => within(grid()).getAllByRole("row", { hidden: true });
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
      (within(r).getByRole("rowheader", { hidden: true }).textContent ?? "").startsWith(label),
  );
const headers = (): string[] =>
  gridRows()
    .filter((r) => r.getAttribute("aria-level") === "1" && r.dataset["part"] === "GroupHeaderRow")
    .map((r) => within(r).getByRole("rowheader", { hidden: true }).textContent ?? "");
const positionsHandle = () => ws.live("positions")[0];
/** The shell announcer's region (its two are the page's only inert-exempt live regions). */
const region = (politeness: "polite" | "assertive"): string =>
  document.querySelector(`[data-cv-inert-exempt][aria-live="${politeness}"]`)?.textContent ?? "";
/** The message a region last took: a new message is a new node with the next `data-seq`. */
const regionSeq = (politeness: "polite" | "assertive"): string | null =>
  document
    .querySelector(`[data-cv-inert-exempt][aria-live="${politeness}"] [data-seq]`)
    ?.getAttribute("data-seq") ?? null;
/**
 * The panel's own live regions (E17-D02 §11: it owns none): every one but the shell's two and the atoms' own,
 * CMP-042's refusal status and the toolbar controls' (CMP-009's field message).
 */
const ownRegions = (): Element[] =>
  [...document.querySelectorAll('[aria-live], [role="status"], [role="alert"]')].filter(
    (el) =>
      !el.hasAttribute("data-cv-inert-exempt") &&
      el.closest('.cv-tabs__bar, [data-part="Toolbar"]') === null,
  );

/**
 * The first render of the panel's whole tree in a worker compiles each component it reaches: 4.6 s
 * cold at a load of about 34 on the build host, against well under 1 s warm. It is paid here once,
 * under the screen tests' measured bound (`SCREEN`, past the default hook timeout's 10 s), not by
 * whichever test runs first.
 */
beforeAll(async () => {
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
}, SCREEN.timeout);

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
    "REST paints first, the WS snapshot replaces it in the same decimal form; each row's columns; a TOTAL row aggregates",
    SCREEN,
    async () => {
      await open();
      expect(screen.getByRole("heading", { level: 1, name: "Positions and orders" })).toBeVisible();
      // focus was not on the shell's main as the panel mounted: the panel leaves it where it is
      expect(document.activeElement).toBe(document.body);
      expect(headers().map((h) => h.split(" · ").slice(0, 2).join(" · "))).toEqual([
        "Main · LIVE",
        "Sub-1 · LIVE",
        "Sub-2 · LIVE",
      ]);
      // REST sends "0.250" and "63980.0": the row reads as the snapshot's will, so its name never changes
      const first = positionRow("BTCUSDT · Long · 0.25 BTC · Main");
      expect(first).toBeVisible();
      expect(within(first).getAllByRole("gridcell", { hidden: true })[3]?.textContent).toBe(
        "63,980",
      );
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
    "the account filter narrows to Sub-1's rows and a removable chip, each result said politely once; removing it restores the book",
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
      // D04 §2.6, D05 §8.1 (WCAG 4.1.3): the filtered result, in CMP-049's words, through the shell's region
      expect(region("polite")).toBe("2 rows");
      const group = screen.getByRole("group", { name: "Active filters" });
      fireEvent.click(within(group).getByRole("button", { name: "Remove filter Account: Sub-1" }));
      await settle(TICK);
      expect(headers()).toHaveLength(3);
      expect(region("polite")).toBe("2 rows"); // the region's 5 s budget: the next result waits
      idle(5_000);
      expect(region("polite")).toBe("5 rows");
    },
  );

  it(
    "a picker change that leaves no row is filter-empty, restated and said; Clear filters restores the book, says it and keeps focus off body",
    SCREEN,
    async () => {
      await open();
      positionsHandle()?.push(snap(snapshot));
      await settle(TICK);
      // a stored Symbol chip (no chooser is drawn for it yet), then an Account chosen in the picker
      act(() => updateChips({ type: "add", chip: { kind: "symbol", value: "SOLUSDT" } }));
      await settle(TICK);
      expect(region("polite")).toBe(""); // a change the user did not make is not said
      fireEvent.click(screen.getByRole("button", { name: "Filter" }));
      fireEvent.click(screen.getByRole("option", { name: "Sub-1" }));
      fireEvent.keyDown(screen.getByRole("listbox"), { key: "Escape" });
      await settle(TICK);
      expect(
        screen.getByRole("heading", { level: 2, name: "No rows match 2 filters" }),
      ).toBeVisible();
      expect(screen.getByText("Symbol: SOLUSDT · Account: Sub-1")).toBeVisible();
      expect(region("polite")).toBe("No rows match 2 filters");
      const clear = screen.getByRole("button", { name: "Clear filters" });
      act(() => clear.focus());
      fireEvent.click(clear);
      await settle(TICK);
      expect(headers()).toHaveLength(3);
      expect(screen.queryByRole("group", { name: "Active filters" })?.textContent).toBe("Filter");
      // the button left with the state: focus is on "+ Filter", as CMP-055's Clear all leaves it
      expect(document.activeElement).toBe(screen.getByRole("button", { name: "Filter" }));
      idle(5_000);
      expect(region("polite")).toBe("5 rows");
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

  it(
    "offline with nothing read: loading and busy, never 'No open positions' (S-03 needs a book read empty)",
    SCREEN,
    async () => {
      ws.setLink({ kind: "offline", cause: "offline" });
      await open({ hangPositions: true });
      expect(screen.queryByRole("heading", { name: "No open positions", hidden: true })).toBeNull();
      expect(screen.getByText("Loading Main · LIVE…")).toBeVisible();
      const groups = document.querySelectorAll('[data-part="Loading"] [role="group"]');
      expect([...groups].map((g) => g.getAttribute("aria-busy"))).toEqual(["true", "true", "true"]);
      // the loading lines own no live region: the panel says them once, through the shell's
      expect(ownRegions()).toEqual([]);
      expect(region("polite")).toBe(
        "Loading Main · LIVE… Loading Sub-1 · LIVE… Loading Sub-2 · LIVE…",
      );
    },
  );
});

describe("a load's result (D04:273, D05:285, `15`:530; CMP-049 mounts with the rows, silent)", () => {
  it.each([
    ["the rows in view in CMP-049's words", snapshot, "5 rows"],
    [
      "S-03's title for a book read empty",
      { positions: [] } satisfies Positions,
      "No open positions",
    ],
  ])(
    "PR1: a first load's lines, then once the book is read its result, said once: %s",
    SCREEN,
    async (_case, book, result) => {
      await open({ hangPositions: true });
      expect(region("polite")).toBe(
        "Loading Main · LIVE… Loading Sub-1 · LIVE… Loading Sub-2 · LIVE…",
      );
      positionsHandle()?.push(snap(book));
      await settle(TICK);
      idle(5_000); // the region's budget after the loading lines
      expect(region("polite")).toBe(result);
      const said = regionSeq("polite");
      idle(10_000);
      expect(regionSeq("polite")).toBe(said); // once per load
    },
  );
});

describe("a failed snapshot (S-02)", () => {
  it(
    "no snapshot within the 5 s budget: Could not load per account, said once, no row of them; Retry re-subscribes, focus kept",
    SCREEN,
    async () => {
      await open();
      idle(SNAPSHOT_BUDGET_MS);
      expect(screen.getByText("Could not load Main · LIVE")).toBeVisible();
      expect(screen.getByText("Could not load Sub-2 · LIVE")).toBeVisible();
      expect(region("polite")).toBe(
        "Could not load Main · LIVE Could not load Sub-1 · LIVE Could not load Sub-2 · LIVE",
      );
      // D02:333, :389: a failed account shows no row, whatever the first-paint read painted
      expect(screen.queryByRole("treegrid", { hidden: true })).toBeNull();
      expect(screen.queryByText(/LIVE total/)).toBeNull();
      const before = positionsHandle();
      const retry = screen.getByRole("button", { name: "Retry" });
      act(() => retry.focus());
      fireEvent.click(retry);
      await settle(TICK);
      // before any snapshot: the failure is gone, a fresh subscription waits, and focus stayed in the tab
      const panel = screen.getByRole("tabpanel", { hidden: false });
      expect(within(panel).queryByText(/Could not load/)).toBeNull();
      expect(before?.released).toBe(true);
      expect(positionsHandle()).not.toBe(before);
      // the tab's root, named by its tab: focus never lands on an unnamed node
      expect(document.activeElement).toBe(within(panel).getByRole("group", { name: "Positions" }));
      expect(document.activeElement).toBe(panel.querySelector('[data-part="PositionsTab"]'));
      positionsHandle()?.push(snap(snapshot));
      await settle(TICK);
      expect(positionRow("BTCUSDT · Long · 0.25 BTC · Main")).toBeVisible();
    },
  );
});

describe("an account withdrawn (S-08)", () => {
  const withdrawnLines = [
    "No longer shown — access to Main was withdrawn.",
    "No longer shown — access to Sub-1 was withdrawn.",
    "No longer shown — access to Sub-2 was withdrawn.",
  ];

  it(
    "a revoke: each account's line where its rows were, not live, not dismissible, said once in one message, Retry with them",
    SCREEN,
    async () => {
      await open();
      positionsHandle()?.push(snap(snapshot));
      await settle(TICK);
      positionsHandle()?.push(reset("revoked"));
      await settle(TICK);
      for (const line of withdrawnLines) expect(screen.getByText(line)).toBeVisible();
      expect(screen.queryByRole("treegrid", { hidden: true })).toBeNull();
      expect(screen.queryByRole("button", { name: /Dismiss/ })).toBeNull();
      expect(ownRegions()).toEqual([]);
      expect(region("polite")).toBe(withdrawnLines.join(" "));
      expect(screen.getByRole("button", { name: "Retry" })).toBeVisible();
    },
  );

  it(
    "F-02: the focused row's account narrowed away, focus goes to its line, never body, and RT-15 leaves the line to the focus move",
    SCREEN,
    async () => {
      await open();
      positionsHandle()?.push(snap(snapshot));
      await settle(TICK);
      const sol = positionRow("SOLUSDT · Long · 20 SOL · Sub-2");
      act(() => (within(sol).getByRole("rowheader", { hidden: true }) as HTMLElement).focus());
      // the directory now lists Main and Sub-1; the narrowing drops every row until it says who left
      vi.stubGlobal("fetch", fakeFetch([MAIN, SUB1]));
      positionsHandle()?.push(reset("narrowed"));
      await settle(TICK);
      await settle(TICK);
      expect(document.activeElement).toBe(screen.getByText(withdrawnLines[2] as string));
      idle(10_000); // past every region's budget: a queued line would have been written by now
      expect(region("polite")).not.toContain("No longer shown");
      positionsHandle()?.push(
        snap({ positions: snapshot.positions.filter((p) => p.exchange_account_id !== SUB2) }),
      );
      await settle(TICK);
      expect(headers().map((h) => h.split(" · ")[0])).toEqual(["Main", "Sub-1"]);
      expect(screen.getByText(withdrawnLines[2] as string)).toBeVisible();
    },
  );

  it(
    "S08: a revoke, Retry, a sub_ok naming all three and a snap with no Sub-2 position: every line goes, Sub-2's too",
    SCREEN,
    async () => {
      await open();
      positionsHandle()?.push(snap(snapshot));
      await settle(TICK);
      positionsHandle()?.push(reset("revoked"));
      await settle(TICK);
      expect(screen.getByText(withdrawnLines[2] as string)).toBeVisible();
      fireEvent.click(screen.getByRole("button", { name: "Retry" }));
      await settle(TICK);
      // the Retry's own subscription: its sub_ok names the three, and Sub-2 has no position open
      positionsHandle()?.setEffective({ exchange_account_ids: [MAIN, SUB1, SUB2] });
      positionsHandle()?.push(
        snap({ positions: snapshot.positions.filter((p) => p.exchange_account_id !== SUB2) }),
      );
      await settle(TICK);
      expect(headers().map((h) => h.split(" · ")[0])).toEqual(["Main", "Sub-1"]);
      for (const line of withdrawnLines) expect(screen.queryByText(line)).toBeNull();
    },
  );

  it(
    "PN: a narrowing's reload says no loading line naming the account it withdraws; its F-02 line is said once",
    SCREEN,
    async () => {
      await open();
      positionsHandle()?.push(snap(snapshot));
      await settle(TICK);
      vi.stubGlobal("fetch", fakeFetch([MAIN, SUB1]));
      positionsHandle()?.push(reset("narrowed"));
      await settle(TICK);
      await settle(TICK);
      // written at once: no loading line went first to start the region's budget
      expect(region("polite")).toBe(withdrawnLines[2]);
      const said = regionSeq("polite");
      positionsHandle()?.push(
        snap({ positions: snapshot.positions.filter((p) => p.exchange_account_id !== SUB2) }),
      );
      await settle(TICK);
      idle(10_000); // past every region's budget: the reload's result is not said either
      expect(regionSeq("polite")).toBe(said);
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
      // each line's id is keyed by its permission, so a gated control's pointer survives a grant
      expect(screen.getByText(lines[0] as string).id).toMatch(/-positions-write$/);
      expect(screen.getByText(lines[1] as string).id).toMatch(/-orders-write$/);
      // boards 16 and 17: the notice sits in the band under the toolbar, led by CMP-019's lock
      const notice = screen.getByText(lines[0] as string).closest('[data-part="ReadOnlyNotice"]');
      const toolbar = document.querySelector('[data-part="Toolbar"]');
      expect(
        (toolbar?.compareDocumentPosition(notice as Node) ?? 0) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
      expect(notice?.querySelector(".cv-positions__lock svg")).not.toBeNull();
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
  /** The glyph leading a slot line (D03 §4.1's "Tone, glyph"; §4.4's lock). */
  const glyphOf = (line: Element): string | null | undefined =>
    line
      .closest('[data-cmp="CMP-028"]')
      ?.querySelector(".cv-callout__glyph svg")
      ?.getAttribute("data-icon");

  it(
    "reconciling, seeded at mount under StrictMode: the header's 'checking', one slot line with live off, said once by the account's label",
    SCREEN,
    async () => {
      // the shell's last notice is in before the panel mounts; the directory names Sub-1 only later
      setShellState({ systemByKind: { account_notice: golden("ws_system_account_notice.json") } });
      await open({ strict: true });
      positionsHandle()?.push(snap(snapshot));
      await settle(TICK);
      expect(groupRow("Sub-1 · LIVE")).toHaveTextContent("checking");
      const slot = screen.getByText(/^Sub-1 · LIVE — Reconciling with the exchange…/);
      expect(slot.closest('[role="status"], [role="alert"]')).toBeNull();
      expect(glyphOf(slot)).toBe("refresh");
      // held until its label is known (never "…0002"), and heard although StrictMode remounted the panel
      expect(region("polite")).toBe(
        "Reconciling Sub-1 with Bybit. Closing, cancelling and tightening stops still work.",
      );
      expect(ownRegions()).toEqual([]);
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
    "the locked chip as far as no B20 allows: the stale lock with no cause for any role, and the kill-switch lock, each on its header and said",
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
      // no client reads B19, so even the Owner reads and hears the lock with its cause withheld (D03 §4.1)
      const lockLine = screen.getByText(
        "Sub-2 · LIVE is stale — new orders are locked until the owner resolves it; closing, cancelling and tightening stops still work.",
      );
      expect(lockLine).toBeVisible();
      expect(glyphOf(lockLine)).toBe("lock");
      expect(screen.queryByText(/could not reconcile/)).toBeNull();
      expect(region("assertive")).toBe(
        "Sub-2 is locked for new orders until the owner resolves it. Closing, cancelling and tightening stops still work.",
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
      // RT-07: the kill-switch lock is said too, assertively, after the region's 5 s budget
      idle(5_000);
      expect(region("assertive")).toBe(
        "Sub-1 is still locked for new orders after the kill switch. Closing, cancelling and tightening stops still work.",
      );
      expect(ws.subs.filter((ch) => ch.startsWith("machines."))).toEqual([]);
      expect(screen.queryByText(/daily loss limit/)).toBeNull(); // S-21's chip waits for B20
    },
  );

  it(
    "a Manager sees S-20's two lines under the kill switch, in the band under the toolbar",
    SCREEN,
    async () => {
      await open({ role: "manager" });
      act(() => {
        ws.setState({ killSwitch: { state: "engaged", scope: "global", exchangeAccountIds: [] } });
      });
      await settle(TICK);
      expect(screen.getByText(/^Kill switch active since — UTC$/)).toBeVisible();
      expect(screen.getByText("Ask the owner to close or release.")).toBeVisible();
      // board 16: tab strip, toolbar, then the band, then the grid
      const band = document.querySelector('[data-part="KillSwitchBanner"]');
      const toolbar = document.querySelector('[data-part="Toolbar"]');
      expect(
        (toolbar?.compareDocumentPosition(band as Node) ?? 0) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
      expect(
        (band?.compareDocumentPosition(grid()) ?? 0) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    },
  );
});

describe("a tab switch (CMP-042 mounts the selected tab only; the panel owns the feed)", () => {
  const sizeHeader = (): HTMLElement | undefined =>
    within(grid())
      .getAllByRole("columnheader", { hidden: true })
      .find((h) => (h.textContent ?? "").startsWith("Size"));

  it(
    "keeps the book, the sort, every account state and its since; re-reads nothing and says nothing again",
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
      // the shell keeps one notice, its last: Sub-1's now, Sub-2's no longer
      act(() =>
        setShellState({
          systemByKind: { account_notice: notice("oms.account_resyncing", [SUB1], "info") },
        }),
      );
      await settle(TICK);
      const since = /Stale — locked since (\d\d:\d\d:\d\d) UTC/.exec(
        groupRow("Sub-2 · LIVE")?.textContent ?? "",
      )?.[1];
      expect(since).toBeDefined();
      fireEvent.click(sizeHeader()?.querySelector("button") as HTMLElement);
      await settle(TICK);
      const sorted = sizeHeader()?.getAttribute("aria-sort");
      expect(sorted).not.toBe("none");
      idle(10 * 60_000); // ten minutes on: a "since" taken again would read the return's time
      const said = { polite: regionSeq("polite"), assertive: regionSeq("assertive") };
      const handle = positionsHandle();
      const reads = fetchMock.mock.calls.length;
      const subs = ws.subs.length;
      fireEvent.click(screen.getByRole("tab", { name: "Fills" }));
      await settle(TICK);
      expect(ws.live("positions")).toEqual([handle]); // the feed runs while another tab shows
      fireEvent.click(screen.getByRole("tab", { name: "Positions" }));
      await settle(TICK);
      expect(groupRow("Sub-2 · LIVE")).toHaveTextContent(
        `Stale — locked since ${String(since)} UTC`,
      );
      expect(groupRow("Sub-1 · LIVE")).toHaveTextContent("checking");
      expect(screen.getByText(/^Sub-2 · LIVE is stale — new orders are locked/)).toBeVisible();
      expect(sizeHeader()?.getAttribute("aria-sort")).toBe(sorted);
      expect(positionRow("BTCUSDT · Long · 0.25 BTC · Main")).toBeVisible();
      expect({ polite: regionSeq("polite"), assertive: regionSeq("assertive") }).toEqual(said);
      expect(positionsHandle()).toBe(handle);
      expect(fetchMock.mock.calls.length).toBe(reads);
      expect(ws.subs.length).toBe(subs);
    },
  );
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
    // one chip: the singular, PROPOSED as `blotter.ui.filter_empty#2` (the deck's plural reads "1 filters")
    expect(screen.getByRole("heading", { level: 2, name: "No rows match 1 filter" })).toBeVisible();
    expect(positionNames()).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    await settle(TICK);
    expect(positionNames()).toHaveLength(2);
    expect(region("polite")).toBe("2 rows");
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

describe("the stored tab mounts alone", () => {
  it(
    "the tabs wait for the user's view, so a stored Fills never mounts the Positions tab first",
    SCREEN,
    async () => {
      localStorage.setItem(
        `${PANEL_STORAGE_KEY}:${USER}`,
        JSON.stringify({ v: 1, tab: "fills", groupBy: "account", chips: [], columns: {} }),
      );
      const added: Node[] = [];
      const observer = new MutationObserver((records) => {
        for (const record of records) added.push(...record.addedNodes);
      });
      observer.observe(document.body, { childList: true, subtree: true });
      await open();
      for (const record of observer.takeRecords()) added.push(...record.addedNodes);
      observer.disconnect();
      expect(screen.getByRole("tab", { name: "Fills", selected: true })).toBeVisible();
      const positionsTab = (n: Node): boolean =>
        n instanceof Element &&
        (n.matches('[data-part="PositionsTab"]') ||
          n.querySelector('[data-part="PositionsTab"]') !== null);
      expect(added.filter(positionsTab)).toEqual([]);
    },
  );
});

describe("focus and teardown", () => {
  it(
    "the first visit: focus the route left on the shell's main, before the lazy chunk rendered, goes to the h1",
    SCREEN,
    async () => {
      await open({ focusedMain: true });
      expect(document.activeElement).toBe(
        screen.getByRole("heading", { level: 1, name: "Positions and orders" }),
      );
    },
  );

  it("unmounting the panel releases the feed's subscriptions", SCREEN, async () => {
    const view = await open();
    expect(ws.live("positions")).toHaveLength(1);
    expect(ws.live("wallet")).toHaveLength(1);
    view.unmount();
    expect(ws.live("positions")).toEqual([]);
    expect(ws.live("wallet")).toEqual([]);
  });
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
