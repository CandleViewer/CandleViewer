import { createRequire } from "node:module";
import { Profiler } from "react";
import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  REGION_BUDGET_MS,
  ShellAnnouncer,
  clearAnnouncements,
} from "../../../../src/features/app-shell/announcer";
import {
  SyncBusProvider,
  announceSyncState,
} from "../../../../src/features/workspace/sync/SyncBusProvider";
import type { SyncBus } from "../../../../src/features/workspace/sync/syncBus";
import type { SyncGroupId, SyncMember } from "../../../../src/features/workspace/sync/types";
import { useMultiChartLinker } from "../../../../src/features/workspace/sync/useMultiChartLinker";
import { ALL_ON, busWithFrames, fakeMember, type FakeMember } from "./fakes";

// axe-core is a transitive dependency of @axe-core/playwright (already a devDependency).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { id: string }[] }> };
// jsdom has no layout, so contrast is the real-browser collectors' (as in keymap-editor-axe).
const NO_CONTRAST = { rules: { "color-contrast": { enabled: false } } };

afterEach(() => {
  if (vi.isFakeTimers()) vi.runOnlyPendingTimers();
  vi.useRealTimers();
  clearAnnouncements();
});

function Pane(props: { member: SyncMember | null; group: SyncGroupId | null }): null {
  useMultiChartLinker({ groupId: props.group, member: props.member });
  return null;
}

function Grid(props: {
  bus: SyncBus;
  members: FakeMember[];
  group?: SyncGroupId | null;
  onCommit?: () => void;
}) {
  const panes = props.members.map((m) => (
    <Pane key={m.paneId} member={m} group={props.group === undefined ? "A" : props.group} />
  ));
  return (
    <Profiler id="grid" onRender={() => props.onCommit?.()}>
      <SyncBusProvider bus={props.bus}>{panes}</SyncBusProvider>
    </Profiler>
  );
}

const ids = (bus: SyncBus, g: SyncGroupId): string[] =>
  bus.snapshot(g).members.map((m) => m.paneId);

describe("CMP-196 useMultiChartLinker", () => {
  it("joins on mount, moves on a group change and leaves on unmount", () => {
    const { bus } = busWithFrames();
    const members = [fakeMember("p1"), fakeMember("p2")];
    const view = render(<Grid bus={bus} members={members} />);
    expect(ids(bus, "A")).toEqual(["p1", "p2"]);
    view.rerender(<Grid bus={bus} members={members} group="B" />);
    expect([ids(bus, "A"), ids(bus, "B")]).toEqual([[], ["p1", "p2"]]);
    view.rerender(<Grid bus={bus} members={members} group={null} />);
    expect([ids(bus, "A"), ids(bus, "B")]).toEqual([[], []]);
    view.rerender(<Grid bus={bus} members={members} group="C" />);
    view.unmount();
    expect(ids(bus, "C")).toEqual([]);
  });

  it("does nothing without a provider or a member", () => {
    const { bus } = busWithFrames();
    render(<Pane member={fakeMember("p1")} group="A" />);
    render(
      <SyncBusProvider bus={bus}>
        <Pane member={null} group="A" />
      </SyncBusProvider>,
    );
    expect(ids(bus, "A")).toEqual([]);
  });

  it("sweeps the crosshair across three panes with zero React commits", () => {
    const { bus, frames } = busWithFrames();
    const members = [fakeMember("p1"), fakeMember("p2"), fakeMember("p3")];
    let commits = 0;
    render(<Grid bus={bus} members={members} onCommit={() => void (commits += 1)} />);
    act(() => void frames.run());
    const before = commits;
    act(() => {
      for (let t = 0; t < 300; t += 1) {
        bus.publish("p1", { axis: "crosshair", crosshair: t });
        frames.run();
      }
    });
    expect(commits).toBe(before);
    expect(members[1]?.received).toHaveLength(300);
    expect(members[2]?.received.at(-1)).toEqual({ axis: "crosshair", crosshair: 299 });
  });

  it("leaks no member over 1,000 mount/unmount cycles", () => {
    const { bus, frames } = busWithFrames();
    for (let i = 0; i < 1_000; i += 1) {
      const view = render(<Grid bus={bus} members={[fakeMember(`m${i}`), fakeMember(`n${i}`)]} />);
      bus.publish(`m${i}`, { axis: "crosshair", crosshair: i });
      view.unmount();
    }
    frames.run();
    expect([ids(bus, "A"), ids(bus, "B"), ids(bus, "C")]).toEqual([[], [], []]);
    expect(bus.devCounters().dispatches).toBe(0);
  });

  it("says each link change once, politely, within the region budget, axe-clean", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true }); // axe runs on real time
    const { bus, frames } = busWithFrames({ announce: announceSyncState });
    const members = [fakeMember("p1"), fakeMember("p2"), fakeMember("p3")];
    const grid = (group: SyncGroupId | null) => (
      <>
        <ShellAnnouncer />
        <Grid bus={bus} members={members} group={group} />
      </>
    );
    const view = render(grid("A"));
    const polite = view.container.querySelector('[aria-live="polite"]');
    const said = (): (string | null | undefined)[] =>
      [...(polite?.querySelectorAll("p") ?? [])].map((p) => p.textContent);
    const axeClean = async () =>
      expect((await axe.run(view.container, NO_CONTRAST)).violations).toEqual([]);
    const ALL = "symbol, interval, crosshair, time range, levels.";
    act(() => void frames.run());
    expect(said()).toEqual([`Panes linked in sync group A: ${ALL}`]);
    await axeClean();
    act(() => {
      bus.publish("p1", { axis: "crosshair", crosshair: 1 }); // a value, not a link change
      bus.setAxes("A", { ...ALL_ON, symbol: false }); // a later link change, inside the budget
      frames.run();
    });
    expect(said()).toEqual([`Panes linked in sync group A: ${ALL}`]);
    act(() => void vi.advanceTimersByTime(REGION_BUDGET_MS));
    expect(said()).toEqual([
      "Panes linked in sync group A: interval, crosshair, time range, levels.",
    ]);
    await axeClean();
    view.rerender(grid(null)); // unlink, then relink before the budget ends: both are said
    act(() => void frames.run());
    view.rerender(grid("A"));
    act(() => void frames.run());
    act(() => void vi.advanceTimersByTime(REGION_BUDGET_MS));
    expect(said()).toEqual([
      "Panes in sync group A are no longer linked. " +
        "Panes linked in sync group A: interval, crosshair, time range, levels.",
    ]);
    await axeClean();
  });
});
