import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { FilterBar, type FilterBarFilter, type FilterBarProps } from "./FilterBar.js";
import { formatRbacReason } from "./rbacReasons.js";

const options = (...labels: string[]) =>
  labels.map((label) => ({ value: label.toLowerCase(), label }));
/** E16-D02 §1's filter row (SCR-140): Reason, State, Pinned and Needs attention, each with its values (BQ-10). */
const FIELDS = [
  { id: "reason", label: "Reason", options: options("Manual", "Auto") },
  { id: "state", label: "State", options: options("Recording", "Degraded", "Write gate closed") },
  { id: "pinned", label: "Pinned", options: options("Yes", "No") },
  { id: "attention", label: "Needs attention", options: options("Yes", "No") },
];
const AUTO = { field: "reason", value: "auto" };
const DEGRADED = { field: "state", value: "degraded" };
const PINNED = { field: "pinned", value: "yes" };
/** E09-D09 §3.1's `rbac.owner_only` with `recording:write`'s verb (E16-D02 §10.5). */
const REASON = formatRbacReason("rbac.owner_only", { verb: "change recording" });

type DemoProps = Partial<FilterBarProps> & {
  readonly initial?: readonly FilterBarFilter[];
  /** A narrow wrapper (R1), or room below the bar for the menu and its submenu. */
  readonly maxWidth?: string;
  readonly minHeight?: string;
};

/** The host owns the list, as a screen does; the wrapper carries the DS type. */
function Demo({ initial = [], maxWidth, minHeight, ...props }: DemoProps): JSX.Element {
  const [value, setValue] = useState(initial);
  const font =
    "var(--type-ui-body-font-weight) var(--type-ui-body-font-size) / var(--type-ui-body-line-height) var(--type-ui-body-font-family)";
  return (
    <div style={{ font, color: "var(--color-text-primary)", maxWidth, minHeight }}>
      <FilterBar fields={FIELDS} value={value} onChange={setValue} {...props} />
    </div>
  );
}

/** Theme and density come from the toolbars; the light and high-contrast stories pin the theme for axe. */
const meta: Meta = {
  title: "Molecules/FilterBar",
  component: FilterBar,
  render: () => <Demo initial={[AUTO, DEGRADED]} />,
};
export default meta;
type Story = StoryObj;

const bar = (canvas: HTMLElement): ReturnType<typeof within> =>
  within(within(canvas).getByRole("group", { name: "Active filters" }));

/** E16-D02 §1: the summary's link applied "Reason: Auto"; one chip, so no Clear all. */
export const WithFilters: Story = {
  render: () => <Demo initial={[AUTO]} />,
  play: async ({ canvasElement }) => {
    await expect(
      bar(canvasElement).getByRole("button", { name: "Remove Reason: Auto" }),
    ).toBeVisible();
    await expect(bar(canvasElement).queryByRole("button", { name: "Clear all" })).toBeNull();
  },
};

/** No filter: the line says so; Add filter is the one control. */
export const Empty: Story = {
  render: () => <Demo />,
  play: async ({ canvasElement }) =>
    expect(bar(canvasElement).getByText("No filters")).toBeVisible(),
};

/** Two chips or more: Clear all follows Add filter. */
export const SeveralFilters: Story = {
  render: () => <Demo initial={[AUTO, DEGRADED, PINNED]} />,
  play: async ({ canvasElement }) =>
    expect(bar(canvasElement).getByRole("button", { name: "Clear all" })).toBeVisible(),
};

/** Add filter open on State's value submenu: the applied value is a checked `menuitemcheckbox`. */
export const AddFilterMenu: Story = {
  render: () => <Demo initial={[AUTO, DEGRADED]} minHeight="20rem" />,
  play: async ({ canvasElement }) => {
    bar(canvasElement).getByRole("button", { name: "Add filter" }).focus();
    await userEvent.keyboard("{Enter}{ArrowDown}{ArrowRight}");
    const values = within(document.body).getByRole("menu", { name: "State" });
    await waitFor(() => expect(values).toHaveAttribute("data-positioned"));
    const degraded = within(values).getByRole("menuitemcheckbox", { name: "Degraded" });
    await expect(degraded).toHaveAttribute("aria-checked", "true");
  },
};

/**
 * T2 (E09-D09 §2.2): every control focusable, `aria-disabled`, described by the reason; Add filter and Clear all
 * lead with the named lock (2a), each remove carries the lock badge and its echo (2b); the reason is drawn once.
 */
export const ReadOnly: Story = {
  render: () => <Demo initial={[AUTO, DEGRADED]} writeReason={REASON} />,
  play: async ({ canvasElement }) => {
    const add = bar(canvasElement).getByRole("button", { name: "Not available Add filter" });
    await expect(add).toHaveAttribute("aria-disabled", "true");
    await expect(add).toHaveAccessibleDescription(REASON);
  },
};

/** Narrow (R1): the chips wrap to as many rows as they need, then Add filter and Clear all; nothing is clipped. */
export const Narrow: Story = {
  render: () => (
    <Demo
      initial={[AUTO, { field: "state", value: "write gate closed" }, PINNED]}
      maxWidth="14rem"
    />
  ),
  play: async ({ canvasElement }) =>
    expect(bar(canvasElement).getByText("State: Write gate closed")).toBeVisible(),
};

/** The pointer on Add filter (CMP-001 secondary's hover fill). */
export const Hover: Story = {
  play: async ({ canvasElement }) =>
    userEvent.hover(bar(canvasElement).getByRole("button", { name: "Add filter" })),
};

/** The keyboard on the first chip's remove: its ring on clear fill (CMP-011 E7). */
export const FocusVisible: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(
      bar(canvasElement).getByRole("button", { name: "Remove Reason: Auto" }),
    ).toHaveFocus();
  },
};

/** The light and high-contrast themes, filtered and read-only; axe checks each theme. */
const themed = (theme: "light" | "high-contrast"): Story => ({
  globals: { theme },
  render: () => (
    <>
      <Demo initial={[AUTO, DEGRADED]} />
      <Demo initial={[AUTO, DEGRADED]} writeReason={REASON} />
    </>
  ),
  // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
  play: async () =>
    waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme)),
});
export const ContrastLight: Story = themed("light");
export const ContrastHighContrast: Story = themed("high-contrast");
