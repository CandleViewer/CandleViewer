// E15-T02 DockGrid (CMP-081) beyond the churn guard: lazy mount, the 30 s hidden-tab unsubscribe,
// keyboard resize, focus order = reading order (and focus kept through a move), the kind check
// before mount, close, the store, axe.
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import {
  EMPTY_TREE,
  activateTab,
  counterMinter,
  maximise,
  move,
  restore,
  type DockLeaf,
  type DockNode,
  type DockTree,
} from "@candleviewer/dock";
import { createRequire } from "node:module";
import { useEffect, type JSX } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  DockGrid,
  HIDDEN_UNSUBSCRIBE_MS,
  type Timers,
} from "../../../../src/features/workspace/dock/DockGrid";
import { createDockStore } from "../../../../src/features/workspace/dock/dockStore";
import { layoutSummary } from "../../../../src/features/workspace/dock/layoutSummary";
import {
  PlaceholderPanel,
  createDefaultPaneRegistry,
  createPaneRegistry,
  type PaneProps,
} from "../../../../src/features/workspace/dock/paneRegistry";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as {
  run: (
    el: Element,
    o?: object,
  ) => Promise<{ violations: { id: string; impact?: string | null }[] }>;
};

const mounted: string[] = [];
function Probe({ paneId, subscribed }: PaneProps): JSX.Element {
  useEffect(() => void mounted.push(paneId), [paneId]);
  return <button type="button" data-subscribed={String(subscribed)}>{`Act ${paneId}`}</button>;
}

const leaf = (paneId: string, kind = "probe", minWidth = 0): DockLeaf => ({
  type: "leaf",
  id: `leaf-${paneId}`,
  paneId,
  kind,
  minWidth,
  minHeight: 0,
});

function setup(root: DockNode, opts: { kinds?: Record<string, string>; timers?: Timers } = {}) {
  const registry = createPaneRegistry();
  registry.register("probe", { label: "Probe", component: Probe, minWidth: 0, minHeight: 0 });
  registry.register("gated", {
    label: "Gated",
    component: Probe,
    minWidth: 0,
    minHeight: 0,
    disabledReason: "Owner only",
  });
  const announce = vi.fn();
  const onLayoutChanged = vi.fn();
  const tree: DockTree = { ...EMPTY_TREE, root };
  const store = createDockStore({
    tree,
    mint: counterMinter("op-"),
    announce,
    onLayoutChanged,
    now: () => 0,
  });
  const view = render(
    <DockGrid
      store={store}
      registry={registry}
      paneName={(l) => l.paneId.toUpperCase()}
      {...(opts.timers ? { timers: opts.timers } : {})}
    />,
  );
  return { store, announce, onLayoutChanged, ...view };
}

const regions = (): string[] =>
  screen.getAllByRole("region").map((r) => r.getAttribute("aria-label") ?? "");
const row = (...children: DockNode[]): DockNode => ({
  type: "row",
  id: "r",
  sizes: children.map(() => 1 / children.length),
  children,
});
const tabs = (...children: DockLeaf[]): DockNode => ({
  type: "tabset",
  id: "t",
  active: 0,
  children,
});

afterEach(() => {
  mounted.length = 0;
  Reflect.deleteProperty(Element.prototype, "moveBefore");
  vi.restoreAllMocks();
});

/**
 * jsdom focuses an element in a `hidden` subtree, which a browser never does (an element that is
 * not rendered is not focusable). This puts the browser's rule in: `focus()` inside `[hidden]` is
 * a no-op, and the optional `moveBefore` keeps focus only into a rendered parent.
 */
function browserFocusRules(withMoveBefore: boolean): void {
  const realFocus = HTMLElement.prototype.focus;
  vi.spyOn(HTMLElement.prototype, "focus").mockImplementation(function (
    this: HTMLElement,
    options?: FocusOptions,
  ) {
    if (this.closest("[hidden]") === null) realFocus.call(this, options);
  });
  if (!withMoveBefore) return;
  Object.defineProperty(Element.prototype, "moveBefore", {
    configurable: true,
    value: function (this: Element, node: Node, child: Node | null) {
      const active = document.activeElement;
      const kept = active instanceof HTMLElement && node.contains(active) ? active : null;
      this.insertBefore(node, child);
      if (kept !== null && this.closest("[hidden]") === null) realFocus.call(kept);
      else if (kept !== null) kept.blur();
    },
  });
}

const act_ = (name: string): HTMLElement =>
  screen.getByRole("button", { name: `Act ${name}`, hidden: true });

describe("DockGrid (CMP-081)", () => {
  it("mounts a hidden tab on first view and unsubscribes it after 30 s hidden, never unmounting it", () => {
    const pending: (() => void)[] = [];
    const timers: Timers = { setTimeout: (fn) => pending.push(fn), clearTimeout: () => undefined };
    setup(row(leaf("a"), tabs(leaf("b"), leaf("c"))), { timers });
    expect(mounted).not.toContain("c");
    fireEvent.click(screen.getByRole("tab", { name: "C" }));
    expect(mounted).toContain("c");
    const b = screen.getByRole("button", { name: "Act b", hidden: true });
    expect(b.dataset["subscribed"]).toBe("true");
    expect(HIDDEN_UNSUBSCRIBE_MS).toBe(30_000);
    act(() => pending.forEach((fn) => fn()));
    expect(b.dataset["subscribed"]).toBe("false");
    expect(b.isConnected).toBe(true);
  });

  it("the DOM order of the panels is the reading order after a move, and focus stays put", () => {
    const { store } = setup(row(leaf("a"), leaf("b"), leaf("c")));
    expect(regions()).toEqual(["A", "B", "C"]);
    screen.getByRole("button", { name: "Act a" }).focus();
    act(() => void store.apply("move", (t, c) => move(t, "a", "c", "right", c)));
    expect(regions()).toEqual(["B", "C", "A"]);
    expect(screen.getByRole("button", { name: "Act a" })).toHaveFocus();
  });

  it("uses Element.moveBefore where the browser has it", () => {
    const moveBefore = vi.fn(function (this: Element, node: Node, child: Node | null) {
      this.insertBefore(node, child);
    });
    Object.defineProperty(Element.prototype, "moveBefore", {
      value: moveBefore,
      configurable: true,
    });
    const { store } = setup(row(leaf("a"), leaf("b")));
    moveBefore.mockClear();
    // Into a tab group: a new slot, so the host is moved (a reorder alone moves the slot itself).
    act(() => void store.apply("move", (t, c) => move(t, "a", "b", "centre", c)));
    expect(moveBefore).toHaveBeenCalled();
    expect(regions()).toEqual(["A"]);
  });

  it("resizes by keyboard on the separator, one store commit per step, and equalises on Home", () => {
    const { store, onLayoutChanged } = setup(row(leaf("a"), leaf("b")));
    const separator = screen.getByRole("separator", { name: "A and B splitter" });
    fireEvent.keyDown(separator, { key: "ArrowRight" });
    expect(store.getTree().root).toMatchObject({ sizes: [0.52, 0.48] });
    fireEvent.keyDown(separator, { key: "Home" });
    expect(store.getTree().root).toMatchObject({ sizes: [0.5, 0.5] });
    expect(onLayoutChanged.mock.calls.map(([e]) => e.op)).toEqual(["resize", "equalise"]);
  });

  it("never mounts an unknown kind; a gated kind shows its reason instead of its panel", () => {
    setup(row(leaf("a", "script"), leaf("b", "gated")));
    expect(screen.getByRole("region", { name: "A" })).toHaveAttribute("data-state", "error");
    expect(within(screen.getByRole("region", { name: "B" })).getByText("Owner only")).toBeVisible();
    expect(mounted).toEqual([]);
  });

  it("close unmounts the pane and says one polite summary", () => {
    const { store, announce } = setup(row(leaf("a"), leaf("b")));
    fireEvent.click(screen.getAllByRole("button", { name: "Close Probe" })[0] as HTMLElement);
    expect(regions()).toEqual(["B"]);
    expect(announce.mock.calls).toEqual([["A closed."]]);
    expect(store.getTree().root).toMatchObject({ paneId: "b" });
  });

  it("draws the maximised pane alone and restores the grid", () => {
    const { store } = setup(row(leaf("a"), leaf("b")));
    act(() => void store.apply("maximise", (t, c) => maximise(t, "b", c)));
    expect(regions()).toEqual(["B"]);
    act(() => void store.apply("restore", (t, c) => restore(t, c)));
    expect(regions()).toEqual(["A", "B"]);
    expect(mounted.filter((p) => p === "a")).toHaveLength(1);
  });

  describe.each([
    ["insertBefore", false],
    ["moveBefore", true],
  ])("a pane keeps focus across every layout operation (A1, FM-01..03), via %s", (_, mb) => {
    it("tabify: the moved pane keeps focus in its new tab group", () => {
      browserFocusRules(mb);
      const { store } = setup(row(leaf("a"), leaf("b")));
      act_("a").focus();
      act(() => void store.apply("move", (t, c) => move(t, "a", "b", "centre", c)));
      expect(screen.getAllByRole("tab")).toHaveLength(2);
      expect(act_("a")).toHaveFocus();
    });

    it("split out: a tab moved out of its group keeps focus", () => {
      browserFocusRules(mb);
      const { store } = setup(row(leaf("a"), tabs(leaf("b"), leaf("c"))));
      act_("b").focus();
      act(() => void store.apply("move", (t, c) => move(t, "b", "a", "left", c)));
      expect(regions()).toEqual(["B", "A", "C"]);
      expect(act_("b")).toHaveFocus();
    });

    it("maximise and restore: the pane keeps focus both ways", () => {
      browserFocusRules(mb);
      const { store } = setup(row(leaf("a"), leaf("b")));
      act_("b").focus();
      act(() => void store.apply("maximise", (t, c) => maximise(t, "b", c)));
      expect(regions()).toEqual(["B"]);
      expect(act_("b")).toHaveFocus();
      act(() => void store.apply("restore", (t, c) => restore(t, c)));
      expect(regions()).toEqual(["A", "B"]);
      expect(act_("b")).toHaveFocus();
    });

    it("tab switch: from the tablist focus stays on the tab; from inside a pane it goes to the shown one", () => {
      browserFocusRules(mb);
      const { store } = setup(row(leaf("a"), tabs(leaf("b"), leaf("c"))));
      const tabC = screen.getByRole("tab", { name: "C" });
      tabC.focus();
      fireEvent.click(tabC);
      expect(screen.getByRole("tab", { name: "C" })).toHaveFocus();
      fireEvent.click(screen.getByRole("tab", { name: "B" }));
      act_("b").focus();
      act(() => void store.apply("activate_tab", (t, c) => activateTab(t, "t", 1, c)));
      expect(screen.getByRole("region", { name: "C" })).toHaveFocus();
      act(() => void store.apply("activate_tab", (t, c) => activateTab(t, "t", 0, c)));
      expect(act_("b")).toBeVisible();
    });
  });

  it("close moves focus to the panel that takes the space, else the dock (A2, FM-11)", () => {
    const { store } = setup(row(leaf("a"), leaf("b"), tabs(leaf("c"), leaf("d"))));
    fireEvent.click(
      within(screen.getByRole("region", { name: "A" })).getByRole("button", {
        name: "Close Probe",
      }),
    );
    expect(screen.getByRole("region", { name: "B" })).toHaveFocus();
    // The last pane of a row: its previous sibling takes the space; in a tab group, the next tab.
    fireEvent.click(
      within(screen.getByRole("region", { name: "C" })).getByRole("button", {
        name: "Close Probe",
      }),
    );
    expect(screen.getByRole("region", { name: "D" })).toHaveFocus();
    fireEvent.click(
      within(screen.getByRole("region", { name: "D" })).getByRole("button", {
        name: "Close Probe",
      }),
    );
    expect(screen.getByRole("region", { name: "B" })).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Close Probe" }));
    expect(store.getTree().root).toBeNull();
    expect(document.querySelector(".cv-dock-root")).toHaveFocus();
  });

  it("draws the focused panel's frame while focus is inside it, and clears it on leaving (A3)", () => {
    setup(row(leaf("a"), leaf("b")));
    const outside = document.body.appendChild(document.createElement("button"));
    act(() => act_("a").focus());
    expect(screen.getByRole("region", { name: "A" })).toHaveAttribute("data-focused");
    expect(screen.getByRole("region", { name: "B" })).not.toHaveAttribute("data-focused");
    act(() => act_("b").focus());
    expect(screen.getByRole("region", { name: "A" })).not.toHaveAttribute("data-focused");
    expect(screen.getByRole("region", { name: "B" })).toHaveAttribute("data-focused");
    act(() => outside.focus());
    expect(screen.getByRole("region", { name: "B" })).not.toHaveAttribute("data-focused");
    outside.remove();
  });

  it("measures a nested split's minimum shares against the split's own size, not the dock's", () => {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1000);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(400);
    const inner: DockNode = {
      type: "row",
      id: "inner",
      sizes: [0.5, 0.5],
      children: [leaf("b", "probe", 100), leaf("c", "probe", 100)],
    };
    const column: DockNode = {
      type: "column",
      id: "col",
      sizes: [0.5, 0.5],
      children: [inner, leaf("d")],
    };
    setup(row(leaf("a"), column));
    // The inner row is 500 px wide, so a 100 px minimum is a 0.2 share of it (not 0.1 of the dock).
    const separator = screen.getByRole("separator", { name: "B and C splitter" });
    expect(separator).toHaveAttribute("aria-valuemin", "20");
    expect(separator).toHaveAttribute("aria-valuemax", "80");
  });

  it("is axe-clean", async () => {
    const { container } = setup(row(leaf("a"), tabs(leaf("b"), leaf("c"))));
    const res = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
      [],
    );
  });
});

describe("the dock store and registry", () => {
  it("a refused operation changes nothing; an unchanged tree publishes nothing", () => {
    const store = createDockStore({ tree: { ...EMPTY_TREE, root: leaf("a") } });
    const listener = vi.fn();
    store.subscribe(listener);
    expect(store.apply("move", (t, c) => move(t, "a", "nope", "left", c))).toBe(false);
    expect(store.apply("move", (t) => t)).toBe(true);
    expect(() =>
      store.apply("move", () => {
        throw new Error("bug");
      }),
    ).toThrow("bug");
    store.setViewport({ width: 100, height: 100 });
    expect(store.apply("resize", (t, c) => (c.viewport?.width === 100 ? { ...t } : t))).toBe(true);
    expect(listener).toHaveBeenCalledOnce();
  });

  it("registers every PaneKind on the placeholder with E15-D04's minimums", () => {
    const registry = createDefaultPaneRegistry();
    expect(registry.minimums("chart")).toEqual({ minWidth: 328, minHeight: 168 });
    expect(registry.minimums("scanner")).toEqual({ minWidth: 232, minHeight: 120 });
    expect(registry.minimums("script")).toBeNull();
    expect(registry.get("dom")?.component).toBe(PlaceholderPanel);
    expect(PlaceholderPanel()).toBeNull();
  });

  it("says SR-01, SR-05, SR-09 and SR-10 in E15-D15's words", () => {
    expect(layoutSummary.presetApplied("Order-flow", 4)).toBe(
      "Layout changed to Order-flow, 4 panels.",
    );
    expect(layoutSummary.presetApplied("Solo", 1)).toBe("Layout changed to Solo, 1 panel.");
    expect(layoutSummary.moved("Positions", "Chart", "bottom")).toBe(
      "Positions moved below Chart.",
    );
    expect(layoutSummary.moved("Tape", "DOM", "centre")).toBe("Tape moved to a tab with DOM.");
    expect(layoutSummary.maximised("Chart")).toBe("Chart maximised.");
    expect(layoutSummary.restored("Chart")).toBe("Chart restored.");
    expect(layoutSummary.poppedOut("DOM")).toBe("DOM popped out to its own window.");
    expect(layoutSummary.returned("DOM")).toBe("DOM returned to the workspace.");
    expect(layoutSummary.closed("Tape")).toBe("Tape closed.");
  });
});
