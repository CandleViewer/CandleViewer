import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor, within } from "storybook/test";
import { Kbd } from "./Kbd.js";
import { Text } from "./Typography.js";

const row = { display: "flex", alignItems: "center", gap: "var(--space-inset-sm)" } as const;
const col = { display: "grid", gap: "var(--space-inset-sm)", justifyItems: "start" } as const;

/** Theme and density come from the toolbars; the light and high-contrast stories pin the theme for axe. */
const meta: Meta<typeof Kbd> = {
  title: "Atoms/Kbd",
  component: Kbd,
  args: { keys: ["Ctrl", "Shift", "K"] },
};
export default meta;
type Story = StoryObj<typeof Kbd>;

/** Three caps, no visible "+"; read once as "Control plus Shift plus K". */
export const Combo: Story = {
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector(".cv-kbd")).toHaveTextContent(
      /Control plus Shift plus K$/,
    );
  },
};

export const SingleKey: Story = { args: { keys: ["F"] } };

/** The keymap's "Alt+1..9": the range ends as caps with an en dash between them. */
export const Range: Story = { args: { keys: ["Alt", "1..9"] } };

/** "Ctrl+click", "Shift+wheel": key caps plus the pointer word as text. */
export const PointerChord: Story = {
  render: () => (
    <div style={col}>
      <Kbd keys={["Ctrl", "click"]} />
      <Kbd keys={["Shift", "wheel"]} />
    </div>
  ),
};

/** In a menu row the item keeps its name; the hint is hidden and `aria-keyshortcuts` carries it. */
export const InMenuRow: Story = {
  render: () => (
    <div
      role="menu"
      aria-label="Layout"
      style={{ ...col, justifyItems: "stretch", width: "18rem" }}
    >
      <div
        role="menuitem"
        tabIndex={-1}
        aria-keyshortcuts="Control+Shift+S"
        style={{ ...row, justifyContent: "space-between" }}
      >
        <Text>Save as new layout…</Text>
        <Kbd keys={["Ctrl", "Shift", "S"]} aria-hidden="true" />
      </div>
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("menuitem")).toHaveAccessibleName(
      "Save as new layout…",
    );
  },
};

/** The user's own binding, with the word "remapped" beside it (SCR-013). */
export const Remapped: Story = {
  render: () => (
    <span style={row}>
      <Kbd keys={["Ctrl", "Alt", "P"]} />
      <Text variant="caption" tone="secondary">
        remapped
      </Text>
    </span>
  ),
};

/** An unbound command renders nothing; the command stays reachable elsewhere. */
export const Unbound: Story = {
  args: { keys: [] },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector(".cv-kbd")).toBeNull();
  },
};

const All: Story = {
  render: () => (
    <div style={col}>
      <Kbd keys={["Ctrl", "Shift", "K"]} />
      <Kbd keys={["Alt", "1..9"]} />
      <Kbd keys={["Ctrl", "click"]} />
    </div>
  ),
};

const themed = (theme: string): Story => ({
  ...All,
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
});
export const ContrastLight: Story = themed("light");
export const ContrastHighContrast: Story = themed("high-contrast");
