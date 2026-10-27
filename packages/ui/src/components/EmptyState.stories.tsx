import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { EmptyState } from "./EmptyState.js";
import { ProgressBar } from "./ProgressBar.js";

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof EmptyState> = {
  title: "Atoms/EmptyState",
  component: EmptyState,
  args: {
    variant: "no-data",
    title: "No rules yet",
    description: "Start from a template.",
  },
};
export default meta;
type Story = StoryObj<typeof EmptyState>;

const col = { display: "grid", gap: "var(--space-stack-md)", maxWidth: "40rem" } as const;

/** The no-data cell: the fact, its sentence and one primary CTA. */
export const Default: Story = {
  args: { cta: { label: "Browse templates", onClick: fn() } },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { level: 3, name: "No rules yet" })).toBeVisible();
    await userEvent.tab();
    await expect(canvas.getByRole("button", { name: "Browse templates" })).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await expect(args.cta?.onClick).toHaveBeenCalledTimes(1);
  },
};

/** The CTA's ring, drawn by the nested CMP-001. */
export const FocusVisible: Story = {
  args: { cta: { label: "Browse templates", onClick: fn() } },
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(
      within(canvasElement).getByRole("button", { name: "Browse templates" }),
    ).toHaveFocus();
  },
};

/** Recording not started: the owner's CTA to the recorder and the one secondary link (H13). */
export const RecordingNotStarted: Story = {
  args: {
    variant: "recording-not-started",
    title: "History starts 12 Oct 14:02 UTC",
    description: "Recording began then; earlier bars are not stored.",
    cta: { label: "Open the recorder", onClick: fn() },
    link: { label: "Show coverage", href: "#coverage" },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.tab();
    await userEvent.tab();
    await expect(canvas.getByRole("link", { name: "Show coverage" })).toHaveFocus();
  },
};

/** Backfill: informational, never danger, with the host's determinate CMP-023. */
export const BackfillInProgress: Story = {
  args: {
    variant: "backfill-in-progress",
    title: "Loading history",
    description: "Recorded coverage is catching up.",
    progress: <ProgressBar label="History" value={33} valueText="page 3 of ~9" />,
  },
};

/** Filtered-empty: the `search` glyph and a "Clear filters" CTA. */
export const FilteredEmpty: Story = {
  args: {
    variant: "filtered-empty",
    title: "No rows match",
    description: "Filters: Bid-stacked, Delta negative.",
    cta: { label: "Clear filters", onClick: fn() },
  },
};

/** The error variant is CMP-027's panel, polite: an in-panel load failure is met where the user looks. */
export const ErrorVariant: Story = {
  args: {
    variant: "error",
    title: "Couldn't load users",
    description: "The store is unavailable.",
    cta: { label: "Retry", onClick: fn() },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("status")).toHaveTextContent("The store is unavailable.");
    await expect(canvas.queryByRole("alert")).toBeNull();
    await expect(canvas.getByRole("button", { name: "Retry" })).toBeVisible();
  },
};

/** The sentence form (E09-D09 §8): the sole CTA is gated, so the host's reason replaces it; no button. */
export const SentenceForm: Story = {
  args: {
    title: "No rules yet",
    description: "Your role can't change rules.",
  },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button")).toBeNull();
  },
};

/** The five variants and both sentence cells, at heading level 2. */
export const AllVariants: Story = {
  render: () => (
    <div style={col}>
      <EmptyState
        headingLevel={2}
        title="No rules yet"
        description="Start from a template."
        cta={{ label: "Browse templates", onClick: fn() }}
      />
      <EmptyState
        headingLevel={2}
        variant="recording-not-started"
        title="History starts 12 Oct 14:02 UTC"
        description="Recording began then; earlier bars are not stored."
        cta={{ label: "Open the recorder", onClick: fn() }}
        link={{ label: "Show coverage", href: "#coverage" }}
      />
      <EmptyState
        headingLevel={2}
        variant="recording-not-started"
        title="History starts 12 Oct 14:02 UTC"
        description="Only the owner can start recording."
      />
      <EmptyState
        headingLevel={2}
        variant="backfill-in-progress"
        title="Loading history"
        progress={<ProgressBar label="History" value={33} valueText="page 3 of ~9" />}
      />
      <EmptyState
        headingLevel={2}
        variant="filtered-empty"
        title="No rows match"
        description="Filters: Bid-stacked, Delta negative."
        cta={{ label: "Clear filters", onClick: fn() }}
      />
      <EmptyState
        headingLevel={2}
        variant="error"
        title="Couldn't load users"
        description="The store is unavailable."
        cta={{ label: "Retry", onClick: fn() }}
      />
    </div>
  ),
};

/** Long words wrap; nothing truncates. */
export const LongText: Story = {
  render: () => (
    <div style={{ width: "16rem" }}>
      <EmptyState
        variant="filtered-empty"
        title="No rows match BTCUSDT-PERPETUAL-LINEAR-DEMO-ACCOUNT-SUBACCOUNT-7"
        description="Filters: Bid-stacked, Delta negative, Absorption above 2.5, Session Asia, Venue Bybit."
        cta={{ label: "Clear every filter in this panel", onClick: fn() }}
        link={{ label: "How filters combine", href: "#filters" }}
      />
    </div>
  ),
};

/** Every variant under the light and high-contrast themes; axe checks each theme. */
const themeMatrix = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: () => (
    <div style={col}>
      <EmptyState
        title="No rules yet"
        description="Start from a template."
        cta={{ label: "Browse templates", onClick: fn() }}
        link={{ label: "Learn more", href: "#rules" }}
      />
      <EmptyState
        variant="filtered-empty"
        title="No rows match"
        description="Filters: Bid-stacked."
      />
      <EmptyState
        variant="error"
        title="Couldn't load users"
        description="The store is unavailable."
        cta={{ label: "Retry", onClick: fn() }}
      />
    </div>
  ),
});
export const ContrastLight: Story = themeMatrix("light");
export const ContrastHighContrast: Story = themeMatrix("high-contrast");
