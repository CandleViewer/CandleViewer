import { createRequire } from "node:module";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ConnectionStatus,
  type ConnectionStatusProps,
} from "../../../src/features/app-shell/ConnectionStatus";
import {
  announce,
  clearAnnouncements,
  CONNECTION_KEYS,
  ShellAnnouncer,
} from "../../../src/features/app-shell/announcer";
import { ShellConnectionSlot } from "../../../src/features/app-shell/slots";
import {
  resetShellState,
  setShellState,
  type ConnectionState,
} from "../../../src/shell/bootstrap/store.js";
import { toLatencyIndicator } from "../../../src/lib/telemetry/latencyIndicator.js";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };
// color-contrast is off: jsdom computes no styles, so axe cannot measure it here (the E17-D02 §14
// matrix and the a11y suite own contrast).
const seriousAxe = async (el: Element): Promise<unknown[]> =>
  (await axe.run(el, { rules: { "color-contrast": { enabled: false } } })).violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
const go = (connection: ConnectionState): void => act(() => setShellState({ connection }));
const region = (live: "assertive" | "polite"): HTMLElement => {
  const el = document.querySelector<HTMLElement>(`[aria-live="${live}"]`);
  if (el === null) throw new Error(`no ${live} region`);
  return el;
};
const seq = (live: "assertive" | "polite" = "assertive"): string | null =>
  region(live).querySelector("p")?.getAttribute("data-seq") ?? null;

afterEach(() => act(() => clearAnnouncements()));

const T0 = Date.UTC(2026, 9, 27, 13, 42, 5);

const UTC = "last data 13:42:05 UTC";
const STATES: readonly [ConnectionStatusProps, string][] = [
  [{ status: "live", lastGoodTs: null, latencyMs: 42, nowMs: T0 }, "Live 42 ms"],
  [
    { status: "delayed", lastGoodTs: T0, throttleMultiplier: 4, nowMs: T0 },
    `Reduced rate ×4, ${UTC}`,
  ],
  [{ status: "stale", lastGoodTs: T0, staleAgeMs: 7_400, nowMs: T0 }, `Stale 7s, ${UTC}`],
  [
    { status: "stale", lastGoodTs: T0, staleAgeMs: 15e3, strong: true, nowMs: T0 },
    `Stale 15s, ${UTC}`,
  ],
  [
    { status: "reconnecting", lastGoodTs: T0, attempt: 3, nowMs: T0 + 12e3 },
    "Reconnecting (3), last data 00:12 ago, 13:42:05 UTC",
  ],
  [{ status: "reconnecting", lastGoodTs: null, firstConnect: true, nowMs: T0 }, "Connecting…"],
  [
    { status: "offline", lastGoodTs: T0, nowMs: T0 + 12e3 },
    "Offline — retry stopped, last data 00:12 ago, 13:42:05 UTC",
  ],
];

describe("CMP-076 ConnectionStatus chip", () => {
  it.each(STATES)(
    "state %#: Connection: %s, with a glyph and no live region",
    async (props, name) => {
      const { container } = render(<ConnectionStatus {...props} />);
      const chip = screen.getByRole("button", { name: `Connection: ${name}` });
      // Every visible part of the name is text on the chip (SC 2.5.3); the UTC time is the title.
      for (const part of name.split(", ").filter((p) => !p.endsWith("UTC"))) {
        expect(chip).toHaveTextContent(part);
      }
      expect(chip.querySelector("[data-glyph] :is(svg, [aria-hidden='true'])")).not.toBeNull();
      expect(chip.getAttribute("title")).toBe(
        props.lastGoodTs === null ? null : "last 13:42:05 UTC",
      );
      expect(chip).not.toHaveAttribute("aria-haspopup");
      expect(container.querySelector("[aria-live], [role='status'], [role='alert']")).toBeNull();
      expect(await seriousAxe(container)).toEqual([]);
    },
  );
});

describe("the shell announcer", () => {
  it("announces a key once, whoever writes it, until the episode is cleared", () => {
    render(<ShellAnnouncer />);
    expect(region("polite")).toBeEmptyDOMElement();
    expect(region("assertive")).toBeEmptyDOMElement();
    act(() => {
      expect(announce("assertive", "Disconnected.", CONNECTION_KEYS.disconnected)).toBe(true);
    });
    const first = seq();
    // The same key again (a remounted writer) says nothing.
    act(() => {
      expect(announce("assertive", "Disconnected.", CONNECTION_KEYS.disconnected)).toBe(false);
    });
    expect(seq()).toBe(first);
    expect(region("assertive").querySelectorAll("p")).toHaveLength(1);
    act(() => clearAnnouncements());
    expect(region("assertive")).toBeEmptyDOMElement();
    act(() => {
      announce("assertive", "Disconnected.", CONNECTION_KEYS.disconnected);
    });
    expect(seq()).not.toBe(first);
  });
});

describe("ShellConnectionSlot: the container", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(T0);
  });
  afterEach(() => {
    act(() => resetShellState());
    vi.useRealTimers();
  });

  it("announces nothing itself: §11 rows 1 and 14 are CMP-077's (#306 slice 4b)", async () => {
    render(
      <>
        <ShellConnectionSlot />
        <ShellAnnouncer />
      </>,
    );
    expect(screen.getByRole("button", { name: /^Connection: Connecting…/ })).toBeInTheDocument();
    act(() => setShellState({ connection: { kind: "live" }, latency: toLatencyIndicator(42) }));
    expect(screen.getByRole("button", { name: "Connection: Live 42 ms" })).toBeInTheDocument();
    go({ kind: "reconnecting", attempt: 1, nextAttemptAtMs: T0 + 1000 });
    go({ kind: "connecting" });
    go({ kind: "offline", cause: "backend_unreachable" });
    go({ kind: "reconnecting", attempt: 2, nextAttemptAtMs: T0 + 3000 });
    for (let s = 0; s < 12; s += 1) {
      act(() => {
        setShellState({ latency: toLatencyIndicator(40 + s) });
        vi.advanceTimersByTime(1000);
      });
    }
    expect(
      screen.getByRole("button", {
        name: "Connection: Reconnecting (2), last data 00:12 ago, 13:42:05 UTC",
      }),
    ).toBeInTheDocument();
    go({ kind: "live" });
    go({ kind: "offline", cause: "tailnet_unreachable" });
    expect(
      screen.getByRole("button", { name: /^Connection: Reconnecting, last data 00:00 ago/ }),
    ).toBeInTheDocument();
    expect(region("assertive")).toBeEmptyDOMElement();
    expect(region("polite")).toBeEmptyDOMElement();
    vi.useRealTimers(); // axe schedules with real timers
    expect(await seriousAxe(document.body)).toEqual([]);
  });
});
