/**
 * E08-S09 PR C1: SCR-102 in the shell (E08-D05 §6.1, §6.2, §6.4, §8, §9.2, D-10, D-11), on a fake instrument index.
 * The TopBar draws its trigger only once a workspace has bound a pane: until then it is absent, with no placeholder.
 */
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearAnnouncements } from "../../../src/features/app-shell/announcer";
import type { IndexSnapshot } from "../../../src/features/symbol-search/instrumentIndex";
import { toEntry, type Instrument } from "../../../src/features/symbol-search/ranking";
import {
  getSymbolSearchState,
  openSymbolSearch,
  rememberSymbol,
  resetSymbolSearch,
  setSymbolOpener,
  startSymbolSearch,
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

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
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

  it("§9.2: with the trigger gone, focus goes back to the target panel; with the workspace gone, to the shell's main", async () => {
    const { open } = await shell(CHART_1);
    const panel = document.createElement("div"); // the workspace's target panel (E15 / E12-S11 own it)
    panel.tabIndex = -1;
    screen.getByRole("main").append(panel);
    const bound = (target: SymbolTarget | null) => ({ target, open, panel: { current: panel } });
    act(() => setSymbolOpener(bound(CHART_1)));
    press(trigger());
    act(() => setSymbolOpener(bound(null))); // the pane unbinds while SCR-102 is open: the TopBar drops the trigger
    expect(screen.queryByRole("button", { name: /^Symbol/ })).toBeNull();
    key("Escape");
    expect(document.activeElement).toBe(panel);
    act(() => setSymbolOpener(bound(CHART_1)));
    press(trigger());
    act(() => {
      panel.remove(); // the workspace leaves: its panel and its opener go in one commit
      setSymbolOpener(null);
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("main"));
    expect(open).not.toHaveBeenCalled();
  });

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
    expect(within(recent).getByRole("option")).toHaveAccessibleName("ETHUSDT, ETH / USDT");
    key("ArrowDown");
    key("Enter", { shiftKey: true });
    expect(open).toHaveBeenLastCalledWith("ETHUSDT", "new-chart");
    expect(polite()).toContain("Opened ETHUSDT in a new chart.");
  });

  it("§6.2's commit sentence: an armed pane adds 'Chart trading locked.'; a lost link adds the resume line", async () => {
    const { open } = await shell({ ...CHART_1, armed: true });
    press(trigger());
    expect(within(screen.getByRole("dialog")).getByText("ARMED")).toBeVisible(); // the chip's pill (D-10)
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
    expect(luna).toHaveAccessibleName("LUNAUSDT, Delisted by the exchange"); // the chip's words
    expect(luna).toHaveAccessibleDescription("LUNAUSDT is not trading on Bybit. Status: Closed.");
    expect(fresh).toHaveAccessibleName("NEWUSDT"); // pre-launch is not delisted: no chip
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
    setSymbolOpener({ target: null, open: vi.fn() }); // the first opener: the read starts, once
    setSymbolOpener({ target: CHART_1, open: vi.fn() });
    expect(fake.start).toHaveBeenCalledTimes(1);
    end();
    expect([fake.stop.mock.calls.length, getSymbolSearchState().index]).toEqual([1, null]);
    const rows = [800, 1080].flatMap((h) => [visibleRows(h, false), visibleRows(h, true)]);
    expect(rows).toEqual([16, 11, 16, 12]);
  });
});
