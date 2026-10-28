import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { Button } from "./Button.js";
import { InfoPanel, type InfoPanelProps, type InfoPanelTriggerProps } from "./InfoPanel.js";
import { Link } from "./Link.js";

const column = { display: "flex", flexDirection: "column", gap: "var(--space-stack-sm)" } as const;

/** The CMP-227 chip's stand-in until it ships: a CMP-001 ghost button spreading the trigger props. */
const chip = (props: InfoPanelTriggerProps): JSX.Element => (
  <Button variant="ghost" size="sm" {...props}>
    Estimated
  </Button>
);

const methodology = (
  <>
    <p style={{ margin: 0 }}>
      An iceberg is a resting order that shows only part of its size: the level refills after each
      print at the same price.
    </p>
    <p style={{ margin: 0 }}>
      Technical detail: a refill counts when the visible size returns within the window after a
      trade at the level, at least three times in a row.
    </p>
    <Link href="#methodology">Read the full methodology</Link>
  </>
);
const values = <p style={{ margin: 0 }}>Refill window: 250 ms. Minimum refills: 3.</p>;

type DemoProps = Partial<Omit<InfoPanelProps, "trigger">>;

/** A value row with its chip, and a page control after it (the non-modal Tab path lands there). */
function Demo(props: DemoProps): JSX.Element {
  return (
    <div style={column}>
      <p style={{ margin: 0 }}>Iceberg at 65,430</p>
      <InfoPanel
        title="Iceberg detector"
        content={methodology}
        values={values}
        relatedDetector="iceberg"
        trigger={chip}
        {...props}
      />
      <Button variant="ghost">Next control</Button>
    </div>
  );
}

const meta: Meta = {
  title: "Molecules/InfoPanel",
  component: InfoPanel,
  render: () => <Demo />,
};
export default meta;
type Story = StoryObj;

const page = within(document.body);
const pressTrigger = async (canvas: HTMLElement, keyName = "{Enter}"): Promise<HTMLElement> => {
  const trigger = within(canvas).getByRole("button", { name: "Estimated" });
  trigger.focus();
  await userEvent.keyboard(keyName);
  return trigger;
};

/** Variant=drawer, State=open (J18): Enter on the chip opens it, focus on the heading, Esc back to the chip. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const trigger = await pressTrigger(canvasElement);
    const drawer = await page.findByRole("dialog", { name: "Iceberg detector" });
    await expect(drawer).not.toHaveAttribute("aria-modal");
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    await expect(within(drawer).getByRole("heading", { name: "Iceberg detector" })).toHaveFocus();
    // Tab past its last control leaves it open.
    within(drawer).getByRole("link", { name: "Read the full methodology" }).focus();
    await userEvent.tab();
    await expect(within(canvasElement).getByRole("button", { name: "Next control" })).toHaveFocus();
    await expect(drawer).toBeVisible();
    within(drawer).getByRole("heading", { name: "Iceberg detector" }).focus();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(document.querySelector(".cv-drawer-layer")).toBeNull());
    await expect(trigger).toHaveFocus();
    // Space opens it too.
    await pressTrigger(canvasElement, " ");
    await page.findByRole("dialog", { name: "Iceberg detector" });
  },
};

/** Variant=inline (J17): an APG Disclosure under its trigger row; Esc inside closes it, focus back. */
export const Inline: Story = {
  render: () => <Demo variant="inline" />,
  play: async ({ canvasElement }) => {
    const trigger = await pressTrigger(canvasElement);
    const region = await within(canvasElement).findByRole("region", { name: "Iceberg detector" });
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    await expect(within(region).getByRole("heading", { name: "Iceberg detector" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    await expect(within(canvasElement).queryByRole("region")).toBeNull();
    await expect(trigger).toHaveFocus();
  },
};

/** Variant=inline, State=collapsed: the trigger with `aria-expanded="false"`; nothing else renders. */
export const InlineCollapsed: Story = {
  render: () => <Demo variant="inline" />,
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole("button", { name: "Estimated" });
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await expect(canvasElement.querySelector('[data-cmp="CMP-069"]')).toBeNull();
  },
};

/** State=loading: the static text at once, CMP-015 rows for the values, `aria-busy` on the body. */
export const Loading: Story = {
  render: () => <Demo defaultOpen loading />,
  play: async () => {
    const drawer = await page.findByRole("dialog", { name: "Iceberg detector" });
    await expect(drawer.querySelector(".cv-drawer__body")).toHaveAttribute("aria-busy", "true");
    await expect(within(drawer).getByRole("link")).toBeVisible();
  },
};

/** State=error: the static text kept; the values replaced by a polite CMP-027 with Retry. */
export const LoadError: Story = {
  name: "Error",
  render: function Render() {
    const [failed, setFailed] = useState(true);
    return (
      <Demo
        defaultOpen
        {...(failed ? { error: "Couldn't load the current values." } : {})}
        onRetry={() => setFailed(false)}
      />
    );
  },
  play: async () => {
    const drawer = await page.findByRole("dialog", { name: "Iceberg detector" });
    await expect(within(drawer).getByRole("status")).toHaveTextContent(
      "Couldn't load the current values.",
    );
    await userEvent.click(within(drawer).getByRole("button", { name: "Retry" }));
    await expect(within(drawer).getByText(/Refill window/)).toBeVisible();
  },
};

/** Inline, loading: `aria-busy` on the region, base-surface rows. */
export const InlineLoading: Story = {
  render: () => <Demo variant="inline" defaultOpen loading />,
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("region", { name: "Iceberg detector" }),
    ).toHaveAttribute("aria-busy", "true");
  },
};

const themed = (theme: string, variant: "drawer" | "inline"): Story => ({
  globals: { theme },
  render: () => <Demo variant={variant} defaultOpen />,
  play: async () => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
});
export const ContrastLight: Story = themed("light", "drawer");
export const ContrastHighContrast: Story = themed("high-contrast", "inline");
