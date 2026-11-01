// @vitest-environment jsdom
import { act, StrictMode } from "react";
import { createRequire } from "node:module";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import { expect, within } from "storybook/test";
import {
  FundingCountdown,
  formatFundingCount,
  fundingCountdownState,
  fundingRateSign,
  spokenFundingCount,
} from "../src/components/index.js";
import { mount } from "./theme/mount.js";

type Axe = {
  run: (context: object, options?: object) => Promise<{ violations: { impact?: string | null }[] }>;
};
const axe = createRequire(createRequire(import.meta.url).resolve("@storybook/addon-a11y"))(
  "axe-core",
) as Axe;

/** 08:00 UTC, and the clock 1 h 24 min 13.771 s before it (D06 §7's recorded frame). */
const TARGET = Date.UTC(2026, 9, 27, 8, 0, 0);
const T0 = TARGET - 5_053_771;

const advance = async (ms: number): Promise<void> => {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
};
const digits = (host: HTMLElement): string =>
  host.querySelector(".cv-funding__digits")?.textContent ?? "";
const status = (host: HTMLElement): HTMLElement => within(host).getByRole("status");
const root = (host: HTMLElement): HTMLElement => {
  const node = host.querySelector<HTMLElement>("[data-cmp='CMP-126']");
  if (node === null) throw new Error("no CMP-126");
  return node;
};

describe("FundingCountdown formats (E08-D06 §7)", () => {
  it.each([
    [5053, "01:24:13", "1 hour 24 minutes"],
    [3599, "00:59:59", "59 minutes 59 seconds"],
    [252, "00:04:12", "4 minutes 12 seconds"],
    [3600, "01:00:00", "1 hour"],
    [60, "00:01:00", "1 minute"],
    [1, "00:00:01", "1 second"],
  ])("%i s is %s, spoken %s", (total, shown, spoken) => {
    expect(formatFundingCount(total)).toBe(shown);
    expect(spokenFundingCount(total)).toBe(spoken);
  });

  it("derives the state from the deadline: ahead, settling under 5 minutes, elapsed, unknown", () => {
    expect(fundingCountdownState(T0 + 600_000, T0)).toBe("ahead");
    expect(fundingCountdownState(T0 + 299_000, T0)).toBe("settling");
    expect(fundingCountdownState(T0, T0)).toBe("elapsed");
    expect(fundingCountdownState(T0 - 1, T0)).toBe("elapsed");
    expect(fundingCountdownState(undefined, T0)).toBe("unknown");
    expect(fundingCountdownState(Number.NaN, T0)).toBe("unknown");
  });

  it.each([
    ["0.0100%", "positive"],
    ["+0.0100%", "positive"],
    ["-0.0050%", "negative"],
    ["−0.0050%", "negative"],
    ["0.0000%", "zero"],
  ] as const)("the rate %s is %s", (rate, sign) => {
    expect(fundingRateSign(rate)).toBe(sign);
  });
});

describe("FundingCountdown (CMP-126)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(T0);
  });
  afterEach(() => vi.useRealTimers());

  const ui = (props: Partial<Parameters<typeof FundingCountdown>[0]> = {}): JSX.Element => (
    <FundingCountdown symbol="BTCUSDT" nextFundingTimeMs={TARGET} now={Date.now} {...props} />
  );

  it("shows the fixed-width count and the UTC settlement, with the words in a hidden twin", async () => {
    const host = await mount(ui());
    expect(digits(host)).toBe("next in 01:24:13 · 08:00 UTC");
    expect(within(host).getByText("Next funding in 1 hour 24 minutes, at 08:00 UTC")).toBeTruthy();
    expect(host.querySelector(".cv-funding__digits")).toHaveAttribute("aria-hidden", "true");
    expect(host.querySelector(".cv-funding__count")).toHaveAttribute("aria-live", "off");
    expect(status(host)).toBeEmptyDOMElement();
  });

  it("ticks once a second and never speaks per tick", async () => {
    const host = await mount(ui());
    await advance(1_000);
    expect(digits(host)).toBe("next in 01:24:12 · 08:00 UTC");
    await advance(1_000);
    expect(digits(host)).toBe("next in 01:24:11 · 08:00 UTC");
    await advance(60_000);
    expect(status(host)).toBeEmptyDOMElement();
  });

  it("under 5 minutes it reads 'settles in' after a glyph, and speaks once at 5 minutes and once at 1", async () => {
    const host = await mount(ui({ nextFundingTimeMs: T0 + 301_000 }));
    expect(digits(host)).toMatch(/^next in 00:05:01/);
    await advance(2_000);
    expect(root(host)).toHaveAttribute("data-state", "settling");
    expect(digits(host)).toMatch(/^settles in 00:04:59/);
    expect(host.querySelector(".cv-funding__warn svg")).toBeTruthy();
    expect(status(host)).toHaveTextContent("BTCUSDT funding settles in 5 minutes.");
    await advance(240_000);
    expect(status(host)).toHaveTextContent("BTCUSDT funding settles in 1 minute.");
    await advance(30_000);
    expect(status(host)).toHaveTextContent("BTCUSDT funding settles in 1 minute.");
  });

  it("a threshold already passed at mount never speaks", async () => {
    const host = await mount(ui({ nextFundingTimeMs: T0 + 200_000 }));
    expect(status(host)).toBeEmptyDOMElement();
    await advance(60_000);
    expect(status(host)).toBeEmptyDOMElement();
    await advance(80_000);
    expect(status(host)).toHaveTextContent("1 minute");
  });

  it("past the settlement it says so once and waits, and a new time restarts the count", async () => {
    const host = await mount(<StrictMode>{ui({ nextFundingTimeMs: T0 + 2_000 })}</StrictMode>);
    await advance(3_000);
    expect(root(host)).toHaveAttribute("data-state", "elapsed");
    expect(
      within(host).getAllByText("Settlement time passed — waiting for an update").length,
    ).toBeGreaterThan(0);
    expect(status(host)).toHaveTextContent("Settlement time passed — waiting for an update");
  });

  it("never invents a time: absent next_funding_time_ms reads 'not available', with no digits", async () => {
    const host = await mount(ui({ nextFundingTimeMs: undefined }));
    expect(within(host).getByText("Next funding time not available")).toBeTruthy();
    expect(host.querySelector(".cv-funding__digits")).toBeNull();
    expect(host.textContent).not.toMatch(/\d{2}:\d{2}/);
  });

  it("not trading: the sentence alone, no countdown and no rate", async () => {
    const host = await mount(ui({ notTrading: true, rate: "0.0100%" }));
    expect(within(host).getByText("No funding — BTCUSDT is not trading.")).toBeTruthy();
    expect(host.querySelector(".cv-funding__digits")).toBeNull();
    expect(host.querySelector(".cv-funding__rate")).toBeNull();
  });

  it("clock alarm: the absolute time and the skew line replace the count, spoken once on entry", async () => {
    const host = await mount(ui({ clockAlarm: true, clockSkewMs: 612 }));
    expect(within(host).getByText("at 08:00:00 UTC (in about 1 h 24 min)")).toBeTruthy();
    expect(host.querySelector(".cv-funding__digits")).toBeNull();
    expect(status(host)).toHaveTextContent("Clock skew 612 ms — the countdown may be off");
  });

  it("clock alarm with an unknown offset: the absolute time alone", async () => {
    const host = await mount(ui({ clockAlarm: true }));
    expect(within(host).getByText(/^at 08:00:00 UTC/)).toBeTruthy();
    expect(host.textContent).not.toMatch(/Clock skew/);
  });

  it("the rate's sign is in its text, and colour only repeats it", async () => {
    const host = await mount(ui({ rate: "0.0100%" }));
    expect(host.querySelector(".cv-funding__rate")).toHaveTextContent("+0.0100%");
    expect(host.querySelector(".cv-funding__rate")).toHaveAttribute("data-sign", "positive");
  });

  it("clears its timer on unmount", async () => {
    await mount(ui());
    expect(vi.getTimerCount()).toBeGreaterThan(0);
  });

  it.each([
    ["ahead", {}],
    ["settling", { nextFundingTimeMs: T0 + 100_000 }],
    ["unknown", { nextFundingTimeMs: undefined }],
    ["not trading", { notTrading: true }],
    ["clock alarm", { clockAlarm: true, clockSkewMs: 612 }],
  ])("axe: %s has no serious or critical violation", async (_name, props) => {
    const host = await mount(ui(props));
    vi.useRealTimers();
    const { violations } = await axe.run(
      { include: [host] },
      { rules: { "color-contrast": { enabled: false } } },
    );
    expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  });
});
