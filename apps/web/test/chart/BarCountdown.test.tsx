import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRequire } from "node:module";
import { BarCountdown } from "../../src/chart";

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as {
  run: (
    el: Element,
    o?: object,
  ) => Promise<{ violations: { id: string; impact?: string | null }[] }>;
};

describe("BarCountdown", () => {
  const OPEN = Date.UTC(2026, 10, 1, 12, 0, 0);

  it("holds the word closing in text at 8 s, with aria-live off", () => {
    const { container } = render(
      <BarCountdown barOpenMs={OPEN} intervalMs={60_000} now={() => OPEN + 52_000} />,
    );
    expect(screen.getByText("0:08 closing")).toBeInTheDocument();
    expect(container.firstElementChild).toHaveAttribute("aria-live", "off");
    expect(container.firstElementChild).toHaveAttribute("data-state", "warn");
  });

  it("ticks on the second boundary and reaches closed", () => {
    let t = OPEN + 57_400;
    render(<BarCountdown barOpenMs={OPEN} intervalMs={60_000} now={() => t} />);
    expect(screen.getByText("0:03 closing")).toBeInTheDocument();
    t += 600; // the boundary
    act(() => void vi.advanceTimersByTime(600));
    expect(screen.getByText("0:02 closing")).toBeInTheDocument();
    t += 2_000;
    act(() => void vi.advanceTimersByTime(2_000));
    expect(screen.getByText("closed")).toBeInTheDocument();
  });

  it("flips the digits exactly on the skewed second boundary", () => {
    let t = OPEN + 47_000 + 100; // server time is t + 340: 47.440 s into the bar
    render(<BarCountdown barOpenMs={OPEN} intervalMs={60_000} skewMs={340} now={() => t} />);
    expect(screen.getByText("0:13")).toBeInTheDocument();
    t += 559;
    act(() => void vi.advanceTimersByTime(559)); // one ms short of server 48.000 s
    expect(screen.getByText("0:13")).toBeInTheDocument();
    t += 1;
    act(() => void vi.advanceTimersByTime(1));
    expect(screen.getByText("0:12")).toBeInTheDocument();
  });

  it("re-arms the timer on the new skewed boundary when the skew changes", () => {
    let t = OPEN + 50_100; // skew 0: the first tick is 900 ms away
    const now = (): number => t; // stable, so only skewMs can re-arm the effect
    const view = render(<BarCountdown barOpenMs={OPEN} intervalMs={60_000} skewMs={0} now={now} />);
    view.rerender(<BarCountdown barOpenMs={OPEN} intervalMs={60_000} skewMs={340} now={now} />);
    expect(screen.getByText("0:10 closing")).toBeInTheDocument(); // server 50.440 s
    t += 559;
    act(() => void vi.advanceTimersByTime(559)); // one ms short of server 51.000 s
    expect(screen.getByText("0:10 closing")).toBeInTheDocument();
    t += 1;
    act(() => void vi.advanceTimersByTime(1));
    expect(screen.getByText("0:09 closing")).toBeInTheDocument();
  });

  it("marks the warn glyph decorative", () => {
    const { container } = render(
      <BarCountdown barOpenMs={OPEN} intervalMs={60_000} now={() => OPEN + 52_000} />,
    );
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it.each([
    ["normal", 60_000 as number | null, 10_000],
    ["warn", 60_000 as number | null, 52_000],
    ["na", null, 0],
  ])("has no axe violations in the %s state", async (_name, interval, at) => {
    vi.useRealTimers();
    const { container } = render(
      <BarCountdown barOpenMs={OPEN} intervalMs={interval} now={() => OPEN + at} />,
    );
    const { violations } = await axe.run(container);
    expect(violations).toEqual([]);
  });

  it("shows a dash with the title for non-time bars and never ticks", () => {
    const { container } = render(
      <BarCountdown barOpenMs={OPEN} intervalMs={null} now={() => OPEN} />,
    );
    expect(container.firstElementChild).toHaveAttribute("title", "No countdown for tick bars");
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("clears its timer on unmount", () => {
    const view = render(<BarCountdown barOpenMs={OPEN} intervalMs={60_000} now={() => OPEN} />);
    expect(vi.getTimerCount()).toBe(1);
    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
