// E15-T02 Gherkin "Moving a pane never remounts its canvas": the GL-churn guard over a 2x2 of four
// GL panels (a fake WebGL panel, and the real <Chart> binding over a counting engine) through every
// operation the README guarantee names: move, tabify, split-out, a preset keeping the panes,
// maximise / restore, a tab switch and a resize, checked after each step; and a negative control
// proving the guard fails a remounting renderer.
import { act, render } from "@testing-library/react";
import {
  EMPTY_TREE,
  activateTab,
  applyPreset,
  counterMinter,
  leavesOf,
  maximise,
  move,
  presetToTree,
  resize,
  restore,
  separatorId,
  tabify,
  type DockLeaf,
  type DockNode,
  type DockTree,
} from "@candleviewer/dock";
import { DockGridView } from "@candleviewer/ui";
import { useEffect, useRef, useState, type JSX } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Chart } from "../../../../src/chart";
import { DockGrid } from "../../../../src/features/workspace/dock/DockGrid";
import {
  createDockStore,
  useDockTree,
  type DockStore,
} from "../../../../src/features/workspace/dock/dockStore";
import {
  installGlChurnGuard,
  type GlChurnGuard,
} from "../../../../src/features/workspace/dock/glChurnGuard";
import {
  createPaneRegistry,
  type PaneProps,
  type PaneRegistry,
} from "../../../../src/features/workspace/dock/paneRegistry";

const engine = vi.hoisted(() => ({ created: 0, disposed: 0 }));
vi.mock("@candleviewer/chart-engine", () => ({
  createChart: () => {
    engine.created += 1;
    return {
      subscribe: () => () => undefined,
      setTheme: () => undefined,
      setDensity: () => undefined,
      dispose: () => {
        engine.disposed += 1;
      },
    };
  },
}));

let instances = 0;
/** A panel holding a live GL context and a data window that only a remount would lose. */
function GlPanel({ paneId }: PaneProps): JSX.Element {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [window] = useState(() => `${paneId}:${(instances += 1)}`);
  useEffect(() => {
    canvas.current?.getContext("webgl2");
  }, []);
  return <canvas ref={canvas} data-window={window} />;
}

function ChartPanel(): JSX.Element {
  return <Chart options={{ theme: {} as never }} label="Chart" />;
}

const leaf = (paneId: string, kind: string): DockLeaf => ({
  type: "leaf",
  id: `leaf-${paneId}`,
  paneId,
  kind,
  minWidth: 0,
  minHeight: 0,
});

function grid(kind: string): DockStore {
  const panes = ["a", "b", "c", "d"].map((p) => leaf(p, kind));
  const tree: DockTree = {
    ...EMPTY_TREE,
    root: presetToTree("2x2", panes, counterMinter("node-")),
  };
  return createDockStore({ tree, mint: counterMinter("op-") });
}

function registry(): PaneRegistry {
  const r = createPaneRegistry();
  r.register("gl", { label: "Chart", component: GlPanel, minWidth: 0, minHeight: 0 });
  r.register("chart", { label: "Chart", component: ChartPanel, minWidth: 0, minHeight: 0 });
  return r;
}

/** The first tab group in reading order (the tab switch's target). */
function tabsetOf(node: DockNode | null): Extract<DockNode, { type: "tabset" }> | null {
  if (node === null || node.type === "leaf") return null;
  if (node.type === "tabset") return node;
  for (const child of node.children) {
    const found = tabsetOf(child);
    if (found !== null) return found;
  }
  return null;
}

/** The root split's id: its first separator is the resize target. */
function rootSplit(tree: DockTree): string {
  const root = tree.root;
  if (root === null || (root.type !== "row" && root.type !== "column")) throw new Error("no split");
  return root.id;
}

interface Step {
  readonly name: string;
  readonly run: (store: DockStore) => boolean;
}

/**
 * The README guarantee's operations: to the opposite corner, a tab, split out again, a preset that
 * keeps all four panes, maximise and restore, a tab switch inside a tab group, and a resize.
 */
const STEPS: readonly Step[] = [
  { name: "move", run: (s) => s.apply("move", (t, c) => move(t, "a", "d", "bottom", c)) },
  { name: "tabify", run: (s) => s.apply("tabify", (t, c) => tabify(t, "a", "c", c)) },
  { name: "split out", run: (s) => s.apply("move", (t, c) => move(t, "a", "b", "left", c)) },
  { name: "preset 1+3", run: (s) => s.apply("apply_preset", (t, c) => applyPreset(t, "1+3", c)) },
  { name: "maximise", run: (s) => s.apply("maximise", (t, c) => maximise(t, "b", c)) },
  { name: "restore", run: (s) => s.apply("restore", (t, c) => restore(t, c)) },
  { name: "tab group", run: (s) => s.apply("tabify", (t, c) => tabify(t, "d", "c", c)) },
  {
    name: "tab switch",
    run: (s) =>
      s.apply("activate_tab", (t, c) => {
        const group = tabsetOf(t.root);
        if (group === null) throw new Error("no tab group");
        return activateTab(t, group.id, group.active === 0 ? 1 : 0, c);
      }),
  },
  {
    name: "resize",
    run: (s) => s.apply("resize", (t, c) => resize(t, separatorId(rootSplit(t), 0), -0.1, c)),
  },
];

/** Runs every step; `after` checks the dock once each step has committed. */
function sequence(store: DockStore, after: (step: string) => void = () => undefined): void {
  for (const step of STEPS) {
    const before = store.getTree();
    let applied = false;
    act(() => {
      applied = step.run(store);
    });
    // A refused or no-op step would prove nothing: each one changes the tree.
    expect(applied, step.name).toBe(true);
    expect(store.getTree(), step.name).not.toBe(before);
    after(step.name);
  }
}

const windows = (host: HTMLElement): string[] =>
  [...host.querySelectorAll("canvas")].map((c) => c.dataset["window"] ?? "").sort();

let guard: GlChurnGuard;
beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  guard = installGlChurnGuard();
});
afterEach(() => {
  guard.uninstall();
  vi.restoreAllMocks();
});

describe("GL-churn guard (SCR-020: layout changes never remount the WebGL context)", () => {
  it("every guaranteed operation: zero contexts, zero losses, zero unmounts, same data windows", () => {
    const store = grid("gl");
    const { container } = render(
      <DockGrid store={store} registry={registry()} paneName={(l) => l.paneId} />,
    );
    expect(guard.counters.contextsCreated).toBe(4);
    const before = windows(container);
    const canvases = new Map(
      [...container.querySelectorAll("canvas")].map((c) => [c.dataset["window"], c]),
    );
    guard.reset();
    const zero = {
      contextsCreated: 0,
      offscreenTransfers: 0,
      contextsLost: 0,
      panelMounts: 0,
      panelUnmounts: 0,
    };
    const steps: string[] = [];
    sequence(store, (step) => {
      steps.push(step);
      expect({ step, ...guard.counters }).toEqual({ step, ...zero });
      expect(container.querySelectorAll("canvas"), step).toHaveLength(4);
    });
    expect(steps).toEqual(STEPS.map((s) => s.name));
    expect(windows(container)).toEqual(before);
    for (const c of container.querySelectorAll("canvas"))
      expect(canvases.get(c.dataset["window"])).toBe(c);
    expect(leavesOf(store.getTree().root).map((l) => l.paneId)).toEqual(["a", "b", "c", "d"]);
  });

  it("the real <Chart> binding is created once per pane and never disposed by a layout change", () => {
    engine.created = 0;
    engine.disposed = 0;
    const store = grid("chart");
    render(<DockGrid store={store} registry={registry()} paneName={(l) => l.paneId} />);
    expect(engine.created).toBe(4);
    sequence(store, (step) =>
      expect({ step, ...engine }).toEqual({ step, created: 4, disposed: 0 }),
    );
  });

  it("negative control: a renderer that mounts panels inline in their slots fails the guard", () => {
    const store = grid("gl");
    const r = registry();
    function InlineGrid(): JSX.Element {
      const tree = useDockTree(store);
      return (
        <DockGridView
          root={tree.root}
          paneName={String}
          renderSlot={(l) => {
            const Body = r.get((l as DockLeaf).kind)?.component ?? GlPanel;
            return <Body key={l.paneId} paneId={l.paneId} subscribed />;
          }}
          onResize={() => undefined}
          onActivateTab={() => undefined}
        />
      );
    }
    render(<InlineGrid />);
    guard.reset();
    sequence(store);
    // The remove-and-insert render remounts the moved canvas: the guard sees new contexts.
    expect(guard.counters.contextsCreated).toBeGreaterThan(0);
  });

  it("counts offscreen transfers and context losses, and restores the canvas on uninstall", () => {
    const canvas = document.createElement("canvas");
    expect(() => canvas.transferControlToOffscreen()).toThrow();
    canvas.dispatchEvent(new Event("webglcontextlost"));
    document.body.append(canvas);
    canvas.dispatchEvent(new Event("webglcontextlost"));
    expect(guard.counters).toMatchObject({ offscreenTransfers: 1, contextsLost: 1 });
    guard.uninstall();
    expect("transferControlToOffscreen" in HTMLCanvasElement.prototype).toBe(false);
    canvas.remove();
    guard = installGlChurnGuard();
  });
});
