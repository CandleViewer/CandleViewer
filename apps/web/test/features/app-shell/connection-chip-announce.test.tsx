// #5345: the chip's announcements in the shell (E17-D02 §11; the Gherkin of #5345), through the
// shell's one live-region pair, on a fake clock: the exchange's feed down is said once, politely,
// by CMP-092's row and never by the chip; a stale topic is said once on entry and once on exit,
// and its T2 once per episode, assertively; Delayed once on entry; nothing per tick or heartbeat.
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

const ticker = (freshAtMs: number, over: Partial<TopicReading> = {}): TopicReading => ({
  ch: "ticker.BTCUSDT",
  rs: undefined,
  source: "live",
  status: "live",
  freshAtMs,
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
    ws.setTopics([ticker(Date.now())]);
    act(() => vi.advanceTimersByTime(1_000));
  }
};

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
  it("one polite announcement names it (CMP-092's row), none per heartbeat, and the chip says nothing", async () => {
    ws.setTopics([ticker(T0)]);
    mount();
    const polite = watch("polite");
    const assertive = watch("assertive");
    system({ kind: "exchange_state", public_ws: "disconnected" });
    for (let s = 0; s < 10; s += 1) {
      system({ kind: "health", exchange: { public_ws: "disconnected" } }); // a heartbeat re-asserts it
      seconds(1);
    }
    system({ kind: "exchange_state", public_ws: "connected" });
    live(10);
    await settle();
    expect(polite).toEqual([ROW]);
    expect(assertive).toEqual([]);
  });
});

describe("Scenario 2: a topic goes stale", () => {
  it("is said once on entry, its T2 once assertively, never per tick, and once on exit", async () => {
    ws.setTopics([ticker(T0)]);
    mount();
    const polite = watch("polite");
    const assertive = watch("assertive");
    seconds(5); // T1
    await settle();
    expect(polite).toEqual(["Price feed stale."]);
    seconds(10); // T2: 15 s
    await settle();
    expect(assertive).toEqual(["Price feed stale 15 s on BTCUSDT. New orders off."]);
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
    ws.setTopics([ticker(T0)]);
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
    ws.setTopics([ticker(T0, { status: "pending", awaitingReconnect: true })]);
    seconds(1);
    ws.go(reduce(reduce(dropped, connecting), authOk(OFF)));
    live(6);
    await settle();
    expect(polite).toEqual([]);
  });
});
