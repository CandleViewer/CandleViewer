// #5345 (E08-D14 DF-1, FS-1): the CMP-076 chip's container fed from the signals E17-D02 §3 names:
// the shell store's `exchange_state` fact (row 13), the topics the WS client reads (rows 10–12, 16)
// and the `connection_quality` class and multiplier (row 5, §9). Every state is found by role, on
// a fake clock; the words are §10 A's, which CMP-076 already carries.
import { createRequire } from "node:module";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";
import { ShellBannerSlot, ShellConnectionSlot } from "../../../src/features/app-shell/slots";
import { toLatencyIndicator } from "../../../src/lib/telemetry/latencyIndicator.js";
import type { TopicReading } from "../../../src/lib/ws/state/chipState";
import { reduce } from "../../../src/lib/ws/state/reducer";
import type { SystemUpdate } from "../../../src/lib/ws/protocol/frames";
import {
  applySystemUpdate,
  resetShellState,
  setShellState,
} from "../../../src/shell/bootstrap/store.js";
import { OFF, authOk, connecting, quality, stream } from "../../lib/ws/support/engineEvents";
import { fakeActiveClient, runEvents } from "../../lib/ws/support/fakeActiveClient";

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
const DOWN: SystemUpdate = { kind: "exchange_state", public_ws: "disconnected" };
const BACK: SystemUpdate = { kind: "exchange_state", public_ws: "connected" };
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

/** A live ticker whose last fresh frame was at `freshAtMs`. */
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
    ws.setTopics([ticker(T0)]);
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
    system(BACK); // the feed is back, but the ticker has had no fresh frame since it went down
    seconds(2);
    expect(chip()).toHaveTextContent("Stale — exchange feed down");
    ws.setTopics([ticker(Date.now())]); // its upstream_reconnect snapshot
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
    system(BACK);
    expect(chip()).toHaveAccessibleName("Connection: Live 42 ms");
  });

  it("is drawn with the stale glyph on the bar fill, never the strong one", () => {
    ws.setTopics([ticker(T0 - 60_000)]); // a topic past its T2 does not make the feed-down chip strong
    mount();
    system(DOWN);
    expect(chip().style.background).toBe("var(--color-surface-raised)");
    const glyph = chip().querySelector<HTMLElement>("[data-glyph]");
    expect(glyph?.style.color).toBe("var(--color-data-confidence-stale-indicator)");
  });
});

describe("rows 10–12: a topic's age and the server's word", () => {
  it("a ticker silent past T1 reads Stale 7 s, and past T2 Stale 15 s in the strong variant", async () => {
    ws.setTopics([ticker(T0)]);
    mount();
    seconds(4);
    expect(chip()).toHaveAttribute("data-status", "live");
    seconds(3); // 7 s since its last frame: past T1 (5 s)
    expect(chip()).toHaveAttribute("data-status", "stale");
    expect(chip()).toHaveTextContent("Stale 7 s");
    expect(chip().getAttribute("aria-label")).toMatch(/^Connection: Stale 7/);
    expect(chip().style.background).toBe("var(--color-surface-raised)");
    seconds(7);
    expect(chip()).toHaveTextContent("Stale 14 s"); // the age at 1 Hz, never announced
    seconds(1); // 15 s: T2
    expect(chip()).toHaveTextContent("Stale 15 s");
    expect(chip().style.background).toBe("var(--color-status-warning-subtle)");
    const glyph = chip().querySelector<HTMLElement>("[data-glyph]");
    expect(glyph?.style.color).toBe("var(--color-status-warning-strong)");
    vi.useRealTimers(); // axe schedules with real timers
    expect(await seriousAxe(document.body)).toEqual([]);
  });

  it("the stale topic's first fresh frame reads Live again", () => {
    ws.setTopics([ticker(T0)]);
    mount();
    seconds(16);
    expect(chip()).toHaveTextContent("Stale 16 s");
    ws.setTopics([ticker(Date.now())]);
    seconds(1);
    expect(chip()).toHaveAccessibleName("Connection: Live 42 ms");
  });

  it("the last data is the stale topic's, in the name and the title", () => {
    ws.setTopics([ticker(T0)]);
    mount();
    seconds(7);
    expect(chip().getAttribute("aria-label")).toMatch(/, last data 13:42:05 UTC$/);
    expect(chip()).toHaveAttribute("title", "last 13:42:05 UTC");
  });

  it("a ticker whose snapshot says meta.stale reads Stale (server)", () => {
    ws.setTopics([ticker(T0, { serverStale: true })]);
    mount();
    expect(chip()).toHaveAccessibleName("Connection: Stale (server)");
    expect(chip()).toHaveAttribute("data-status", "stale");
  });

  it("a replay, derived or private topic never makes the chip stale", () => {
    ws.setTopics([
      ticker(T0 - 60_000, { rs: "rs-1", source: "replay" }),
      ticker(T0 - 60_000, { ch: "bars.BTCUSDT.1m" }),
      ticker(T0 - 60_000, { ch: "orders" }),
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
    ws.setTopics([ticker(T0)]);
    mount();
    ws.go(SATURATED);
    system(QUALITY("saturated", 4));
    seconds(7); // the ticker past T1 under a saturated link: Stale, never Reduced rate
    expect(chip()).toHaveTextContent("Stale 7 s");
    ws.setTopics([ticker(Date.now())]);
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
    ws.setTopics([ticker(T0)]);
    mount();
    const lost = { sinceMs: T0, lastDataMs: T0 };
    const dropped = reduce(UP, {
      type: "reconnecting",
      attempt: 1,
      nextAttemptAtMs: T0 + 1_000,
      lost,
    });
    ws.go(dropped);
    expect(chip().getAttribute("aria-label")).toMatch(/^Connection: Reconnecting \(1\)/);
    ws.setTopics([ticker(T0, { status: "pending", awaitingReconnect: true })]); // its reset
    seconds(1);
    ws.go(reduce(dropped, connecting));
    ws.go(reduce(reduce(dropped, connecting), authOk(OFF)));
    expect(chip()).toHaveAttribute("data-status", "reconnecting"); // auth_ok alone is not Live
    expect(chip()).toHaveAccessibleName("Connection: Reconnecting");
    ws.setTopics([ticker(Date.now())]); // the public snapshot
    seconds(1);
    expect(chip()).toHaveAccessibleName("Connection: Live 42 ms");
  });
});
