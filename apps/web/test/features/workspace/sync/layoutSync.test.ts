import { describe, expect, it } from "vitest";
import type { PaneFields } from "@candleviewer/dock";
import {
  UNSTORED_OFF,
  applyLayoutAxes,
  axesFromLayout,
  axesToLayout,
  groupOfPane,
  groupsFromPanes,
  panesWithGroups,
  withGroup,
} from "../../../../src/features/workspace/sync/layoutSync";
import { createSyncBus } from "../../../../src/features/workspace/sync/syncBus";
import { manualFrames } from "./fakes";

const pane = (pane_config?: PaneFields["pane_config"]): PaneFields => ({
  symbol: "BTCUSDT",
  interval_code: "time:1",
  chart_template_id: null,
  scale_mode: "auto",
  ...(pane_config === undefined ? {} : { pane_config }),
});

describe("layout sync mapping (BQ-07)", () => {
  it("maps the three stored flags; interval and time range stay off unless held on", () => {
    const flags = { symbol_sync: true, crosshair_sync: false, level_sync: true };
    expect(axesFromLayout(flags)).toEqual({
      symbol: true,
      interval: false,
      crosshair: false,
      timeRange: false,
      drawings: true,
    });
    expect(axesFromLayout(flags, { interval: true, timeRange: true }).timeRange).toBe(true);
    expect(UNSTORED_OFF).toEqual({ interval: false, timeRange: false });
  });

  it("round-trips the flags", () => {
    for (const bits of [0, 1, 2, 3, 4, 5, 6, 7]) {
      const flags = {
        symbol_sync: !!(bits & 1),
        crosshair_sync: !!(bits & 2),
        level_sync: !!(bits & 4),
      };
      expect(axesToLayout(axesFromLayout(flags))).toEqual(flags);
    }
  });

  it("reads a non-boolean stored flag as off", () => {
    const flags = { symbol_sync: "true", crosshair_sync: 1, level_sync: null } as never;
    expect(axesFromLayout(flags)).toEqual({
      symbol: false,
      interval: false,
      crosshair: false,
      timeRange: false,
      drawings: false,
    });
  });

  it("gives every group the layout's flags", () => {
    const bus = createSyncBus({ dev: true, requestFrame: manualFrames().requestFrame });
    applyLayoutAxes(bus, { symbol_sync: false, crosshair_sync: true, level_sync: false });
    for (const g of ["A", "B", "C"] as const) expect(bus.snapshot(g).axes.crosshair).toBe(true);
  });

  it("reads a pane's group, refusing anything but A, B or C", () => {
    expect(groupOfPane(pane({ sync_group: "B" }))).toBe("B");
    expect(groupOfPane(pane({ sync_group: null }))).toBeNull();
    expect(groupOfPane(pane())).toBeNull();
    expect(groupOfPane(undefined)).toBeNull();
    expect(groupOfPane(pane({ sync_group: "Z" as never }))).toBeNull();
  });

  it("round-trips pane groups and keeps other pane_config keys", () => {
    const panes = new Map<string, PaneFields>([
      ["d1", pane({ sync_group: "A", settings: { depth: 20 } })],
      ["d2", pane()],
      ["d3", pane({ sync_group: "C" })],
    ]);
    const groups = groupsFromPanes(panes);
    expect([...groups]).toEqual([
      ["d1", "A"],
      ["d3", "C"],
    ]);
    const written = panesWithGroups(panes, groups);
    expect(groupsFromPanes(written)).toEqual(groups);
    expect(written.get("d1")?.pane_config?.settings).toEqual({ depth: 20 });
    expect(withGroup(pane({ sync_group: "A" }), null).pane_config?.sync_group).toBeNull();
    expect(written.get("d2")).toBe(panes.get("d2")); // an ungrouped pane gains no key
  });

  it("keeps null and omitted sync_group distinct across a round trip", () => {
    const panes = new Map<string, PaneFields>([
      ["nullG", pane({ sync_group: null, settings: { depth: 5 } })],
      ["omitted", pane({ settings: { depth: 7 } })],
      ["none", pane()],
    ]);
    const written = panesWithGroups(panes, groupsFromPanes(panes));
    expect(written.get("nullG")?.pane_config).toEqual({ sync_group: null, settings: { depth: 5 } });
    expect(written.get("omitted")?.pane_config).toEqual({ settings: { depth: 7 } });
    expect(written.get("omitted")?.pane_config).not.toHaveProperty("sync_group");
    expect(written.get("none")).toBe(panes.get("none"));
  });

  it("takes presets as plain input to groupsFromPanes", () => {
    const preset = new Map<string, PaneFields>([["x", pane({ sync_group: "C" })]]);
    expect(groupsFromPanes(preset).get("x")).toBe("C");
  });
});
