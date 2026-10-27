import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor, within } from "storybook/test";
import { Avatar } from "./Avatar.js";

const row = { display: "flex", gap: "var(--space-inset-sm)", alignItems: "center" } as const;
const name = {
  color: "var(--color-text-primary)",
  font: "var(--type-ui-body-font-weight) var(--type-ui-body-font-size) / var(--type-ui-body-line-height) var(--type-ui-body-font-family)",
} as const;

/**
 * Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations.
 * The catalogue's ColorPalette story waits for an avatar palette (E2): until then every avatar uses the
 * interim `color.neutral.subtle` fill, so there is no palette to show.
 */
const meta: Meta<typeof Avatar> = {
  title: "Atoms/Avatar",
  component: Avatar,
  args: { label: "Alpha Desk", standalone: true },
};
export default meta;
type Story = StoryObj<typeof Avatar>;

/** The only content: `role="img"` named by the full label, never the initials. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const avatar = within(canvasElement).getByRole("img", { name: "Alpha Desk" });
    await expect(avatar).toHaveTextContent("AD");
  },
};

/** sm (size.icon) shows one initial, md (size.control.height) two. */
export const AllSizes: Story = {
  render: (args) => (
    <div style={row}>
      <Avatar {...args} size="sm" />
      <Avatar {...args} size="md" />
    </div>
  ),
};

/** Beside its visible name the avatar is decorative. */
export const WithVisibleName: Story = {
  render: (args) => (
    <span style={row}>
      <Avatar label={args.label} />
      <span style={name}>{args.label}</span>
    </span>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("img")).toBeNull();
  },
};

/** A long label still draws two initials in a fixed circle; nothing inside it truncates. */
export const LongLabel: Story = {
  args: { label: "Carry Fund Overnight Hedge Account" },
};

const themed = (theme: string): Story => ({
  ...AllSizes,
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
});
export const ContrastLight: Story = themed("light");
export const ContrastHighContrast: Story = themed("high-contrast");
