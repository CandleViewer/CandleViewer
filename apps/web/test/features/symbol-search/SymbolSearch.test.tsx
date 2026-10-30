/**
 * E08-S09 PRs C1 and C2: SCR-102 in the shell (E08-D05 §6, §8, §9.2, §12.1, D-10, D-11), on a fake instrument index;
 * its symbol checks and lookups on a faked `apiFetch` (no network). The TopBar draws its trigger only once a workspace
 * has bound a pane: until then it is absent, with no placeholder.
 */
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { clearAnnouncements } from "../../../src/features/app-shell/announcer";
import type { IndexSnapshot } from "../../../src/features/symbol-search/instrumentIndex";
import { toEntry, type Instrument } from "../../../src/features/symbol-search/ranking";
import {
  getSymbolSearchState,
  openSymbolSearch,
  rememberSymbol,
  resetSymbolSearch,
  setSymbolInfo,
  setSymbolOpener,
  startSymbolSearch,
  type SymbolOpener,
  type SymbolTarget,
} from "../../../src/features/symbol-search/searchSession";
import { visibleRows } from "../../../src/features/symbol-search/SymbolSearch";
import { KeymapHost } from "../../../src/keymap/KeymapHost";
import { getBindings, resetBindings, setBindings } from "../../../src/keymap/profile";
import { resetMeClaims, setMeClaims } from "../../../src/lib/auth/meCache";
import { buildRoutes } from "../../../src/routes/tree";
import { resetShellState, setShellState, type Me } from "../../../src/shell/bootstrap/store";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const ME = { role: "owner", permissions: [], user: { username: "robin" } } as unknown as Me;
const CHART_1: SymbolTarget = {
  pane: "Chart 1",
  symbol: "BTCUSDT",
  interval: "1m",
  intervalWords: "1 minute",
  armed: false,
};
const entry = (symbol: string, status: NonNullable<Instrument["status"]> = "Trading") =>
  toEntry({ symbol, category: "linear", status, tick_size: "0.1", qty_step: "1" });
const listed = (...symbols: string[]) => symbols.map((symbol) => entry(symbol));
const READY: IndexSnapshot = {
  phase: "ready",
  entries: listed("BTCUSDT", "ETHUSDT", "ETHFIUSDT"),
  known: [],
  unlisted: [],
  loadedAt: 0,
  cacheAgeS: 0,
  staleSince: null,
  refreshing: false,
  retryAt: null,
  failure: null,
};
/** The fake clock's start: the 503 ladder's waits count from a snapshot's arrival. */
const T0 = Date.UTC(2026, 9, 30, 12);
/** CMP-043's reflow breakpoint (`dialog.css`, AppShell): 200 % zoom on the 1280 x 800 frame. */
const REFLOW = "(max-width: 40rem), (max-height: 25rem)";
/** A test that runs axe over the shell: jsdom's axe takes seconds on a loaded runner. */
const AXE_MS = 15_000;

let stop = (): void => undefined;
/**
 * The shell at /journal with SCR-102's runtime on a fake index; `put` moves the index on. `target` is the opener's
 * pane: `null` binds an opener with none, `undefined` binds no opener at all.
 */
async function shell(target: SymbolTarget | null | undefined, first: Partial<IndexSnapshot> = {}) {
  let snap = { ...READY, ...first };
  const told = new Set<() => void>();
  const index = {
    subscribe: (fn: () => void) => (told.add(fn), () => void told.delete(fn)),
    getSnapshot: () => snap,
    ...{ start: vi.fn(), stop: vi.fn(), reread: vi.fn(), learn: vi.fn() },
  };
  stop = startSymbolSearch(index);
  const open = vi.fn();
  if (target !== undefined) setSymbolOpener({ target, open });
  setMeClaims({ authenticated: true, role: "owner", permissions: [] });
  setShellState({ environment: "demo", me: ME });
  const router = createMemoryRouter(buildRoutes(), { initialEntries: ["/journal"] });
  render(
    <>
      <RouterProvider router={router} />
      <KeymapHost />
    </>,
  );
  await screen.findByRole("heading", { level: 1 });
  // The router renders outside act: let its passive effects (the stores' subscriptions) run first.
  await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
  const put = (patch: Partial<IndexSnapshot>): void =>
    act(() => {
      snap = { ...snap, ...patch };
      told.forEach((fn) => fn());
    });
  return { index, open, put };
}
/** The shell on a viewport `zoom` takes to 200 % and back (`matchMedia` answers for CMP-043's breakpoint). */
async function zoomable(): Promise<(on: boolean) => void> {
  let zoomed = false;
  vi.stubGlobal(
    "matchMedia",
    (query: string) =>
      ({
        get matches() {
          return zoomed && query === REFLOW;
        },
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
      }) as unknown as MediaQueryList,
  );
  await shell(CHART_1);
  const main = screen.getByRole("main"); // its rows in the viewport, as the layout would report them
  vi.spyOn(main, "getBoundingClientRect").mockReturnValue({ top: 80, bottom: 720 } as DOMRect);
  return (on) => {
    zoomed = on;
    fireEvent(window, new Event("resize")); // a zoom fires one: the shell re-measures its band
  };
}
const trigger = (): HTMLElement => screen.getByRole("button", { name: /^Symbol/ });
const press = (node: HTMLElement): void =>
  act(() => {
    fireEvent.pointerDown(node);
    node.focus();
    fireEvent.click(node);
  });
const input = (): HTMLElement => screen.getByRole("combobox", { name: "Search symbols" });
const key = (k: string, init: object = {}): void =>
  void act(() => fireEvent.keyDown(input(), { key: k, ...init }));
const type = (text: string): void =>
  void act(() => fireEvent.change(input(), { target: { value: text } }));
const polite = (): string =>
  [...document.querySelectorAll('[aria-live="polite"]')].map((n) => n.textContent).join("");
/** Out of the accessibility tree and the focus order: `inert` where the engine has it, else `aria-hidden` (jsdom). */
const held = (node: Element | null): boolean =>
  node?.closest("[inert], [aria-hidden=true]") != null;
/** The shell's scrim band, which every modal layer reads (AppShell; `dialog.css`). */
const band = (): string[] =>
  ["top", "bottom"].map((side) =>
    document.documentElement.style.getPropertyValue(`--cv-scrim-inset-${side}`),
  );
/** `main` at 80-720 px: the TopBar and the banner above the band, the StatusBar below it. */
const MAIN_BAND = (): string[] => ["80px", `${String(window.innerHeight - 720)}px`];
/**
 * A key that activates the focused button: jsdom has no activation, so this sends the key and the click a browser
 * makes of it (Enter on its press, Space on its release).
 */
const activate = (node: HTMLElement, name: "Enter" | "Space"): void =>
  act(() => {
    const k = name === "Enter" ? "Enter" : " ";
    fireEvent.keyDown(node, { key: k });
    if (name === "Space") fireEvent.keyUp(node, { key: k });
    fireEvent.click(node);
  });
/** The workspace's target panel in `main` (E15 / E12-S11 own it), bound with its pane (§9.2). */
function withPanel(open: SymbolOpener["open"]) {
  const panel = document.createElement("div");
  panel.tabIndex = -1; // it takes programmatic focus (`SymbolOpener.panel`)
  screen.getByRole("main").append(panel);
  const bind = (target: SymbolTarget | null): void =>
    act(() => setSymbolOpener({ target, open, panel: { current: panel } }));
  return { panel, bind };
}
/**
 * jsdom has no `inert`: the stub sends the Dialog down its native path, so `main` is `[inert]` while SCR-102 is open
 * and focus can land there only once the page is released (CR-CF-01; `Dialog.test.tsx`'s stub).
 */
async function nativeInert(run: () => Promise<void>): Promise<void> {
  Object.defineProperty(HTMLElement.prototype, "inert", { configurable: true, value: false });
  try {
    await run();
  } finally {
    delete (HTMLElement.prototype as { inert?: boolean }).inert;
  }
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  apiFetch.mockReset();
  apiFetch.mockRejectedValue(new TypeError("no network in tests"));
  resetMeClaims();
  resetShellState();
  clearAnnouncements();
});
afterEach(() => {
  stop();
  resetSymbolSearch();
  resetBindings();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("SCR-102 symbol search (E08-S09 PR C1)", () => {
  it("is absent until a workspace binds a pane: no Symbol control, no placeholder, and nothing opens it", async () => {
    const { open } = await shell(undefined); // no workspace has bound an opener
    const bar = screen.getByRole("banner");
    const symbol = (): HTMLElement | null => within(bar).queryByRole("button", { name: /^Symbol/ });
    expect(symbol()).toBeNull();
    act(() => openSymbolSearch()); // what `/` and the palette will call: refused with no opener
    expect(screen.queryByRole("dialog")).toBeNull();
    act(() => setSymbolOpener({ target: null, open })); // an opener with no pane: no value to draw
    expect(symbol()).toBeNull();
    act(() => setSymbolOpener({ target: CHART_1, open }));
    expect(symbol()).toHaveAccessibleName("Symbol: BTCUSDT, 1 minute");
    act(() => setSymbolOpener(null)); // withdrawn: gone again
    expect(symbol()).toBeNull();
  });

  it("opens from the TopBar's CMP-219 on a bound pane; focus in and back; D-11's live chrome and presses", async () => {
    const { open } = await shell(CHART_1);
    press(trigger());
    const dialog = screen.getByRole("dialog", { name: "Symbol search" });
    expect(dialog).toHaveAccessibleDescription("Changes Chart 1, BTCUSDT 1 minute.");
    expect(input()).toHaveFocus();
    expect(trigger()).toHaveAttribute("aria-expanded", "true");
    expect(within(dialog).getByText("Changes Chart 1 · BTCUSDT 1m")).toBeVisible();
    // The workspace is inert; the TopBar, the banner slot, the StatusBar, the live regions and the toast host
    // are not (the shell's marks).
    expect(held(document.getElementById("cv-main"))).toBe(true);
    const chrome = [screen.getByRole("banner"), screen.getByRole("contentinfo")];
    const live = [...document.querySelectorAll("[aria-live]")];
    const slot = document.querySelector("[data-shell-slot=banner]");
    expect([...chrome, ...live, slot].filter(held)).toEqual([]);
    const res = await axe.run(dialog, { rules: { "color-contrast": { enabled: false } } });
    expect(res.violations.filter((v) => /serious|critical/.test(v.impact ?? ""))).toEqual([]);
    press(trigger()); // a press on the open trigger closes it, without commit
    expect([trigger().getAttribute("aria-expanded"), document.activeElement]).toEqual([
      "false",
      trigger(),
    ]);
    press(trigger());
    act(() => void fireEvent.pointerDown(screen.getByRole("button", { name: "Sign out" })));
    expect(trigger()).toHaveAttribute("aria-expanded", "false"); // a TopBar press closes it too
    expect(open).not.toHaveBeenCalled();
  });

  it("D-11: Close and a press on the scrim close it without commit, focus back on the trigger", async () => {
    const { open } = await shell(CHART_1);
    const closed = (): unknown[] => [
      trigger().getAttribute("aria-expanded"),
      document.activeElement,
    ];
    press(trigger());
    press(screen.getByRole("button", { name: "Close Symbol search" }));
    expect(closed()).toEqual(["false", trigger()]);
    press(trigger());
    const scrim = document.querySelector<HTMLElement>(".cv-dialog__scrim"); // no role: it is presentational
    expect(scrim).not.toBeNull();
    if (scrim !== null) press(scrim);
    expect(closed()).toEqual(["false", trigger()]);
    expect(open).not.toHaveBeenCalled();
  });

  it("§9.2: with the trigger still there, focus goes back to it, before a registered target panel", async () => {
    const { open } = await shell(CHART_1);
    const { bind } = withPanel(open);
    bind(CHART_1);
    press(trigger());
    key("Escape");
    expect(document.activeElement).toBe(trigger());
  });

  it("§9.2: with the trigger gone, focus goes to the target panel, once the page's inert is released", () =>
    nativeInert(async () => {
      const { open } = await shell(CHART_1);
      const { panel, bind } = withPanel(open);
      bind(CHART_1);
      press(trigger());
      expect(panel.closest("[inert]")).not.toBeNull(); // the native path: the page is inert while open
      bind(null); // the pane unbinds while SCR-102 is open: the TopBar drops the trigger
      expect(screen.queryByRole("button", { name: /^Symbol/ })).toBeNull();
      key("Escape");
      expect(document.activeElement).toBe(panel);
      expect(open).not.toHaveBeenCalled();
    }));

  it("§9.2: with the workspace gone, its panel and opener in one commit, focus goes to the shell's main", () =>
    nativeInert(async () => {
      const { open } = await shell(CHART_1);
      const { panel, bind } = withPanel(open);
      bind(CHART_1);
      press(trigger());
      act(() => {
        panel.remove();
        setSymbolOpener(null);
      });
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(document.activeElement).toBe(screen.getByRole("main"));
    }));

  it("opened at the reflow breakpoint it fills the viewport; above it the scrim spares the TopBar and the StatusBar", async () => {
    const zoom = await zoomable();
    zoom(true); // 200 %: the shell lets go of the band (E10-D03 §11.3)
    press(trigger());
    expect(input()).toHaveFocus();
    expect(band()).toEqual(["", ""]);
    zoom(false); // main's rows only: the TopBar above them, the StatusBar below (E10-D03 §2.2)
    expect(band()).toEqual(MAIN_BAND());
  });

  it("closing leaves the shell's band, so the scrim never covers the TopBar while the dialog fades out", async () => {
    const zoom = await zoomable();
    zoom(false);
    press(trigger());
    key("Escape");
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    expect(band()).toEqual(MAIN_BAND());
  });

  it("§8: keys in the dialog never reach the window keymap; Esc closes; a Global chord closes and goes on", async () => {
    const { open } = await shell(CHART_1);
    press(trigger());
    type("btc");
    for (const k of ["b", " ", "Enter", "ArrowLeft", "Tab", "Delete", "c", "PageDown"]) key(k);
    expect(screen.getByTestId("toast-host")).toBeEmptyDOMElement();
    act(() => input().focus()); // Tab went round to Close, whose tooltip would take the first Esc
    key("Escape");
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    press(trigger());
    key("/", { ctrlKey: true });
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
    expect(open).not.toHaveBeenCalled();
  });

  it("§8: a typed `/` stays in the field, even bound to a Global command: only Ctrl, Alt and function-key chords go on", async () => {
    setBindings(new Map([...getBindings(), ["global.cheatsheet", "/"]])); // `/` as a Global key (A-D05-2)
    await shell(CHART_1);
    press(trigger());
    type("btc");
    let typed = false;
    act(() => void (typed = fireEvent.keyDown(input(), { key: "/" })));
    expect([typed, trigger().getAttribute("aria-expanded")]).toEqual([true, "true"]); // not prevented, open
    expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).toBeNull();
  });

  it("type, ↓, Enter: the target switches and its sentence is said; Recent remembers it; Shift+Enter opens a new chart", async () => {
    const { open } = await shell(CHART_1);
    press(trigger());
    type("eth");
    expect(screen.getAllByRole("option").map((o) => o.getAttribute("aria-label"))).toEqual([
      "ETHUSDT, ETH / USDT",
      "ETHFIUSDT, ETHFI / USDT",
    ]);
    key("ArrowDown");
    key("Enter");
    expect(open).toHaveBeenCalledWith("ETHUSDT", "target");
    expect([trigger().getAttribute("aria-expanded"), polite()]).toEqual([
      "false",
      "Chart 1 now shows ETHUSDT, 1 minute.",
    ]);
    press(trigger()); // each opening starts empty, Recent first
    const recent = screen.getByRole("group", { name: "Recent" });
    expect(within(recent).getByRole("option")).toHaveAccessibleName("ETHUSDT, ETH / USDT, recent");
    key("ArrowDown");
    key("Enter", { shiftKey: true });
    expect(open).toHaveBeenLastCalledWith("ETHUSDT", "new-chart");
    expect(polite()).toContain("Opened ETHUSDT in a new chart.");
  });

  it("§6.2's commit sentence: an armed pane adds 'Chart trading locked.'; a lost link adds the resume line", async () => {
    const { open } = await shell({ ...CHART_1, armed: true });
    press(trigger());
    expect(within(screen.getByRole("dialog")).getByText("ARMED")).toBeVisible(); // the chip's pill (D-10)
    // The detail bar's armed line, said with the input before a commit, not only after it (CR-D-05).
    expect(screen.getByText("Switching locks chart trading on Chart 1.")).toBeVisible();
    expect(input()).toHaveAccessibleDescription(
      /close Switching locks chart trading on Chart 1\.$/,
    );
    type("eth");
    key("ArrowDown");
    key("Enter");
    expect(polite()).toContain("Chart 1 now shows ETHUSDT, 1 minute. Chart trading locked.");
    const lost = { kind: "reconnecting", attempt: 1, nextAttemptAtMs: T0 } as const;
    act(() => setShellState({ connection: lost }));
    press(trigger());
    type("eth");
    key("ArrowDown");
    key("Enter", { shiftKey: true });
    expect(open).toHaveBeenLastCalledWith("ETHUSDT", "new-chart");
    expect(polite()).toContain(
      "Opened ETHUSDT in a new chart. Live data resumes when the connection returns.",
    );
  });

  it("AC 3 (§6.4): a delisted, a pre-launch and an unlisted Recent are reached, never chosen, and say why", async () => {
    const known = [entry("LUNAUSDT", "Closed"), entry("NEWUSDT", "PreLaunch")];
    const { open } = await shell(CHART_1, { known });
    act(() => {
      for (const symbol of ["GONEUSDT", "NEWUSDT", "LUNAUSDT"]) rememberSymbol(symbol); // LUNAUSDT newest
    });
    press(trigger());
    const recent = screen.getByRole("group", { name: "Recent" });
    const [luna, fresh, gone] = within(recent).getAllByRole("option");
    expect(luna).toHaveAccessibleName("LUNAUSDT, LUNA / USDT, Delisted by the exchange, recent");
    expect(luna).toHaveAccessibleDescription("LUNAUSDT is not trading on Bybit. Status: Closed.");
    expect(fresh).toHaveAccessibleName("NEWUSDT, NEW / USDT, recent"); // pre-launch is not delisted
    expect(fresh).toHaveAccessibleDescription(
      "NEWUSDT is not trading on Bybit. Not trading yet — status: Pre-launch.",
    );
    expect(gone).toHaveAccessibleDescription("GONEUSDT is not trading on Bybit.");
    const disabled = [luna, fresh, gone].map((o) => o?.getAttribute("aria-disabled"));
    expect(disabled).toEqual(["true", "true", "true"]);
    key("ArrowDown"); // reached
    key("Enter");
    key("Enter", { shiftKey: true });
    expect([open.mock.calls.length, getSymbolSearchState().open]).toEqual([0, true]); // never chosen
  });

  it("§6.2: loading and the 503 line, never a count; failed with Retry now and the Ref; the first run; over 50", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: T0 }); // the waits count from a snapshot's arrival
    const { index, put } = await shell(CHART_1, { phase: "loading", entries: [] });
    press(trigger());
    const status = within(screen.getByRole("dialog")).getByRole("status");
    expect(screen.getByRole("listbox")).toHaveAttribute("aria-busy", "true");
    expect(status).toHaveTextContent("Loading the instrument list…");
    put({ retryAt: T0 + 4_000 });
    type("btc");
    expect(status).toHaveTextContent(
      /^CandleViewer's server is loading the instrument list from Bybit — next try in 4 s\.$/,
    );
    const failure = { cause: "http", status: 500, instance: "r-7" } as const;
    put({ phase: "failed", failure, retryAt: T0 + 30_000 });
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "Couldn't load the instrument list.",
    );
    expect(screen.getByText("CandleViewer's server answered 500. Next try in 30 s.")).toBeVisible();
    expect(screen.getByText("Ref r-7")).toBeVisible();
    press(screen.getByRole("button", { name: "Retry now" }));
    expect(index.reread).toHaveBeenCalledTimes(1);
    const many = Array.from({ length: 60 }, (_, i) => `S${String(i)}USDT`);
    put({ phase: "ready", failure: null, retryAt: null, entries: listed(...many) });
    expect(input()).toHaveFocus(); // Retry now went with the failure: focus is back where it starts (§9.2)
    type("");
    expect(screen.getByText("Type a symbol or base asset, for example BTC.")).toBeVisible();
    type("s");
    expect(screen.getByText("Showing 50 of 60 results — keep typing to narrow")).toBeVisible();
  });

  it("the index reads once /me has answered and a workspace has bound an opener; it stops with the shell; §5's rows", () => {
    const fake = { start: vi.fn(), stop: vi.fn(), reread: vi.fn(), learn: vi.fn() };
    const index = { ...fake, subscribe: () => () => undefined, getSnapshot: () => READY };
    const end = startSymbolSearch(index);
    setShellState({ me: ME }); // signed in, but nothing can show the list yet: no read
    expect([fake.start.mock.calls.length, getSymbolSearchState().index]).toEqual([0, index]);
    expect(getSymbolSearchState().running).toBe(false); // held, not running (CR-CD-01)
    setSymbolOpener({ target: null, open: vi.fn() }); // the first opener: the read starts, once
    setSymbolOpener({ target: CHART_1, open: vi.fn() });
    expect([fake.start.mock.calls.length, getSymbolSearchState().running]).toEqual([1, true]);
    end();
    expect([fake.stop.mock.calls.length, getSymbolSearchState().index]).toEqual([1, null]);
    // Its listeners go with it: a session that ended starts no index it held, whatever comes after.
    const late = {
      ...fake,
      start: vi.fn(),
      subscribe: () => () => undefined,
      getSnapshot: () => READY,
    };
    resetSymbolSearch();
    startSymbolSearch(late)();
    setShellState({ me: ME });
    setSymbolOpener({ target: CHART_1, open: vi.fn() });
    expect([late.start.mock.calls.length, getSymbolSearchState().running]).toEqual([0, false]);
    const rows = [800, 1080].flatMap((h) => [visibleRows(h, false), visibleRows(h, true)]);
    expect(rows).toEqual([16, 11, 16, 12]);
  });
});

describe("SCR-102, the rest of E08-D05 §6 (E08-S09 PR C2)", () => {
  const dialog = (): HTMLElement => screen.getByRole("dialog", { name: "Symbol search" });
  const heading = (): HTMLElement => within(dialog()).getByRole("heading", { level: 3 });
  const reply = (status: number): Promise<Response> =>
    Promise.resolve(new Response(null, { status }));
  const accepted = (): Promise<Response> => Promise.resolve(new Response("{}", { status: 202 }));
  const urls = (): string[] => apiFetch.mock.calls.map(([url]) => url);
  /** The instrument routes answer as the test says; the rest of the shell still has no network. */
  const instruments = (answer: (url: string) => Promise<Response>): void =>
    void apiFetch.mockImplementation((url) =>
      url.startsWith("/api/v1/instruments/")
        ? answer(url)
        : Promise.reject(new TypeError("no network")),
    );
  const said = (): (string | null)[] =>
    within(dialog())
      .getAllByRole("status")
      .map((node) => node.textContent);
  /** CMP-160's polite region: the surface's one (§9.2). */
  const region = (): Element | null =>
    dialog().querySelector('[data-cmp="CMP-160"] > [role="status"]');
  /** The footer's key hints: the input's first description (§9.1). */
  const hints = (): HTMLElement | null =>
    document.getElementById(input().getAttribute("aria-describedby")?.split(" ")[0] ?? "");
  /** axe's serious and critical rules on the page (jsdom has no layout: contrast is CI's). */
  const audit = async (): Promise<unknown[]> => {
    const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
    return res.violations.filter((v) => /serious|critical/.test(v.impact ?? ""));
  };
  /** Lets an answer land on the fake clock. */
  const answered = async (): Promise<void> => {
    await act(() => vi.advanceTimersByTimeAsync(0));
  };
  /** Lets an answer land on the real clock. */
  const settled = (): Promise<void> => act(() => new Promise<void>((done) => setTimeout(done, 0)));
  const checking = (): string[] =>
    within(dialog())
      .queryAllByText("Checking Bybit for XYZZYUSDT…")
      .map((node) => node.tagName);

  it("§6.1: the column header sits over the list, aria-hidden and outside the listbox", async () => {
    await shell(CHART_1);
    act(() => rememberSymbol("ETHUSDT"));
    press(trigger());
    const head = dialog().querySelector(".cv-fuzzylist__columns");
    expect([head?.textContent, head?.getAttribute("aria-hidden")]).toEqual([
      "SymbolBase / quote24 h24 h turnover",
      "true",
    ]);
    expect(head?.closest('[role="listbox"]')).toBeNull();
    expect(screen.getByRole("listbox")).toBeVisible();
  });

  it("§6.1: a Recent row reads ↺ and its base / quote, its 24 h cells '—' (no ticker is held, D-8)", async () => {
    await shell(CHART_1);
    act(() => rememberSymbol("ETHUSDT"));
    press(trigger());
    const [eth] = within(screen.getByRole("group", { name: "Recent" })).getAllByRole("option");
    expect(eth).toHaveTextContent("ETHUSDT↺ ETH / USDT — —");
  });

  it(
    "§6.4: the active option's ⋯ in the detail bar, a menu button named for it; none while no option is active",
    async () => {
      await shell(CHART_1);
      act(() => rememberSymbol("ETHUSDT"));
      press(trigger());
      expect(within(dialog()).queryByRole("button", { name: /^Actions for/ })).toBeNull();
      key("ArrowDown");
      const dots = within(dialog()).getByRole("button", { name: "Actions for ETHUSDT" });
      expect([dots.getAttribute("aria-haspopup"), dots.getAttribute("aria-expanded")]).toEqual([
        "menu",
        "false",
      ]);
      expect(await audit()).toEqual([]);
    },
    AXE_MS,
  );

  it.each([
    [
      "a target pane",
      CHART_1,
      "Enter open in Chart 1 · Shift plus Enter new chart · Shift plus F10 actions · Esc close",
    ],
    ["no target pane", null, "Enter open in a new chart · Shift plus F10 actions · Esc close"],
  ] as const)(
    "§6.1, §9.1: the footer's key hints, the input's description, name every key, Shift+F10's menu too (%s)",
    async (_target, target, words) => {
      await shell(target);
      act(() => openSymbolSearch());
      expect(input()).toHaveAccessibleDescription(words);
    },
  );

  /** V9 to the check's 404: XYZZYUSDT asked after the 300 ms rest, at 12:00 UTC on the fake clock. */
  const checkedGone = async () => {
    const { put } = await shell(CHART_1);
    vi.useFakeTimers({ now: T0 });
    instruments(() => reply(404));
    press(trigger());
    type("xyzzy");
    await act(() => vi.advanceTimersByTimeAsync(300));
    await answered();
    const again = (): HTMLElement => within(dialog()).getByRole("button", { name: "Check again" });
    return { put, again };
  };

  it("V9: the rest sends and says nothing; then one check, its line in the detail bar and said once", async () => {
    await shell(CHART_1);
    vi.useFakeTimers({ now: T0 });
    instruments(() => new Promise<Response>(() => undefined)); // the check stays in flight
    press(trigger());
    type("xyzzy");
    await act(() => vi.advanceTimersByTimeAsync(299));
    expect([urls(), said()]).toEqual([[], [""]]); // the rest: nothing sent, nothing said
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(urls()).toEqual(["/api/v1/instruments/XYZZYUSDT"]);
    expect(within(dialog()).queryByRole("heading", { level: 3 })).toBeNull(); // no block before its answer
    expect(checking()).toEqual(["SPAN", "P"]); // said once, and drawn in the detail bar
  });

  it("V9: the check's 404 is the No matches block, verbatim, and its sentence is said", async () => {
    await checkedGone();
    expect(heading()).toHaveTextContent("No USDT perpetual matches 'xyzzy'.");
    expect(dialog()).toHaveTextContent(
      "v1 supports Bybit USDT linear perpetuals only. Search by base asset, for example BTC. Checked with the server at 12:00 UTC.",
    );
    expect(said()).toContain(
      "No USDT perpetual matches 'xyzzy'. v1 supports Bybit USDT linear perpetuals only.",
    );
  });

  it(
    "V9, G-T2: Check again is T2 search.check_cooldown, aria-disabled and described; a press sends nothing, says why",
    async () => {
      const { again } = await checkedGone();
      expect([again().getAttribute("aria-disabled"), again().hasAttribute("disabled")]).toEqual([
        "true",
        false,
      ]);
      expect(again()).toHaveAccessibleDescription("Checked a moment ago.");
      act(() => again().click());
      expect(urls()).toHaveLength(1);
      expect(said()).toContain("Checked a moment ago."); // CMP-026's own press region
      vi.useRealTimers(); // axe keeps its own time
      expect(await audit()).toEqual([]);
    },
    AXE_MS,
  );

  it("V9: Check again lifts in place once the 60 s are up", async () => {
    const { again } = await checkedGone();
    const button = again();
    await act(() => vi.advanceTimersByTimeAsync(60_000));
    expect([button.isConnected, button.hasAttribute("aria-disabled")]).toEqual([true, false]);
  });

  it("A11Y-D-01: Check again keeps its block and the focus while it runs", async () => {
    const { again } = await checkedGone();
    await act(() => vi.advanceTimersByTimeAsync(60_000));
    instruments(() => new Promise<Response>(() => undefined)); // this check stays in flight
    const button = again();
    act(() => button.focus());
    act(() => button.click());
    expect([urls().length, document.activeElement, button.isConnected]).toEqual([2, button, true]);
    expect(checking()).toEqual(["SPAN", "P"]);
  });

  it("§9.2: a listing that answers the check replaces the block, and focus goes back to the input", async () => {
    const { put, again } = await checkedGone();
    await act(() => vi.advanceTimersByTimeAsync(60_000));
    instruments(() => new Promise<Response>(() => undefined));
    act(() => again().focus());
    act(() => again().click());
    put({ entries: listed("BTCUSDT", "XYZZYUSDT") });
    expect(screen.getByRole("option")).toHaveAccessibleName("XYZZYUSDT, XYZZY / USDT");
    expect(input()).toHaveFocus();
  });

  it("V10: 'usdt' alone is never checked: its No matches block shows at once, with no Check again", async () => {
    await shell(CHART_1);
    vi.useFakeTimers({ now: T0 });
    press(trigger());
    type("usdt");
    expect(heading()).toHaveTextContent("No USDT perpetual matches 'usdt'.");
    expect(within(dialog()).queryByRole("button", { name: "Check again" })).toBeNull();
    await act(() => vi.advanceTimersByTimeAsync(300));
    expect(urls()).toEqual([]);
  });

  it("§6.2: a check with no usable answer (a 503) says so in the block", async () => {
    await shell(CHART_1);
    vi.useFakeTimers({ now: T0 });
    instruments(() => reply(503));
    press(trigger());
    type("slu");
    await act(() => vi.advanceTimersByTimeAsync(300));
    await answered();
    expect(urls()).toEqual(["/api/v1/instruments/SLUUSDT"]);
    expect(dialog()).toHaveTextContent("Couldn't check Bybit for SLUUSDT just now.");
  });

  it(
    "§6.2's status rule: its block, with View symbol info once SCR-103's port is registered",
    async () => {
      await shell(CHART_1, { known: [entry("LUNAUSDT", "Closed")] });
      const info = vi.fn();
      press(trigger());
      type("luna");
      expect(heading()).toHaveTextContent("LUNAUSDT is not trading on Bybit.");
      expect(dialog()).toHaveTextContent("Status: Closed. It can't be opened as a new chart.");
      expect(within(dialog()).queryByRole("button", { name: "View symbol info" })).toBeNull();
      expect(await audit()).toEqual([]);
      act(() => setSymbolInfo({ open: info }));
      press(within(dialog()).getByRole("button", { name: "View symbol info" }));
      expect(info).toHaveBeenCalledWith("LUNAUSDT", { source: "scr-102" });
      expect([trigger().getAttribute("aria-expanded"), urls()]).toEqual(["false", []]); // closed; nothing checked
    },
    AXE_MS,
  );

  it("§6.2's status rule: Clear search empties the query, focus back in the input", async () => {
    await shell(CHART_1, { known: [entry("LUNAUSDT", "Closed")] });
    press(trigger());
    type("luna");
    press(within(dialog()).getByRole("button", { name: "Clear search" }));
    expect(input()).toHaveValue("");
    expect(input()).toHaveFocus();
  });

  it("§3 row 2: a Recent missing from the listing is looked up once a session, one at a time: 404 gone, 503 unchecked", async () => {
    const { index, put } = await shell(CHART_1);
    vi.useFakeTimers({ now: T0 });
    instruments((url) => reply(url.endsWith("/LUNAUSDT") ? 404 : 503));
    act(() => ["GONEUSDT", "LUNAUSDT"].forEach(rememberSymbol)); // LUNAUSDT newest
    press(trigger());
    await answered();
    expect(index.learn).toHaveBeenCalledWith({ kind: "not_listed", symbol: "LUNAUSDT" });
    put({ unlisted: ["LUNAUSDT"] }); // the index learnt it: the next lookup starts
    await answered();
    expect(urls()).toEqual(["/api/v1/instruments/LUNAUSDT", "/api/v1/instruments/GONEUSDT"]);
    const [luna, gone] = within(screen.getByRole("group", { name: "Recent" })).getAllByRole(
      "option",
    );
    expect(luna).toHaveAccessibleDescription("LUNAUSDT is no longer listed on Bybit.");
    expect(gone).toHaveAccessibleDescription("Couldn't check Bybit for GONEUSDT just now.");
  });

  it("§3 row 2: a query naming a remembered symbol the session found gone says so, and checks nothing", async () => {
    const { put } = await shell(CHART_1);
    vi.useFakeTimers({ now: T0 });
    instruments(() => reply(404));
    act(() => rememberSymbol("LUNAUSDT"));
    press(trigger());
    await answered();
    put({ unlisted: ["LUNAUSDT"] });
    type("lunausdt");
    await act(() => vi.advanceTimersByTimeAsync(300));
    expect([heading().textContent, urls()]).toEqual([
      "LUNAUSDT is no longer listed on Bybit.",
      ["/api/v1/instruments/LUNAUSDT"], // the session's lookup, and no check
    ]);
  });

  it(
    "§6.3: Shift+F10 opens the active option's menu on its first item",
    async () => {
      await shell(CHART_1);
      act(() => rememberSymbol("ETHUSDT"));
      press(trigger());
      key("ArrowDown");
      key("F10", { shiftKey: true });
      const menu = screen.getByRole("menu", { name: "Actions for ETHUSDT" });
      const items = within(menu).getAllByRole("menuitem");
      expect(items.map((item) => item.textContent)).toEqual([
        "Open in Chart 1",
        "Open in new chart",
        "Remove from recent",
      ]);
      expect(items[0]).toHaveFocus();
      expect(await audit()).toEqual([]);
    },
    AXE_MS,
  );

  it("§6.3: Esc closes the menu only, back in the input on the same option", async () => {
    await shell(CHART_1);
    act(() => rememberSymbol("ETHUSDT"));
    press(trigger());
    key("ArrowDown");
    const option = input().getAttribute("aria-activedescendant");
    key("F10", { shiftKey: true });
    const [first] = within(screen.getByRole("menu")).getAllByRole("menuitem");
    act(() => void fireEvent.keyDown(first ?? document.body, { key: "Escape" }));
    expect(screen.queryByRole("menu")).toBeNull();
    expect([document.activeElement, input().getAttribute("aria-activedescendant")]).toEqual([
      input(),
      option,
    ]);
    expect(dialog()).toBeVisible();
  });

  it("§6.3: the ⋯ opens it; Open in new chart commits there and says so", async () => {
    const { open } = await shell(CHART_1);
    act(() => rememberSymbol("ETHUSDT"));
    press(trigger());
    key("ArrowDown");
    press(within(dialog()).getByRole("button", { name: "Actions for ETHUSDT" }));
    press(screen.getByRole("menuitem", { name: "Open in new chart" }));
    expect(open).toHaveBeenCalledWith("ETHUSDT", "new-chart");
    expect(polite()).toBe("Opened ETHUSDT in a new chart.");
  });

  it("§6.3: a right-click opens it at the point; Remove from recent forgets the row, focus in the input", async () => {
    await shell(CHART_1);
    act(() => ["SOLUSDT", "ETHUSDT"].forEach(rememberSymbol));
    press(trigger());
    const recent = (): HTMLElement => screen.getByRole("group", { name: "Recent" });
    const sol = within(recent()).getByRole("option", { name: /^SOLUSDT/ });
    act(() => void fireEvent.contextMenu(sol, { clientX: 40, clientY: 90 }));
    press(screen.getByRole("menuitem", { name: "Remove from recent" }));
    expect(
      within(recent())
        .getAllByRole("option")
        .map((o) => o.getAttribute("aria-label")),
    ).toEqual(["ETHUSDT, ETH / USDT, recent"]);
    expect(input()).toHaveFocus();
  });

  it("§6.4: Shift+Enter on a delisted Recent opens nothing and says why, after Enter has said it too", async () => {
    const { open } = await shell(CHART_1, { known: [entry("LUNAUSDT", "Closed")] });
    act(() => rememberSymbol("LUNAUSDT"));
    press(trigger());
    key("ArrowDown");
    key("Enter"); // CMP-160 says the reason
    const node = region()?.firstChild;
    key("Enter", { shiftKey: true });
    expect([region()?.textContent, region()?.firstChild === node]).toEqual([
      "LUNAUSDT is not trading on Bybit. Status: Closed.",
      false, // a new node: said again
    ]);
    expect(open).not.toHaveBeenCalled();
  });

  const OWNER_ONLY = "Only the owner can refresh the instrument list.";
  const STALE = { loadedAt: T0, cacheAgeS: 14 * 3600, staleSince: "2026-10-30T10:00:00Z" } as const;
  const refresh = (): HTMLElement =>
    within(dialog()).getByRole("button", { name: "Refresh from Bybit" });

  it("§6.2 Stale: the notice is part of the dialog's description and takes the hints' row; Retry re-reads", async () => {
    const { index } = await shell(CHART_1, STALE);
    vi.useFakeTimers({ toFake: ["Date"], now: T0 });
    press(trigger());
    expect(dialog()).toHaveAccessibleDescription(
      "Changes Chart 1, BTCUSDT 1 minute. Instrument list updated 14 h ago — the scheduled refresh is overdue.",
    );
    expect(hints()).toHaveClass("cv-visually-hidden"); // the notice takes the hints' row
    press(within(dialog()).getByRole("button", { name: "Retry" }));
    expect(index.reread).toHaveBeenCalledTimes(1);
  });

  it(
    "§6.2 Stale, G-T2: without instruments:write, Refresh from Bybit is T2 in rendering 2a: the lock, described, its reason beside it",
    async () => {
      await shell(CHART_1, STALE);
      press(trigger());
      const button = refresh();
      expect([button.getAttribute("aria-disabled"), button.hasAttribute("disabled")]).toEqual([
        "true",
        false,
      ]);
      expect(button).toHaveAccessibleDescription(OWNER_ONLY); // rbac.owner_only, at mount
      expect(button.querySelector(".cv-button__glyph svg")).not.toBeNull(); // CMP-019's lock, as CMP-001 places it
      const footer = button.closest("p");
      const beside = [...(footer?.querySelectorAll('[aria-hidden="true"]') ?? [])].filter(
        (node) => node.textContent === OWNER_ONLY,
      );
      expect(beside).toHaveLength(1); // drawn for the eye beside it; its description is the button's own
      expect(await audit()).toEqual([]);
    },
    AXE_MS,
  );

  it.each(["Enter", "Space"] as const)(
    "§6.2 Stale, G-T2.3: %s on the T2 Refresh sends nothing and says its reason once, in the surface's region",
    async (name) => {
      await shell(CHART_1, STALE);
      press(trigger());
      const button = refresh();
      act(() => button.focus());
      activate(button, name); // no hotkey is bound to it
      const first = region()?.firstChild;
      expect([region()?.textContent, said().filter((text) => text === OWNER_ONLY)]).toEqual([
        OWNER_ONLY,
        [OWNER_ONLY], // one region says it
      ]);
      activate(button, name);
      expect([region()?.textContent, region()?.firstChild === first]).toEqual([OWNER_ONLY, false]); // per press
      expect([urls(), document.activeElement]).toEqual([[], button]);
    },
  );

  it("§9.2: when the re-read lands, Retry goes with the stale notice and focus goes back to the input", async () => {
    const { put } = await shell(CHART_1, STALE);
    press(trigger());
    const retry = within(dialog()).getByRole("button", { name: "Retry" });
    press(retry);
    expect(retry).toHaveFocus();
    put({ staleSince: null, loadedAt: T0 + 1 });
    expect(retry.isConnected).toBe(false);
    expect(input()).toHaveFocus();
  });

  it("§6.2 Refreshing: the footer says so, and the re-read's rows wait for the next keystroke", async () => {
    const { put } = await shell(CHART_1);
    press(trigger());
    put({ refreshing: true });
    expect(screen.getByText("Updating the instrument list…")).toBeVisible();
    expect(hints()).toHaveClass("cv-visually-hidden");
    type("eth");
    put({ refreshing: false, loadedAt: T0, entries: listed("BTCUSDT") }); // the re-read lands
    expect(screen.getAllByRole("option")).toHaveLength(2); // kept until the next keystroke
    expect(hints()).not.toHaveClass("cv-visually-hidden");
    type("eth ");
    expect(screen.queryAllByRole("option")).toEqual([]);
  });

  it("§6.2 Disconnected (offline): the footer names the list's time; a commit adds the resume clause", async () => {
    await shell(CHART_1, { loadedAt: T0 });
    act(() => setShellState({ connection: { kind: "offline", cause: "offline" } }));
    press(trigger());
    expect(
      screen.getByText("Disconnected — results come from the list loaded at 12:00 UTC."),
    ).toBeVisible();
    type("btc");
    key("ArrowDown");
    key("Enter");
    expect(polite()).toBe(
      "Chart 1 now shows BTCUSDT, 1 minute. Live data resumes when the connection returns.",
    );
  });

  it("E17-D01: connecting again after a loss is Disconnected too, as the shell reads it", async () => {
    await shell(CHART_1, { loadedAt: T0 });
    act(() => setShellState({ connection: { kind: "live" } }));
    act(() => setShellState({ connection: { kind: "connecting" } })); // not the session's first connect
    press(trigger());
    expect(
      screen.getByText("Disconnected — results come from the list loaded at 12:00 UTC."),
    ).toBeVisible();
    type("btc");
    key("ArrowDown");
    key("Enter");
    expect(polite()).toContain(
      "Chart 1 now shows BTCUSDT, 1 minute. Live data resumes when the connection returns.",
    );
  });

  it("Load failed names its cause, a network error or a minute of 503s, with the Ref only when sent; the header stays", async () => {
    const failure = { cause: "network" } as const;
    const { put } = await shell(CHART_1, { phase: "failed", entries: [], failure, retryAt: T0 });
    press(trigger());
    expect(dialog()).toHaveTextContent("CandleViewer can't reach its server.");
    expect(within(dialog()).queryByText(/^Ref /)).toBeNull();
    put({ failure: { cause: "unavailable", instance: "r-9" } });
    expect(dialog()).toHaveTextContent("The server still has no list from Bybit after a minute.");
    expect(screen.getByText("Ref r-9")).toBeVisible();
    put({ failure: { cause: "unavailable", instance: null } });
    expect(within(dialog()).queryByText(/^Ref /)).toBeNull();
    expect(dialog().querySelector(".cv-fuzzylist__columns")).not.toBeNull();
  });

  /** §12.1's events on the app's seam (`cv:analytics` on `window`), from now to the test's end. */
  const analytics = (): Record<string, unknown>[] => {
    const events: Record<string, unknown>[] = [];
    const take = (event: Event): void => {
      const { detail } = event as CustomEvent<Record<string, unknown>>;
      if (/^(symbol\.|empty_state)/.test(String(detail["name"]))) events.push(detail);
    };
    window.addEventListener("cv:analytics", take);
    onTestFinished(() => window.removeEventListener("cv:analytics", take));
    return events;
  };

  it("§12.1: symbol.searched once the query has rested 300 ms, with its length and never the query", async () => {
    const events = analytics();
    await shell(CHART_1);
    vi.useFakeTimers({ now: T0 });
    press(trigger());
    type("eth");
    await act(() => vi.advanceTimersByTimeAsync(299));
    expect(events).toEqual([]);
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(events).toEqual([
      {
        ...{ name: "symbol.searched", surface: "scr-102", query_length: 3, result_count: 2 },
        ...{ top_tier: 1, catalogue_state: "ready" },
      },
    ]);
    expect(JSON.stringify(events)).not.toContain("eth");
  });

  it("§12.1: the same query with a trailing space is not reported again (once per query)", async () => {
    const events = analytics();
    await shell(CHART_1);
    vi.useFakeTimers({ now: T0 });
    press(trigger());
    type("eth");
    await act(() => vi.advanceTimersByTimeAsync(300));
    type("eth ");
    await act(() => vi.advanceTimersByTimeAsync(300));
    expect(events.map((event) => event["name"])).toEqual(["symbol.searched"]);
  });

  it("§12.1: empty_state_shown once per state entered: loading, then load failed", async () => {
    const events = analytics();
    const { put } = await shell(CHART_1, { phase: "loading", entries: [] });
    press(trigger());
    put({ retryAt: T0 + 4_000 }); // still loading: no new entry
    put({ phase: "failed", failure: { cause: "network" }, retryAt: T0 + 30_000 });
    expect(events).toEqual([
      { name: "empty_state_shown", surface: "scr-102", reason: "catalogue_loading" },
      { name: "empty_state_shown", surface: "scr-102", reason: "catalogue_load_failed" },
    ]);
  });

  it("§12.1: symbol.search_result_opened on a commit: its group, rank, tier and how it came in", async () => {
    const events = analytics();
    await shell(CHART_1);
    press(trigger());
    type("eth");
    key("ArrowDown");
    key("Enter");
    expect(events.filter((event) => event["name"] === "symbol.search_result_opened")).toEqual([
      {
        ...{ name: "symbol.search_result_opened", surface: "scr-102", rank: 1, tier: 1 },
        ...{ group: "results", input: "key", action: "open" },
      },
    ]);
  });

  const FAILED = {
    phase: "failed",
    entries: [],
    failure: { cause: "network" },
    retryAt: T0,
  } as const;

  it.each([
    ["loading", { phase: "loading", entries: [] }, "Loading the instrument list…"],
    ["load failed", FAILED, "Couldn't load the instrument list."],
    ["the first run", {}, "Type a symbol or base asset, for example BTC."],
  ] as const)(
    "§6.2: Enter with no openable option (%s) is inert and says the state's heading again",
    async (_state, first, words) => {
      const { open } = await shell(CHART_1, first);
      press(trigger());
      const node = region()?.firstChild;
      key("Enter");
      expect([region()?.textContent, region()?.firstChild === node]).toEqual([words, false]); // a new node
      expect([open.mock.calls, getSymbolSearchState().open]).toEqual([[], true]);
    },
  );

  it("§9.2: a heading said again is forgotten with its query: back at the same query and state, nothing is said", async () => {
    await shell(CHART_1);
    press(trigger());
    key("Enter"); // the first run's heading, said again
    expect(region()).toHaveTextContent("Type a symbol or base asset, for example BTC.");
    type("b");
    type("");
    expect(region()).toBeEmptyDOMElement();
  });

  const REQUESTED = "Refresh requested — updating the instrument list…";
  /** PROPOSED (E08-D05 §6.2's deck): any answer but 202 and the two 429s. */
  const REFUSED = "Couldn't request a refresh just now.";
  /** The Owner's session: `instruments:write` in its permissions, never a role name. */
  const asOwner = (): void =>
    setMeClaims({ authenticated: true, role: "owner", permissions: ["instruments:write"] });

  it(
    "§6.2 Load failed, G-T2: Refresh from Bybit is T2 rbac.owner_only without instruments:write; a press sends nothing, says why",
    async () => {
      await shell(CHART_1, FAILED);
      press(trigger());
      expect([refresh().getAttribute("aria-disabled"), refresh().hasAttribute("disabled")]).toEqual(
        ["true", false],
      );
      expect(refresh()).toHaveAccessibleDescription(OWNER_ONLY);
      act(() => refresh().click());
      expect(urls()).toEqual([]);
      expect(said()).toContain(OWNER_ONLY); // CMP-026's own press region
      expect(await audit()).toEqual([]);
    },
    AXE_MS,
  );

  it("§6.2 Refresh answered: the Owner's press posts; a 202 is the footer's notice, said once in the surface's region", async () => {
    await shell(CHART_1, FAILED);
    asOwner();
    instruments(accepted);
    press(trigger());
    press(refresh());
    await settled();
    expect(apiFetch).toHaveBeenLastCalledWith(
      "/api/v1/instruments/refresh",
      expect.objectContaining({ method: "POST" }),
    );
    expect(screen.getByText(REQUESTED, { selector: "p" })).toBeVisible();
    expect(said().filter((text) => text === REQUESTED)).toHaveLength(1);
    expect(region()).toHaveTextContent(REQUESTED);
  });

  it.each([
    ["rate_limited", "Too many requests — try again in 12 s."],
    ["exchange_rate_limited", "Bybit is limiting requests — try again in 12 s."],
  ])("§6.2 Refresh answered: a 429 %s shows its wait and says it", async (code, words) => {
    await shell(CHART_1, STALE);
    asOwner();
    const problem = { type: "about:blank", title: "Limited", status: 429, code };
    const body = JSON.stringify({ ...problem, retry_after_seconds: 12 });
    instruments(() => Promise.resolve(new Response(body, { status: 429 })));
    press(trigger());
    press(refresh());
    await settled();
    expect(screen.getByText(words, { selector: "p" })).toBeVisible();
    expect(region()).toHaveTextContent(words);
  });

  it.each([
    ["a 404 (the route is a stub until E08-S01)", () => reply(404)],
    ["a 403", () => reply(403)],
    ["no answer", () => Promise.reject(new TypeError("offline"))],
  ])(
    "§6.2 Refresh answered: %s never reads as success: the PROPOSED refusal shows and is said",
    async (_answer, answer) => {
      await shell(CHART_1, STALE);
      asOwner();
      instruments(answer);
      press(trigger());
      press(refresh());
      await settled();
      expect(screen.getByText(REFUSED, { selector: "p" })).toBeVisible();
      expect(region()).toHaveTextContent(REFUSED);
      expect(screen.queryByText(REQUESTED)).toBeNull();
    },
  );

  it("§6.2: the 202's notice ends when the list next arrives", async () => {
    const { put } = await shell(CHART_1, STALE);
    asOwner();
    instruments(accepted);
    press(trigger());
    press(refresh());
    await settled();
    expect(screen.getByText(REQUESTED, { selector: "p" })).toBeVisible();
    put({ staleSince: null, loadedAt: T0 + 1 }); // the refreshed list lands
    expect(screen.queryByText(REQUESTED, { selector: "p" })).toBeNull();
  });

  it("§6.2: with no job poll yet (E08-S01), the 202's notice ends after the poll's 60 s", async () => {
    await shell(CHART_1, STALE);
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"], now: T0 });
    asOwner();
    instruments(accepted);
    press(trigger());
    press(refresh());
    await answered();
    expect(screen.getByText(REQUESTED, { selector: "p" })).toBeVisible();
    await act(() => vi.advanceTimersByTimeAsync(59_999));
    expect(screen.getByText(REQUESTED, { selector: "p" })).toBeVisible();
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(screen.queryByText(REQUESTED, { selector: "p" })).toBeNull();
  });

  it("§6.2: a press while the refresh is pending, in flight or asked, posts nothing more and says the notice again", async () => {
    await shell(CHART_1, STALE);
    asOwner();
    instruments(accepted);
    press(trigger());
    press(refresh());
    press(refresh()); // in flight
    await settled();
    const node = region()?.firstChild;
    press(refresh()); // asked: the list is on its way
    await settled();
    expect(urls()).toEqual(["/api/v1/instruments/refresh"]);
    expect([region()?.textContent, region()?.firstChild === node]).toEqual([REQUESTED, false]);
  });
});
