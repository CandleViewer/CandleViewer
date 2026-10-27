import type { JSX } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor, within } from "storybook/test";
import { Icon } from "../icons/Icon.js";
import type { IconName } from "../icons/registry.js";
import { Badge, type BadgeTone } from "./Badge.js";

const TONES = ["neutral", "info", "success", "warning", "danger"] as const;
/** A status dot always sits beside the tone's glyph (none for neutral) and a visible word. */
const STATUS: Record<BadgeTone, { word: string; glyph?: IconName }> = {
  neutral: { word: "Idle" },
  info: { word: "Syncing", glyph: "info" },
  success: { word: "Healthy", glyph: "check" },
  warning: { word: "Degraded", glyph: "warning" },
  danger: { word: "Blocked", glyph: "danger" },
};

const row = { display: "flex", gap: "var(--space-inset-sm)", alignItems: "center" } as const;
const col = { display: "grid", gap: "var(--space-inset-sm)", justifyItems: "start" } as const;

function StatusDot({ tone }: { tone: BadgeTone }): JSX.Element {
  const { word: text, glyph } = STATUS[tone];
  return (
    <span style={row}>
      <Badge variant="dot" tone={tone} />
      {glyph ? <Icon name={glyph} size="sm" /> : null}
      <span style={{ color: "var(--color-text-primary)" }}>{text}</span>
    </span>
  );
}

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof Badge> = {
  title: "Atoms/Badge",
  component: Badge,
  args: { value: 3, label: "unread alerts" },
};
export default meta;
type Story = StoryObj<typeof Badge>;

export const Default: Story = {};

/** One, two and three digits, then the "99+" cap; each name keeps the full number. */
export const Count: Story = {
  render: () => (
    <div style={row}>
      {[3, 12, 99, 1500].map((value) => (
        <Badge key={value} value={value} label="unread alerts" tone="danger" />
      ))}
    </div>
  ),
  play: async ({ canvasElement }) => {
    const capped = within(canvasElement).getByRole("img", { name: "1500 unread alerts" });
    await expect(capped).toHaveTextContent("99+");
  },
};

/** On a labelled control the count is hidden and the control's own name carries it. */
export const OnLabelledControl: Story = {
  render: () => (
    <button type="button" className="cv-control" style={row} aria-label="Notifications, 3 unread">
      <Icon name="info" size="md" />
      <Badge value={3} tone="info" />
    </button>
  ),
};

export const Dot: Story = { render: () => <StatusDot tone="warning" /> };

/** Variant x Tone: the catalogue's AllTones, count and dot in each of the five tones. */
export const AllTones: Story = {
  render: () => (
    <div style={col}>
      {TONES.map((tone) => (
        <div key={tone} style={row}>
          <Badge value={7} label={`${tone} items`} tone={tone} />
          <StatusDot tone={tone} />
        </div>
      ))}
    </div>
  ),
};

/** Every tone under the light and high-contrast themes; axe checks each theme. */
const themed = (theme: string): Story => ({
  ...AllTones,
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
});
export const ContrastLight: Story = themed("light");
export const ContrastHighContrast: Story = themed("high-contrast");
