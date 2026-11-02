// #5345: the chip's announcements in the shell (E17-D02 §11; the Gherkin of #5345), through the
// shell's one live-region pair, on a fake clock: the exchange's feed down is entered once, politely,
// by CMP-092's row and left by the chip's one exit sentence; a stale topic is said once on entry and
// once on exit, and its T2 once per episode, assertively; Delayed once on entry; nothing per tick
// or heartbeat; an ended episode's sentences leave the regions, and an unmount leaves no timer.
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";
import { ShellBannerSlot, ShellConnectionSlot } from "../../../src/features/app-shell/slots";
import { toLatencyIndicator } from "../../../src/lib/telemetry/latencyIndicator.js";
import type { SystemUpdate } from "../../../src/lib/ws/protocol/frames";
import type { TopicReading } from "../../../src/lib/ws/state/chipState";
import { reduce } from "../../../src/lib/ws/state/reducer";
import {
  applySystemUpdate,
  resetShellState,
  setShellState,
} from "../../../src/shell/bootstrap/store.js";
import { OFF, authOk, connecting, quality, stream } from "../../lib/ws/support/engineEvents";
import { fakeActiveClient, runEvents } from "../../lib/ws/support/fakeActiveClient";

const T0 = Date.UTC(2026, 10, 1, 13, 42, 5);
const UP = runEvents(connecting, authOk(OFF), stream("live"));
const ROW = "Exchange feed down — the server is restoring the connection.";

/** A live ticker with a fresh frame now, on the client's clocks (monotonic; the wall for the text). */
const ticker = (over: Partial<TopicReading> = {}): TopicReading => ({
  ch: "ticker.BTCUSDT",
  rs: undefined,
  source: "live",
  status: "live",
  freshAtMs: performance.now(),
  agedFromMs: performance.now(),
  lastDataMs: Date.now(),
  serverStale: false,
  awaitingReconnect: false,
  ...over,
});
const seconds = (n: number): void => {
  for (let s = 0; s < n; s += 1) act(() => vi.advanceTimersByTime(1_000));
};
const system = (update: SystemUpdate): void => act(() => applySystemUpdate(update));
/** `n` seconds of a live ticker: a fresh frame each second, as a live feed brings. */
const live = (n: number): void => {
  for (let s = 0; s < n; s += 1) {
    ws.setTopics([ticker()]);
    act(() => vi.advanceTimersByTime(1_000));
  }
};
/** What a live region of `politeness` holds now (the shell's; CMP-092's polite one has its own). */
const holds = (politeness: "polite" | "assertive"): string[] =>
  [...document.querySelectorAll(`[aria-live="${politeness}"]`)].map((r) => r.textContent ?? "");

/** Every message written into a live region of `politeness` from now on: CMP-092's own polite one and the shell's. */
function watch(politeness: "polite" | "assertive"): string[] {
  const said: string[] = [];
  const observer = new MutationObserver((records) => {
    for (const r of records) {
      if ((r.target as Element).getAttribute?.("aria-live") !== politeness) continue;
      for (const node of r.addedNodes) said.push(node.textContent ?? "");
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
  return said;
}
/** Lets the observer's records arrive (a microtask). */
const settle = async (): Promise<void> => {
  await act(async () => await Promise.resolve());
};

let ws: ReturnType<typeof fakeActiveClient>;
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
  ws = fakeActiveClient(UP);
  act(() => setShellState({ connection: { kind: "live" }, latency: toLatencyIndicator(42) }));
});
afterEach(() => {
  ws.detach();
  act(() => {
    resetShellState();
    clearAnnouncements();
  });
  vi.useRealTimers();
});

const mount = () =>
  render(
    <>
      <ShellConnectionSlot />
      <ShellBannerSlot />
      <ShellAnnouncer />
    </>,
  );

describe("Scenario 1: the exchange's public feed down", () => {
  it("one polite announcement names it (CMP-092's row), none per heartbeat, and the chip says only its exit, once", async () => {
    ws.setTopics([ticker()]);
    mount();
    const polite = watch("polite");
    const assertive = watch("assertive");
    system({ kind: "exchange_state", public_ws: "disconnected" });
    for (let s = 0; s < 10; s += 1) {
      system({ kind: "health", exchange: { public_ws: "disconnected" } }); // a heartbeat re-asserts it
      seconds(1);
    }
    await settle();
    expect(polite).toEqual([ROW]);
    system({ kind: "exchange_state", public_ws: "connected" });
    live(10); // the feed back and fresh: §11 row 5's exit after 5 s of freshness
    await settle();
    expect(polite).toEqual([ROW, "Price feed live."]);
    expect(assertive).toEqual([]);
  });
});

describe("Scenario 2: a topic goes stale", () => {
  it("is said once on entry, its T2 once assertively, never per tick, and once on exit", async () => {
    ws.setTopics([ticker()]);
    mount();
    const polite = watch("polite");
    const assertive = watch("assertive");
    seconds(5); // T1
    await settle();
    expect(polite).toEqual(["Price feed stale."]);
    seconds(10); // T2: 15 s
    await settle();
    expect(assertive).toEqual(["Price feed stale 15 s on BTCUSDT."]);
    seconds(20); // the age moves on at 1 Hz: nothing more is said
    await settle();
    expect([polite.length, assertive.length]).toEqual([1, 1]);
    live(1);
    await settle();
    expect(polite).toHaveLength(1); // the exit waits for 5 s of freshness
    live(5);
    await settle();
    expect(polite).toEqual(["Price feed stale.", "Price feed live."]);
    expect(assertive).toHaveLength(1);
    // the episode's sentences leave the regions; its exit, written first, stays
    expect(holds("assertive")).toEqual([""]);
    expect(holds("polite")).toContain("Price feed live.");
  });

  it("a ticker that sends one frame every 6 s is one episode: no exit is said as the chip reads Stale again", async () => {
    // T1 is 5 s, as is the exit's hold: the 5 s of freshness fall due in the second the chip turns Stale
    ws.setTopics([ticker()]);
    mount();
    const polite = watch("polite");
    for (let s = 0; s < 40; s += 1) {
      if (s % 6 !== 0) {
        seconds(1);
        continue;
      }
      act(() => vi.advanceTimersByTime(500)); // its frame lands between two ticks of the chip's clock
      ws.setTopics([ticker()]);
      act(() => vi.advanceTimersByTime(500));
    }
    await settle();
    expect(polite).toEqual(["Price feed stale."]);
  });

  it("a Disconnected episode ends it in silence and takes its sentences out of the regions", async () => {
    ws.setTopics([ticker()]);
    render(
      <>
        <ShellConnectionSlot />
        <ShellAnnouncer />
      </>,
    ); // no CMP-077 region here: nothing else writes over the chip's sentences
    seconds(16); // T1, then T2: both said
    await settle();
    expect([holds("polite"), holds("assertive")]).toEqual([
      ["Price feed stale."],
      ["Price feed stale 15 s on BTCUSDT."],
    ]);
    const lost = { sinceMs: T0, lastDataMs: T0 };
    ws.go(reduce(UP, { type: "reconnecting", attempt: 1, nextAttemptAtMs: T0 + 1_000, lost }));
    expect([holds("polite"), holds("assertive")]).toEqual([[""], [""]]);
  });
});

describe("Scenario 3: saturated", () => {
  it("Delayed is said once, politely, on entry", async () => {
    mount();
    const polite = watch("polite");
    ws.go(reduce(UP, quality("saturated")));
    system({ kind: "connection_quality", class: "saturated", applied: { throttle_multiplier: 4 } });
    seconds(3);
    await settle();
    expect(polite).toEqual(["Reduced rate."]); // the factor comes in the next frame (portHost)
  });
});

describe("Scenario 4: recovery", () => {
  it("after a reconnect the chip reads Live and says nothing of its own: the recovered sentence is CMP-077's (#569)", async () => {
    const fed = ticker();
    ws.setTopics([fed]);
    mount();
    const polite = watch("polite");
    const lost = { sinceMs: T0, lastDataMs: T0 };
    const dropped = reduce(UP, {
      type: "reconnecting",
      attempt: 1,
      nextAttemptAtMs: T0 + 1_000,
      lost,
    });
    ws.go(dropped);
    ws.setTopics([{ ...fed, status: "pending", awaitingReconnect: true }]);
    seconds(1);
    ws.go(reduce(reduce(dropped, connecting), authOk(OFF)));
    live(6);
    await settle();
    expect(polite).toEqual([]);
  });
});

describe("teardown (every subscription has one)", () => {
  it("unmounting the container clears its 1 Hz interval and the announcer's timers", () => {
    ws.setTopics([ticker()]);
    const { unmount } = render(
      <>
        <ShellConnectionSlot />
        <ShellAnnouncer />
      </>,
    );
    expect(vi.getTimerCount()).toBe(1); // the 1 Hz clock: the link is up
    seconds(6); // past T1: the entry is said
    ws.setTopics([ticker()]); // fresh again: the exit waits for 5 s of freshness
    seconds(1);
    act(() => vi.advanceTimersByTime(100)); // the cross-fade's frame
    expect(vi.getTimerCount()).toBe(2); // the clock and the announcer's exit hold
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
