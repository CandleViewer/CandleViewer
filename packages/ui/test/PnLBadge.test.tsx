// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect, within } from "storybook/test";
import { describe, it } from "vitest";
import { PnLBadge, PositionModeToggle } from "../src/components/index.js";
import * as pnlStories from "../src/components/PnLBadge.stories.js";
import * as modeStories from "../src/components/PositionModeToggle.stories.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

const badgeOf = (host: HTMLElement): HTMLElement => {
  const el = host.querySelector<HTMLElement>('[data-cmp="CMP-116"]');
  if (el === null) throw new Error("no CMP-116 rendered");
  return el;
};
const visible = (host: HTMLElement): string =>
  badgeOf(host).querySelector(".cv-pnl-badge__value")?.textContent ?? "";
const spoken = (host: HTMLElement): string =>
  badgeOf(host).querySelector(".cv-visually-hidden")?.textContent ?? "";

describe("PnLBadge (CMP-116)", () => {
  it("marks exactly one root with data-cmp", async () => {
    const host = await mount(<PnLBadge value="8" />);
    expect(host.querySelectorAll('[data-cmp="CMP-116"]')).toHaveLength(1);
    const mode = await mount(<PositionModeToggle value="hedge" />);
    expect(mode.querySelectorAll('[data-cmp="CMP-129"]')).toHaveLength(1);
  });

  it.each([
    ["8", "currency", "+8.00 USDT", "profit 8.00 USDT", "positive"],
    ["-121.5", "currency", "−121.50 USDT", "loss 121.50 USDT", "negative"],
    ["0", "currency", "0.00 USDT", "0.00 USDT", "zero"],
    ["-0.004", "currency", "0.00 USDT", "0.00 USDT", "zero"],
    ["8", "abs", "+8.00", "profit 8.00 USDT", "positive"],
  ] as const)("%s as %s shows %j and reads %j", async (value, format, shown, reading, sign) => {
    const host = await mount(<PnLBadge value={value} places={2} format={format} currency="USDT" />);
    expect(visible(host)).toBe(shown);
    expect(spoken(host)).toBe(reading);
    expect(badgeOf(host).dataset["sign"]).toBe(sign);
  });

  it("reads the sign in words as visually hidden text, never an aria-label; the digits and bar are hidden", async () => {
    const host = await mount(<PnLBadge value="8" places={2} format="currency" currency="USDT" />);
    const badge = badgeOf(host);
    expect(host.querySelector("[aria-label]")).toBeNull();
    expect(badge.hasAttribute("role")).toBe(false);
    expect(badge.querySelector(".cv-pnl-badge__bar")).toHaveAttribute("aria-hidden", "true");
    expect(badge.querySelector(".cv-pnl-badge__value")).toHaveAttribute("aria-hidden", "true");
    // What assistive technology reads is the hidden sentence alone.
    expect(within(host).getByText("profit 8.00 USDT")).toHaveClass("cv-visually-hidden");
  });

  it("an R multiple is signed text with no visible unit; a null R reads its reason and draws no bar", async () => {
    const r = await mount(<PnLBadge value="0.32" format="r" places={2} />);
    expect([visible(r), spoken(r)]).toEqual(["+0.32", "profit 0.32 R"]);
    const none = await mount(<PnLBadge value={null} format="r" />);
    expect([visible(none), spoken(none)]).toEqual(["—", "R unavailable: no stop price"]);
    expect(none.querySelector(".cv-pnl-badge__bar")).toBeNull();
    expect(badgeOf(none).hasAttribute("data-sign")).toBe(false);
  });

  it("a percentage keeps its % visible and spoken", async () => {
    const host = await mount(<PnLBadge value="-1.255" format="pct" places={2} />);
    expect([visible(host), spoken(host)]).toEqual(["−1.26%", "loss 1.26%"]);
  });

  it("a null or non-decimal money value shows a dash read as the host's reason, else CMP-020's 'no value'", async () => {
    const reasoned = await mount(
      <PnLBadge value={null} format="abs" nullReading="the host's reason" />,
    );
    expect(spoken(reasoned)).toBe("the host's reason");
    const garbled = await mount(<PnLBadge value="1e5" format="currency" currency="USDT" />);
    expect([visible(garbled), spoken(garbled)]).toEqual(["—", "no value"]);
  });

  it("keeps the string's own places when none are given, and never rounds through a double", async () => {
    const host = await mount(<PnLBadge value="9007199254740993.5" places={0} format="abs" />);
    expect(visible(host)).toBe("+9,007,199,254,740,994");
    const own = await mount(<PnLBadge value="12.3456" format="abs" />);
    expect(visible(own)).toBe("+12.3456");
  });

  it("maps size to its digit step and defaults to md", async () => {
    const host = await mount(<PnLBadge value="1" size="lg" />);
    expect(badgeOf(host).dataset["size"]).toBe("lg");
    expect(badgeOf(await mount(<PnLBadge value="1" />)).dataset["size"]).toBe("md");
  });

  it("is not interactive: no Tab stop", async () => {
    const host = await mount(<PnLBadge value="8" />);
    expect(host.querySelector("[tabindex], button, a")).toBeNull();
  });

  it("has no serious or critical axe violation", async () => {
    const host = await mount(
      <div>
        <PnLBadge value="8" places={2} format="currency" currency="USDT" />
        <PnLBadge value={null} format="r" />
      </div>,
    );
    expect(await seriousViolations(host)).toEqual([]);
  });
});

describe("PositionModeToggle (CMP-129, display)", () => {
  it.each([
    ["one-way", "One-way"],
    ["hedge", "Hedge"],
  ] as const)("%s reads as the plain word %s: no role, no Tab stop", async (value, word) => {
    const host = await mount(<PositionModeToggle value={value} />);
    const text = within(host).getByText(word);
    expect(text.dataset["cmp"]).toBe("CMP-129");
    expect(text.dataset["variant"]).toBe("display");
    expect(text.hasAttribute("role")).toBe(false);
    expect(host.querySelector("[tabindex], button, input")).toBeNull();
    expect(await seriousViolations(host)).toEqual([]);
  });
});

describe("PnLBadge and PositionModeToggle stories", () => {
  it.each(Object.entries(composeStories(pnlStories)))("PnLBadge %s renders", async (_n, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelectorAll('[data-cmp="CMP-116"]').length).toBeGreaterThan(0);
  });

  it.each(Object.entries(composeStories(modeStories)))(
    "PositionModeToggle %s renders",
    async (_n, Story) => {
      const host = await mount(<Story />);
      expect(host.querySelectorAll('[data-cmp="CMP-129"]').length).toBeGreaterThan(0);
    },
  );
});
