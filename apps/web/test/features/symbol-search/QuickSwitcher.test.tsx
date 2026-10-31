/**
 * E08-S09 PR D: SCR-041 Quick-switcher (E08-D05 §7, §8, §9, §12.1, D-10) on SCR-102's session (PR C2) over a fake
 * instrument index, its checks and lookups on a faked `apiFetch` (no network): absent until a chart is bound and the
 * index runs, the popover on that chart toolbar's CMP-219, the commit to that chart only, §8's key root, the compact
 * states and the shared deck, the analytics seam, axe, and no layout read while typing.
 */
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useState, type JSX, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";
import type {
  IndexSnapshot,
  InstrumentIndex,
} from "../../../src/features/symbol-search/instrumentIndex";
import {
  QuickSwitcher,
  type QuickSwitcherChart,
} from "../../../src/features/symbol-search/QuickSwitcher";
import { toEntry, type Instrument } from "../../../src/features/symbol-search/ranking";
import {
  getSymbolSearchState,
  rememberSymbol,
  resetSymbolSearch,
  setSymbolInfo,
  setSymbolOpener,
  startSymbolSearch,
  type SymbolOpener,
} from "../../../src/features/symbol-search/searchSession";
import { KeymapHost, registerCommand } from "../../../src/keymap/KeymapHost";
import { resetShellState, setShellState, type Me } from "../../../src/shell/bootstrap/store";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as {
  run: (
    el: Element,
    o?: object,
  ) => Promise<{ violations: { id: string; impact?: string | null }[] }>;
};

type Status = NonNullable<Instrument["status"]>;
const inst = (symbol: string, tick: string, status: Status = "Trading"): Instrument => ({
  symbol,
  category: "linear",
  status,
  base_coin: symbol.slice(0, -4),
  quote_coin: "USDT",
  tick_size: tick,
  qty_step: "0.001",
  max_leverage: "100.00",
  funding_interval_minutes: 480,
});
/** E08-D05 §4's fixture symbols, each its own tick (LUNAUSDT Closed, known from Recent) and its illustrative ETHFIUSDT. */
const READY: IndexSnapshot = {
  phase: "ready",
  entries: [
    inst("BTCUSDT", "0.10"),
    inst("ETHUSDT", "0.01"),
    inst("ETHFIUSDT", "0.001"),
    inst("SOLUSDT", "0.0001"),
  ].map((i) => toEntry(i)),
  known: [toEntry(inst("LUNAUSDT", "0.10", "Closed"))],
  unlisted: [],
  loadedAt: 0,
  cacheAgeS: 0,
  staleSince: null,
  refreshing: false,
  retryAt: null,
  failure: null,
};
const FAILED: Partial<IndexSnapshot> = {
  phase: "failed",
  entries: [],
  known: [],
  failure: { cause: "network" },
};
const CHART_1: QuickSwitcherChart = {
  pane: "Chart 1",
  symbol: "BTCUSDT",
  interval: "1m",
  intervalWords: "1 minute",
  armed: false,
};
const CHART_2: QuickSwitcherChart = {
  pane: "Chart 2",
  symbol: "SOLUSDT",
  interval: "5m",
  intervalWords: "5 minutes",
  armed: false,
};
const ME = { role: "owner", permissions: [], user: { username: "robin" } } as unknown as Me;
/** The fake clock's start, 13:02 UTC: the waits and the check's time count from here. */
const T0 = Date.UTC(2026, 9, 30, 13, 2);
/** A test that runs axe: jsdom's axe takes seconds on a loaded runner. */
const AXE_MS = 15_000;

type Commit = SymbolOpener["open"];
interface Setup {
  readonly chart?: Partial<QuickSwitcherChart>;
  readonly index?: Partial<IndexSnapshot>;
  readonly recent?: readonly string[];
  readonly strip?: ReactNode;
}

let stop = (): void => undefined;

/**
 * SCR-102's session over a fake index: the shell's start, `/me` answered and, with `bind`, a workspace's opener, which
 * runs the index (C2's absence rule); Recent newest first. `put` moves the index on and tells its subscribers.
 */
function session({ index: first = {}, recent = ["ETHUSDT", "LUNAUSDT"] }: Setup = {}, bind = true) {
  let snap: IndexSnapshot = { ...READY, ...first };
  const told = new Set<() => void>();
  const index: InstrumentIndex = {
    subscribe: (fn) => {
      told.add(fn);
      return () => void told.delete(fn);
    },
    getSnapshot: () => snap,
    ...{ start: vi.fn(), stop: vi.fn(), reread: vi.fn(), learn: vi.fn() },
  };
  stop = startSymbolSearch(index);
  [...recent].reverse().forEach((symbol) => rememberSymbol(symbol));
  setShellState({ me: ME });
  const bound = (): void => act(() => setSymbolOpener({ target: CHART_1, open: vi.fn() }));
  if (bind) bound();
  const put = (patch: Partial<IndexSnapshot>): void =>
    act(() => {
      snap = { ...snap, ...patch };
      told.forEach((fn) => fn());
    });
  return { index, put, bound };
}

/** Two charts, each with its toolbar's SCR-041, on the session; the shell's announcer and keymap host. */
function charts(setup: Setup = {}) {
  const { index, put } = session(setup);
  const [one, two] = [vi.fn<Commit>(), vi.fn<Commit>()];
  const panes: readonly (readonly [QuickSwitcherChart, Commit])[] = [
    [{ ...CHART_1, ...setup.chart }, one],
    [CHART_2, two],
  ];
  render(
    <>
      {panes.map(([own, onCommit]) => (
        <section key={own.pane} aria-label={own.pane} data-keymap-context="Chart" tabIndex={-1}>
          <QuickSwitcher chart={own} onCommit={onCommit} strip={setup.strip} />
        </section>
      ))}
      <ShellAnnouncer />
      <KeymapHost />
    </>,
  );
  return { index, one, two, put };
}

const trigger = (pane = "Chart 1"): HTMLElement =>
  within(screen.getByRole("region", { name: pane })).getByRole("button", { name: /^Symbol: / });
const press = (node: HTMLElement): void =>
  act(() => {
    fireEvent.pointerDown(node);
    node.focus();
    fireEvent.pointerUp(node);
    fireEvent.click(node);
  });
/** `charts`, with Chart 1's popover opened by a press on its trigger. */
const opened = (setup: Setup = {}): ReturnType<typeof charts> => {
  const made = charts(setup);
  press(trigger());
  return made;
};
const dialog = (pane = "Chart 1"): HTMLElement =>
  screen.getByRole("dialog", { name: `Change symbol and interval, ${pane}` });
const input = (): HTMLInputElement =>
  screen.getByRole<HTMLInputElement>("combobox", { name: "Search symbols" });
const key = (k: string, init: object = {}, on?: HTMLElement): void =>
  void act(() => fireEvent.keyDown(on ?? input(), { key: k, ...init }));
const type = (text: string): void =>
  void act(() => fireEvent.change(input(), { target: { value: text } }));
/** The shell's polite region (the commit's sentence). */
const polite = (): string =>
  [...document.querySelectorAll('[aria-live="polite"]')].map((n) => n.textContent).join("");
/** CMP-160's polite region: the surface's one (§9.2). */
const region = (): Element | null =>
  dialog().querySelector('[data-cmp="CMP-160"] > [role="status"]');
const toasts = (): number => {
  const stack = screen.queryByRole("region", { name: "Notifications" });
  return stack === null ? 0 : within(stack).queryAllByRole("group").length;
};
/** The preview's tick ("tick 0.10"), if a preview shows. */
const tick = (): string | undefined => dialog().textContent?.match(/tick [\d.]+/)?.[0];
/** Lets an answer land on the fake clock. */
const answered = async (): Promise<void> => {
  await act(() => vi.advanceTimersByTimeAsync(0));
};
/** A-D05-6's rest on the fake clock. */
const rest = async (): Promise<void> => {
  await act(() => vi.advanceTimersByTimeAsync(300));
};
/** jsdom has no transition: the open surface is given the popover's own (0.1 s, `--motion-duration-fast`). */
const fading = (): HTMLElement => {
  const panel = dialog();
  panel.style.transitionDuration = "0.1s";
  return panel;
};
/** Closed, the surface is `hidden`; its body is still there until the fade ends (CMP-017's exit fade). */
const kept = (panel: HTMLElement): HTMLElement =>
  within(panel).getByRole("combobox", { hidden: true });

/** The words a control draws (its text outside `.cv-visually-hidden`), lower case, letters and digits only. */
const drawn = (node: Node): string =>
  [...node.childNodes]
    .map((child) => {
      if (child.nodeType === Node.TEXT_NODE) return child.nodeValue ?? "";
      return child instanceof Element && !child.matches(".cv-visually-hidden") ? drawn(child) : "";
    })
    .join("");
const words = (text: string): string[] =>
  text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .split(" ")
    .filter(Boolean);

beforeEach(() => {
  resetShellState();
  clearAnnouncements();
  apiFetch.mockReset();
  apiFetch.mockImplementation(() => Promise.resolve(new Response(null, { status: 404 })));
});
afterEach(() => {
  stop();
  resetSymbolSearch();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("SCR-041 quick-switcher (E08-S09 PR D)", () => {
  it("a press on the toolbar's CMP-219 opens its chart's popover: §9.1's name, the current symbol selected", () => {
    opened();
    const panel = dialog();
    expect([panel.getAttribute("aria-modal"), trigger().getAttribute("aria-expanded")]).toEqual([
      null,
      "true",
    ]);
    expect(
      within(panel).getByRole("heading", { name: "Change symbol and interval" }),
    ).toBeVisible();
    expect(within(panel).getByText("Chart 1 · BTCUSDT 1m")).toBeVisible();
    const field = input();
    expect([field.value, field.selectionStart, field.selectionEnd]).toEqual(["BTCUSDT", 0, 7]);
    expect(field).toHaveFocus();
  });

  it("idle, it shows the session's Recent (a delisted one reached, never chosen), the strip's slot, the preview", () => {
    opened({ strip: <p>Interval slot</p> });
    const recent = within(dialog()).getByRole("group", { name: "Recent" });
    expect(
      within(recent)
        .getAllByRole("option")
        .map((o) => o.getAttribute("aria-label")),
    ).toEqual([
      "ETHUSDT, ETH / USDT, recent",
      "LUNAUSDT, LUNA / USDT, Delisted by the exchange, recent",
    ]);
    const luna = within(recent).getByRole("option", { name: /^LUNAUSDT/ });
    expect(luna).toHaveAttribute("aria-disabled", "true");
    expect(luna).toHaveAccessibleDescription("LUNAUSDT is not trading on Bybit. Status: Closed.");
    // B15's order: the list, the strip's slot (E12-D02 NC-10), then the current symbol's preview (D-8: no ticker held).
    expect(dialog().textContent).toMatch(
      /LUNAUSDT.*Interval slot.*tick 0\.10 · lot 0\.001 · max leverage 100× · funding every 8 h · 24 h turnover —/,
    );
  });

  it("closes on the open trigger's press, Esc or a press outside, without commit, focus back on the trigger", () => {
    const { one } = charts();
    const outside = (): void =>
      act(() => {
        fireEvent.pointerDown(document.body);
        fireEvent.pointerUp(document.body);
      });
    for (const close of [() => press(trigger()), () => key("Escape"), outside]) {
      press(trigger());
      expect(input().value).toBe("BTCUSDT"); // each opening starts from the chart's symbol (§7)
      type("eth");
      key("ArrowDown");
      close();
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(trigger()).toHaveFocus();
    }
    expect(one).not.toHaveBeenCalled();
  });

  it("non-modal: Tab out closes it without commit, focus on the next stop; Shift+Tab, back on its trigger", () => {
    const { one } = opened();
    key("Tab");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger("Chart 2")).toHaveFocus();
    press(trigger());
    key("Tab", { shiftKey: true });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger()).toHaveFocus();
    expect([one.mock.calls, toasts()]).toEqual([[], 0]);
  });

  it("absent with no chart bound: no trigger, no placeholder", () => {
    session();
    const { container } = render(<QuickSwitcher chart={null} onCommit={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
    expect(document.body.querySelector("[role='dialog'], button")).toBeNull();
  });

  it("CR-CD-01: absent while the shell holds its index unrun; the trigger shows once a bound opener runs it", () => {
    const { bound } = session({}, false);
    render(<QuickSwitcher chart={CHART_1} onCommit={vi.fn()} />);
    expect([getSymbolSearchState().index, screen.queryByRole("button")]).toEqual([
      expect.anything(),
      null,
    ]);
    bound();
    expect(screen.getByRole("button", { name: "Symbol: BTCUSDT, 1 minute" })).toBeVisible();
  });

  it("CR-D-04: a host opens it with no press (`/`, #305) and closes it on its request; each opening starts afresh", () => {
    session();
    const asked = vi.fn<(open: boolean) => void>();
    function Host(): JSX.Element {
      const [open, setOpen] = useState(false);
      const change = (next: boolean): void => {
        asked(next);
        setOpen(next);
      };
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Slash
          </button>
          <QuickSwitcher chart={CHART_1} onCommit={vi.fn()} open={open} onOpenChange={change} />
        </>
      );
    }
    render(<Host />);
    const slash = screen.getByRole("button", { name: "Slash" });
    act(() => slash.click());
    expect(input()).toHaveFocus();
    type("eth");
    key("Escape");
    expect([asked.mock.calls, screen.queryByRole("dialog")]).toEqual([[[false]], null]);
    act(() => slash.click());
    expect(input().value).toBe("BTCUSDT");
  });
});

describe("SCR-041's commit (§6.2, §7, D-9, D-10)", () => {
  it("each chart's trigger opens its own: eth, ↓, Enter commits to that chart only, said, focus back on its trigger", () => {
    const { one, two } = charts();
    press(trigger("Chart 2"));
    expect(dialog("Chart 2")).toBeVisible();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    type("eth");
    key("ArrowDown");
    key("Enter");
    expect([one.mock.calls, two.mock.calls]).toEqual([[], [["ETHUSDT", "target"]]]);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger("Chart 2")).toHaveFocus();
    expect(polite()).toBe("Chart 2 now shows ETHUSDT, 5 minutes.");
  });

  it("D-9: a commit joins the session's one Recent list, which SCR-102 shares", () => {
    charts();
    press(trigger("Chart 2"));
    type("ethfi");
    key("ArrowDown");
    key("Enter");
    press(trigger());
    const recent = within(dialog()).getByRole("group", { name: "Recent" });
    expect(within(recent).getAllByRole("option")[0]).toHaveAccessibleName(
      "ETHFIUSDT, ETHFI / USDT, recent",
    );
    expect(getSymbolSearchState().recent).toEqual(["ETHFIUSDT", "ETHUSDT", "LUNAUSDT"]);
  });

  it("D-10, CR-D-05: an armed chart's ARMED pill, and its line describes the input before any switch", () => {
    opened({ chart: { armed: true } });
    expect(within(dialog()).getByText("ARMED")).toBeVisible();
    expect(input()).toHaveAccessibleDescription("Switching locks chart trading on Chart 1.");
  });

  it("D-10: a commit on an armed chart says 'Chart trading locked.'", () => {
    opened({ chart: { armed: true } });
    type("eth");
    key("ArrowDown");
    key("Enter");
    expect(polite()).toBe("Chart 1 now shows ETHUSDT, 1 minute. Chart trading locked.");
  });

  it("Shift+Enter opens a new chart at this chart's interval; a lost link adds the resume clause", () => {
    const { one } = charts();
    act(() => setShellState({ connection: { kind: "offline", cause: "offline" } }));
    press(trigger());
    type("eth");
    key("ArrowDown");
    key("Enter", { shiftKey: true });
    expect(one.mock.calls).toEqual([["ETHUSDT", "new-chart"]]);
    expect(polite()).toBe(
      "Opened ETHUSDT in a new chart. Live data resumes when the connection returns.",
    );
  });

  it("D-6: Enter and Shift+Enter on the delisted Recent row commit nothing, keep it open, and each says why", () => {
    const { one } = opened();
    key("ArrowDown");
    key("ArrowDown"); // ETHUSDT, then LUNAUSDT
    key("Enter");
    const why = "LUNAUSDT is not trading on Bybit. Status: Closed.";
    const said = region()?.firstChild;
    expect(said?.textContent).toBe(why);
    key("Enter", { shiftKey: true });
    expect([region()?.textContent, region()?.firstChild === said]).toEqual([why, false]); // said again
    expect([one.mock.calls, screen.queryAllByRole("dialog").length]).toEqual([[], 1]);
  });

  it("CR-D-01: typing with no row active previews nothing; ↓ previews the active row, never the chart's own", () => {
    opened();
    expect(tick()).toBe("tick 0.10"); // BTCUSDT's, while the input holds it
    type("eth");
    expect(tick()).toBeUndefined();
    key("ArrowDown");
    expect(tick()).toBe("tick 0.01"); // ETHUSDT's
  });
});

describe("SCR-041's key root (§8)", () => {
  it("keys typed in it stop at its root, §8's QA list included, so the toast host stays empty", () => {
    opened();
    for (const k of [..."btc/usdt", " ", "f", "ArrowLeft", "ArrowRight", "Home", "End", "Delete"])
      key(k);
    key("Enter");
    for (const k of ["a", "z", "y", "ArrowLeft", "ArrowRight"]) key(k, { ctrlKey: true });
    for (const k of ["ArrowLeft", "ArrowRight"]) key(k, { shiftKey: true });
    expect(toasts()).toBe(0);
    expect(dialog()).toBeVisible();
  });

  it("Ctrl+K closes it without commit and goes on to the palette; outside it, the keymap still reports a key", () => {
    const palette = vi.fn();
    onTestFinished(registerCommand("global.palette", palette));
    const { one } = opened();
    key("k", { ctrlKey: true });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect([palette.mock.calls.length, one.mock.calls.length]).toEqual([1, 0]);
    act(() => void fireEvent.keyDown(document.body, { key: "f" }));
    expect(toasts()).toBe(1);
  });

  it("A11Y-D-03: the root holds the popover's surface and heading too, so keys pressed there never reach the keymap", () => {
    const seen = vi.fn();
    window.addEventListener("keydown", seen);
    onTestFinished(() => window.removeEventListener("keydown", seen));
    opened();
    act(() => dialog().focus()); // a press on its text focuses the surface
    key("f", {}, dialog());
    const heading = within(dialog()).getByRole("heading", { name: "Change symbol and interval" });
    act(() => heading.focus());
    key("b", {}, heading);
    expect([seen.mock.calls.length, toasts()]).toEqual([0, 0]);
    expect(dialog()).toBeVisible();
  });

  it("A11Y-D-03: the trigger shares the root and keeps its keys: closed, a key on it reaches the window keymap", () => {
    const seen = vi.fn();
    window.addEventListener("keydown", seen);
    onTestFinished(() => window.removeEventListener("keydown", seen));
    charts();
    key("f", {}, trigger());
    expect(seen).toHaveBeenCalledOnce();
  });
});

describe("SCR-041's compact states (§6.2, §7)", () => {
  it("Loading is one line, then the 503 line with its wait from the snapshot's arrival; never 'no matches'", () => {
    vi.useFakeTimers({ now: T0 });
    const { put } = opened({ index: { phase: "loading", entries: [], known: [] } });
    type("eth");
    expect(dialog()).toHaveTextContent("Loading the instrument list…");
    put({ retryAt: T0 + 4_000 });
    expect(dialog()).toHaveTextContent(
      "CandleViewer's server is loading the instrument list from Bybit — next try in 4 s.",
    );
    expect(dialog()).not.toHaveTextContent("No USDT");
    expect(within(dialog()).queryByRole("option")).toBeNull();
  });

  it("Load failed is CMP-026's alert with Retry now, which re-reads the list", () => {
    const { index } = opened({ index: FAILED });
    expect(within(dialog()).getByRole("alert")).toHaveTextContent(
      "Couldn't load the instrument list.",
    );
    act(() => within(dialog()).getByRole("button", { name: "Retry now" }).click());
    expect(index.reread).toHaveBeenCalledOnce();
  });

  it("A11Y-D-02: Retry now goes with Load failed when the list arrives, and focus goes to the input, not the page", () => {
    const { put } = opened({ index: FAILED });
    const retry = within(dialog()).getByRole("button", { name: "Retry now" });
    act(() => retry.focus());
    act(() => retry.click());
    put({ ...READY });
    expect(retry.isConnected).toBe(false);
    expect(input()).toHaveFocus();
  });

  it("the first run: with no Recent, its two lines stand in the list's place", () => {
    opened({ recent: [] });
    for (const line of [
      "Type a symbol or base asset, for example BTC.",
      "Your recent symbols appear here.",
    ])
      expect(within(dialog()).getByText(line)).toBeVisible();
  });

  it("§6.2: Enter with no openable option is inert and says the state's heading again", () => {
    const { one } = opened({ recent: [] });
    const said = region()?.firstChild ?? null;
    key("Enter");
    expect([region()?.textContent, region()?.firstChild === said]).toEqual([
      "Type a symbol or base asset, for example BTC.",
      false,
    ]);
    expect([one.mock.calls, screen.queryAllByRole("dialog").length]).toEqual([[], 1]);
  });

  it("§6.2 Refreshing: a re-read's rows wait for the next keystroke, so the list and its active row stay put", () => {
    const { put } = opened();
    type("eth");
    key("ArrowDown");
    const rows = (): number => within(dialog()).getAllByRole("option").length;
    put({ entries: [...READY.entries, toEntry(inst("ETHWUSDT", "0.01"))], loadedAt: 1 });
    expect(rows()).toBe(2);
    expect(within(dialog()).getByRole("option", { selected: true })).toHaveAccessibleName(
      /^ETHUSDT/,
    );
    type("eth ");
    expect(rows()).toBe(3);
  });

  it("B19: a delisted current value is struck in the input, which its sentence describes; no preview", () => {
    opened({ chart: { symbol: "LUNAUSDT", delisted: true } });
    expect([input().value, input().style.textDecoration]).toEqual(["LUNAUSDT", "line-through"]);
    expect(input()).toHaveAccessibleDescription(
      "LUNAUSDT is not trading on Bybit — choose another symbol.",
    );
    expect(tick()).toBeUndefined();
    type("e");
    expect(input().style.textDecoration).toBe("");
  });

  it("§3 row 2: a Recent missing from the listing is looked up once a session; its 404 reads no longer listed", async () => {
    vi.useFakeTimers({ now: T0 });
    const { index, put } = opened({ recent: ["GONEUSDT"] });
    await answered();
    expect(apiFetch.mock.calls.map(([url]) => url)).toEqual(["/api/v1/instruments/GONEUSDT"]);
    expect(index.learn).toHaveBeenCalledWith({ kind: "not_listed", symbol: "GONEUSDT" });
    put({ unlisted: ["GONEUSDT"] }); // the index learnt it
    expect(within(dialog()).getByRole("option", { name: /^GONEUSDT/ })).toHaveAccessibleDescription(
      "GONEUSDT is no longer listed on Bybit.",
    );
  });
});

describe("SCR-041 on the shared deck (§6.2: the check, No matches, the status rule)", () => {
  /** V9 to the 404 of XYZZYUSDT at 13:02 UTC on the fake clock: Check again, T2 for the next 60 s. */
  const checkedGone = async (): Promise<() => HTMLElement> => {
    vi.useFakeTimers({ now: T0 });
    opened();
    type("xyzzy");
    await rest();
    await answered();
    return () => within(dialog()).getByRole("button", { name: "Check again" });
  };
  const checking = (): string[] =>
    within(dialog())
      .queryAllByText("Checking Bybit for XYZZYUSDT…")
      .map((node) => node.tagName);

  it("V9: the rest sends and says nothing; then one check of XYZZYUSDT, its line in the list's place, said once", async () => {
    vi.useFakeTimers({ now: T0 });
    apiFetch.mockImplementation(() => new Promise<Response>(() => undefined)); // the check stays in flight
    opened();
    type("xyzzy");
    await act(() => vi.advanceTimersByTimeAsync(299));
    expect([apiFetch.mock.calls.length, region()?.textContent]).toEqual([0, ""]);
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(apiFetch.mock.calls.map(([url]) => url)).toEqual(["/api/v1/instruments/XYZZYUSDT"]);
    expect(checking()).toEqual(["P", "SPAN"]); // drawn, and said once in the region
  });

  it("V9: the check's 404 is the No matches block, verbatim, and its sentence is said", async () => {
    await checkedGone();
    expect(within(dialog()).getByRole("heading", { level: 3 })).toHaveTextContent(
      "No USDT perpetual matches 'xyzzy'.",
    );
    expect(dialog()).toHaveTextContent(
      "v1 supports Bybit USDT linear perpetuals only. Search by base asset, for example BTC. Checked with the server at 13:02 UTC.",
    );
    expect(region()?.textContent).toBe(
      "No USDT perpetual matches 'xyzzy'. v1 supports Bybit USDT linear perpetuals only.",
    );
  });

  it("V9, G-T2: Check again is T2 search.check_cooldown, aria-disabled and described; a press sends nothing, says why", async () => {
    const again = await checkedGone();
    expect([again().getAttribute("aria-disabled"), again().hasAttribute("disabled")]).toEqual([
      "true",
      false,
    ]);
    expect(again()).toHaveAccessibleDescription("Checked a moment ago.");
    act(() => again().click());
    expect(apiFetch).toHaveBeenCalledTimes(1);
    const said = within(dialog())
      .getAllByRole("status")
      .map((node) => node.textContent);
    expect(said).toContain("Checked a moment ago."); // CMP-026's own press region (G-T2.3)
  });

  it("V9: Check again lifts in place once the 60 s are up", async () => {
    const again = await checkedGone();
    const button = again();
    await act(() => vi.advanceTimersByTimeAsync(60_000));
    expect([button.isConnected, button.hasAttribute("aria-disabled")]).toEqual([true, false]);
  });

  it("A11Y-D-01: Check again keeps its block and the focus while it runs and once answered; its line beside it", async () => {
    const again = await checkedGone();
    await act(() => vi.advanceTimersByTimeAsync(60_000));
    let answer: (res: Response) => void = () => undefined;
    apiFetch.mockImplementationOnce(
      () =>
        new Promise<Response>((done) => {
          answer = done;
        }),
    );
    const button = again();
    act(() => button.focus());
    act(() => button.click());
    expect([apiFetch.mock.calls.length, button.isConnected, checking()]).toEqual([
      2,
      true,
      ["P", "SPAN"],
    ]);
    expect(button).toHaveFocus();
    await act(async () => answer(new Response(null, { status: 404 })));
    await answered();
    expect(button).toHaveFocus();
  });

  it("§6.2: a check with no usable answer (a 503) says so in the No matches block", async () => {
    vi.useFakeTimers({ now: T0 });
    apiFetch.mockImplementation(() => Promise.resolve(new Response(null, { status: 503 })));
    opened();
    type("xyzzy");
    await rest();
    await answered();
    expect(dialog()).toHaveTextContent("Couldn't check Bybit for XYZZYUSDT just now.");
  });

  it("A11Y-D-04: an unchecked no-match ('xy', too short) is said once its query rests, never per keystroke", async () => {
    vi.useFakeTimers({ now: T0 });
    opened();
    type("x");
    type("xy");
    expect(within(dialog()).getByRole("heading", { level: 3 })).toHaveTextContent(
      "No USDT perpetual matches 'xy'.",
    );
    expect(region()?.textContent).toBe("");
    await rest();
    expect(region()?.textContent).toBe(
      "No USDT perpetual matches 'xy'. v1 supports Bybit USDT linear perpetuals only.",
    );
    expect(apiFetch).not.toHaveBeenCalled(); // V10: nothing to check
  });

  it("CR-DD2-03: a query is rested only after its own rest: back at the one that rested last, it is quiet again", async () => {
    vi.useFakeTimers({ now: T0 });
    opened();
    const sentence = (query: string): string =>
      `No USDT perpetual matches '${query}'. v1 supports Bybit USDT linear perpetuals only.`;
    type("xy");
    await rest();
    expect(region()?.textContent).toBe(sentence("xy"));
    type("xyz");
    await act(() => vi.advanceTimersByTimeAsync(100)); // inside xyz's rest
    type("xy"); // the query that rested last, but not yet for this keystroke
    expect(region()?.textContent).toBe("");
    await act(() => vi.advanceTimersByTimeAsync(299));
    expect(region()?.textContent).toBe("");
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(region()?.textContent).toBe(sentence("xy"));
  });

  it("§6.2: Enter with no option active on No matches says its heading again", async () => {
    await checkedGone();
    key("Enter");
    expect(region()?.textContent).toBe("No USDT perpetual matches 'xyzzy'.");
  });

  it("CR-DD-02, §3 row 2: a query naming a remembered symbol the session found gone says so, checks nothing", async () => {
    vi.useFakeTimers({ now: T0 });
    const { put } = opened({ recent: ["GONEUSDT"] });
    await answered(); // the session's one lookup: a 404
    put({ unlisted: ["GONEUSDT"] }); // the index learnt it
    type("gone");
    await rest();
    await answered();
    expect(within(dialog()).getByRole("heading", { level: 3 })).toHaveTextContent(
      "GONEUSDT is no longer listed on Bybit.",
    );
    const buttons = within(dialog()).getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual(["Clear search"]); // no Check again
    expect(apiFetch.mock.calls.map(([url]) => url)).toEqual(["/api/v1/instruments/GONEUSDT"]);
  });

  it("CR-DD-02, §9.2: a heading said again is forgotten once its query moves on, and not said when it returns", async () => {
    vi.useFakeTimers({ now: T0 });
    opened();
    const sentence = "v1 supports Bybit USDT linear perpetuals only.";
    type("xy");
    await rest();
    key("Enter"); // No matches' heading, said again over its sentence
    expect(region()?.textContent).toBe("No USDT perpetual matches 'xy'.");
    type("xyz"); // the query moves on
    type("xy"); // and comes back, to the same query and state
    await rest();
    expect(region()?.textContent).toBe(`No USDT perpetual matches 'xy'. ${sentence}`);
  });

  it("§6.2's status rule: luna names a known Closed symbol; Clear search goes back to Recent, focus in the input", () => {
    opened();
    type("luna");
    expect(within(dialog()).getByRole("heading", { level: 3 })).toHaveTextContent(
      "LUNAUSDT is not trading on Bybit.",
    );
    expect(dialog()).toHaveTextContent("Status: Closed. It can't be opened as a new chart.");
    expect(within(dialog()).queryByRole("option")).toBeNull();
    act(() => within(dialog()).getByRole("button", { name: "Clear search" }).click());
    expect(input()).toHaveFocus();
    expect(input().value).toBe("");
    expect(within(dialog()).getByRole("group", { name: "Recent" })).toBeVisible();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("§6.2's status rule: View symbol info once SCR-103's port is registered, opened from scr-041, closing it", () => {
    charts();
    const info = vi.fn();
    act(() => setSymbolInfo({ open: info }));
    press(trigger());
    type("luna");
    act(() => within(dialog()).getByRole("button", { name: "View symbol info" }).click());
    expect(info).toHaveBeenCalledWith("LUNAUSDT", { source: "scr-041" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("teardown: closing it mid-check aborts the lookup in flight", async () => {
    vi.useFakeTimers({ now: T0 });
    const signals: AbortSignal[] = [];
    apiFetch.mockImplementation((_url, init) => {
      if (init?.signal) signals.push(init.signal);
      return new Promise<Response>(() => undefined);
    });
    opened();
    type("xyzzy");
    await rest();
    expect(signals.map((signal) => signal.aborted)).toEqual([false]);
    key("Escape");
    expect(signals.map((signal) => signal.aborted)).toEqual([true]);
  });

  describe("CR-DD-03: CMP-017 keeps its body through the exit fade, and nothing is looked up for it then", () => {
    it("Esc before the check's rest is up sends no lookup", async () => {
      vi.useFakeTimers({ now: T0 });
      opened();
      const panel = fading();
      type("xyzzy");
      await act(() => vi.advanceTimersByTimeAsync(250));
      key("Escape");
      expect(kept(panel)).toBeInTheDocument();
      await act(() => vi.advanceTimersByTimeAsync(500)); // the rest, then the fade, are over
      expect(apiFetch).not.toHaveBeenCalled();
    });

    it("Esc with a lookup in flight aborts it at once, not when the fade ends", async () => {
      vi.useFakeTimers({ now: T0 });
      const signals: AbortSignal[] = [];
      apiFetch.mockImplementation((_url, init) => {
        if (init?.signal) signals.push(init.signal);
        return new Promise<Response>(() => undefined);
      });
      opened();
      const panel = fading();
      type("xyzzy");
      await rest();
      key("Escape");
      expect(kept(panel)).toBeInTheDocument();
      expect(signals.map((signal) => signal.aborted)).toEqual([true]);
    });

    it("CR-DD2-01: a re-read that lands in the fade asks nothing of the abandoned query", async () => {
      vi.useFakeTimers({ now: T0 });
      const { put } = opened();
      const panel = fading();
      type("sol"); // ranks SOLUSDT: nothing to check
      key("Escape");
      expect(kept(panel)).toBeInTheDocument();
      put({ entries: READY.entries.filter((entry) => entry.symbol !== "SOLUSDT") }); // now it ranks nothing
      await act(() => vi.advanceTimersByTimeAsync(500));
      expect(apiFetch).not.toHaveBeenCalled();
    });
  });
});

describe("SCR-041's §12.1 analytics on the app's cv:analytics seam (SCR-102's)", () => {
  const analytics = (): Record<string, unknown>[] => {
    const events: Record<string, unknown>[] = [];
    const take = (event: Event): void =>
      void events.push((event as CustomEvent<Record<string, unknown>>).detail);
    window.addEventListener("cv:analytics", take);
    onTestFinished(() => window.removeEventListener("cv:analytics", take));
    return events;
  };

  it("symbol.searched once the query has rested 300 ms: surface scr-041, its length and never the query", async () => {
    const events = analytics();
    vi.useFakeTimers({ now: T0 });
    opened();
    type("eth");
    await act(() => vi.advanceTimersByTimeAsync(299));
    expect(events).toEqual([]);
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(events).toEqual([
      {
        ...{ name: "symbol.searched", surface: "scr-041", query_length: 3, result_count: 2 },
        ...{ top_tier: 1, catalogue_state: "ready" },
      },
    ]);
    expect(JSON.stringify(events)).not.toContain("eth");
  });

  it("CR-DD2-02: a query abandoned inside its rest is not reported, though CMP-017's body outlives the close", async () => {
    const events = analytics();
    vi.useFakeTimers({ now: T0 });
    opened();
    const panel = fading();
    type("eth");
    await act(() => vi.advanceTimersByTimeAsync(250));
    key("Escape");
    expect(kept(panel)).toBeInTheDocument(); // still mounted when the 300 ms are up
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(events).toEqual([]);
  });

  it("symbol.search_result_opened on each commit: its group, rank, tier and how it came in", () => {
    const events = analytics();
    opened();
    type("eth");
    key("ArrowDown");
    key("Enter");
    press(trigger());
    press(within(dialog()).getByRole("option", { name: /^ETHUSDT/ })); // Recent's first
    expect(events.filter((event) => event["name"] === "symbol.search_result_opened")).toEqual([
      {
        ...{ name: "symbol.search_result_opened", surface: "scr-041", rank: 1, tier: 1 },
        ...{ group: "results", input: "key", action: "open" },
      },
      {
        ...{ name: "symbol.search_result_opened", surface: "scr-041", rank: 1, tier: null },
        ...{ group: "recent", input: "pointer", action: "open" },
      },
    ]);
  });

  it("empty_state_shown once per state entered: no matches, then the status rule", () => {
    const events = analytics();
    vi.useFakeTimers({ now: T0 });
    opened();
    type("x");
    type("xy"); // the same state
    type("luna");
    expect(events).toEqual([
      { name: "empty_state_shown", surface: "scr-041", reason: "no_matches" },
      { name: "empty_state_shown", surface: "scr-041", reason: "scope_filtered" },
    ]);
  });
});

describe("SCR-041's budgets and a11y (§5, §9)", () => {
  it("typing reads no layout: no rect, offset, client, scroll or computed-style read on any keystroke", () => {
    opened();
    const field = input();
    const reads = [
      vi.spyOn(Element.prototype, "getBoundingClientRect"),
      vi.spyOn(Element.prototype, "getClientRects"),
      vi.spyOn(window, "getComputedStyle"),
      ...(["offsetTop", "offsetLeft", "offsetWidth", "offsetHeight"] as const).map((p) =>
        vi.spyOn(HTMLElement.prototype, p, "get"),
      ),
      ...(["clientWidth", "clientHeight", "scrollWidth", "scrollHeight", "scrollTop"] as const).map(
        (p) => vi.spyOn(Element.prototype, p, "get"),
      ),
    ];
    for (const value of ["e", "et", "eth", "eth/", "eth/usdt", "s", "so", "luna", "x"])
      act(() => void fireEvent.change(field, { target: { value } })); // no getByRole: it reads styles
    expect(reads.map((spy) => spy.mock.calls.length)).toEqual(reads.map(() => 0));
    void field.getBoundingClientRect(); // the positive control: a read the spies see
    expect(reads[0]).toHaveBeenCalledOnce();
  });

  it(
    "axe finds no serious or critical issue open, typed or on the deck; every named control's name holds its words",
    async () => {
      opened();
      const audit = async (): Promise<string[]> => {
        const { violations } = await axe.run(document.body, {
          rules: { "color-contrast": { enabled: false } }, // jsdom has no layout
        });
        return violations
          .filter((v) => v.impact === "serious" || v.impact === "critical")
          .map((v) => v.id);
      };
      // axe's label-content-name-mismatch runs in CI's Chromium only: here each named control's drawn words are one
      // run of its name's words, in order.
      const misnamed = (): string[] =>
        [...document.querySelectorAll("button[aria-label], [role='option'][aria-label]")].flatMap(
          (node) => {
            const [seen, name] = [words(drawn(node)), words(node.getAttribute("aria-label") ?? "")];
            const held = name.some((_, at) => seen.every((word, i) => name[at + i] === word));
            return held ? [] : [node.getAttribute("aria-label") ?? ""];
          },
        );
      expect(
        document.querySelectorAll("button[aria-label], [role='option'][aria-label]"),
      ).toHaveLength(4);
      expect([await audit(), misnamed()]).toEqual([[], []]);
      type("eth");
      key("ArrowDown");
      expect([await audit(), misnamed()]).toEqual([[], []]);
      type("luna");
      expect([await audit(), misnamed()]).toEqual([[], []]);
    },
    AXE_MS,
  );
});
