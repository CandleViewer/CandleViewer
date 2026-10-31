import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import type { DensityName } from "../theme/store.js";
import { DENSITY_TOGGLE_COPY, DensityToggle, DensityToggleConnected } from "./DensityToggle.js";

/** Theme and density come from the toolbars; every story renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof DensityToggle> = {
  title: "Molecules/DensityToggle",
  component: DensityToggle,
};
export default meta;
type Story = StoryObj<typeof DensityToggle>;

const col = { display: "grid", gap: "var(--space-inset-lg)", justifyItems: "start" } as const;
const LONG_PANEL = "Order book and recent trades for BTCUSDT perpetual";

/** A host that keeps a global value, as SCR-116's form does (it never reads the store). */
function GlobalHost({
  initial = "compact",
  onChange,
}: {
  initial?: DensityName;
  onChange?: (v: DensityName) => void;
}): JSX.Element {
  const [value, setValue] = useState<DensityName>(initial);
  return (
    <DensityToggle
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange?.(next);
      }}
    />
  );
}

/** A panel's override: the host keeps it per panel, with the runtime's two densities (BQ-19). */
function Panel({
  name,
  initial = "compact",
}: {
  name: string;
  initial?: DensityName;
}): JSX.Element {
  const [value, setValue] = useState<DensityName>(initial);
  return <DensityToggle scope="panel" panelName={name} value={value} onChange={setValue} />;
}

const live = (): string => document.getElementById("cv-theme-live-region")?.textContent ?? "";

/** Cell "global": Compact · Comfortable on SCR-116, Compact checked. */
export const Global: Story = {
  render: () => <GlobalHost />,
  play: async ({ canvasElement }) => {
    const group = within(canvasElement).getByRole("radiogroup", { name: "Density" });
    await expect(within(group).getAllByRole("radio")).toHaveLength(2);
    await expect(within(group).getByRole("radio", { name: "Compact" })).toBeChecked();
  },
};

/** Cell "comfortable": Comfortable checked, the control itself at comfortable density. */
export const Comfortable: Story = {
  render: () => <DensityToggle value="comfortable" onChange={fn()} density="comfortable" />,
};

/** Cell "panel": a per-panel override, the panel's name in the group's name and the sentence (J16). */
export const PanelOverride: Story = {
  render: () => <Panel name="Order book" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("radio", { name: "Comfortable" }));
    await waitFor(() => expect(live()).toBe("Order book density: comfortable"));
    await expect(canvas.getByRole("radiogroup", { name: "Order book density" })).toBeVisible();
  },
};

/** A chart panel offers the same two densities: J14's Dense is slice H's reconcile row (BQ-19). */
export const ChartPanel: Story = {
  render: () => <Panel name="Chart panel" initial="comfortable" />,
  play: async ({ canvasElement }) => {
    const group = within(canvasElement).getByRole("radiogroup", { name: "Chart panel density" });
    await expect(within(group).getAllByRole("radio")).toHaveLength(2);
    await expect(within(group).getByRole("radio", { name: "Comfortable" })).toBeChecked();
  },
};

/** Cell "focus-visible": the CMP-039 ring on the checked segment. */
export const FocusVisible: Story = {
  render: () => <GlobalHost initial="comfortable" />,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(within(canvasElement).getByRole("radio", { name: "Comfortable" })).toHaveFocus();
  },
};

export const Hover: Story = {
  render: () => <GlobalHost />,
  play: async ({ canvasElement }) =>
    userEvent.hover(within(canvasElement).getByRole("radio", { name: "Comfortable" })),
};

/** CMP-003's own disabled state, passed through: no reason form and no lock. */
export const Disabled: Story = {
  render: () => <DensityToggle value="compact" onChange={fn()} disabled />,
};

/** J16: each arrow is a committed change; the region's text is replaced, so a run speaks its last value. */
export const KeyboardCommits: Story = {
  render: () => <Panel name="Chart panel" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.tab();
    await userEvent.keyboard("{ArrowRight}");
    await expect(canvas.getByRole("radio", { name: "Comfortable" })).toHaveFocus();
    await waitFor(() => expect(live()).toBe("Chart panel density: comfortable"));
  },
};

/** The long-text case: a long panel name wraps in the sentence, never in the segments. */
export const LongPanelName: Story = {
  render: () => <Panel name={LONG_PANEL} />,
};

/** Bound to the theme runtime: a pick re-points the whole page (the toolbar's store) in one frame. */
export const Connected: Story = {
  render: () => <DensityToggleConnected />,
  play: async ({ canvasElement }) => {
    const radio = within(canvasElement).getByRole("radio", { name: "Comfortable" });
    await userEvent.click(radio);
    await waitFor(() =>
      expect(document.documentElement).toHaveAttribute("data-density", "comfortable"),
    );
    await expect(radio).toBeChecked();
  },
};

/** Every drawn cell side by side (spec matrix), plus the copy override. */
export const AllStates: Story = {
  render: () => (
    <div style={col}>
      <GlobalHost />
      <DensityToggle value="comfortable" onChange={fn()} density="comfortable" />
      <Panel name="Order book" />
      <Panel name="Chart panel" initial="comfortable" />
      <DensityToggle value="compact" onChange={fn()} disabled />
      <DensityToggle value="compact" onChange={fn()} size="sm" />
      <Panel name={LONG_PANEL} />
      <DensityToggle
        value="compact"
        onChange={fn()}
        copy={{ groupLabel: "Interface density", options: { ...DENSITY_TOGGLE_COPY.options } }}
      />
    </div>
  ),
};

/** Reduced motion: the density swap is a cut either way; axe runs with the override on. */
export const ReducedMotion: Story = {
  globals: { motion: "on" },
  render: () => <Panel name="Chart panel" />,
  play: async () => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-motion", "reduce"));
  },
};
