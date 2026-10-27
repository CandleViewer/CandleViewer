import type { JSX } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";
import { Icon } from "./Icon.js";
import { ICON_SIZES } from "./IconSvg.js";
import { ICONS, type IconName } from "./registry.js";

// Object.keys widens to string[]; ICONS' keys are exactly IconName, the type derived from them.
const NAMES = Object.keys(ICONS) as IconName[];
/** E05-D02 §7.12's trading glyphs: the custom ones, CandleViewer's own. */
const TRADING = NAMES.filter((name) => ICONS[name].source.startsWith("custom/"));

/** CMP-019 Icon: every registered glyph by name, the base set and the trading glyphs. */
const meta: Meta = { title: "Atoms/Icon" };
export default meta;
type Story = StoryObj;

/** Every registered icon, decorative, beside its name; axe-clean. */
export const FullSet: Story = {
  render: (): JSX.Element => (
    <ul aria-label="Icon registry">
      {NAMES.map((name) => (
        <li key={name}>
          <Icon name={name} size="lg" /> <code>{name}</code>
        </li>
      ))}
    </ul>
  ),
  play: async ({ canvasElement }) => {
    const list = within(canvasElement).getByRole("list", { name: "Icon registry" });
    expect(list.querySelectorAll("svg[aria-hidden='true']")).toHaveLength(NAMES.length);
  },
};

/** The three optical sizes, each the `size.icon.*` token, and a meaningful (named) icon. */
export const SizeScale: Story = {
  render: (): JSX.Element => (
    <p>
      {ICON_SIZES.map((size) => (
        <Icon key={size} name="info" size={size} />
      ))}
      <Icon name="lock" decorative={false} label="Locked" />
    </p>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("img", { name: "Locked" })).toBeVisible();
  },
};

/**
 * The trading glyphs at sm, md and lg: `estimated` draws its reduced form at sm, and a "16 px
 * minimum" glyph is never drawn there (E05-D02 §6 J24).
 */
export const TradingGlyphs: Story = {
  render: (): JSX.Element => (
    <ul aria-label="Trading glyphs">
      {TRADING.map((name) => {
        const minimum = "minimumPx" in ICONS[name];
        return (
          <li key={name}>
            {ICON_SIZES.filter((size) => !minimum || size !== "sm").map((size) => (
              <Icon key={size} name={name} size={size} />
            ))}{" "}
            <code>{name}</code>
            {minimum ? " (16 px minimum: md and lg only)" : ""}
          </li>
        );
      })}
    </ul>
  ),
  play: async ({ canvasElement }) => {
    const list = within(canvasElement).getByRole("list", { name: "Trading glyphs" });
    const drawn = [...list.querySelectorAll("svg[aria-hidden='true']")];
    const minimum = TRADING.filter((name) => "minimumPx" in ICONS[name]);
    expect(drawn).toHaveLength(TRADING.length * ICON_SIZES.length - minimum.length);
    // At sm (12 px as shipped), every trading glyph but a "16 px minimum" one.
    const sm = drawn.filter((svg) => svg.getAttribute("style")?.includes("--size-icon-sm"));
    expect(sm.map((svg) => svg.getAttribute("data-icon"))).toEqual(
      TRADING.filter((name) => !minimum.includes(name)),
    );
  },
};
