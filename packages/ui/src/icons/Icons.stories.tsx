import type { JSX } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";
import { Icon } from "./Icon.js";
import { ICON_SIZES } from "./IconSvg.js";
import { ICONS, type IconName } from "./registry.js";

// Object.keys widens to string[]; ICONS' keys are exactly IconName, the type derived from them.
const NAMES = Object.keys(ICONS) as IconName[];

/** CMP-019 Icon: every registered glyph by name (the base set; trading glyphs join it later). */
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
