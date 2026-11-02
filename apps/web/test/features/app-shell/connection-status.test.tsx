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
import { resetShellState, setShellState } from "../../../src/shell/bootstrap/store.js";
import { toLatencyIndicator } from "../../../src/lib/telemetry/latencyIndicator.js";
import { reduce } from "../../../src/lib/ws/state/reducer";
import type { EngineEvent, WsState } from "../../../src/lib/ws/state/types";
import { appThemeStore } from "../../../src/shell/bootstrap/themeStore";
import { OFF, authOk, connecting, stream } from "../../lib/ws/support/engineEvents";
import { fakeActiveClient, runEvents } from "../../lib/ws/support/fakeActiveClient";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };
// color-contrast is off: jsdom computes no styles, so axe cannot measure it here (the E17-D02 §14
// matrix and the a11y suite own contrast).
const seriousAxe = async (el: Element): Promise<unknown[]> =>
  (await axe.run(el, { rules: { "color-contrast": { enabled: false } } })).violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
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
  [{ status: "stale", lastGoodTs: T0, staleAgeMs: 7_400, nowMs: T0 }, `Stale 7 seconds, ${UTC}`],
  [
    { status: "stale", lastGoodTs: T0, staleAgeMs: 15e3, strong: true, nowMs: T0 },
    `Stale 15 seconds, ${UTC}`,
  ],
  // #5345: the two detail states E17-D02 §5 draws on the stale value (rows 12 and 13)
  [{ status: "stale", lastGoodTs: null, serverStale: true, nowMs: T0 }, "Stale (server)"],
  [
    { status: "stale", lastGoodTs: T0, upstreamDown: true, nowMs: T0 },
    `Stale — exchange feed down, ${UTC}`,
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
      // DF-24 (CP-7): the name spells the age out, "Stale 7 seconds" for the chip's "Stale 7 s".
      for (const part of name.split(", ").filter((p) => !p.endsWith("UTC"))) {
        expect(chip).toHaveTextContent(part.replace(/ (\d+) seconds?$/u, " $1 s"));
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

describe("DF-24 (CP-7): the accessible name spells the stale age out", () => {
  it.each([
    [7_400, "Stale 7 s", "Connection: Stale 7 seconds, last data 13:42:05 UTC"],
    [15_000, "Stale 15 s", "Connection: Stale 15 seconds, last data 13:42:05 UTC"],
    [1_999, "Stale 1 s", "Connection: Stale 1 second, last data 13:42:05 UTC"],
  ])("%i ms: the chip reads %s and is named %s", async (staleAgeMs, word, name) => {
    const { container } = render(
      <ConnectionStatus status="stale" lastGoodTs={T0} staleAgeMs={staleAgeMs} nowMs={T0} />,
    );
    const chip = screen.getByRole("button", { name });
    expect(chip).toHaveTextContent(word);
    // axe's label-content-name-mismatch (SC 2.5.3) runs here: "Stale 7 s" is part of the name.
    expect(await seriousAxe(container)).toEqual([]);
  });

  it("the other words are their own names", () => {
    render(<ConnectionStatus status="stale" lastGoodTs={null} serverStale nowMs={T0} />);
    expect(screen.getByRole("button", { name: "Connection: Stale (server)" })).toBeVisible();
  });
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
      appThemeStore().setMotionOverride("system");
    });
    vi.useRealTimers();
  });

  const LOST = { sinceMs: T0, lastDataMs: T0 - 12_000 };
  const UP = runEvents(connecting, authOk(OFF), stream("live"));
  const drop = (event: EngineEvent): WsState => reduce(UP, event);
  const mount = () =>
    render(
      <>
        <ShellConnectionSlot />
        <ShellAnnouncer />
      </>,
    );

  it("announces nothing itself: §11 rows 1 and 14 are CMP-077's (#306 slice 4b)", async () => {
    mount();
    expect(screen.getByRole("button", { name: /^Connection: Connecting…/ })).toBeInTheDocument();
    ws.go(UP);
    act(() => setShellState({ latency: toLatencyIndicator(42) }));
    expect(screen.getByRole("button", { name: "Connection: Live 42 ms" })).toBeInTheDocument();
    ws.go(drop({ type: "reconnecting", attempt: 1, nextAttemptAtMs: T0 + 1000, lost: LOST }));
    ws.go(reduce(ws.current(), connecting));
    ws.go(reduce(ws.current(), { type: "offline", cause: "backend_unreachable" }));
    ws.go(reduce(ws.current(), { type: "reconnecting", attempt: 2, nextAttemptAtMs: T0 + 3000 }));
    for (let s = 0; s < 12; s += 1) {
      act(() => {
        setShellState({ latency: toLatencyIndicator(40 + s) });
        vi.advanceTimersByTime(1000);
      });
    }
    // the age runs from the real last data (`outage.lastDataMs`), 12 s before the drop
    expect(
      screen.getByRole("button", {
        name: "Connection: Reconnecting (2), last data 00:24 ago, 13:41:53 UTC",
      }),
    ).toBeInTheDocument();
    expect(region("assertive")).toBeEmptyDOMElement();
    expect(region("polite")).toBeEmptyDOMElement();
    vi.useRealTimers(); // axe schedules with real timers
    expect(await seriousAxe(document.body)).toEqual([]);
  });

  it("reads Reconnecting during a shell-cause outage (a retry is running)", () => {
    mount();
    ws.go(drop({ type: "offline", cause: "tailnet_unreachable", lost: LOST }));
    expect(
      screen.getByRole("button", { name: /^Connection: Reconnecting, last data 00:12 ago/ }),
    ).toBeInTheDocument();
  });

  it.each([1002, 4403])(
    "fatal %i reads Offline — retry stopped, never Reconnecting (E04-D02-F08)",
    async (closeCode) => {
      mount();
      ws.go(drop({ type: "offline", cause: "fatal", closeCode, lost: LOST }));
      const chip = screen.getByRole("button", {
        name: "Connection: Offline — retry stopped, last data 00:12 ago, 13:41:53 UTC",
      });
      expect(chip).toHaveAttribute("data-status", "offline");
      expect(screen.queryByRole("button", { name: /Reconnecting/ })).toBeNull();
      vi.useRealTimers();
      expect(await seriousAxe(document.body)).toEqual([]);
    },
  );

  it("carries the CMP-039 focus ring on a native, focusable button (E04-D02-F12)", () => {
    mount();
    const chip = screen.getByRole("button", { name: /^Connection:/ });
    expect(chip).toHaveClass("cv-focus-ring");
    expect(chip.tagName).toBe("BUTTON");
    act(() => chip.focus());
    expect(chip).toHaveFocus();
  });

  it("cross-fades the content once per status change, and draws it at once under reduce (F37)", () => {
    mount();
    const fade = (): HTMLElement => {
      const el = document.querySelector<HTMLElement>("[data-fade]");
      if (el === null) throw new Error("no fade wrapper");
      return el;
    };
    // a manual requestAnimationFrame: `frame()` runs what was asked for, as the display would
    const asked: FrameRequestCallback[] = [];
    const raf = vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
      asked.push(cb);
      return asked.length;
    });
    const frame = (): void => act(() => asked.splice(0).forEach((cb) => cb(0)));
    try {
      expect(fade().style.opacity).toBe("1"); // the first render does not fade
      ws.go(UP);
      expect(fade().style.opacity).toBe("0");
      expect(fade().style.transition).toBe("none");
      frame();
      expect(fade().style.opacity).toBe("1");
      expect(fade().style.transition).toMatch(/^opacity var\(--motion-duration-normal\)/);
      act(() => appThemeStore().setMotionOverride("on"));
      ws.go(drop({ type: "reconnecting", attempt: 1, nextAttemptAtMs: T0 + 1000, lost: LOST }));
      expect(fade().style.transition).toBe("none");
      expect(fade().style.opacity).toBe("");
    } finally {
      raf.mockRestore(); // before the fake timers are uninstalled
    }
  });
});
