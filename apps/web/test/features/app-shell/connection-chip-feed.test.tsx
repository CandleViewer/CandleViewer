// #5345 (E08-D14 DF-1, FS-1): the CMP-076 chip's container fed from the signals E17-D02 §3 names:
// the shell store's `exchange_state` fact (row 13), the topics the WS client reads (rows 10–12, 16)
// and the `connection_quality` class and multiplier (row 5, §9). Every state is found by role, on
// a fake clock; the words are §10 A's, which CMP-076 already carries, the stale age spelled out.
import { createRequire } from "node:module";
import { Profiler } from "react";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";
import { ShellBannerSlot, ShellConnectionSlot } from "../../../src/features/app-shell/slots";
import { toLatencyIndicator } from "../../../src/lib/telemetry/latencyIndicator.js";
import type { TopicFrame } from "../../../src/lib/ws/api";
import { setActiveClient } from "../../../src/lib/ws/client/activeClient";
import { createWsClient } from "../../../src/lib/ws/client/createWsClient";
import type { TopicReading } from "../../../src/lib/ws/state/chipState";
import type { Timers } from "../../../src/lib/ws/policy/timers";
import { INITIAL_WS_STATE, reduce } from "../../../src/lib/ws/state/reducer";
import type { SystemUpdate } from "../../../src/lib/ws/protocol/frames";
import {
  applySystemUpdate,
  resetShellState,
  setShellState,
  subscribeShellState,
} from "../../../src/shell/bootstrap/store.js";
import { OFF, authOk, connecting, quality, stream } from "../../lib/ws/support/engineEvents";
import { fakeActiveClient, runEvents } from "../../lib/ws/support/fakeActiveClient";
import { fakePage } from "../../lib/ws/support/fakePage";
import { FakePort } from "../../lib/ws/support/fakePort";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };
// color-contrast is off: jsdom computes no styles (the e2e spec runs it in Chromium).
const seriousAxe = async (el: Element): Promise<unknown[]> =>
  (await axe.run(el, { rules: { "color-contrast": { enabled: false } } })).violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );

const T0 = Date.UTC(2026, 10, 1, 13, 42, 5);
const UP = runEvents(connecting, authOk(OFF), stream("live"));
const SATURATED = reduce(UP, quality("saturated"));
const DROPPED = reduce(UP, {
  type: "reconnecting",
  attempt: 1,
  nextAttemptAtMs: T0 + 1_000,
  lost: { sinceMs: T0, lastDataMs: T0 },
});
const BACK = reduce(reduce(DROPPED, connecting), authOk(OFF));
const DOWN: SystemUpdate = { kind: "exchange_state", public_ws: "disconnected" };
const FEED_BACK: SystemUpdate = { kind: "exchange_state", public_ws: "connected" };
const HEARTBEAT: SystemUpdate = {
  kind: "health",
  health: "degraded",
  exchange: { public_ws: "disconnected" },
};
const QUALITY = (cls: "saturated" | "healthy", multiplier?: number): SystemUpdate => ({
  kind: "connection_quality",
  class: cls,
  queue_pct: cls === "saturated" ? 72 : 10,
  rtt_ms: cls === "saturated" ? 640 : 40,
  ...(multiplier !== undefined && { applied: { throttle_multiplier: multiplier } }),
});

/**
 * A live ticker whose last fresh frame came `ageMs` ago, on the clocks the client stamps with: its
 * monotonic one (`performance.now`, which `vi.setSystemTime` never moves) and the wall for the text.
 */
const ticker = (ageMs = 0, over: Partial<TopicReading> = {}): TopicReading => {
  const at = performance.now() - ageMs;
  return {
    ch: "ticker.BTCUSDT",
    rs: undefined,
    source: "live",
    status: "live",
    freshAtMs: at,
    agedFromMs: at,
    lastDataMs: Date.now() - ageMs,
    serverStale: false,
    awaitingReconnect: false,
    ...over,
  };
};

const chip = (): HTMLElement => screen.getByRole("button", { name: /^Connection: / });
const seconds = (n: number): void => {
  for (let s = 0; s < n; s += 1) act(() => vi.advanceTimersByTime(1_000));
};
const system = (update: SystemUpdate): void => act(() => applySystemUpdate(update));

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

describe("row 13 (FS-1): the exchange's public feed down", () => {
  it("reads Stale — exchange feed down within the frame of the message, and never Live until a public snapshot arrives", async () => {
    ws.setTopics([ticker()]);
    mount();
    expect(chip()).toHaveAccessibleName("Connection: Live 42 ms");
    seconds(1);
    system(DOWN); // no timer runs between the message and the check
    expect(chip()).toHaveAttribute("data-status", "stale");
    expect(chip()).toHaveTextContent("Stale — exchange feed down");
    expect(chip().getAttribute("aria-label")).toMatch(/^Connection: Stale — exchange feed down, /);
    for (let s = 0; s < 3; s += 1) {
      system(HEARTBEAT); // the server re-asserts it: nothing moves
      seconds(1);
      expect(chip()).toHaveTextContent("Stale — exchange feed down");
    }
    system(FEED_BACK); // the feed is back, but the ticker has had no fresh frame since it went down
    seconds(2);
    expect(chip()).toHaveTextContent("Stale — exchange feed down");
    ws.setTopics([ticker()]); // its upstream_reconnect snapshot
    seconds(1);
    expect(chip()).toHaveAccessibleName("Connection: Live 42 ms");
    expect(chip()).toHaveAttribute("data-status", "live");
    vi.useRealTimers(); // axe schedules with real timers
    expect(await seriousAxe(document.body)).toEqual([]);
  });

  it("with no public topic to wait for, reads Live as soon as the feed is back", () => {
    mount();
    system(DOWN);
    expect(chip()).toHaveTextContent("Stale — exchange feed down");
    expect(chip().getAttribute("aria-label")).toBe("Connection: Stale — exchange feed down");
    system(FEED_BACK);
    expect(chip()).toHaveAccessibleName("Connection: Live 42 ms");
  });

  it("a topic subscribed during the outage holds it once the feed is back, until its snapshot arrives", () => {
    mount();
    system(DOWN);
    seconds(1);
    // made in the outage: no frame yet, aged from its consume time
    ws.setTopics([ticker(0, { status: "pending", freshAtMs: null, lastDataMs: null })]);
    seconds(1);
    system(FEED_BACK);
    seconds(2);
    expect(chip()).toHaveTextContent("Stale — exchange feed down");
    expect(chip()).toHaveAttribute("data-status", "stale");
    ws.setTopics([ticker()]); // its snapshot
    seconds(1);
    expect(chip()).toHaveAccessibleName("Connection: Live 42 ms");
  });

  it("after a reconnect it wins over the wait for the public snapshots: the fact comes with auth_ok", () => {
    const fed = ticker();
    ws.setTopics([fed]);
    mount();
    ws.go(DROPPED);
    ws.setTopics([{ ...fed, status: "pending", awaitingReconnect: true }]); // its reset
    seconds(1);
    ws.go(BACK);
    system(DOWN); // auth_ok's system snapshot: the exchange's feed is still down
    expect(chip()).toHaveTextContent("Stale — exchange feed down");
    expect(chip()).toHaveAttribute("data-status", "stale");
  });

  it("is drawn with the stale glyph on the bar fill, never the strong one", () => {
    ws.setTopics([ticker(60_000)]); // a topic past its T2 does not make the feed-down chip strong
    mount();
    system(DOWN);
    expect(chip().style.background).toBe("var(--color-surface-raised)");
    const glyph = chip().querySelector<HTMLElement>("[data-glyph]");
    expect(glyph?.style.color).toBe("var(--color-data-confidence-stale-indicator)");
  });
});

describe("rows 10–12: a topic's age and the server's word", () => {
  it("a ticker silent past T1 reads Stale 7 seconds, and past T2 Stale 15 seconds in the strong variant", async () => {
    ws.setTopics([ticker()]);
    mount();
    seconds(4);
    expect(chip()).toHaveAttribute("data-status", "live");
    seconds(3); // 7 s since its last frame: past T1 (5 s)
    expect(chip()).toHaveAttribute("data-status", "stale");
    expect(chip()).toHaveTextContent("Stale 7 seconds");
    expect(chip()).toHaveAccessibleName("Connection: Stale 7 seconds, last data 13:42:05 UTC");
    expect(chip().style.background).toBe("var(--color-surface-raised)");
    seconds(7);
    expect(chip()).toHaveTextContent("Stale 14 seconds"); // the age at 1 Hz, never announced
    seconds(1); // 15 s: T2
    expect(chip()).toHaveTextContent("Stale 15 seconds");
    expect(chip()).toHaveAccessibleName("Connection: Stale 15 seconds, last data 13:42:05 UTC");
    expect(chip().style.background).toBe("var(--color-status-warning-subtle)");
    const glyph = chip().querySelector<HTMLElement>("[data-glyph]");
    expect(glyph?.style.color).toBe("var(--color-status-warning-strong)");
    vi.useRealTimers(); // axe schedules with real timers
    expect(await seriousAxe(document.body)).toEqual([]);
  });

  it("a step of the wall clock neither resets nor stretches an age: it runs on the monotonic clock", () => {
    ws.setTopics([ticker()]);
    mount();
    seconds(7);
    expect(chip()).toHaveTextContent("Stale 7 seconds");
    act(() => vi.setSystemTime(Date.now() - 60_000)); // the wall clock steps back a minute
    seconds(1);
    expect(chip()).toHaveTextContent("Stale 8 seconds");
    act(() => vi.setSystemTime(Date.now() + 120_000)); // and forward two
    seconds(1);
    expect(chip()).toHaveTextContent("Stale 9 seconds");
    expect(chip().getAttribute("aria-label")).toMatch(/, last data 13:42:05 UTC$/);
  });

  it("the stale topic's first fresh frame reads Live again", () => {
    ws.setTopics([ticker()]);
    mount();
    seconds(16);
    expect(chip()).toHaveTextContent("Stale 16 seconds");
    ws.setTopics([ticker()]);
    seconds(1);
    expect(chip()).toHaveAccessibleName("Connection: Live 42 ms");
  });

  it("the last data is the stale topic's, in the name and the title", () => {
    ws.setTopics([ticker()]);
    mount();
    seconds(7);
    expect(chip().getAttribute("aria-label")).toMatch(/, last data 13:42:05 UTC$/);
    expect(chip()).toHaveAttribute("title", "last 13:42:05 UTC");
  });

  it("a ticker whose snapshot says meta.stale reads Stale (server)", () => {
    ws.setTopics([ticker(0, { serverStale: true })]);
    mount();
    expect(chip()).toHaveAccessibleName("Connection: Stale (server)");
    expect(chip()).toHaveAttribute("data-status", "stale");
  });

  it("a replay, derived or private topic never makes the chip stale", () => {
    ws.setTopics([
      ticker(60_000, { rs: "rs-1", source: "replay" }),
      ticker(60_000, { ch: "bars.BTCUSDT.1m" }),
      ticker(60_000, { ch: "orders" }),
    ]);
    mount();
    seconds(2);
    expect(chip()).toHaveAccessibleName("Connection: Live 42 ms");
  });
});

describe("row 5: Delayed (saturated), §9's treatment and T3", () => {
  it("reads Reduced rate ×4 with the ◐ glyph and the info fill", async () => {
    mount();
    ws.go(SATURATED);
    system(QUALITY("saturated", 4));
    expect(chip()).toHaveAttribute("data-status", "delayed");
    expect(chip()).toHaveTextContent("Reduced rate ×4");
    expect(chip().getAttribute("aria-label")).toBe("Connection: Reduced rate ×4");
    expect(chip()).toHaveTextContent("◐");
    expect(chip().style.background).toBe("var(--color-status-info-subtle)");
    vi.useRealTimers(); // axe schedules with real timers
    expect(await seriousAxe(document.body)).toEqual([]);
  });

  it("a stale topic wins over it (D2), and it resumes on the topic's first fresh frame", () => {
    ws.setTopics([ticker()]);
    mount();
    ws.go(SATURATED);
    system(QUALITY("saturated", 4));
    seconds(7); // the ticker past T1 under a saturated link: Stale, never Reduced rate
    expect(chip()).toHaveTextContent("Stale 7 seconds");
    ws.setTopics([ticker()]);
    seconds(1);
    expect(chip()).toHaveTextContent("Reduced rate ×4");
  });

  it("stays at least 5 s from its entry once the link improves, then reads Live", () => {
    mount();
    ws.go(SATURATED);
    system(QUALITY("saturated", 4));
    seconds(2);
    ws.go(UP);
    system(QUALITY("healthy"));
    expect(chip()).toHaveTextContent("Reduced rate ×4");
    seconds(2);
    expect(chip()).toHaveTextContent("Reduced rate ×4");
    seconds(1); // 5 s since it entered
    expect(chip()).toHaveAccessibleName("Connection: Live 42 ms");
  });

  it("without an applied multiplier reads Reduced rate", () => {
    mount();
    ws.go(SATURATED);
    system(QUALITY("saturated"));
    expect(chip()).toHaveAccessibleName("Connection: Reduced rate");
  });
});

describe("row 16 (Scenario 4): recovery", () => {
  it("after a reconnect reads Live once auth_ok and the public snapshots are in", () => {
    const fed = ticker();
    ws.setTopics([fed]);
    mount();
    ws.go(DROPPED);
    expect(chip().getAttribute("aria-label")).toMatch(/^Connection: Reconnecting \(1\)/);
    ws.setTopics([{ ...fed, status: "pending", awaitingReconnect: true }]); // its reset
    seconds(1);
    ws.go(reduce(DROPPED, connecting));
    ws.go(BACK);
    expect(chip()).toHaveAttribute("data-status", "reconnecting"); // auth_ok alone is not Live
    expect(chip()).toHaveAccessibleName("Connection: Reconnecting");
    ws.setTopics([ticker()]); // the public snapshot
    seconds(1);
    expect(chip()).toHaveAccessibleName("Connection: Live 42 ms");
  });
});

describe("the real WS client behind the chip (a fake worker port)", () => {
  /** `createWsClient` on a fake port, made the shell's client; its frames apply on `frame()`. */
  function realClient(timers?: Partial<Timers>) {
    const port = new FakePort();
    const asked: ((frameTimeMs: number) => void)[] = [];
    const client = createWsClient({
      wsUrl: "wss://cv.test/api/v1/ws",
      tokens: {
        getToken: () => Promise.resolve({ kind: "unavailable" }),
        invalidate: () => undefined,
      },
      shell: "browser",
      locale: "en-GB",
      clientVersion: "1.0.0",
      port,
      page: fakePage().page,
      raf: (callback) => asked.push(callback),
      caf: () => undefined,
      timers,
    });
    act(() => setActiveClient(client));
    const frame = (): void => asked.splice(0).forEach((callback) => callback(16));
    return { client, port, frame };
  }
  const data = (id: string, frames: TopicFrame[], status = "live") => ({
    t: "data",
    id,
    frames,
    status,
    effective: {},
    source: "live",
  });
  const base = { ts: 1_000, sp: undefined, decodeMs: 0.5, size: 20, meta: undefined };
  const snap = (seq: number): TopicFrame => ({
    kind: "snap",
    seq,
    ...base,
    bodies: [{ e: "j", p: {} }],
  });
  const delta = (seq: number): TopicFrame => ({ kind: "d", seq, ...base, body: { e: "j", p: {} } });
  const TRADES = { ch: "trades.BTCUSDT", paneId: "p1", priority: "other" } as const;

  it("a consumer made 40 s before the link came up reads Live at link-up, aged from it", () => {
    const { client, port } = realClient();
    mount();
    act(() => port.say({ t: "state", state: INITIAL_WS_STATE })); // the first socket opens
    expect(chip()).toHaveAccessibleName("Connection: Connecting…");
    client.consume(TRADES);
    port.say(data("c1", [], "pending"));
    seconds(40);
    act(() => port.say({ t: "state", state: UP }));
    expect(chip()).toHaveAccessibleName("Connection: Live 42 ms");
    seconds(1);
    port.say(data("c1", [snap(1)])); // its snapshot, a second after link-up
    seconds(9);
    expect(chip()).toHaveAccessibleName("Connection: Live 42 ms");
    seconds(1); // silent 10 s since its snapshot: trades' T1
    expect(chip()).toHaveTextContent("Stale 10 seconds");
    act(() => client.stop());
  });

  it("a consumer nobody snapshots after a reconnect reads Stale at its T1 from the link's return, not Reconnecting for good", () => {
    const { client, port } = realClient();
    mount();
    act(() => port.say({ t: "state", state: UP }));
    // a ticker whose stream the engine let go of (a pane that collapsed): no snapshot comes, nor an overdue mark
    client.consume({ ...TRADES, ch: "ticker.BTCUSDT" });
    port.say(data("c1", [snap(1)]));
    seconds(1);
    act(() => port.say({ t: "state", state: DROPPED })); // the drop owes every consumer a snapshot
    seconds(5);
    act(() => port.say({ t: "state", state: BACK }));
    expect(chip()).toHaveAccessibleName("Connection: Reconnecting"); // row 16 holds it
    seconds(4);
    expect(chip()).toHaveAttribute("data-status", "reconnecting"); // 4 s from the link's return: inside the ticker's T1
    seconds(1);
    expect(chip()).toHaveAttribute("data-status", "stale");
    expect(chip()).toHaveTextContent("Stale 5 seconds"); // its age, from the link's return
    seconds(55);
    expect(chip()).toHaveTextContent("Stale 60 seconds"); // and it goes on ageing, never Reconnecting again
    act(() => client.stop());
  });

  it("ages on the client's own clock, whatever its origin: an injected clock is not performance.now", () => {
    // `Timers.now` may be a skew-corrected clock; the chip reads the one the topics are stamped on
    const { client, port } = realClient({ now: () => performance.now() + 5_000_000 });
    mount();
    act(() => port.say({ t: "state", state: UP }));
    client.consume({ ...TRADES, ch: "ticker.BTCUSDT" });
    port.say(data("c1", [snap(1)]));
    seconds(4);
    expect(chip()).toHaveAttribute("data-status", "live");
    seconds(3); // 7 s since its snapshot: past the ticker's T1
    expect(chip()).toHaveTextContent("Stale 7 seconds");
    act(() => client.stop());
  });

  it("a frame notifies nobody: no client listener, no store update, no render; the chip reads it on its clock", () => {
    const { client, port, frame } = realClient();
    act(() => port.say({ t: "state", state: UP }));
    let commits = 0;
    render(
      <Profiler id="chip" onRender={() => void (commits += 1)}>
        <ShellConnectionSlot />
      </Profiler>,
    );
    client.consume({ ...TRADES, ch: "ticker.BTCUSDT" });
    const heard = vi.fn();
    client.subscribe(heard);
    const stored = vi.fn();
    const unstore = subscribeShellState(stored);
    const before = commits;
    port.say(data("c1", [snap(1), delta(2)]));
    port.say(data("c1", [delta(3)]));
    frame(); // the display applies what a handle reads: still a plain write
    expect([heard.mock.calls.length, stored.mock.calls.length, commits - before]).toEqual([
      0, 0, 0,
    ]);
    expect(client.topics()[0]?.freshAtMs).toBe(performance.now()); // the reading was written
    seconds(1); // the chip's own 1 Hz clock reads it
    expect(commits - before).toBeGreaterThan(0);
    expect(chip()).toHaveAccessibleName("Connection: Live 42 ms");
    unstore();
    act(() => client.stop());
  });
});
