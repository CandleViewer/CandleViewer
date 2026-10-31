import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Chart as ChartApi, ChartEvents, PriceScale } from "@candleviewer/chart-engine";
import { clearAnnouncements, ShellAnnouncer } from "../../../src/features/app-shell/announcer";
import { Chart } from "../../../src/chart";
import {
  PRICE_SCALE_MENU_EVENT,
  PriceScaleMenu,
  PriceScaleMenuHost,
} from "../../../src/features/chart-price-scale/PriceScaleMenu";
import { logReasonText } from "../../../src/features/chart-price-scale/copy";

// `<Chart>` mounts the fake below: the menu is tested against the engine's reported state.
const engine = vi.hoisted(() => ({ next: null as unknown }));
vi.mock("@candleviewer/chart-engine", () => ({ createChart: () => engine.next }));

// axe-core is a transitive dependency of @axe-core/playwright (already a devDependency).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

type ScaleState = ReturnType<PriceScale["getState"]>;
type Spied = {
  [K in "setAutoScale" | "setMode" | "setInverted" | "setOptions"]: ReturnType<typeof vi.fn>;
};

const AUTO_LINEAR: ScaleState = {
  mode: "linear",
  requestedMode: "linear",
  inverted: false,
  autoScale: true,
  includeDrawings: false,
  priceOnly: false,
  marginTop: 0.05,
  marginBottom: 0.05,
  logAvailable: true,
  logReason: null,
  anchorTick: null,
};
const NON_POSITIVE = "Log scale needs all-positive values; this series contains a value <= 0";

let state: ScaleState;
let scale: Spied;
let viewport: (() => void)[];
let container: HTMLDivElement;
let analytics: Record<string, unknown>[];
const onAnalytics = (e: Event): void => {
  analytics.push((e as CustomEvent<Record<string, unknown>>).detail);
};

function fakeChart(): ChartApi {
  scale = {
    setAutoScale: vi.fn(),
    setMode: vi.fn(),
    setInverted: vi.fn(),
    setOptions: vi.fn(),
  };
  // The setters move `state` as the engine would, so getState() after a change is the new state.
  scale.setAutoScale.mockImplementation((on: boolean) => {
    state = { ...state, autoScale: on };
  });
  scale.setMode.mockImplementation((m: ScaleState["mode"]) => {
    state = { ...state, mode: m, requestedMode: m };
  });
  scale.setInverted.mockImplementation((on: boolean) => {
    state = { ...state, inverted: on };
  });
  scale.setOptions.mockImplementation((o: Partial<ScaleState>) => {
    state = { ...state, ...o };
  });
  const priceScale = { ...scale, getVisibleRange: () => null, getState: () => ({ ...state }) };
  const subscribe = (e: keyof ChartEvents, cb: () => void): (() => void) => {
    if (e === "viewportChanged") viewport.push(cb);
    return () => {
      viewport = viewport.filter((f) => f !== cb);
    };
  };
  const panes = [{ id: "p0", priceScale }];
  return { panes, subscribe, dispose: () => undefined } as unknown as ChartApi;
}

function mount(initial: Partial<ScaleState> = {}): void {
  state = { ...AUTO_LINEAR, ...initial };
  render(
    <>
      <ShellAnnouncer />
      <PriceScaleMenuHost chart={fakeChart()} container={container} />
    </>,
  );
}

function openByEvent(byKey = false): void {
  act(() => {
    const detail = { pane: 0, x: 600, y: 40, byKey };
    container.dispatchEvent(new CustomEvent(PRICE_SCALE_MENU_EVENT, { bubbles: true, detail }));
  });
}

function openByKey(): void {
  container.focus();
  fireEvent.keyDown(container, { key: "F10", shiftKey: true });
}

const ROLES = ["menuitemradio", "menuitemcheckbox", "menuitem"] as const;
/** The menu item named `name`, whichever of the three item roles it has. */
const item = (name: string): HTMLElement => {
  for (const role of ROLES) {
    const found = screen.queryByRole(role, { name });
    if (found !== null) return found;
  }
  throw new Error(`no menu item ${name}`);
};
const menu = (): HTMLElement => screen.getByRole("menu", { name: "Price scale menu" });
const polite = (): HTMLElement => document.querySelector<HTMLElement>('[aria-live="polite"]')!; // ShellAnnouncer is rendered
const said = (): string => polite().textContent ?? "";
/** Counts the messages written into the polite region from now on (one node per message). */
function countSaid(): () => number {
  let n = 0;
  const observer = new MutationObserver((records) => {
    for (const r of records) n += [...r.addedNodes].filter((node) => node.nodeName === "P").length;
  });
  observer.observe(polite(), { childList: true });
  return () => {
    observer.takeRecords().forEach((r) => {
      n += [...r.addedNodes].filter((node) => node.nodeName === "P").length;
    });
    observer.disconnect();
    return n;
  };
}

beforeEach(() => {
  viewport = [];
  analytics = [];
  container = document.createElement("div");
  container.tabIndex = -1;
  container.getBoundingClientRect = () => new DOMRect(0, 0, 640, 480);
  document.body.append(container);
  window.addEventListener("cv:analytics", onAnalytics);
});

afterEach(() => {
  window.removeEventListener("cv:analytics", onAnalytics);
  container.remove();
  clearAnnouncements();
});

describe("PriceScaleMenu (SCR-043, E11-D03 §3)", () => {
  it("opens on the engine's gutter event with focus on the first item, in D03's order", () => {
    mount();
    expect(screen.queryByRole("menu")).toBeNull();
    openByEvent();
    const items = [...menu().querySelectorAll<HTMLElement>("[data-menu-item]")];
    expect(items.map((i) => i.getAttribute("role"))).toEqual([
      ...Array<string>(4).fill("menuitemradio"),
      ...Array<string>(4).fill("menuitemcheckbox"),
      "menuitem",
    ]);
    expect(items.map((i) => i.textContent)).toEqual([
      "Linear",
      "Logarithmic",
      "Percent",
      "Indexed to 100",
      "Lock scale",
      "Invert scale",
      "Merge indicator scales",
      "Scale price only",
      "Reset scale",
    ]);
    expect(document.activeElement).toBe(items[0]);
    expect(within(menu()).getByRole("group", { name: "Scale mode" })).toBeTruthy();
    expect(within(menu()).getByRole("group", { name: "Scale" })).toBeTruthy();
  });

  it("opens by key (byKey) and by Shift+F10 or the Menu key with focus in the chart", () => {
    mount();
    openByEvent(true);
    expect(document.activeElement).toBe(screen.getByRole("menuitemradio", { name: "Linear" }));
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    openByKey();
    expect(menu()).toBeTruthy();
    // The key's own contextmenu is swallowed once (no native menu, no engine reading of it).
    const ctx = new MouseEvent("contextmenu", { bubbles: true, cancelable: true });
    document.activeElement!.dispatchEvent(ctx);
    expect(ctx.defaultPrevented).toBe(true);
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    fireEvent.keyDown(container, { key: "ContextMenu" });
    expect(menu()).toBeTruthy();
  });

  it("ignores a malformed event, an unknown pane and a modified Shift+F10", () => {
    mount();
    act(() => {
      container.dispatchEvent(new CustomEvent(PRICE_SCALE_MENU_EVENT, { detail: { pane: "x" } }));
      const detail = { pane: 3, x: 0, y: 0, byKey: false };
      container.dispatchEvent(new CustomEvent(PRICE_SCALE_MENU_EVENT, { detail }));
    });
    fireEvent.keyDown(container, { key: "F10", shiftKey: true, ctrlKey: true });
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("mirrors getState: the drawn mode, lock, invert and price-only", () => {
    mount({
      mode: "percent",
      requestedMode: "percent",
      autoScale: false,
      inverted: true,
      priceOnly: true,
    });
    openByEvent();
    const checked = (name: string): string | null => item(name).getAttribute("aria-checked");
    expect(checked("Percent")).toBe("true");
    expect(checked("Linear")).toBe("false");
    expect(checked("Lock scale")).toBe("true");
    expect(checked("Invert scale")).toBe("true");
    expect(checked("Scale price only")).toBe("true");
    expect(
      screen.getByRole("menuitem", { name: "Reset scale" }).getAttribute("aria-disabled"),
    ).toBe(null);
  });

  it.each([
    ["Logarithmic", "setMode", ["log"], "Price scale: logarithmic"],
    ["Percent", "setMode", ["percent"], "Price scale: percent"],
    ["Indexed to 100", "setMode", ["indexed"], "Price scale: indexed to 100"],
    ["Lock scale", "setAutoScale", [false], "Price scale locked"],
    ["Invert scale", "setInverted", [true], "Price scale inverted"],
    ["Scale price only", "setOptions", [{ priceOnly: true }], "Price scale: price only"],
  ] as const)("%s calls %s, closes, says it once and reports it", (name, method, args, text) => {
    mount();
    openByEvent();
    const count = countSaid();
    fireEvent.click(item(name));
    expect(scale[method]).toHaveBeenCalledWith(...args);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(said()).toBe(text);
    expect(count()).toBe(1);
    expect(analytics).toHaveLength(1);
    expect(analytics[0]).toMatchObject({ name: "chart.price_scale_changed", source: "menu" });
  });

  it.each([
    ["Lock scale", "setAutoScale", true, "Price scale: auto"],
    ["Invert scale", "setInverted", false, "Price scale upright"],
    ["Linear", "setMode", "linear", "Price scale: linear"],
    ["Scale price only", "setOptions", { priceOnly: false }, "Price scale: includes overlays"],
    ["Reset scale", "setAutoScale", true, "Price scale: auto"],
  ] as const)(
    "from locked, inverted, price-only, log asked: %s calls %s",
    (name, method, arg, text) => {
      mount({ requestedMode: "log", autoScale: false, inverted: true, priceOnly: true });
      openByEvent();
      fireEvent.click(item(name));
      expect(scale[method]).toHaveBeenCalledWith(arg);
      expect(said()).toBe(text);
    },
  );

  it("the analytics payload is D03 §9's full state after the change", () => {
    mount({ autoScale: false, inverted: true });
    openByEvent();
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Logarithmic" }));
    expect(analytics).toEqual([
      {
        name: "chart.price_scale_changed",
        mode: "log",
        locked: true,
        inverted: true,
        merged_scales: false,
        position: "right",
        price_only: false,
        source: "menu",
      },
    ]);
  });

  it("choosing the drawn and requested mode again changes nothing and says nothing", () => {
    mount();
    openByEvent();
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Linear" }));
    expect(scale.setMode).not.toHaveBeenCalled();
    expect(screen.queryByRole("menu")).toBeNull();
    expect(said()).toBe("");
    expect(analytics).toEqual([]);
  });

  it("Log is refused, not faked: T2 with D03's reason, never activated, the reason re-said", () => {
    mount({ logAvailable: false, logReason: "non-positive" });
    openByEvent();
    const log = screen.getByRole("menuitemradio", { name: "Logarithmic" });
    expect(log.getAttribute("aria-disabled")).toBe("true");
    expect(log.getAttribute("aria-checked")).toBe("false");
    const reason = document.getElementById(log.getAttribute("aria-describedby")!);
    expect(reason?.textContent).toBe(NON_POSITIVE);
    log.focus();
    fireEvent.keyDown(log, { key: "Enter" });
    expect(scale.setMode).not.toHaveBeenCalled();
    expect(menu()).toBeTruthy(); // the scale stays on its previous mode, the menu open
    expect(said()).toBe(NON_POSITIVE);
    expect(analytics).toEqual([]);
  });

  it("after a D5 fallback, Linear is checked and the reason keeps the preference", () => {
    mount({ requestedMode: "log", logAvailable: false, logReason: "non-positive" });
    openByEvent();
    expect(screen.getByRole("menuitemradio", { name: "Linear" }).getAttribute("aria-checked")).toBe(
      "true",
    );
    const log = screen.getByRole("menuitemradio", { name: "Logarithmic" });
    expect(document.getElementById(log.getAttribute("aria-describedby")!)?.textContent).toBe(
      `${NON_POSITIVE}. Your Logarithmic preference is kept`,
    );
    expect(logReasonText("no-price-origin", "linear")).toBe(
      "Log scale needs prices; this pane has no bars yet",
    );
  });

  it("Merge is gated until E13; Reset is gated while auto", () => {
    mount();
    openByEvent();
    const merge = screen.getByRole("menuitemcheckbox", { name: "Merge indicator scales" });
    expect(merge.getAttribute("aria-disabled")).toBe("true");
    const reset = screen.getByRole("menuitem", { name: "Reset scale" });
    expect(reset.getAttribute("aria-disabled")).toBe("true");
    expect(document.getElementById(reset.getAttribute("aria-describedby")!)?.textContent).toBe(
      "Already auto-scaled",
    );
    fireEvent.click(reset);
    fireEvent.click(merge);
    expect(scale.setAutoScale).not.toHaveBeenCalled();
  });

  it("closes on activation by Space (D1) and returns focus to the chart container", () => {
    mount();
    container.focus();
    openByEvent();
    const invert = screen.getByRole("menuitemcheckbox", { name: "Invert scale" });
    invert.focus();
    fireEvent.keyDown(invert, { key: " " });
    expect(scale.setInverted).toHaveBeenCalledWith(true);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(container);
  });

  it("a right-click open with focus outside the chart still returns focus to the container", () => {
    mount();
    const outside = document.createElement("button");
    document.body.append(outside);
    outside.focus();
    openByEvent();
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(container);
    outside.remove();
  });

  it("keyboard: arrows wrap and reach the gated items, Home / End, Enter activates", () => {
    mount({ logAvailable: false, logReason: "non-positive" });
    openByEvent(true);
    const key = (k: string): void => {
      fireEvent.keyDown(document.activeElement!, { key: k });
    };
    key("ArrowDown");
    expect(document.activeElement?.textContent).toBe("Logarithmic");
    key("ArrowUp");
    key("ArrowUp");
    expect(document.activeElement?.textContent).toBe("Reset scale");
    key("Home");
    expect(document.activeElement?.textContent).toBe("Linear");
    key("End");
    expect(document.activeElement?.textContent).toBe("Reset scale");
    key("Home");
    key("ArrowDown");
    key("ArrowDown");
    key("Enter");
    expect(scale.setMode).toHaveBeenCalledWith("percent");
    expect(said()).toBe("Price scale: percent");
  });

  it("says the D5 fallback once and reports source fallback", () => {
    mount({ mode: "log", requestedMode: "log" });
    state = { ...state, mode: "linear", logAvailable: false, logReason: "non-positive" };
    act(() => viewport.forEach((f) => f()));
    act(() => viewport.forEach((f) => f())); // a later report with no change says nothing
    expect(said()).toBe(
      "Log scale unavailable — switched to linear: this series now contains a value <= 0",
    );
    expect(analytics).toEqual([
      expect.objectContaining({ source: "fallback", mode: "linear", locked: false }),
    ]);
  });

  it("an open menu follows a D5 fallback: Linear checked, Logarithmic T2 with the kept clause", () => {
    mount({ mode: "log", requestedMode: "log" });
    openByEvent();
    expect(item("Logarithmic").getAttribute("aria-checked")).toBe("true");
    state = { ...state, mode: "linear", logAvailable: false, logReason: "non-positive" };
    act(() => viewport.forEach((f) => f()));
    expect(item("Linear").getAttribute("aria-checked")).toBe("true");
    const log = item("Logarithmic");
    expect(log.getAttribute("aria-disabled")).toBe("true");
    expect(document.getElementById(log.getAttribute("aria-describedby")!)?.textContent).toBe(
      `${NON_POSITIVE}. Your Logarithmic preference is kept`,
    );
  });

  it("reports what the engine holds after the change, not the asked-for state", () => {
    mount();
    // An engine that keeps the drawn mode (e.g. no price origin yet) while recording the request.
    scale.setMode.mockImplementation((m: ScaleState["mode"]) => {
      state = { ...state, requestedMode: m };
    });
    openByEvent();
    fireEvent.click(item("Percent"));
    expect(analytics).toEqual([expect.objectContaining({ mode: "linear", source: "menu" })]);
  });

  it("has no serious or critical axe violations with the menu open", async () => {
    mount({ logAvailable: false, logReason: "non-positive", autoScale: false });
    openByEvent();
    const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
    expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
      [],
    );
  });

  it("inside <Chart>, finds the chart and its container", () => {
    state = AUTO_LINEAR;
    engine.next = fakeChart();
    const theme = { palette: "default", convention: "standard", colors: {} } as const;
    render(
      <Chart options={{ theme }} label="BTCUSDT chart">
        <PriceScaleMenu />
      </Chart>,
    );
    const figure = screen.getByRole("figure", { name: "BTCUSDT chart" });
    act(() => {
      const detail = { pane: 0, x: 600, y: 40, byKey: false };
      figure.dispatchEvent(new CustomEvent(PRICE_SCALE_MENU_EVENT, { bubbles: true, detail }));
    });
    expect(menu()).toBeTruthy();
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(document.activeElement).toBe(figure);
  });
});
