// @vitest-environment jsdom
import { describe, it } from "vitest";
import { expect, within } from "storybook/test";
import { Skeleton, SkeletonChart } from "../src/components/index.js";
import { mount } from "./theme/mount.js";

const blocks = (host: HTMLElement, sel = ".cv-skeleton__block"): number =>
  host.querySelectorAll(sel).length;

describe("Skeleton (CMP-015)", () => {
  it("is hidden from assistive technology inside a busy host whose words carry the wait", async () => {
    const host = await mount(
      <section aria-label="Positions" aria-busy="true">
        Loading positions…
        <Skeleton />
      </section>,
    );
    const region = within(host).getByRole("region", { name: "Positions" });
    expect(region).toHaveAttribute("aria-busy", "true");
    expect(region).toHaveAccessibleName("Positions");
    const skeleton = host.querySelector(".cv-skeleton");
    expect(skeleton).toHaveAttribute("aria-hidden", "true");
    expect(skeleton).toHaveAttribute("data-cmp", "CMP-015");
    expect(within(host).queryAllByRole("img")).toHaveLength(0);
    expect(host.querySelector("[tabindex]")).toBeNull();
  });

  it("text is the default shape with three lines; count sets the lines", async () => {
    const host = await mount(<Skeleton />);
    expect(host.querySelector(".cv-skeleton")).toHaveAttribute("data-shape", "text");
    expect(blocks(host)).toBe(3);
    expect(blocks(await mount(<Skeleton count={5} />))).toBe(5);
  });

  it("row renders count rows of three cells; card a heading and two lines; chart one block", async () => {
    const rows = await mount(<Skeleton shape="row" count={2} />);
    expect(blocks(rows, ".cv-skeleton__row")).toBe(2);
    expect(blocks(rows)).toBe(6);
    const card = await mount(<Skeleton shape="card" />);
    expect(blocks(card, ".cv-skeleton__card")).toBe(1);
    expect(blocks(card)).toBe(3);
    const chart = await mount(<Skeleton shape="chart" />);
    expect(blocks(chart)).toBe(1);
  });

  it("count is a whole number from 1 to 50; NaN and Infinity fall back to 1", async () => {
    expect(blocks(await mount(<Skeleton count={0} />))).toBe(1);
    expect(blocks(await mount(<Skeleton shape="row" count={2.7} />), ".cv-skeleton__row")).toBe(2);
    expect(blocks(await mount(<Skeleton count={Number.NaN} />))).toBe(1);
    expect(blocks(await mount(<Skeleton count={Number.POSITIVE_INFINITY} />))).toBe(1);
    expect(blocks(await mount(<Skeleton count={500} />))).toBe(50);
  });

  it("marks an overlay host only when asked", async () => {
    const base = await mount(<Skeleton />);
    expect(base.querySelector(".cv-skeleton")).not.toHaveAttribute("data-surface");
    const overlay = await mount(<Skeleton surface="overlay" />);
    expect(overlay.querySelector(".cv-skeleton")).toHaveAttribute("data-surface", "overlay");
  });
});

describe("SkeletonChart (CMP-029)", () => {
  it("is hidden, one price pane by default, with price and time axis blocks", async () => {
    const host = await mount(<SkeletonChart />);
    const root = host.querySelector("[data-cmp='CMP-029']");
    expect(root).toHaveAttribute("aria-hidden", "true");
    expect(blocks(host, ".cv-skeleton-chart__pane")).toBe(1);
    expect(blocks(host, ".cv-skeleton-chart__wick")).toBeGreaterThan(0);
    expect(blocks(host, ".cv-skeleton-chart__time > .cv-skeleton__block")).toBe(5);
  });

  it("paneCount adds sub-panes of bars, 1 to 6; NaN and Infinity fall back to 1", async () => {
    const host = await mount(<SkeletonChart paneCount={3} />);
    const panes = host.querySelectorAll(".cv-skeleton-chart__pane");
    expect(panes).toHaveLength(3);
    expect(panes[0]).not.toHaveAttribute("data-sub");
    expect(panes[1]).toHaveAttribute("data-sub", "");
    expect(panes[2]?.querySelector(".cv-skeleton-chart__wick")).toBeNull();
    const paneTotal = async (n: number): Promise<number> =>
      blocks(await mount(<SkeletonChart paneCount={n} />), ".cv-skeleton-chart__pane");
    expect(await paneTotal(0)).toBe(1);
    expect(await paneTotal(Number.NaN)).toBe(1);
    expect(await paneTotal(Number.POSITIVE_INFINITY)).toBe(1);
    expect(await paneTotal(40)).toBe(6);
  });

  it("the candle geometry is deterministic and inside the pane", async () => {
    const a = (await mount(<SkeletonChart />)).innerHTML;
    const b = (await mount(<SkeletonChart />)).innerHTML;
    expect(a).toBe(b);
    const host = await mount(<SkeletonChart />);
    for (const candle of host.querySelectorAll<HTMLElement>(".cv-skeleton-chart__candle")) {
      const top = parseFloat(candle.style.getPropertyValue("--cv-wick-top"));
      const h = parseFloat(candle.style.getPropertyValue("--cv-wick-h"));
      expect(top).toBeGreaterThanOrEqual(0);
      expect(top + h).toBeLessThanOrEqual(100);
    }
  });
});
