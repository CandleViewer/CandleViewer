// E22-S01 (#714) PR-B: the tape controller's lifecycle and its frame-rate ladder. Teardown
// (rules/30: every subscription has a teardown test): unmounting the panel or disposing the
// controller removes the frame listener, disconnects the ResizeObserver, unregisters the nine
// Tape commands and unpins the ring. The BQ-218 ladder steps down on measured overruns and back
// up on clean frames. "Load missed prints" asks for both ends of the gap inclusively.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TapeAnnouncer } from "../../../src/features/tape/announce";
import { startTapeFeed, type TapeClock } from "../../../src/features/tape/model/tapeFeed";
import { T0, TapeStateFixture } from "../../../src/features/tape/view/TapePanel.stories";
import { TapePanel } from "../../../src/features/tape/view/TapePanel";
import { FRAME_BUDGET_MS, TapeController } from "../../../src/features/tape/view/tapeController";
import { KeymapHost, registerCommand } from "../../../src/keymap/KeymapHost";
import { KEYMAP } from "../../../src/keymap/keymap";
import { fakeClient, type FakeHandle } from "./fakeFeed";
import { delta, items, snap } from "./frames";

const TAPE_COMMANDS = KEYMAP.filter((c) => c.context === "Tape").map((c) => c.id);

/** A manual display whose frame interval the test sets (the ladder reads the intervals). */
function steppedDisplay(initialStepMs: number) {
  const requested = new Map<number, (t: number) => void>();
  let id = 0;
  let now = 0;
  let step = initialStepMs;
  const clock: TapeClock = {
    raf: (callback) => {
      id += 1;
      requested.set(id, callback);
      return id;
    },
    caf: (h) => void requested.delete(h),
    now: () => now,
  };
  return {
    clock,
    setStep: (ms: number) => {
      step = ms;
    },
    frame: () => {
      now += step;
      const callbacks = [...requested.values()];
      requested.clear();
      for (const callback of callbacks) callback(now);
    },
  };
}

class FakeResizeObserver {
  static readonly made: FakeResizeObserver[] = [];
  readonly observe = vi.fn();
  readonly disconnect = vi.fn();
  constructor() {
    FakeResizeObserver.made.push(this);
  }
}

const bareNodes: HTMLElement[] = [];

afterEach(() => {
  vi.unstubAllGlobals();
  FakeResizeObserver.made.length = 0;
  for (const node of bareNodes.splice(0)) node.remove();
});

const tapeDom = () => {
  const grid = document.createElement("div");
  const body = document.createElement("div");
  const windowEl = document.createElement("div");
  const status = document.createElement("div");
  body.append(windowEl);
  grid.append(body);
  document.body.append(grid, status);
  bareNodes.push(grid, status);
  return { grid, body, windowEl, status };
};

/** A controller on a real feed, outside React, with a counted frame-listener teardown. */
const bare = (stepMs: number, capacity = 10_000) => {
  vi.stubGlobal("ResizeObserver", FakeResizeObserver);
  const fake = fakeClient();
  const display = steppedDisplay(stepMs);
  const feed = startTapeFeed(fake.client, {
    symbol: "BTCUSDT",
    paneId: "tape",
    capacity,
    clock: display.clock,
  });
  const offFrame = vi.fn();
  const counted = {
    ...feed,
    onFrame: (listener: (appended: number) => void) => {
      const off = feed.onFrame(listener);
      return () => {
        offFrame();
        off();
      };
    },
  };
  const controller = new TapeController({
    feed: counted,
    clock: display.clock,
    wallNow: () => T0,
    fetchTrades: () => Promise.resolve([]),
    announcer: new TapeAnnouncer(),
    idBase: "tc",
  });
  const dom = tapeDom();
  controller.attach(dom);
  const handle = fake.handles[0] as FakeHandle;
  handle.status = "live";
  return { feed, controller, display, handle, dom, offFrame };
};

describe("tape controller teardown", () => {
  it("dispose removes the frame listener, disconnects the ResizeObserver and unpins the ring", () => {
    const t = bare(16, 200);
    t.handle.queue.push(snap(items(1, 150)));
    t.display.frame();
    t.controller.gridFocus();
    t.controller.gridKey("ArrowDown"); // FP-12: pauses on the newest row, pinning it and the window
    t.display.frame();
    expect(t.controller.pause.focus).toBe(true);
    const observer = FakeResizeObserver.made[0];
    expect(observer?.observe).toHaveBeenCalledWith(t.dom.grid);

    t.controller.dispose();
    expect(t.offFrame).toHaveBeenCalledTimes(1);
    expect(observer?.disconnect).toHaveBeenCalled();
    // with the pins gone, a full ring keeps evicting: nothing is refused (S22's notKept stays 0)
    t.handle.queue.push(delta(items(151, 600)));
    t.display.frame();
    expect(t.feed.ring.notKept).toBe(0);
    expect(t.feed.ring.length).toBe(200);
    t.controller.dispose(); // idempotent
    expect(t.offFrame).toHaveBeenCalledTimes(1);
    t.feed.stop();
  });

  it("unmounting the panel disposes its controller and unregisters the nine Tape commands", () => {
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    const fake = fakeClient();
    const display = steppedDisplay(16);
    let controller: TapeController | null = null;
    const view = render(
      <>
        <KeymapHost />
        <TapePanel
          symbol="BTCUSDT"
          enabled
          client={fake.client}
          clock={display.clock}
          transport="connected"
          fetchTrades={() => Promise.resolve([])}
          onController={(c) => {
            if (c !== null) controller = c;
          }}
        />
      </>,
    );
    expect(controller).not.toBeNull();
    expect(TAPE_COMMANDS).toHaveLength(9);
    // while mounted the panel holds every Tape command: a second handler is refused
    expect(() => registerCommand("tape.pause_toggle", () => undefined)).toThrow(/already/);
    const observer = FakeResizeObserver.made.at(-1);
    act(() => view.unmount());
    expect(observer?.disconnect).toHaveBeenCalled();
    // every handler is gone: each command takes a new one
    const offs = TAPE_COMMANDS.map((id) => registerCommand(id, () => undefined));
    offs.forEach((off) => off());
  });
});

describe("tape fallback ladder (BQ-218)", () => {
  const frames = (t: ReturnType<typeof bare>, n: number, perFrame = 0) => {
    for (let k = 0; k < n; k += 1) {
      if (perFrame > 0) {
        const from = t.feed.ring.nextSeq + 1;
        t.handle.queue.push(delta(items(from, from + perFrame - 1)));
      }
      t.display.frame();
    }
  };

  it("holds rung 0 while every frame is inside the 55 fps budget", () => {
    const t = bare(FRAME_BUDGET_MS - 2);
    t.handle.queue.push(snap(items(1, 50)));
    frames(t, 200, 2);
    expect(t.controller.metrics().rung).toBe(0);
    expect(t.controller.getSnapshot().rung).toBe(0);
    t.controller.dispose();
    t.feed.stop();
  });

  it("steps down a rung per 30 overrun frames, and rung 2 writes rows every 2nd frame", () => {
    const t = bare(30);
    t.handle.queue.push(snap(items(1, 50)));
    frames(t, 31);
    expect(t.controller.metrics().rung).toBe(1);
    expect(t.controller.getSnapshot().rung).toBe(1); // a rung change publishes at once
    frames(t, 30);
    expect(t.controller.metrics().rung).toBe(2);
    frames(t, 60);
    expect(t.controller.metrics().rung).toBe(2); // rung 3 is not built (BQ-218)
    // rung 2: one print a frame, the rows (and their count) follow every 2nd frame only
    const rowCount = () => t.dom.grid.getAttribute("aria-rowcount");
    let last = rowCount();
    let writes = 0;
    for (let k = 0; k < 6; k += 1) {
      frames(t, 1, 1);
      if (rowCount() !== last) writes += 1;
      last = rowCount();
    }
    expect(writes).toBe(3);
    t.controller.dispose();
    t.feed.stop();
  });

  it("steps back up a rung per 120 clean frames in a row", () => {
    const t = bare(30);
    t.handle.queue.push(snap(items(1, 50)));
    frames(t, 61);
    expect(t.controller.metrics().rung).toBe(2);
    t.display.setStep(16);
    frames(t, 119);
    expect(t.controller.metrics().rung).toBe(2);
    frames(t, 2);
    expect(t.controller.metrics().rung).toBe(1);
    frames(t, 120);
    expect(t.controller.metrics().rung).toBe(0);
    expect(t.controller.getSnapshot().rung).toBe(0);
    t.controller.dispose();
    t.feed.stop();
  });
});

describe("tape missed prints (S16)", () => {
  it("asks for the gap with both ends inclusive: prints sharing the edge millisecond are fetched", async () => {
    const onFetch = vi.fn();
    render(<TapeStateFixture state="S16" onFetch={onFetch} />);
    await waitFor(() =>
      expect(screen.getByRole("status", { name: "Tape status" }).textContent).toBe(
        "3 missed prints loaded",
      ),
    );
    // the last print before the reset is #1 400 and the first after it #1 401, 5 ms apart
    expect(onFetch).toHaveBeenCalledWith({
      symbol: "BTCUSDT",
      fromMs: T0 + 1_400 * 5,
      toMs: T0 + 1_401 * 5 + 1,
    });
  });
});

describe("tape panel props and feed changes", () => {
  const panel = (fake: ReturnType<typeof fakeClient>, clock: TapeClock) =>
    function Panel(props: Partial<ComponentProps<typeof TapePanel>>) {
      return (
        <TapePanel
          symbol="BTCUSDT"
          enabled
          client={fake.client}
          clock={clock}
          transport="connected"
          fetchTrades={() => Promise.resolve([])}
          registerKeys={false}
          {...props}
        />
      );
    };

  it("a new locate prop applies to the running controller (the props are read at each call)", () => {
    const fake = fakeClient();
    const display = steppedDisplay(16);
    const Panel = panel(fake, display.clock);
    const first = vi.fn();
    const second = vi.fn();
    const view = render(<Panel locate={first} />);
    const handle = fake.handles[0] as FakeHandle;
    handle.status = "live";
    handle.queue.push(snap(items(1, 20)));
    act(() => display.frame());
    view.rerender(<Panel locate={second} />);
    const grid = screen.getByRole("grid", { name: "Tape BTCUSDT" });
    const cell = grid.querySelector('[role="row"][aria-rowindex="2"] [role="gridcell"]');
    if (cell === null) throw new Error("no row");
    fireEvent.click(cell);
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });

  it("a feed change leaves no stale active cell or row count on the grid", () => {
    const fake = fakeClient();
    const display = steppedDisplay(16);
    const Panel = panel(fake, display.clock);
    const view = render(<Panel />);
    const handle = fake.handles[0] as FakeHandle;
    handle.status = "live";
    handle.queue.push(snap(items(1, 20)));
    act(() => display.frame());
    const grid = screen.getByRole("grid", { name: "Tape BTCUSDT" });
    act(() => grid.focus());
    const cell = grid.querySelector('[role="row"][aria-rowindex="2"] [role="gridcell"]');
    if (cell === null) throw new Error("no row");
    fireEvent.click(cell);
    expect(grid).toHaveAttribute("aria-activedescendant");
    view.rerender(<Panel symbol="ETHUSDT" />);
    const next = screen.getByRole("grid", { name: "Tape ETHUSDT" });
    expect(next).not.toHaveAttribute("aria-activedescendant");
    expect(next).toHaveAttribute("aria-rowcount", "1");
  });
});
