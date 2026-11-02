import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { AccountMultiSelect, type AccountOption } from "./AccountMultiSelect.js";
import { Button } from "./Button.js";
import { FilterBar } from "./FilterBar.js";

/** The fixture accounts (E29-D04 header: Main, Sub-1, Sub-2). */
const OWNER: readonly Pick<AccountOption, "id" | "label">[] = [
  { id: "main", label: "Main" },
  { id: "sub-1", label: "Sub-1" },
  { id: "sub-2", label: "Sub-2" },
];
/** A Manager's assigned accounts only, set server-side (E29-D04 §2.6; board 05 `CMP-105/filter-manager-scope`). */
const MANAGER = OWNER.slice(1);

/** The picker as SCR-063's toolbar drives it: the host holds the chosen ids. */
function Picker({
  accounts = OWNER,
  initial = ["sub-1"],
  defaultOpen = false,
}: {
  readonly accounts?: readonly Pick<AccountOption, "id" | "label">[];
  readonly initial?: readonly string[];
  readonly defaultOpen?: boolean;
}): JSX.Element {
  const [chosen, setChosen] = useState<ReadonlySet<string>>(new Set(initial));
  return (
    <AccountMultiSelect
      mode="account"
      trigger={<Button iconLeft="plus">Filter</Button>}
      accounts={accounts.map((a) => ({ ...a, selected: chosen.has(a.id) }))}
      onToggle={(id) =>
        setChosen((was) => {
          const next = new Set(was);
          if (!next.delete(id)) next.add(id);
          return next;
        })
      }
      onSelectAll={() => setChosen(new Set(accounts.map((a) => a.id)))}
      defaultOpen={defaultOpen}
    />
  );
}

const meta: Meta<typeof AccountMultiSelect> = {
  title: "Trading/AccountMultiSelect",
  component: AccountMultiSelect,
  render: () => <Picker />,
};
export default meta;
type Story = StoryObj<typeof AccountMultiSelect>;

const page = within(document.body);
const option = (name: string): HTMLElement => page.getByRole("option", { name });

/** Closed: the toolbar's "+ Filter" (board 05). */
export const Default: Story = {};

/** Board 05 `CMP-105/filter-picker`: the owner's three accounts, Sub-1 chosen. */
export const FilterPicker: Story = {
  render: () => <Picker defaultOpen />,
  play: async () => {
    const list = await page.findByRole("listbox", { name: "Filter" });
    await expect(list).toHaveAttribute("aria-multiselectable", "true");
    await expect(option("Sub-1")).toHaveAttribute("aria-selected", "true");
    await expect(option("Main")).toHaveAttribute("aria-selected", "false");
    await waitFor(() => expect(list).toHaveFocus());
  },
};

/** Board 05 `CMP-105/filter-manager-scope`: a Manager sees only the assigned accounts; no option is T2. */
export const FilterManagerScope: Story = {
  render: () => <Picker accounts={MANAGER} defaultOpen />,
  play: async () => {
    await page.findByRole("listbox", { name: "Filter" });
    await expect(page.getAllByRole("option").map((o) => o.textContent)).toEqual(["Sub-1", "Sub-2"]);
    await expect(page.queryByRole("option", { name: "Main" })).toBeNull();
    for (const o of page.getAllByRole("option"))
      await expect(o).not.toHaveAttribute("aria-disabled");
  },
};

/** The keyboard path (E29-D04 §2.6): `Alt+↓` opens, `↓` moves, `Space` includes, `Esc` returns to the trigger. */
export const Keyboard: Story = {
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole("button", { name: "Filter" });
    await userEvent.tab();
    await expect(trigger).toHaveFocus();
    await userEvent.keyboard("{Alt>}{ArrowDown}{/Alt}");
    const list = await page.findByRole("listbox", { name: "Filter" });
    await waitFor(() => expect(list).toHaveFocus());
    await userEvent.keyboard("{ArrowDown}");
    await expect(list).toHaveAttribute("aria-activedescendant", option("Sub-2").id);
    await userEvent.keyboard(" ");
    await expect(option("Sub-2")).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(trigger).toHaveFocus());
  },
};

/** Keyboard focus in the list: the active row, Sub-2, in `color.surface.hover` with CMP-039's inset ring. */
export const ActiveOptionFocusVisible: Story = {
  play: async () => {
    await userEvent.tab();
    await userEvent.keyboard("{Alt>}{ArrowDown}{/Alt}");
    const list = await page.findByRole("listbox", { name: "Filter" });
    await waitFor(() => expect(list).toHaveFocus());
    await userEvent.keyboard("{ArrowDown}");
    await expect(list).toHaveAttribute("aria-activedescendant", option("Sub-2").id);
  },
};

/** The pointer on a row makes it the active one. */
export const OptionHover: Story = {
  render: () => <Picker defaultOpen />,
  play: async () => {
    await userEvent.hover(await page.findByRole("option", { name: "Main" }));
    await expect(page.getByRole("listbox")).toHaveAttribute(
      "aria-activedescendant",
      option("Main").id,
    );
  },
};

/** "Select all", a distinct labelled control after the list (`15` CMP-105 A11y). */
export const SelectAll: Story = {
  render: () => <Picker defaultOpen initial={[]} />,
  play: async () => {
    await userEvent.click(await page.findByRole("button", { name: "Select all" }));
    for (const name of ["Main", "Sub-1", "Sub-2"])
      await expect(option(name)).toHaveAttribute("aria-selected", "true");
  },
};

/** E29-D02 D-8's 24-character account label wraps in the list; the option keeps its whole name. */
export const LongText: Story = {
  render: () => (
    <Picker
      defaultOpen
      accounts={[...OWNER, { id: "desk-4", label: "Desk 4 swing book London" }]}
    />
  ),
  play: async () => {
    await expect(
      await page.findByRole("option", { name: "Desk 4 swing book London" }),
    ).toBeVisible();
  },
};

/** Board 05 `CMP-105/filter-chips`: each chosen account becomes a CMP-055 chip, "+ Filter" after them. */
function FilterChips(): JSX.Element {
  const [chosen, setChosen] = useState<readonly string[]>(["sub-1"]);
  const toggle = (id: string): void =>
    setChosen((was) => (was.includes(id) ? was.filter((x) => x !== id) : [...was, id]));
  return (
    <FilterBar
      filters={chosen.map((id) => ({
        id,
        label: `Account: ${OWNER.find((a) => a.id === id)?.label ?? id}`,
        onRemove: () => toggle(id),
      }))}
      onClearAll={() => setChosen([])}
      addFilter={
        <AccountMultiSelect
          mode="account"
          trigger={<Button iconLeft="plus">Filter</Button>}
          accounts={OWNER.map((a) => ({ ...a, selected: chosen.includes(a.id) }))}
          onToggle={toggle}
          onSelectAll={() => setChosen(OWNER.map((a) => a.id))}
        />
      }
    />
  );
}

export const FilterChipsWithPicker: Story = {
  render: () => <FilterChips />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("button", { name: "Remove filter Account: Sub-1" }),
    ).toBeVisible();
    await userEvent.click(canvas.getByRole("button", { name: "Filter" }));
    await userEvent.click(option("Sub-2"));
    await expect(
      canvas.getByRole("button", { name: "Remove filter Account: Sub-2" }),
    ).toBeVisible();
  },
};

/** The open picker under the light and high-contrast themes; axe checks each theme. */
const themeMatrix = (theme: string): Story => ({
  globals: { theme },
  render: () => <Picker defaultOpen />,
  play: async () => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
    await page.findByRole("listbox", { name: "Filter" });
  },
});
export const ContrastLight: Story = themeMatrix("light");
export const ContrastHighContrast: Story = themeMatrix("high-contrast");
