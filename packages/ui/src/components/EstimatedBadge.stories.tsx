import type { Meta, StoryObj } from "@storybook/react-vite";
import { Component, type JSX, type ReactNode } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { Callout } from "./Callout.js";
import { FreshnessMarker } from "./FreshnessMarker.js";
import {
  EstimatedBadge,
  EstimatedMethodologyProvider,
  type EstimatedBadgeProps,
} from "./EstimatedBadge.js";

const SENTENCE =
  "The rate accruing for the next settlement; it can still move until then. Bybit publishes no separate predicted rate.";
const opened = fn();

const meta: Meta<typeof EstimatedBadge> = {
  title: "Atoms/EstimatedBadge",
  component: EstimatedBadge,
  args: { detector: "funding", variant: "inline", size: "sm", tooltip: SENTENCE },
  decorators: [
    (Story) => (
      <EstimatedMethodologyProvider openMethodology={opened}>
        <Story />
      </EstimatedMethodologyProvider>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof EstimatedBadge>;

const row = { display: "flex", gap: "var(--space-inset-sm)", alignItems: "center" } as const;
const badge = (props: Partial<EstimatedBadgeProps>): JSX.Element => (
  <EstimatedBadge detector="funding" variant="inline" size="sm" {...props} />
);

export const Inline: Story = {};
export const Marker: Story = { args: { variant: "marker" } };
export const Section: Story = { args: { variant: "section", size: "md" } };
export const SizeSm: Story = { args: { size: "sm" } };
export const SizeMd: Story = { args: { size: "md" } };
export const WithConfidenceWord: Story = { args: { confidence: "low" } };
export const LongDetectorName: Story = {
  args: {
    detector: "liquidation_cluster",
    name: "Liquidation cluster across every tracked account",
  },
};

const button = (canvasElement: HTMLElement): HTMLElement =>
  within(canvasElement).getByRole("button", { name: /Estimated/ });

export const Hover: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.hover(button(canvasElement));
    await expect(button(canvasElement)).toBeVisible();
  },
};

export const FocusVisible: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(button(canvasElement)).toHaveFocus();
  },
};

/** The pressed state: the pointer is down and not yet released. */
export const Active: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.pointer({ keys: "[MouseLeft>]", target: button(canvasElement) });
    await expect(button(canvasElement)).toBeVisible();
  },
};

export const TooltipOpen: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(button(canvasElement)).toHaveAccessibleDescription(SENTENCE);
  },
};

/** `Enter` opens the methodology through the provider, passing the badge as the focus-return target. */
export const Opens: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    await expect(opened).toHaveBeenCalledWith("funding", button(canvasElement));
    await expect(button(canvasElement)).toHaveAttribute("aria-haspopup", "dialog");
  },
};

/** CMP-227 renders first and CMP-239 right after it, each with its own accessible name (E08-D04). */
export const WithStaleFreshnessMarker: Story = {
  render: (args) => (
    <span style={{ ...row, gap: "var(--space-inset-xs)" }}>
      <EstimatedBadge {...args} />
      <FreshnessMarker presentation="compact" state="stale" lastUpdatedAgeMs={4000} />
    </span>
  ),
};

/** The decision-point callout is a composition: CMP-028 `info` with an inline badge, not a fourth variant. */
export const CalloutComposition: Story = {
  render: (args) => (
    <Callout tone="info" title="This is an estimate, not exchange-provided fact.">
      <EstimatedBadge {...args} />
    </Callout>
  ),
};

const gallery = (filter?: string): JSX.Element => (
  <div style={{ ...row, ...(filter === undefined ? {} : { filter }) }}>
    {badge({})}
    {badge({ size: "md", variant: "section" })}
    {badge({ variant: "marker" })}
  </div>
);

/** Greyscale: the word and the dashed edge remain. */
export const Greyscale: Story = { render: () => gallery("grayscale(1)") };

const themed = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: () => gallery(),
});
/** The high-contrast theme, through the toolbar global (forced-colours edges are the CSS contract's). */
export const HighContrast: Story = themed("high-contrast");
export const LightTheme: Story = themed("light");

/** The badge has no motion: its look is the same with `prefers-reduced-motion`. */
export const ReducedMotion: Story = {
  render: () => gallery(),
};

class Boundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  override state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error): { error: Error } {
    return { error };
  }
  override render(): ReactNode {
    return this.state.error === null ? (
      this.props.children
    ) : (
      <p role="alert">{this.state.error.message}</p>
    );
  }
}

/** Outside the provider the badge throws `EstimatedBadgeOutsideProviderError`; it never renders a bare chip. */
export const OutsideProviderThrows: Story = {
  decorators: [
    (Story) => (
      <Boundary>
        <Story />
      </Boundary>
    ),
  ],
  render: () => <EstimatedBadge detector="funding" variant="inline" size="sm" />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("alert")).toHaveTextContent(
      "EstimatedBadge needs an EstimatedMethodologyProvider",
    );
  },
};
