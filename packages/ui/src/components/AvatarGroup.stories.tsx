import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor, within } from "storybook/test";
import { AvatarGroup } from "./AvatarGroup.js";

const ACCOUNTS = ["Alpha Desk", "Bravo Sub", "Carry Fund", "Delta Main", "Echo Hedge"].map(
  (label) => ({ label }),
);
const NAME = "5 accounts: Alpha Desk, Bravo Sub, Carry Fund, Delta Main, Echo Hedge";

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof AvatarGroup> = {
  title: "Atoms/AvatarGroup",
  component: AvatarGroup,
  args: { items: ACCOUNTS.slice(0, 3), max: 4 },
};
export default meta;
type Story = StoryObj<typeof AvatarGroup>;

/** Overflow=false: every avatar drawn. */
export const Default: Story = {};

/** Overflow=true: three avatars and a +2 chip; the group's name still lists all five. */
export const Overflow: Story = {
  args: { items: ACCOUNTS, max: 3 },
  play: async ({ canvasElement }) => {
    const group = within(canvasElement).getByRole("img", { name: NAME });
    await expect(group).toHaveTextContent("+2");
  },
};

/** On a raised surface the host re-points the cut-out ring to its own surface token (E23). */
export const OnRaisedSurface: Story = {
  args: { items: ACCOUNTS, max: 3 },
  render: (args) => (
    <div
      style={{
        background: "var(--color-surface-raised)",
        padding: "var(--space-inset-sm)",
        ["--cv-avatar-group-ring" as string]: "var(--color-surface-raised)",
      }}
    >
      <AvatarGroup {...args} />
    </div>
  ),
};

const themed = (theme: string): Story => ({
  args: { items: ACCOUNTS, max: 3 },
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
});
export const ContrastLight: Story = themed("light");
export const ContrastHighContrast: Story = themed("high-contrast");
