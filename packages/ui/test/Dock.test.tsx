// @vitest-environment jsdom
import { act } from "react";
import { expect, fireEvent, within } from "storybook/test";
import { describe, it, vi } from "vitest";
import {
  DockGridView,
  DockPanel,
  PanelHeader,
  SplitPane,
  type DockViewNode,
} from "../src/components/index.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

const leaf = (paneId: string): DockViewNode => ({ type: "leaf", id: `leaf-${paneId}`, paneId });

function split(onResize = vi.fn(), onAnnounce = vi.fn(), sizes = [0.5, 0.5]) {
  return (
    <SplitPane
      direction="row"
      sizes={sizes}
      minSizes={[0.2, 0.2]}
      labels={["Chart and DOM splitter"]}
      cells={[
        { key: "a", content: <DockPanel title="Chart" /> },
        { key: "b", content: <DockPanel title="DOM" /> },
      ]}
      onResize={onResize}
      onAnnounce={onAnnounce}
    />
  );
}

describe("SplitPane (CMP-083)", () => {
  it("is a named separator with its value, minimum and maximum in %", async () => {
    const host = await mount(split());
    const separator = within(host).getByRole("separator", { name: "Chart and DOM splitter" });
    expect(separator).toHaveAttribute("aria-orientation", "vertical");
    expect(separator).toHaveAttribute("aria-valuenow", "50");
    expect(separator).toHaveAttribute("aria-valuemin", "20");
    expect(separator).toHaveAttribute("aria-valuemax", "80");
    expect(separator).toHaveAttribute("tabindex", "0");
  });

  it("arrows move 2 %, Shift 10 %, Home equalises, End maximises; other keys pass", async () => {
    const onResize = vi.fn();
    const host = await mount(split(onResize, vi.fn(), [0.6, 0.4]));
    const separator = within(host).getByRole("separator");
    for (const init of [
      { key: "ArrowRight" },
      { key: "ArrowLeft", shiftKey: true },
      { key: "Home" },
      { key: "End" },
      { key: "a" },
    ]) {
      fireEvent.keyDown(separator, init);
    }
    const deltas = onResize.mock.calls.map(([, d]) => Math.round((d as number) * 100) / 100);
    expect(deltas).toEqual([0.02, -0.1, -0.1, 0.2]);
  });

  it("says Minimum size. once per stop, not on every press against it", async () => {
    const onResize = vi.fn();
    const onAnnounce = vi.fn();
    const host = await mount(split(onResize, onAnnounce, [0.8, 0.2]));
    const separator = within(host).getByRole("separator");
    fireEvent.keyDown(separator, { key: "ArrowRight" });
    fireEvent.keyDown(separator, { key: "ArrowRight" });
    expect(onAnnounce.mock.calls).toEqual([["Minimum size."]]);
    expect(onResize).not.toHaveBeenCalled();
  });

  it("a drag writes flex once per frame and commits once, on release", async () => {
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => frames.push(cb));
    vi.stubGlobal("cancelAnimationFrame", () => undefined);
    // jsdom has no PointerEvent: a MouseEvent carries the coordinates the drag reads.
    vi.stubGlobal("PointerEvent", MouseEvent);
    const onResize = vi.fn();
    const host = await mount(split(onResize));
    const root = host.querySelector(".cv-splitpane") as HTMLElement;
    Object.defineProperty(root, "clientWidth", { value: 1000 });
    const separator = within(host).getByRole("separator");
    fireEvent.pointerDown(separator, { clientX: 500, pointerId: 1 });
    fireEvent.pointerMove(separator, { clientX: 550 });
    fireEvent.pointerMove(separator, { clientX: 600 });
    expect(frames).toHaveLength(1);
    act(() => frames[0]?.(0));
    expect((root.children[0] as HTMLElement).style.flexGrow).toBe("0.6");
    expect(onResize).not.toHaveBeenCalled();
    fireEvent.pointerUp(separator);
    expect(onResize.mock.calls).toEqual([[0, 0.1]]);
    vi.unstubAllGlobals();
  });
});

describe("DockPanel and PanelHeader (CMP-080, CMP-082)", () => {
  it("a region named by its title, busy while loading, focus shown inside the box", async () => {
    const onClose = vi.fn();
    const host = await mount(
      <DockPanel
        title="Chart BTCUSDT 1 minute"
        state="loading"
        focused
        header={
          <PanelHeader
            kind="Chart"
            title="Chart"
            level={3}
            onMove={vi.fn()}
            onClose={onClose}
            actions={<button type="button">Indicators</button>}
          />
        }
      />,
    );
    const region = within(host).getByRole("region", { name: "Chart BTCUSDT 1 minute" });
    expect(region).toHaveAttribute("aria-busy", "true");
    expect(region).toHaveAttribute("data-focused");
    expect(within(region).getByRole("heading", { level: 3 })).toHaveTextContent("Chart");
    expect(within(region).getByRole("toolbar", { name: "Chart actions" })).toBeInTheDocument();
    fireEvent.click(within(region).getByRole("button", { name: "Close Chart" }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(within(region).getByRole("button", { name: "Move Chart" })).toBeInTheDocument();
  });
});

describe("DockGridView (CMP-081)", () => {
  const tree: DockViewNode = {
    type: "row",
    id: "r",
    sizes: [0.5, 0.5],
    children: [
      leaf("a"),
      {
        type: "tabset",
        id: "t",
        active: 0,
        children: [
          { type: "leaf", id: "leaf-b", paneId: "b" },
          { type: "leaf", id: "leaf-c", paneId: "c" },
        ],
      },
    ],
  };
  const view = (onActivateTab = vi.fn(), onResize = vi.fn()) => (
    <DockGridView
      root={tree}
      paneName={(p) => p.toUpperCase()}
      renderSlot={(l) => <DockPanel title={l.paneId.toUpperCase()} />}
      onResize={onResize}
      onActivateTab={onActivateTab}
      minSizes={() => [0.1, 0.1]}
    />
  );

  it("renders splits, a tab group and the visible slots, axe-clean", async () => {
    const host = await mount(view());
    expect(
      within(host)
        .getAllByRole("region")
        .map((r) => r.getAttribute("aria-label")),
    ).toEqual(["A", "B"]);
    expect(within(host).getByRole("separator", { name: "A and B splitter" })).toBeInTheDocument();
    expect(within(host).getByRole("tablist", { name: "B, C" })).toBeInTheDocument();
    expect(await seriousViolations(host)).toEqual([]);
  });

  it("reports a tab switch and a resize by node id", async () => {
    const onActivateTab = vi.fn();
    const onResize = vi.fn();
    const host = await mount(view(onActivateTab, onResize));
    fireEvent.click(within(host).getByRole("tab", { name: "C" }));
    expect(onActivateTab).toHaveBeenCalledWith("t", 1);
    fireEvent.keyDown(within(host).getByRole("separator"), { key: "ArrowLeft" });
    expect(onResize).toHaveBeenCalledWith("r", 0, -0.02);
  });

  it("Home equalises the whole split when the host offers it", async () => {
    const onEqualise = vi.fn();
    const host = await mount(
      <DockGridView
        root={tree}
        paneName={String}
        renderSlot={() => null}
        onResize={vi.fn()}
        onActivateTab={vi.fn()}
        onEqualise={onEqualise}
      />,
    );
    fireEvent.keyDown(within(host).getByRole("separator"), { key: "Home" });
    expect(onEqualise).toHaveBeenCalledWith("r");
  });

  it("draws nothing for an empty dock", async () => {
    const host = await mount(
      <DockGridView
        root={null}
        paneName={String}
        renderSlot={() => null}
        onResize={vi.fn()}
        onActivateTab={vi.fn()}
      />,
    );
    expect(host.querySelector(".cv-dockgrid")?.childElementCount).toBe(0);
  });
});
