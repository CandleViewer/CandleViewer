import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { Button } from "./Button.js";
import { FilterBar } from "./FilterBar.js";

/** The bar as a host drives it: each remove drops its chip, "Clear all" drops every one. */
function Bar({
  initial,
  clearable = true,
  withAdd = true,
}: {
  readonly initial: readonly string[];
  readonly clearable?: boolean;
  readonly withAdd?: boolean;
}): JSX.Element {
  const [labels, setLabels] = useState(initial);
  return (
    <FilterBar
      filters={labels.map((label) => ({
        id: label,
        label,
        onRemove: () => setLabels((all) => all.filter((l) => l !== label)),
      }))}
      {...(clearable ? { onClearAll: () => setLabels([]) } : {})}
      {...(withAdd ? { addFilter: <Button iconLeft="plus">Filter</Button> } : {})}
    />
  );
}

/** E29-D02 board 11's chips. */
const BOARD = ["Account: Sub-1", "Symbol: BTCUSDT"];

const meta: Meta<typeof FilterBar> = {
  title: "Molecules/FilterBar",
  component: FilterBar,
  render: () => <Bar initial={BOARD} />,
};
export default meta;
type Story = StoryObj<typeof FilterBar>;

const bar = (canvas: HTMLElement) => within(canvas).getByRole("group", { name: "Active filters" });
const remove = (canvas: HTMLElement, label: string): HTMLElement =>
  within(canvas).getByRole("button", { name: `Remove filter ${label}` });

/** No filter yet: the group holds only the add control. */
export const Empty: Story = {
  render: () => <Bar initial={[]} />,
  play: async ({ canvasElement }) => {
    await expect(within(bar(canvasElement)).getByRole("button", { name: "Filter" })).toBeVisible();
    await expect(within(canvasElement).queryByRole("button", { name: "Clear all" })).toBeNull();
  },
};

/** One chip: "Clear all" waits for a second (E29-D04 §2.8.5). */
export const OneFilter: Story = {
  render: () => <Bar initial={["Account: Sub-1"]} />,
  play: async ({ canvasElement }) => {
    await expect(remove(canvasElement, "Account: Sub-1")).toBeVisible();
    await expect(within(canvasElement).queryByRole("button", { name: "Clear all" })).toBeNull();
  },
};

/** Board 11: two chips, "+ Filter", then "Clear all". */
export const WithFilters: Story = {
  play: async ({ canvasElement }) => {
    const group = bar(canvasElement);
    for (const label of BOARD) await expect(within(group).getByText(label)).toBeVisible();
    await expect(within(group).getByRole("button", { name: "Clear all" })).toBeVisible();
  },
};

/** Each chip's remove is the only stop in it; this one shows the ring. */
export const RemoveFocusVisible: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(remove(canvasElement, "Account: Sub-1")).toHaveFocus();
  },
};

export const RemoveHover: Story = {
  play: async ({ canvasElement }) => userEvent.hover(remove(canvasElement, "Symbol: BTCUSDT")),
};

/** The hand-off: a removed chip passes focus to the next remove, the last one to the add control. */
export const KeyboardRemove: Story = {
  render: () => <Bar initial={["Account: Sub-1", "Symbol: BTCUSDT", "Side: Long"]} />,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(remove(canvasElement, "Account: Sub-1")).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(remove(canvasElement, "Symbol: BTCUSDT")).toHaveFocus());
    await userEvent.keyboard(" ");
    await waitFor(() => expect(remove(canvasElement, "Side: Long")).toHaveFocus());
    await userEvent.keyboard("{Enter}");
    await waitFor(() =>
      expect(within(canvasElement).getByRole("button", { name: "Filter" })).toHaveFocus(),
    );
  },
};

/** "Clear all" drops every chip and hands focus to the add control. */
export const ClearAll: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Clear all" }));
    await waitFor(() =>
      expect(within(canvasElement).getByRole("button", { name: "Filter" })).toHaveFocus(),
    );
    await expect(
      within(canvasElement).queryByRole("button", { name: /^Remove filter/ }),
    ).toBeNull();
  },
};

/** No add control: the last chip's removal leaves focus on the group, never on the body. */
export const NoAddControl: Story = {
  render: () => <Bar initial={["Account: Sub-1"]} withAdd={false} clearable={false} />,
  play: async ({ canvasElement }) => {
    await userEvent.click(remove(canvasElement, "Account: Sub-1"));
    await waitFor(() => expect(bar(canvasElement)).toHaveFocus());
  },
};

/** E29-D02 D-8's long fixtures (a 24-character account label, "10000SATSUSDT"): the chips wrap, a remove keeps the full name. */
export const LongText: Story = {
  render: () => (
    <div style={{ width: "20rem" }}>
      <Bar
        initial={["Account: Desk 4 swing book London", "Symbol: 10000SATSUSDT", "Side: Short"]}
      />
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(remove(canvasElement, "Account: Desk 4 swing book London")).toBeVisible();
  },
};

/** The bar under the light and high-contrast themes; axe checks each theme. */
const themeMatrix = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
});
export const ContrastLight: Story = themeMatrix("light");
export const ContrastHighContrast: Story = themeMatrix("high-contrast");
