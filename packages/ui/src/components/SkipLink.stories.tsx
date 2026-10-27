import type { Meta, StoryObj } from "@storybook/react-vite";
import type { CSSProperties, JSX } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { SKIP_LINK_COPY, SkipLink, type SkipLinkTarget } from "./SkipLink.js";

/** Theme and density come from the toolbars; every story renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof SkipLink> = {
  title: "Atoms/SkipLink",
  component: SkipLink,
};
export default meta;
type Story = StoryObj<typeof SkipLink>;

const frame: CSSProperties = {
  position: "relative",
  display: "grid",
  gap: "var(--space-inset-sm)",
  paddingTop: "calc(var(--size-control-height) + var(--space-inset-sm))",
  color: "var(--color-text-primary)",
};
const region: CSSProperties = { padding: "var(--space-inset-sm)" };

/** A stand-in page: the links first, a TopBar control, then the regions they skip to. */
function Page({ prefix, several }: { prefix: string; several: boolean }): JSX.Element {
  const main: SkipLinkTarget = { id: `${prefix}-main`, label: SKIP_LINK_COPY.main };
  const ticket: SkipLinkTarget = { id: `${prefix}-ticket`, label: SKIP_LINK_COPY.orderTicket };
  const chart: SkipLinkTarget = { id: `${prefix}-chart`, label: SKIP_LINK_COPY.chart };
  return (
    <div style={frame}>
      <SkipLink targets={several ? [main, ticket, chart] : [main]} />
      <header>
        <button type="button">Workspace menu</button>
      </header>
      <main id={main.id} style={region}>
        <h1>Workspace</h1>
        {several && (
          <>
            <section id={ticket.id} aria-label="Order ticket" style={region}>
              <button type="button">Buy</button>
            </section>
            <section id={chart.id} aria-label="Chart" style={region}>
              <button type="button">Zoom in</button>
            </section>
          </>
        )}
        <button type="button">After the target</button>
      </main>
    </div>
  );
}

const link = (canvas: HTMLElement, name: string = SKIP_LINK_COPY.main): HTMLElement =>
  within(canvas).getByRole("link", { name });

/** Hidden: in the Tab order and the tree, clipped to nothing until focused. */
export const Unfocused: Story = {
  render: () => <Page prefix="unfocused" several={false} />,
  play: async ({ canvasElement }) => {
    const a = link(canvasElement);
    await expect(a).toHaveAttribute("href", "#unfocused-main");
    await expect(a.getBoundingClientRect().width).toBeLessThanOrEqual(1);
  },
};

/** The first Tab shows the pill; Enter focuses main; the next Tab continues from it (J20). */
export const Focused: Story = {
  render: () => <Page prefix="focused" several={false} />,
  play: async ({ canvasElement }) => {
    const a = link(canvasElement);
    await userEvent.tab();
    await expect(a).toHaveFocus();
    const { width, height } = a.getBoundingClientRect();
    await expect(width).toBeGreaterThan(1);
    await expect(height).toBeGreaterThanOrEqual(24);
    // Leave the pill shown for the visual and axe passes: the activation is FocusedThenEnter.
  },
};

export const FocusedThenEnter: Story = {
  render: () => <Page prefix="enter" several={false} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    const main = canvas.getByRole("main");
    await expect(main).toHaveFocus();
    await expect(main).toHaveAttribute("tabindex", "-1");
    await userEvent.tab();
    await expect(canvas.getByRole("button", { name: "After the target" })).toHaveFocus();
    await expect(main).not.toHaveAttribute("tabindex");
  },
};

/** Main content first, then one link per mounted region, each shown only while focused (J19). */
export const Several: Story = {
  render: () => <Page prefix="several" several />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.tab();
    await expect(link(canvasElement)).toHaveFocus();
    await userEvent.tab();
    await userEvent.tab();
    const chartLink = link(canvasElement, SKIP_LINK_COPY.chart);
    await expect(chartLink).toHaveFocus();
    await expect(link(canvasElement).getBoundingClientRect().width).toBeLessThanOrEqual(1);
    await userEvent.keyboard("{Enter}");
    await expect(canvas.getByRole("region", { name: "Chart" })).toHaveFocus();
    await userEvent.tab();
    await expect(canvas.getByRole("button", { name: "Zoom in" })).toHaveFocus();
  },
};

/** Reduced motion: the pill appears as a cut either way; axe runs with the override on. */
export const FocusedReducedMotion: Story = {
  globals: { motion: "on" },
  render: () => <Page prefix="reduced" several={false} />,
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-motion", "reduce"));
    await userEvent.tab();
    await expect(link(canvasElement)).toHaveFocus();
  },
};
