/**
 * E16-S01 PR 3 on SCR-140's page: the row detail's registration (`openRowDetail`, #485/#486 BQ-6), the disk card's
 * Shorten retention that opens the largest row's detail (E16-D02 §8.3), over a stubbed `apiFetch` and a fake socket
 * whose animation frame the test steps; every timer fake, no network (C-13.5).
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";
import {
  useRecorderExtensions,
  type RecorderExtensions,
} from "../../../src/features/recorder/extensions";
import type { RecorderFrame } from "../../../src/features/recorder/model";
import { RecorderScreen } from "../../../src/features/recorder/RecorderScreen";
import { NOW } from "./gridFixtures";
import { LIST, STATUS, STORAGE, fakeSocket, frameOf, router } from "./screenFixtures";

const flush = () => act(async () => void (await vi.advanceTimersByTimeAsync(0)));
let clock = { now: NOW };

const json = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });
/** Nothing recorded yet: the three first reads empty (CMP-026 in the grid's place). */
const EMPTY = router((_, url) =>
  url.includes("/recording/symbols?")
    ? json(200, { items: [], meta: { count: 0, has_more: false } })
    : url.endsWith("/recording/status")
      ? json(200, { ...STATUS, symbols: [] })
      : url.endsWith("/recording/storage")
        ? json(200, { ...STORAGE, tiers: [], symbols: [] })
        : undefined,
);

async function mountPage(frame: RecorderFrame = frameOf(), answers = router()) {
  apiFetch.mockImplementation(answers);
  const socket = fakeSocket(clock);
  const view = render(
    <>
      <RecorderScreen data={socket.options} instruments={["SOLUSDT"]} />
      <ShellAnnouncer />
    </>,
  );
  await flush();
  socket.push(frame);
  act(() => socket.step(0));
  await flush();
  return { ...view, socket };
}

/** The registry as another part sees it (S03's "Manage pin in Recorder"), from its own root. */
function probe(): { readonly current: () => RecorderExtensions; readonly unmount: () => void } {
  let seen: RecorderExtensions = {};
  function Probe(): null {
    seen = useRecorderExtensions();
    return null;
  }
  const view = render(<Probe />);
  return { current: () => seen, unmount: view.unmount };
}

const scroll = Element.prototype.scrollIntoView;
beforeEach(() => {
  vi.useFakeTimers({
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date", "performance"],
    now: NOW,
  });
  clock = { now: NOW };
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  Element.prototype.scrollIntoView = scroll;
  act(() => clearAnnouncements());
  apiFetch.mockReset();
  vi.useRealTimers();
});

const CASE = { timeout: 20_000 } as const;

describe("the row detail on the page (E16-D02 §6.7; #485/#486 BQ-6)", CASE, () => {
  it("registers openRowDetail while mounted: it opens the symbol's detail; unmounted, it is gone", async () => {
    const registry = probe();
    const page = await mountPage();
    const open = registry.current().openRowDetail;
    expect(open).toBeTypeOf("function");
    act(() => open?.("ETHUSDT"));
    expect(screen.getByRole("dialog", { name: "ETHUSDT recording" })).toBeInTheDocument();
    page.unmount();
    expect(registry.current().openRowDetail).toBeUndefined();
    registry.unmount();
  });

  it("a press on a row's symbol opens its detail on its heading", async () => {
    await mountPage();
    const symbol = screen.getByRole("button", { name: "BTCUSDT" });
    act(() => symbol.focus());
    fireEvent.click(symbol);
    const heading = screen.getByRole("heading", { level: 2, name: "BTCUSDT recording" });
    expect(heading).toHaveFocus();
  });

  it("Shorten retention sorts by size and opens the largest row's detail (D02 §8.3)", async () => {
    await mountPage(frameOf({}, { level: 1, used_bytes: 161e9 }));
    fireEvent.click(screen.getByRole("button", { name: "Shorten retention" }));
    expect(screen.getByRole("dialog", { name: "BTCUSDT recording" })).toBeInTheDocument();
  });

  it("a detail asked for while no grid is drawn is dropped: it never opens by itself once rows arrive (C-5347-08)", async () => {
    const registry = probe();
    const { socket } = await mountPage({ ...frameOf({}, { used_bytes: 0 }), symbols: [] }, EMPTY);
    expect(
      screen.getByRole("heading", { level: 2, name: "Nothing is recorded yet" }),
    ).toBeVisible();
    act(() => registry.current().openRowDetail?.("ETHUSDT"));
    await flush();
    expect(screen.queryByRole("dialog")).toBeNull();
    socket.push(frameOf());
    act(() => socket.step(1_000));
    await flush();
    expect(screen.getByRole("button", { name: "ETHUSDT" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    registry.unmount();
  });
});

describe("the last row's going (A-5347-d03; F-05)", CASE, () => {
  it("unpinning the only row from the grid swaps it for the empty state; focus lands on the H1, never body", async () => {
    const only = { ...LIST[0], state: "stopped" } as const; // BTCUSDT, pinned, stopped
    let unpinned = false;
    const answers = router((method, url) => {
      if (method === "PUT" && url.endsWith("/recording/symbols/id-btcusdt/pin")) {
        unpinned = true; // `22`: unpinning a stopped row ends its listing
        return json(200, { ...only, pinned: false, retention_days: 30 });
      }
      if (url.includes("/recording/symbols?")) {
        const items = unpinned ? [] : [only];
        return json(200, { items, meta: { count: items.length, has_more: false } });
      }
      if (url.endsWith("/recording/status")) {
        return json(200, { ...STATUS, symbols: STATUS.symbols?.slice(0, 1) });
      }
      return undefined;
    });
    const frameWith = (symbols: RecorderFrame["symbols"]): RecorderFrame => ({
      ...frameOf(),
      symbols,
    });
    const btc = frameOf({ BTCUSDT: { state: "stopped" } }).symbols.slice(0, 1);
    const { socket } = await mountPage(frameWith(btc), answers);
    const keep = screen.getByRole("switch", { name: "Keep BTCUSDT data forever" });
    act(() => keep.focus());
    fireEvent.click(keep);
    const confirm = screen.getByRole("alertdialog", { name: "Stop keeping BTCUSDT forever?" });
    fireEvent.change(screen.getByRole("textbox", { name: "Type BTCUSDT to confirm" }), {
      target: { value: "BTCUSDT" },
    });
    await act(async () => void (await vi.advanceTimersByTimeAsync(500)));
    const stop = screen.getByRole("button", { name: "Stop keeping BTCUSDT forever" });
    act(() => stop.focus());
    fireEvent.click(stop);
    await flush();
    await flush();
    expect(confirm).not.toBeInTheDocument();
    // The list is read again past the topic's 5 s gap (ROWS_REREAD_GAP_MS), with the frame that no longer names it.
    socket.push(frameWith([]));
    act(() => socket.step(5_000));
    await flush();
    await flush();
    expect(
      screen.getByRole("heading", { level: 2, name: "Nothing is recorded yet" }),
    ).toBeVisible();
    expect(screen.getByRole("heading", { level: 1, name: "Recorder" })).toHaveFocus();
  });

  it("a page that opens empty leaves focus where it is: nothing to land from", async () => {
    await mountPage({ ...frameOf({}, { used_bytes: 0 }), symbols: [] }, EMPTY);
    expect(
      screen.getByRole("heading", { level: 2, name: "Nothing is recorded yet" }),
    ).toBeVisible();
    expect(document.activeElement).toBe(document.body);
  });
});
