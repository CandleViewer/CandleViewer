// E15-T02 DockGrid (CMP-081) beyond the churn guard: lazy mount, the 30 s hidden-tab unsubscribe,
// keyboard resize, focus order = reading order (and focus kept through a move), the kind check
// before mount, close, the store, axe.
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import {
  EMPTY_TREE,
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

const leaf = (paneId: string, kind = "probe"): DockLeaf => ({
  type: "leaf",
  id: `leaf-${paneId}`,
  paneId,
  kind,
  minWidth: 0,
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
});

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
