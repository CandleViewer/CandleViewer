// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import type { JSX } from "react";
import { expect, within } from "storybook/test";
import { describe, it } from "vitest";
import { SwatchLegendItem } from "../src/components/index.js";
import * as stories from "../src/components/SwatchLegendItem.stories.js";
import { mount } from "./theme/mount.js";

const inList = (item: JSX.Element): Promise<HTMLElement> => mount(<ul>{item}</ul>);

describe("SwatchLegendItem (CMP-037)", () => {
  it("is a list item read by its label and value; the swatch is hidden and token-coloured", async () => {
    const host = await inList(
      <SwatchLegendItem color="var(--color-heatmap-bid-3)" label="Bid liquidity" value={1.2e6} />,
    );
    const item = within(host).getByRole("listitem");
    expect(item.dataset["cmp"]).toBe("CMP-037");
    const swatch = within(host).getByTestId("legend-swatch");
    expect(swatch).toHaveAttribute("aria-hidden", "true");
    expect(swatch.style.getPropertyValue("--cv-legend-swatch")).toBe("var(--color-heatmap-bid-3)");
    expect(swatch).not.toHaveAttribute("width");
    expect(host.querySelector(".cv-legend-item__label")?.getAttribute("data-variant")).toBe(
      "caption",
    );
  });

  it("shows the value through NumericText: '1.2M' hidden, '1,200,000' read", async () => {
    const host = await inList(<SwatchLegendItem color="red" label="Bid" value={1_200_000} />);
    const value = host.querySelector(".cv-legend-item__value");
    expect(value).toHaveClass("cv-num");
    expect(value?.getAttribute("data-size")).toBe("sm");
    expect(value?.querySelector('[aria-hidden="true"]')).toHaveTextContent("1.2M");
    expect(value?.querySelector(".cv-visually-hidden")).toHaveTextContent("1,200,000");
  });

  it("formats and rounds per the given format and precision", async () => {
    const host = await inList(
      <SwatchLegendItem color="red" label="Fill" value={42.5} format="pct" precision={0} />,
    );
    expect(host.querySelector(".cv-legend-item__value")).toHaveTextContent(/^43%$/);
  });

  it.each(["", "  "])("treats a blank glyph (%j) as absent", async (glyph) => {
    const host = await inList(<SwatchLegendItem color="red" glyph={glyph} label="Zero" />);
    expect(host.querySelector(".cv-legend-item__glyph")).toBeNull();
  });

  it("omits the value and the glyph when not given", async () => {
    const host = await inList(<SwatchLegendItem color="var(--color-heatmap-zero)" label="Zero" />);
    expect(host.querySelector(".cv-legend-item__value")).toBeNull();
    expect(host.querySelector(".cv-legend-item__glyph")).toBeNull();
  });

  it("hides the glyph, which a directional colour requires at the type level", async () => {
    const host = await inList(
      <SwatchLegendItem color="var(--color-buy-default)" glyph="▲" label="Buy" />,
    );
    expect(host.querySelector(".cv-legend-item__glyph")).toHaveAttribute("aria-hidden", "true");
    expect(within(host).getByRole("listitem")).toHaveTextContent(/^▲Buy$/);
    // @ts-expect-error a buy / sell swatch encodes direction: the glyph is required
    const buy = <SwatchLegendItem color="var(--color-buy-default)" label="x" />;
    // @ts-expect-error so is the sell side
    const sell = <SwatchLegendItem color="var(--color-sell-default)" label="Sell" />;
    // @ts-expect-error so is an up / down candle swatch
    const up = <SwatchLegendItem color="var(--color-candle-up)" label="Up" />;
    expect([buy, sell, up]).toHaveLength(3);
  });
});

describe("SwatchLegendItem stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelector(".cv-legend-item")).not.toBeNull();
  });
});
