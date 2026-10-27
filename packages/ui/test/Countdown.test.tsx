// @vitest-environment jsdom
import { act, Profiler, StrictMode, type JSX } from "react";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import { expect, within } from "storybook/test";
import { Countdown } from "../src/components/index.js";
import {
  countdownPhase,
  formatCountdown,
  secondsLeft,
  spokenCountdown,
} from "../src/components/Countdown.js";
import { mount } from "./theme/mount.js";

const T0 = Date.UTC(2026, 9, 27, 12, 0, 0);

const advance = async (ms: number): Promise<void> => {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
};
const digits = (host: HTMLElement): string =>
  host.querySelector(".cv-countdown__digits")?.textContent ?? "";
const status = (host: HTMLElement): HTMLElement | null => within(host).queryByRole("status");

describe("Countdown formats (CMP-035, J6)", () => {
  it.each([
    [20, "mm:ss", "0:20", "20 seconds"],
    [65, "mm:ss", "1:05", "1 minute 5 seconds"],
    [0, "mm:ss", "0:00", "0 seconds"],
    [4500, "mm:ss", "75:00", "1 hour 15 minutes"],
    [28692, "hh:mm:ss", "07:58:12", "7 hours 58 minutes 12 seconds"],
    [35880, "words", "9 h 58 m", "9 hours 58 minutes"],
    [35892, "words", "9 h 58 m", "9 hours 58 minutes"],
    [192, "words", "3 m 12 s", "3 minutes 12 seconds"],
    [9, "words", "9 s", "9 seconds"],
    [4, "approx", "~4 s", "about 4 seconds"],
    [1, "approx", "~1 s", "about 1 second"],
    [150, "approx", "~3 m", "about 3 minutes"],
    [7300, "approx", "~2 h", "about 2 hours"],
  ] as const)("%i s as %s: %s, spoken %s", (total, format, shown, spoken) => {
    expect(formatCountdown(total, format)).toBe(shown);
    expect(spokenCountdown(total, format)).toBe(spoken);
  });

  it("rounds up to whole seconds and never goes below zero", () => {
    expect(secondsLeft(T0 + 19_001, T0)).toBe(20);
    expect(secondsLeft(T0 + 20_000, T0)).toBe(20);
    expect(secondsLeft(T0 - 5_000, T0)).toBe(0);
  });

  it("phase: under-threshold only at or below the smallest positive threshold", () => {
    expect(countdownPhase(20, [60, 10, 0])).toBe("running");
    expect(countdownPhase(10, [60, 10, 0])).toBe("under-threshold");
    expect(countdownPhase(0, [60, 10, 0])).toBe("expired");
  });

  it.each([[[]], [[0]]] as const)(
    "phase: with no positive threshold (%j) it stays running until expiry",
    (marks) => {
      for (const left of [3600, 60, 10, 1]) expect(countdownPhase(left, marks)).toBe("running");
      expect(countdownPhase(0, marks)).toBe("expired");
    },
  );
});

describe("Countdown (CMP-035)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(T0);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows hidden tabular digits plus a words twin, aria-live off, and an empty polite status", async () => {
    const host = await mount(<Countdown expiresAt={T0 + 20_000} />);
    const root = host.querySelector("[data-cmp='CMP-035']");
    expect(root).toHaveAttribute("data-format", "mm:ss");
    expect(root).toHaveAttribute("data-phase", "running");
    expect(digits(host)).toBe("0:20");
    expect(host.querySelector(".cv-countdown__digits")).toHaveAttribute("aria-hidden", "true");
    expect(host.querySelector(".cv-countdown__count")).toHaveAttribute("aria-live", "off");
    expect(host.querySelector(".cv-countdown__count .cv-visually-hidden")).toHaveTextContent(
      /^20 seconds$/,
    );
    const live = status(host);
    expect(live).toHaveAttribute("aria-live", "polite");
    expect(live).toBeEmptyDOMElement();
    expect(host.querySelector("[tabindex]")).toBeNull();
  });

  it("ticks once a second on the deadline's second boundary", async () => {
    const host = await mount(<Countdown expiresAt={T0 + 20_500} />);
    expect(digits(host)).toBe("0:21");
    await advance(499);
    expect(digits(host)).toBe("0:21");
    await advance(1);
    expect(digits(host)).toBe("0:20");
    await advance(1000);
    expect(digits(host)).toBe("0:19");
  });

  it("never announces per tick: the status changes only at a threshold", async () => {
    const host = await mount(<Countdown expiresAt={T0 + 75_000} />);
    const texts = new Set<string>();
    for (let i = 0; i < 14; i += 1) {
      await advance(1000);
      texts.add(status(host)?.textContent ?? "");
    }
    // 61 s left: no threshold yet, and the status never changed while the digits did.
    expect(digits(host)).toBe("1:01");
    expect([...texts]).toEqual([""]);
    await advance(1000);
    expect(status(host)).toHaveTextContent(/^1 minute left$/);
    for (let i = 0; i < 20; i += 1) await advance(1000);
    expect(status(host)).toHaveTextContent(/^1 minute left$/);
  });

  it("speaks each default threshold once with the host's sentence, then expires", async () => {
    const announce = vi.fn((s: number) => `${s} seconds until this confirmation cancels`);
    const onExpire = vi.fn();
    const host = await mount(
      <Countdown expiresAt={T0 + 61_000} announce={announce} onExpire={onExpire} />,
    );
    expect(announce).not.toHaveBeenCalled();
    await advance(1000);
    expect(status(host)).toHaveTextContent("60 seconds until this confirmation cancels");
    await advance(50_000);
    expect(status(host)).toHaveTextContent("10 seconds until this confirmation cancels");
    expect(host.querySelector("[data-cmp='CMP-035']")).toHaveAttribute(
      "data-phase",
      "under-threshold",
    );
    await advance(10_000);
    expect(status(host)).toHaveTextContent("0 seconds until this confirmation cancels");
    expect(announce.mock.calls.map(([s]) => s)).toEqual([60, 10, 0]);
    expect(onExpire).toHaveBeenCalledTimes(1);
    expect(host.querySelector("[data-cmp='CMP-035']")).toHaveAttribute("data-phase", "expired");
    expect(digits(host)).toBe("0:00");
    await advance(10_000);
    expect(onExpire).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("a crossing of several thresholds at once speaks the latest only", async () => {
    const announce = vi.fn((s: number) => `t${s}`);
    let now = T0;
    const host = await mount(
      <Countdown expiresAt={T0 + 65_000} announce={announce} now={() => now} />,
    );
    // The tab was in the background: the clock jumps past 60 and 10 before the next tick.
    now = T0 + 57_000;
    await advance(1000);
    expect(digits(host)).toBe("0:08");
    expect(announce.mock.calls.map(([s]) => s)).toEqual([10]);
    expect(status(host)).toHaveTextContent(/^t10$/);
  });

  it("thresholds already passed at mount never speak", async () => {
    const announce = vi.fn((s: number) => `t${s}`);
    const host = await mount(<Countdown expiresAt={T0 + 30_000} announce={announce} />);
    await advance(19_000);
    expect(announce.mock.calls.map(([s]) => s)).toEqual([]);
    await advance(1000);
    expect(announce.mock.calls.map(([s]) => s)).toEqual([10]);
    expect(status(host)).toHaveTextContent("t10");
  });

  it("takes custom thresholds (E30-D03: 10 and 0 only)", async () => {
    const announce = vi.fn((s: number) => `t${s}`);
    await mount(<Countdown expiresAt={T0 + 70_000} thresholds={[10, 0]} announce={announce} />);
    await advance(70_000);
    expect(announce.mock.calls.map(([s]) => s)).toEqual([10, 0]);
  });

  it("in a grid column (no thresholds) it has no status region and announces nothing", async () => {
    const onExpire = vi.fn();
    const host = await mount(
      <Countdown expiresAt={T0 + 12_000} thresholds={[]} onExpire={onExpire} />,
    );
    expect(status(host)).toBeNull();
    expect(host.querySelector("[aria-live='polite'], [role='alert']")).toBeNull();
    await advance(12_000);
    expect(onExpire).toHaveBeenCalledTimes(1);
    expect(host.querySelector("[data-cmp='CMP-035']")).toHaveAttribute("data-phase", "expired");
  });

  it("an already-passed deadline fires onExpire once on mount and starts no timer", async () => {
    const onExpire = vi.fn();
    const host = await mount(<Countdown expiresAt={T0 - 3_000} onExpire={onExpire} />);
    expect(onExpire).toHaveBeenCalledTimes(1);
    expect(digits(host)).toBe("0:00");
    expect(status(host)).toBeEmptyDOMElement();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("a new expiresAt restarts the count, and its expiry fires again", async () => {
    const onExpire = vi.fn();
    const host = document.body.appendChild(document.createElement("div"));
    const { createRoot } = await import("react-dom/client");
    const root = createRoot(host);
    await act(async () => root.render(<Countdown expiresAt={T0 + 2_000} onExpire={onExpire} />));
    await advance(2_000);
    expect(onExpire).toHaveBeenCalledTimes(1);
    await act(async () => root.render(<Countdown expiresAt={T0 + 5_000} onExpire={onExpire} />));
    expect(digits(host)).toBe("0:03");
    await advance(3_000);
    expect(onExpire).toHaveBeenCalledTimes(2);
    await act(async () => root.unmount());
  });

  it("clears its timer on unmount, and nothing fires after", async () => {
    const onExpire = vi.fn();
    const host = document.body.appendChild(document.createElement("div"));
    const { createRoot } = await import("react-dom/client");
    const root = createRoot(host);
    await act(async () => root.render(<Countdown expiresAt={T0 + 5_000} onExpire={onExpire} />));
    expect(vi.getTimerCount()).toBe(1);
    await act(async () => root.unmount());
    expect(vi.getTimerCount()).toBe(0);
    await advance(10_000);
    expect(onExpire).not.toHaveBeenCalled();
  });

  it("renders the hh:mm:ss, words and approx formats with their twins", async () => {
    const hh = await mount(<Countdown expiresAt={T0 + 28_692_000} format="hh:mm:ss" />);
    expect(digits(hh)).toBe("07:58:12");
    const words = await mount(<Countdown expiresAt={T0 + 35_880_000} format="words" />);
    expect(digits(words)).toBe("9 h 58 m");
    expect(words.querySelector(".cv-countdown__count .cv-visually-hidden")).toHaveTextContent(
      "9 hours 58 minutes",
    );
    const approx = await mount(<Countdown expiresAt={T0 + 4_000} format="approx" />);
    expect(digits(approx)).toBe("~4 s");
    expect(approx.querySelector("[data-cmp='CMP-035']")).toHaveAttribute("data-format", "approx");
  });

  it("StrictMode: a passed deadline fires onExpire exactly once", async () => {
    const onExpire = vi.fn();
    await mount(
      <StrictMode>
        <Countdown expiresAt={T0 - 3_000} onExpire={onExpire} />
      </StrictMode>,
    );
    await advance(5_000);
    expect(onExpire).toHaveBeenCalledTimes(1);
  });

  it("StrictMode: a running deadline that expires fires onExpire exactly once", async () => {
    const onExpire = vi.fn();
    const host = await mount(
      <StrictMode>
        <Countdown expiresAt={T0 + 3_000} onExpire={onExpire} />
      </StrictMode>,
    );
    expect(onExpire).not.toHaveBeenCalled();
    await advance(3_000);
    expect(digits(host)).toBe("0:00");
    await advance(5_000);
    expect(onExpire).toHaveBeenCalledTimes(1);
  });

  it.each([[[]], [[0]]] as const)(
    "with thresholds %j the rendered phase is running until expiry",
    async (marks) => {
      const host = await mount(<Countdown expiresAt={T0 + 12_000} thresholds={marks} />);
      const root = host.querySelector("[data-cmp='CMP-035']");
      for (let i = 0; i < 11; i += 1) {
        await advance(1_000);
        expect(root).toHaveAttribute("data-phase", "running");
      }
      await advance(1_000);
      expect(root).toHaveAttribute("data-phase", "expired");
    },
  );

  it("a new expiresAt shows its own count in the same render, never the old one", async () => {
    const seen: string[] = [];
    const Probe = ({ at }: { at: number }): JSX.Element => (
      <Profiler
        id="cd"
        onRender={() => {
          seen.push(document.querySelector(".cv-countdown__digits")?.textContent ?? "");
        }}
      >
        <Countdown expiresAt={at} thresholds={[]} />
      </Profiler>
    );
    const host = document.body.appendChild(document.createElement("div"));
    const { createRoot } = await import("react-dom/client");
    const root = createRoot(host);
    await act(async () => root.render(<Probe at={T0 + 20_000} />));
    seen.length = 0;
    await act(async () => root.render(<Probe at={T0 + 90_000} />));
    expect(seen.length).toBeGreaterThan(0);
    expect(seen.every((t) => t === "1:30")).toBe(true);
    await act(async () => root.unmount());
  });

  it("re-renders only when the shown or spoken text changes (words, approx), never per tick", async () => {
    const commits = vi.fn();
    const host = await mount(
      <Profiler id="cd" onRender={commits}>
        <Countdown expiresAt={T0 + 7_200_000} format="words" thresholds={[]} />
      </Profiler>,
    );
    const shown: string[] = [];
    commits.mockClear();
    for (let i = 0; i < 120; i += 1) {
      await advance(1_000);
      const text = digits(host);
      if (shown[shown.length - 1] !== text) shown.push(text);
    }
    // Over an hour left, "2 h 0 m" → "1 h 59 m" → "1 h 58 m": two changes in 120 ticks.
    expect(shown).toEqual(["1 h 59 m", "1 h 58 m"]);
    // React may commit once more as it bails out after a change; never once a tick.
    expect(commits.mock.calls.length).toBeLessThanOrEqual(4);

    const approxCommits = vi.fn();
    const approx = await mount(
      <Profiler id="ap" onRender={approxCommits}>
        <Countdown expiresAt={T0 + 120_000 + 3_000_000} format="approx" thresholds={[]} />
      </Profiler>,
    );
    expect(digits(approx)).toBe("~50 m");
    approxCommits.mockClear();
    // ~50 m holds until fewer than 49.5 min are left: 30 ticks with no commit.
    for (let i = 0; i < 30; i += 1) await advance(1_000);
    expect(approxCommits).not.toHaveBeenCalled();
    await advance(1_000);
    expect(digits(approx)).toBe("~49 m");
  });

  it("the digits take the host's type.num step (sm by default)", async () => {
    const host = await mount(<Countdown expiresAt={T0 + 5_000} />);
    expect(host.querySelector(".cv-countdown__digits")).toHaveAttribute("data-size", "sm");
    const md = await mount(<Countdown expiresAt={T0 + 5_000} size="md" />);
    expect(md.querySelector(".cv-countdown__digits")).toHaveAttribute("data-size", "md");
  });
});
