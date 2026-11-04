// @vitest-environment jsdom
import { act, StrictMode } from "react";
import { createRequire } from "node:module";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import { expect, within } from "storybook/test";
import {
  createSecondTick,
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

const utcHm = (ms: number): string => new Date(ms).toISOString().slice(11, 16);

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

  it("renders the host's rateExtra after the rate and before the count, and with no rate (n/a)", async () => {
    const extra = <span data-testid="extra">/ 8 h · predicted</span>;
    const host = await mount(ui({ rate: "+0.0100 %", rateExtra: extra }));
    const rate = host.querySelector(".cv-funding__rate");
    const node = within(host).getByTestId("extra");
    expect(rate?.compareDocumentPosition(node)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(node.compareDocumentPosition(host.querySelector(".cv-funding__count") as Element)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    const na = await mount(ui({ rateExtra: extra }));
    expect(within(na).getByTestId("extra")).toBeTruthy();
    expect(na.querySelector(".cv-funding__rate")).toBeNull();
    const idle = await mount(ui({ rate: "+0.0100 %", notTrading: true, rateExtra: extra }));
    expect(within(idle).queryByTestId("extra")).toBeNull();
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

  it("each threshold is announced exactly once: the status node says each line once over the whole run", async () => {
    const host = await mount(ui({ nextFundingTimeMs: T0 + 301_000 }));
    const node = status(host);
    const said: string[] = [];
    const watch = new MutationObserver(() => said.push(node.textContent ?? ""));
    watch.observe(node, { childList: true, characterData: true, subtree: true });
    for (let i = 0; i < 302; i += 1) {
      await advance(1_000);
      said.push(...watch.takeRecords().map(() => node.textContent ?? ""));
    }
    watch.disconnect();
    expect(status(host)).toBe(node);
    expect([...new Set(said)]).toEqual([
      "BTCUSDT funding settles in 5 minutes.",
      "BTCUSDT funding settles in 1 minute.",
      "Settlement time passed — waiting for an update",
    ]);
    expect(said.filter((text) => text.includes("5 minutes"))).toHaveLength(1);
    expect(said.filter((text) => text.includes("1 minute."))).toHaveLength(1);
  });

  it("a threshold already passed at mount never speaks", async () => {
    const host = await mount(ui({ nextFundingTimeMs: T0 + 200_000 }));
    expect(status(host)).toBeEmptyDOMElement();
    await advance(60_000);
    expect(status(host)).toBeEmptyDOMElement();
    await advance(80_000);
    expect(status(host)).toHaveTextContent("1 minute");
  });

  it("past the settlement it says so once and waits", async () => {
    const host = await mount(<StrictMode>{ui({ nextFundingTimeMs: T0 + 2_000 })}</StrictMode>);
    await advance(3_000);
    expect(root(host)).toHaveAttribute("data-state", "elapsed");
    expect(
      within(host).getAllByText("Settlement time passed — waiting for an update").length,
    ).toBeGreaterThan(0);
    expect(status(host)).toHaveTextContent("Settlement time passed — waiting for an update");
  });

  it("a new time restarts the count and clears the old message", async () => {
    const host = document.body.appendChild(document.createElement("div"));
    const tree = createRoot(host);
    await act(async () => tree.render(ui({ nextFundingTimeMs: T0 + 2_000 })));
    await advance(3_000);
    expect(status(host)).toHaveTextContent("Settlement time passed — waiting for an update");
    await act(async () => tree.render(ui({ nextFundingTimeMs: T0 + 3_000 + 3_600_000 })));
    expect(digits(host)).toBe(`next in 01:00:00 · ${utcHm(T0 + 3_000 + 3_600_000)} UTC`);
    expect(root(host)).toHaveAttribute("data-state", "ahead");
    expect(status(host)).toBeEmptyDOMElement();
    await act(async () => tree.unmount());
  });

  it("the passed deadline wins over the clock alarm, and the alarm silences the thresholds", async () => {
    const host = await mount(ui({ nextFundingTimeMs: T0 + 301_000, clockAlarm: true }));
    expect(root(host)).toHaveAttribute("data-state", "clock-alarm");
    await advance(250_000);
    expect(status(host)).toBeEmptyDOMElement();
    await advance(60_000);
    expect(root(host)).toHaveAttribute("data-state", "elapsed");
    expect(host.textContent).not.toMatch(/at \d{2}:\d{2}:\d{2} UTC/);
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

  it("the rate's sign is in its text, never a side hue", async () => {
    const host = await mount(ui({ rate: "0.0100%" }));
    expect(host.querySelector(".cv-funding__rate")).toHaveTextContent("+0.0100%");
    expect(host.querySelector(".cv-funding__rate")).toHaveAttribute("data-sign", "positive");
  });

  it("clears its timer on unmount", async () => {
    const host = document.body.appendChild(document.createElement("div"));
    const tree = createRoot(host);
    await act(async () => tree.render(ui()));
    expect(vi.getTimerCount()).toBeGreaterThan(0);
    await act(async () => tree.unmount());
    expect(vi.getTimerCount()).toBe(0);
  });

  it("under 5 minutes it shows each server charge as its own line, and none without a position", async () => {
    const pay = {
      accountLabel: "Demo 1",
      env: "DEMO",
      direction: "pay",
      amountUsdt: "12.40",
    } as const;
    const live = { ...pay, accountLabel: "Sub-1", env: "LIVE" } as const;
    const host = await mount(ui({ nextFundingTimeMs: T0 + 252_000, charges: [pay, live] }));
    expect(root(host)).toHaveAttribute("data-state", "settling");
    expect(within(host).getByText("— you pay ≈ 12.40 USDT on Demo 1 · DEMO")).toBeTruthy();
    expect(within(host).getByText("— you pay ≈ 12.40 USDT on Sub-1 · LIVE")).toBeTruthy();
    expect(within(host).getByText("you pay about 12.40 USDT on Demo 1, DEMO")).toBeTruthy();
    const none = await mount(ui({ nextFundingTimeMs: T0 + 252_000, charges: [] }));
    expect(none.querySelector(".cv-funding__charge")).toBeNull();
    expect(none.textContent).not.toMatch(/USDT/);
    const ahead = await mount(ui({ charges: [pay] }));
    expect(ahead.querySelector(".cv-funding__charge")).toBeNull();
  });

  it("speaks the charge with the 5 minute and 1 minute lines only (D03 AN-1, AN-2)", async () => {
    const pay = {
      accountLabel: "Demo 1",
      env: "DEMO",
      direction: "receive",
      amountUsdt: "12.40",
    } as const;
    const host = await mount(ui({ nextFundingTimeMs: T0 + 301_000, charges: [pay] }));
    await advance(2_000);
    expect(status(host)).toHaveTextContent(
      "BTCUSDT funding settles in 5 minutes — you receive about 12.40 USDT on Demo 1, DEMO.",
    );
    await advance(240_000);
    expect(status(host)).toHaveTextContent(
      "BTCUSDT funding settles in 1 minute — you receive about 12.40 USDT on Demo 1, DEMO.",
    );
  });

  it("a stale estimate keeps its line and carries the marker text", async () => {
    const stale = {
      accountLabel: "Demo 1",
      env: "DEMO",
      direction: "pay",
      amountUsdt: "12.40",
      staleNote: "Stale 7s · last 15:55:41",
    } as const;
    const host = await mount(ui({ nextFundingTimeMs: T0 + 252_000, charges: [stale] }));
    expect(host.querySelector(".cv-funding__charge")).toHaveAttribute("data-stale", "true");
    expect(within(host).getByText("Stale 7s · last 15:55:41")).toBeTruthy();
  });

  it("of two instances of one countdown only the one that announces speaks (D03 §13)", async () => {
    const host = await mount(
      <>
        {ui({ nextFundingTimeMs: T0 + 301_000 })}
        {ui({ nextFundingTimeMs: T0 + 301_000, announce: false })}
      </>,
    );
    expect(within(host).getAllByRole("status")).toHaveLength(1);
    await advance(2_000);
    expect(host.querySelectorAll("[data-state='settling']")).toHaveLength(2);
    expect(within(host).getByRole("status")).toHaveTextContent(
      "BTCUSDT funding settles in 5 minutes.",
    );
    expect(host.textContent?.match(/funding settles in 5 minutes/g)).toHaveLength(1);
  });

  it("every countdown on one tick shares its single timer and shows one value", async () => {
    const tick = createSecondTick();
    const host = await mount(
      <>
        {ui({ tick, now: undefined })}
        {ui({ tick, now: undefined })}
      </>,
    );
    expect(vi.getTimerCount()).toBe(1);
    await advance(5_000);
    const [a, b] = [...host.querySelectorAll(".cv-funding__digits")].map((n) => n.textContent);
    expect(a).toBe("next in 01:24:08 · 08:00 UTC");
    expect(b).toBe(a);
  });

  it("under a 3 s clock skew it reaches zero within one second of the true settlement", async () => {
    // the local clock runs 3 s ahead of the exchange: the synced clock is local − 3 000 ms
    const tick = createSecondTick({ now: () => Date.now() - 3_000 });
    // a settlement on a whole exchange second, about ten seconds out
    const target = Math.ceil((Date.now() - 3_000) / 1000) * 1000 + 10_000;
    const host = await mount(ui({ tick, now: undefined, nextFundingTimeMs: target }));
    const exchangeNow = (): number => Date.now() - 3_000;
    let zeroAt: number | null = null;
    for (let i = 0; i < 12_000 && zeroAt === null; i += 50) {
      await advance(50);
      if (root(host).getAttribute("data-state") === "elapsed") zeroAt = exchangeNow();
    }
    expect(zeroAt).not.toBeNull();
    expect(Math.abs((zeroAt ?? 0) - target)).toBeLessThan(1_000);
    // a second before the settlement it still counted, never ended early
    expect(zeroAt ?? 0).toBeGreaterThanOrEqual(target);
  });

  it("restarts from the advanced next time across a settlement, never from an interval", async () => {
    const host = document.body.appendChild(document.createElement("div"));
    const tree = createRoot(host);
    const first = T0 + 2_000;
    await act(async () => tree.render(ui({ nextFundingTimeMs: first })));
    await advance(3_000);
    expect(root(host)).toHaveAttribute("data-state", "elapsed");
    const next = first + 4 * 3_600_000; // the ticker's advanced time, a 4 h symbol
    await act(async () => tree.render(ui({ nextFundingTimeMs: next })));
    expect(digits(host)).toBe(`next in 03:59:59 · ${utcHm(next)} UTC`);
    await act(async () => tree.unmount());
  });

  it.each([
    ["ahead", {}],
    ["settling", { nextFundingTimeMs: T0 + 100_000 }],
    ["unknown", { nextFundingTimeMs: undefined }],
    ["not trading", { notTrading: true }],
    ["clock alarm", { clockAlarm: true, clockSkewMs: 612 }],
    [
      "settling with charges",
      {
        nextFundingTimeMs: T0 + 100_000,
        charges: [
          { accountLabel: "Demo 1", env: "DEMO", direction: "pay", amountUsdt: "1.00" } as const,
        ],
      },
    ],
  ])(
    "axe: %s has no serious or critical violation",
    async (_name, props) => {
      const host = await mount(ui(props));
      vi.useRealTimers();
      const { violations } = await axe.run(
        { include: [host] },
        { rules: { "color-contrast": { enabled: false } } },
      );
      expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
        [],
      );
    },
    30_000,
  );
});
