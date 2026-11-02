// E15-T02 (#403) e2e-only harness: DockGrid over four real `<Chart>` panes (the chart-engine render
// worker and OffscreenCanvas), with `window.__dockHarness` running the same dock operations the
// DockGrid handlers run. Only e2e/dock/gl-churn.spec.ts builds it; no route or bundle imports it.
import "@candleviewer/ui/tokens.dark.css";
import "@candleviewer/ui/theme.css";
import "@candleviewer/ui/components.css";
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
import { StrictMode, useEffect, useSyncExternalStore, type JSX } from "react";
import { createRoot } from "react-dom/client";
import { Chart, Pane, useChartApi } from "../../../src/chart";
import { DockGrid } from "../../../src/features/workspace/dock/DockGrid";
import { createDockStore, type DockStore } from "../../../src/features/workspace/dock/dockStore";
import {
  createPaneRegistry,
  type PaneProps,
} from "../../../src/features/workspace/dock/paneRegistry";
import { PANE_IDS, type DockHarness, type StepName } from "./api";

const THEME = { palette: "default", convention: "standard", colors: {} } as const;

const errors: Record<string, string[]> = {};
const frames: Record<string, { profile: string; count: number }> = {};

/** Each pane's live chart API, for the liveness probe (`takeScreenshot` renders in the worker). */
const charts = new Map<string, NonNullable<ReturnType<typeof useChartApi>>>();

function ChartProbe({ paneId }: { readonly paneId: string }): null {
  const api = useChartApi();
  useEffect(() => {
    if (api === null) return undefined;
    charts.set(paneId, api);
    return () => {
      if (charts.get(paneId) === api) charts.delete(paneId);
    };
  }, [api, paneId]);
  return null;
}

/** Per-pane `<Chart>` keys: only the negative control changes one. */
const epochs = new Map<string, number>();
const epochListeners = new Set<() => void>();
const subscribeEpochs = (listener: () => void): (() => void) => {
  epochListeners.add(listener);
  return () => epochListeners.delete(listener);
};

function ChartPane({ paneId }: PaneProps): JSX.Element {
  const epoch = useSyncExternalStore(subscribeEpochs, () => epochs.get(paneId) ?? 0);
  return (
    <div className="harness-pane" data-harness-pane={paneId}>
      <Chart
        key={epoch}
        options={{ theme: THEME }}
        label={`Chart ${paneId}`}
        onError={(e) => (errors[paneId] ??= []).push(e.code)}
        onFrameStats={(s) => {
          const was = frames[paneId]?.count ?? 0;
          frames[paneId] = { profile: s.renderProfile, count: was + 1 };
        }}
      >
        <Pane />
        <ChartProbe paneId={paneId} />
      </Chart>
    </div>
  );
}

const leaf = (paneId: string): DockLeaf => ({
  type: "leaf",
  id: `leaf-${paneId}`,
  paneId,
  kind: "chart",
  minWidth: 0,
  minHeight: 0,
});

/** The first tab group in reading order. */
function tabsetOf(node: DockNode | null): Extract<DockNode, { type: "tabset" }> | null {
  if (node === null || node.type === "leaf") return null;
  if (node.type === "tabset") return node;
  for (const child of node.children) {
    const found = tabsetOf(child);
    if (found !== null) return found;
  }
  return null;
}

function rootSplit(tree: DockTree): string {
  const root = tree.root;
  if (root === null || (root.type !== "row" && root.type !== "column")) throw new Error("no split");
  return root.id;
}

/** The README guarantee's operations, each through `store.apply` as DockGrid's handlers do. */
const STEPS: Readonly<Record<StepName, (s: DockStore) => boolean>> = {
  move: (s) => s.apply("move", (t, c) => move(t, "a", "d", "bottom", c)),
  tabify: (s) => s.apply("tabify", (t, c) => tabify(t, "a", "c", c)),
  "split out": (s) => s.apply("move", (t, c) => move(t, "a", "b", "left", c)),
  "preset 1+3": (s) => s.apply("apply_preset", (t, c) => applyPreset(t, "1+3", c)),
  maximise: (s) => s.apply("maximise", (t, c) => maximise(t, "b", c)),
  restore: (s) => s.apply("restore", (t, c) => restore(t, c)),
  "tab group": (s) => s.apply("tabify", (t, c) => tabify(t, "d", "c", c)),
  "tab switch": (s) =>
    s.apply("activate_tab", (t, c) => {
      const group = tabsetOf(t.root);
      if (group === null) throw new Error("no tab group");
      return activateTab(t, group.id, group.active === 0 ? 1 : 0, c);
    }),
  resize: (s) => s.apply("resize", (t, c) => resize(t, separatorId(rootSplit(t), 0), -0.1, c)),
};

const mint = counterMinter("node-");
const store = createDockStore({
  tree: { ...EMPTY_TREE, root: presetToTree("2x2", PANE_IDS.map(leaf), mint) },
  mint: counterMinter("op-"),
});
const registry = createPaneRegistry();
registry.register("chart", { label: "Chart", component: ChartPane, minWidth: 0, minHeight: 0 });

const harness: DockHarness = {
  run: (step) => {
    const before = store.getTree();
    // A refused or no-op step proves nothing: report it as not applied.
    return STEPS[step](store) && store.getTree() !== before;
  },
  remount: (paneId) => {
    epochs.set(paneId, (epochs.get(paneId) ?? 0) + 1);
    for (const listener of [...epochListeners]) listener();
  },
  panes: () => leavesOf(store.getTree().root).map((l) => l.paneId),
  errors: () => structuredClone(errors),
  frames: () => structuredClone(frames),
  screenshot: async (paneId) => {
    const api = charts.get(paneId);
    if (api === undefined) throw new Error(`no chart in pane ${paneId}`);
    return (await api.takeScreenshot()).size;
  },
};
window.__dockHarness = harness;

const root = document.getElementById("root");
if (root === null) throw new Error("root element not found");
createRoot(root).render(
  <StrictMode>
    <DockGrid store={store} registry={registry} paneName={(l) => `Chart ${l.paneId}`} />
  </StrictMode>,
);
