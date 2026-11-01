import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearAnnouncements, ShellAnnouncer } from "../../../src/features/app-shell/announcer";
import {
  createClockStore,
  formatUtcClock,
  type ClockSource,
} from "../../../src/features/app-shell/clock";
import { StatusBar } from "../../../src/features/app-shell/StatusBar";
import { CLIENT_VERSION } from "../../../src/lib/ws/protocol/frames";
import { resetShellState, setShellState } from "../../../src/shell/bootstrap/store.js";
import { toLatencyIndicator } from "../../../src/lib/telemetry/latencyIndicator.js";
import { reduce } from "../../../src/lib/ws/state/reducer";
import type { WsState } from "../../../src/lib/ws/state/types";
import { OFF, authOk, connecting, stream } from "../../lib/ws/support/engineEvents";
import { fakeActiveClient, runEvents } from "../../lib/ws/support/fakeActiveClient";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const T0 = Date.UTC(2026, 9, 27, 13, 42, 5);
const UP = runEvents(connecting, authOk(OFF), stream("live"));
const LOST = { sinceMs: T0, lastDataMs: T0 - 12_000 };
const RETRYING: WsState = reduce(UP, {
  type: "reconnecting",
  attempt: 2,
  nextAttemptAtMs: T0 + 4_000,
  lost: LOST,
});
const polite = (): HTMLElement => {
  const el = document.querySelector<HTMLElement>('[aria-live="polite"]');
  if (el === null) throw new Error("no polite region");
  return el;
};
const chip = (kind: string): HTMLElement => {
  const el = document.querySelector<HTMLElement>(`[data-chip="${kind}"]`);
  if (el === null) throw new Error(`no ${kind} chip`);
  return el;
};

describe("formatUtcClock", () => {
  it("formats epoch ms as HH:MM:SS UTC, whatever the local zone", () => {
    expect(formatUtcClock(T0)).toBe("13:42:05 UTC");
    expect(formatUtcClock(T0 + 999)).toBe("13:42:05 UTC");
    expect(formatUtcClock(0)).toBe("00:00:00 UTC");
    expect(formatUtcClock(Date.UTC(2026, 0, 1, 23, 59, 59))).toBe("23:59:59 UTC");
    expect(formatUtcClock(Date.UTC(2026, 0, 2, 9, 5, 7))).toBe("09:05:07 UTC");
    expect(formatUtcClock(Number.NaN)).toBe("--:--:-- UTC");
  });
});

describe("createClockStore", () => {
  function fakeSource(): ClockSource & { ms: number; ticks: Map<number, () => void> } {
    const ticks = new Map<number, () => void>();
    let id = 0;
    return {
      ms: T0,
      ticks,
      now() {
        return this.ms;
      },
      setInterval: (tick) => {
        id += 1;
        ticks.set(id, tick);
        return id;
      },
      clearInterval: (handle) => ticks.delete(handle as number),
    };
  }

  it("runs one interval while subscribed and clears it when the last subscriber leaves", () => {
    const source = fakeSource();
    const store = createClockStore(source);
    const a = vi.fn();
    const b = vi.fn();
    const offA = store.subscribe(a);
    const offB = store.subscribe(b);
    expect(source.ticks.size).toBe(1);
    source.ms += 400;
    source.ticks.forEach((tick) => tick());
    expect(a).not.toHaveBeenCalled(); // same second, same string: no notify
    source.ms += 600;
    source.ticks.forEach((tick) => tick());
    expect(a).toHaveBeenCalledTimes(1);
    expect(store.getSnapshot()).toBe("13:42:06 UTC");
    offA();
    expect(source.ticks.size).toBe(1);
    offB();
    expect(source.ticks.size).toBe(0);
    source.ms += 5000;
    expect(store.getSnapshot()).toBe("13:42:11 UTC"); // idle: read on demand
  });
});

describe("StatusBar (CMP-208) and its health chips (CMP-210)", () => {
  let ws: ReturnType<typeof fakeActiveClient>;
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(T0);
    ws = fakeActiveClient();
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
        <StatusBar barClose={<span>Bar close 00:42</span>} />
        <ShellAnnouncer />
      </>,
    );

  it("ticks the UTC clock at 1 Hz, outside any live region, and leaves no timer after unmount", () => {
    const { unmount } = mount();
    expect(screen.getByText("13:42:05 UTC")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(3000));
    const clock = screen.getByText("13:42:08 UTC");
    expect(clock.closest("[aria-live], [role=status], [role=alert]")).toBeNull();
    expect(polite()).toBeEmptyDOMElement();
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("names each chip in words, with a glyph, for every connection and latency state", () => {
    mount();
    const group = screen.getByRole("status", { name: "System status" });
    expect(screen.getByText("Connection: connecting")).toBeInTheDocument();
    expect(group.contains(chip("connection"))).toBe(false); // never live content
    expect(within(group).getByText("WS latency: unavailable")).toBeInTheDocument();
    expect(chip("latency").dataset["tone"]).toBe("none");
    expect(chip("latency").querySelector("svg")).not.toBeNull(); // the neutral info glyph
    const cases = [
      [UP, "live", "ok"],
      [RETRYING, "reconnecting", "error"],
      [
        reduce(UP, { type: "offline", cause: "fatal", closeCode: 1002, lost: LOST }),
        "offline",
        "error",
      ],
    ] as const;
    for (const [state, word, tone] of cases) {
      ws.go(state);
      expect(screen.getByText(`Connection: ${word}`)).toBeInTheDocument();
      expect(chip("connection").dataset["tone"]).toBe(tone);
      expect(chip("connection").querySelector("svg")).not.toBeNull();
    }
    for (const [ms, name, tone] of [
      [38, "WS latency: ok, 38 ms", "ok"],
      [140, "WS latency: slow, 140 ms", "warn"],
      [300, "WS latency: over budget, 300 ms", "error"],
    ] as const) {
      act(() => setShellState({ latency: toLatencyIndicator(ms) }));
      // the verbatim D03 §10.2 name in browse mode, outside the live region
      expect(screen.getByText(name)).toBeInTheDocument();
      expect(group.contains(screen.getByText(name))).toBe(false);
      expect(chip("latency").dataset["tone"]).toBe(tone);
      expect(chip("latency").querySelector("svg")).not.toBeNull();
    }
  });

  it("keeps the System status region's text still on value-only updates, changed on a transition", () => {
    mount();
    ws.go(UP);
    act(() => setShellState({ latency: toLatencyIndicator(38) }));
    const region = screen.getByRole("status", { name: "System status" });
    const before = region.textContent;
    expect(before).toBe("WS latency: ok");
    for (let s = 0; s < 5; s += 1) {
      act(() => {
        setShellState({ latency: toLatencyIndicator(40 + s) });
        vi.advanceTimersByTime(1000);
      });
      expect(region.textContent).toBe(before);
    }
    expect(screen.getByText("WS latency: ok, 44 ms")).toBeInTheDocument();
    expect(region.contains(screen.getByText(/UTC$/))).toBe(false);
    act(() => setShellState({ latency: toLatencyIndicator(150) }));
    expect(region.textContent).toBe("WS latency: slow");
    expect(polite()).toBeEmptyDOMElement(); // the region speaks for itself, not the announcer
  });

  it("leaves the System status region's text unchanged on a connection transition (no double voice)", () => {
    mount();
    ws.go(UP);
    act(() => setShellState({ latency: toLatencyIndicator(38) }));
    const region = screen.getByRole("status", { name: "System status" });
    expect(chip("connection")).toHaveTextContent("Connection: live");
    ws.go(RETRYING);
    expect(chip("connection")).toHaveTextContent("Connection: reconnecting");
    expect(region.textContent).toBe("WS latency: ok");
    expect(region.contains(chip("connection"))).toBe(false);
    expect(chip("connection").closest("[aria-live], [role=status], [role=alert]")).toBeNull();
  });

  it("reads reconnecting during a shell-cause outage with a retry running (E04-D02-F09)", () => {
    mount();
    for (const cause of ["offline", "tailnet_unreachable", "backend_unreachable"] as const) {
      ws.go(reduce(UP, { type: "offline", cause, lost: LOST }));
      expect(chip("connection")).toHaveTextContent("Connection: reconnecting");
    }
    ws.go(reduce(UP, { type: "offline", cause: "fatal", closeCode: 4403, lost: LOST }));
    expect(chip("connection")).toHaveTextContent("Connection: offline");
  });

  it('maps every latency state to its display word, never "degraded" (E04-D02-F25)', () => {
    mount();
    const region = screen.getByRole("status", { name: "System status" });
    for (const [ms, word] of [
      [null, "unavailable"],
      [38, "ok"],
      [100, "slow"],
      [249, "slow"],
      [250, "over budget"],
    ] as const) {
      act(() => setShellState({ latency: toLatencyIndicator(ms) }));
      expect(region.textContent).toBe(`WS latency: ${word}`);
    }
    expect(document.body.textContent).not.toMatch(/degraded|breach/);
  });

  it("repeats the environment in words, never a defaulted Demo, and shows the build version", () => {
    mount();
    expect(screen.getByText("Trading environment: unknown")).toBeInTheDocument();
    expect(screen.getByText("ENV UNKNOWN")).toBeInTheDocument();
    act(() => setShellState({ environment: "live" }));
    expect(screen.getByText("Trading environment: Live")).toBeInTheDocument();
    expect(screen.getByText("LIVE")).toBeInTheDocument();
    const pkg = JSON.parse(
      readFileSync(resolve(import.meta.dirname, "../../../package.json"), "utf8"),
    ) as { version: string };
    expect(CLIENT_VERSION).toBe(pkg.version); // the one build version hello reports (SCR-157)
    expect(screen.getByText(`v${pkg.version}`)).toBeInTheDocument();
    expect(screen.getByText("Bar close 00:42")).toBeInTheDocument();
  });

  it("has no serious or critical axe violations", async () => {
    mount();
    ws.go(UP);
    act(() => setShellState({ latency: toLatencyIndicator(300), environment: "demo" }));
    vi.useRealTimers(); // axe schedules with real timers
    const { violations } = await axe.run(document.body);
    expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  });
});
