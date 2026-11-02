// E15-T02 perf (SCR-022, SCR-024 via CMP-080): a preset apply commits in <= 300 ms and the grid's
// panels mount in <= 150 ms, at E15-K01's pane counts (1, 4, 6, 16), with GL-holding fake panels in
// jsdom: the React commit and the host moves, not the engine. Wall time of one cold run per count,
// bounded through the runner calibration. The perf project: no coverage.
import { act, cleanup, render } from "@testing-library/react";
import { budget, why } from "@candleviewer/config/perf-calibration";
import {
  EMPTY_TREE,
  applyPreset,
  counterMinter,
  type DockLeaf,
  type DockNode,
} from "@candleviewer/dock";
import type { JSX } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { DockGrid } from "../../../../src/features/workspace/dock/DockGrid";
import { createDockStore } from "../../../../src/features/workspace/dock/dockStore";
import { createPaneRegistry } from "../../../../src/features/workspace/dock/paneRegistry";

function Panel(): JSX.Element {
  return <canvas />;
}

const registry = createPaneRegistry();
registry.register("chart", { label: "Chart", component: Panel, minWidth: 0, minHeight: 0 });

function store(panes: number) {
  const leaves: DockLeaf[] = Array.from({ length: panes }, (_, i) => ({
    type: "leaf",
    id: `leaf-${i}`,
    paneId: `p${i}`,
    kind: "chart",
    minWidth: 0,
    minHeight: 0,
  }));
  const root: DockNode =
    panes === 1
      ? (leaves[0] as DockLeaf)
      : { type: "row", id: "r", sizes: leaves.map(() => 1 / panes), children: leaves };
  return createDockStore({ tree: { ...EMPTY_TREE, root }, mint: counterMinter("op-") });
}

afterEach(cleanup);

describe.each([1, 4, 6, 16])("%i panes", (panes) => {
  it("mounts the grid's panels within 150 ms", () => {
    const s = store(panes);
    const started = performance.now();
    render(<DockGrid store={s} registry={registry} paneName={(l) => l.paneId} />);
    const ms = performance.now() - started;
    expect(ms, why(ms, 150)).toBeLessThanOrEqual(budget(150));
  });

  it("applies a preset over the existing panes within 300 ms", () => {
    const s = store(panes);
    render(<DockGrid store={s} registry={registry} paneName={(l) => l.paneId} />);
    const preset = panes >= 4 ? "1+3" : "1x1";
    const started = performance.now();
    act(() => void s.apply("apply_preset", (t, c) => applyPreset(t, preset, c)));
    const ms = performance.now() - started;
    expect(ms, why(ms, 300)).toBeLessThanOrEqual(budget(300));
  });
});
