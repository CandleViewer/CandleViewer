import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor, within } from "storybook/test";
import { Countdown } from "./Countdown.js";
import { Text } from "./Typography.js";

/** A frozen clock: the frozen stories render the same digits on every run (visual regression). */
const T0 = Date.UTC(2026, 9, 27, 14, 2, 0);
const frozen = (): number => T0;

const col = { display: "grid", gap: "var(--space-inset-sm)", justifyItems: "start" } as const;

/** Theme and density come from the toolbars; the light and high-contrast stories pin the theme for axe. */
const meta: Meta<typeof Countdown> = {
  title: "Atoms/Countdown",
  component: Countdown,
  args: { expiresAt: T0 + 20_000, now: frozen },
  render: (args) => (
    <Text variant="caption" tone="secondary">
      Cancels in <Countdown {...args} />
    </Text>
  ),
};
export default meta;
type Story = StoryObj<typeof Countdown>;

/** The order confirm's "Cancels in 0:20" (E30-D03); the digits are hidden, the twin reads the words. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector(".cv-countdown__digits")).toHaveTextContent("0:20");
    await expect(within(canvasElement).getByText("20 seconds")).toBeTruthy();
    await expect(within(canvasElement).getByRole("status")).toBeEmptyDOMElement();
  },
};

/** Under the 10 s threshold: the number alone carries it (J1 (b)); no colour step, no glyph yet. */
export const UnderThreshold: Story = { args: { expiresAt: T0 + 9_000 } };

/** Expired: the host's outcome replaces the countdown (SCR-076 cancels and closes). */
export const Expired: Story = {
  render: function ExpiredHost(args) {
    const [cancelled, setCancelled] = useState(false);
    return cancelled ? (
      <Text variant="caption" tone="secondary">
        Order cancelled: the confirmation timed out.
      </Text>
    ) : (
      <Text variant="caption" tone="secondary">
        Cancels in <Countdown {...args} onExpire={() => setCancelled(true)} />
      </Text>
    );
  },
  args: { expiresAt: T0 - 1_000 },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText(/Order cancelled/)).toBeTruthy();
  },
};

/** E24-D02's funding clock. */
export const HhMmSs: Story = {
  args: { format: "hh:mm:ss", expiresAt: T0 + 28_692_000 },
  render: (args) => (
    <Text variant="caption" tone="secondary">
      Funding in <Countdown {...args} />
    </Text>
  ),
};

/** E39-D02: the absolute time first, the relative count second. */
export const Words: Story = {
  args: { format: "words", expiresAt: T0 + 35_880_000 },
  render: (args) => (
    <Text variant="caption" tone="secondary">
      until 00:00 UTC, in <Countdown {...args} />
    </Text>
  ),
};

/** E17-D02's retry: "Next try in ~4 s". */
export const Approx: Story = {
  args: { format: "approx", expiresAt: T0 + 4_000 },
  render: (args) => (
    <Text variant="caption" tone="secondary">
      Next try in <Countdown {...args} />
    </Text>
  ),
};

/** A SCR-100 "Funding in" cell: same digits, no status region, no announcement at any threshold. */
export const InGrid: Story = {
  args: { format: "hh:mm:ss", expiresAt: T0 + 7_200_000, thresholds: [] },
  render: (args) => (
    <table>
      <thead>
        <tr>
          <th scope="col">Symbol</th>
          <th scope="col">Funding in</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>BTCUSDT</td>
          <td>
            <Countdown {...args} />
          </td>
        </tr>
      </tbody>
    </table>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("status")).toBeNull();
  },
};

/** The real clock: one tick a second, and the 10 s and 0 s thresholds speak once each. */
export const Live: Story = {
  render: function LiveHost(args) {
    const [expiresAt] = useState(() => Date.now() + 15_000);
    return (
      <Text variant="caption" tone="secondary">
        Cancels in{" "}
        <Countdown
          {...args}
          now={Date.now}
          expiresAt={expiresAt}
          announce={(s) =>
            s === 0 ? "Confirmation cancelled" : `${s} seconds until this confirmation cancels`
          }
        />
      </Text>
    );
  },
};

const All: Story = {
  render: () => (
    <div style={col}>
      <Text variant="caption" tone="secondary">
        Cancels in <Countdown expiresAt={T0 + 20_000} now={frozen} />
      </Text>
      <Text variant="caption" tone="secondary">
        Funding in <Countdown expiresAt={T0 + 28_692_000} now={frozen} format="hh:mm:ss" />
      </Text>
      <Text variant="caption" tone="secondary">
        Next try in <Countdown expiresAt={T0 + 4_000} now={frozen} format="approx" />
      </Text>
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
export const Light: Story = themed("light");
export const HighContrast: Story = themed("high-contrast");
