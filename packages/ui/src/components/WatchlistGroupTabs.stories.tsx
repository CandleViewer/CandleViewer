import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { eventually, shownWith } from "../../.storybook/eventually.js";
import { IconButton } from "./IconButton.js";
import {
  WatchlistGroupTabs,
  type WatchlistGroup,
  type WatchlistGroupTabsProps,
} from "./WatchlistGroupTabs.js";

/** E08-D07's sample lists (§4): Majors (12), My Setups (8) and Alts (120). */
const LISTS: readonly WatchlistGroup[] = [
  { id: "majors", name: "Majors" },
  { id: "setups", name: "My Setups" },
  { id: "alts", name: "Alts" },
];
const COUNTS: Readonly<Record<string, number>> = { majors: 12, setups: 8, alts: 120 };
const READ_ONLY = "Read-only — your role can't change watchlists.";
/** The design-system face on the stories' wrapper, so a host's own text never falls back to the browser's serif. */
const FONT = "var(--font-family-ui), system-ui, sans-serif";
const noop = (): void => undefined;

type HostProps = Partial<WatchlistGroupTabsProps> & { readonly initial?: string };

/** A host that owns the lists and the active one, as SCR-100 does; "+" adds "Watchlist 2" (E08-D07 §4.3). */
function Host({
  groups: startGroups = LISTS,
  counts: startCounts = COUNTS,
  initial = "majors",
  ...props
}: HostProps): JSX.Element {
  const [groups, setGroups] = useState(startGroups);
  const [counts, setCounts] = useState(startCounts);
  const [active, setActive] = useState(initial);
  return (
    <WatchlistGroupTabs
      aria-label="Watchlists"
      groups={groups}
      counts={counts}
      activeId={active}
      onSwitch={setActive}
      onCreate={() => {
        const id = `list-${groups.length + 1}`;
        setGroups((all) => [...all, { id, name: `Watchlist ${all.length - 1}` }]);
        setCounts((all) => ({ ...all, [id]: 0 }));
        setActive(id);
      }}
      onRename={noop}
      onDuplicate={noop}
      onDelete={noop}
      onManage={noop}
      headerEnd={<IconButton icon="more-vertical" label="Panel options" variant="ghost" />}
      {...props}
    >
      <p style={{ margin: "0.5rem 0" }}>The {groups.find((g) => g.id === active)?.name} grid.</p>
    </WatchlistGroupTabs>
  );
}

const meta: Meta = {
  title: "Molecules/WatchlistGroupTabs",
  component: WatchlistGroupTabs,
  decorators: [
    (Story) => (
      <div style={{ width: "49rem", fontFamily: FONT }}>
        <Story />
      </div>
    ),
  ],
  render: () => <Host />,
};
export default meta;
type Story = StoryObj;

/** The CMP-042 pattern, manual activation: the arrows move focus, `Enter` switches; tabs named with their counts. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.tab();
    await expect(canvas.getByRole("tab", { name: "Majors, 12 symbols" })).toHaveFocus();
    await userEvent.keyboard("{ArrowRight}");
    const setups = canvas.getByRole("tab", { name: "My Setups, 8 symbols" });
    await expect(setups).toHaveAttribute("aria-selected", "false");
    await userEvent.keyboard("{Enter}");
    await expect(setups).toHaveAttribute("aria-selected", "true");
    await expect(canvas.getByRole("tabpanel")).toHaveTextContent("The My Setups grid.");
  },
};

/** Hover: the pointer on "+": CMP-016's echo names it, "New watchlist", after the hover delay (CMP-002, D10). */
export const Hover: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.hover(within(canvasElement).getByRole("button", { name: "New watchlist" }));
    // CMP-016's hover delay; the wait counts only time the runner's page could run (#5274).
    const tooltip = await eventually(
      "the tooltip",
      () => shownWith('[data-cmp="CMP-016"]', "New watchlist"),
      1000,
    );
    await expect(tooltip).toHaveTextContent("New watchlist");
  },
};

/** FocusVisible: Tab reaches the strip's one stop, the active tab, with the focus ring; nothing switches. */
export const FocusVisible: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    const majors = within(canvasElement).getByRole("tab", { name: "Majors, 12 symbols" });
    await expect(majors).toHaveFocus();
    await expect(majors).toHaveAttribute("aria-selected", "true");
  },
};

/** "+" creates a list (the host names it "Watchlist 2", E08-D07 §4.3) and switches to it. */
export const CreateNew: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "New watchlist" }));
    await expect(canvas.getByRole("tab", { name: "Watchlist 2, 0 symbols" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  },
};

const MANY: readonly WatchlistGroup[] = [
  ...LISTS,
  { id: "breakouts", name: "Breakouts" },
  { id: "defi", name: "DeFi" },
  { id: "memes", name: "Memes" },
];
const MANY_COUNTS = { ...COUNTS, breakouts: 23, defi: 17, memes: 41 };

/** A narrow header row (D4): the tabs that do not fit go into "More lists"; the active one always shows. */
export const Overflow: Story = {
  decorators: [
    (Story) => (
      <div style={{ width: "26rem" }}>
        <Story />
      </div>
    ),
  ],
  render: () => <Host groups={MANY} counts={MANY_COUNTS} initial="memes" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "More lists" })).toBeVisible());
    await expect(canvas.getByRole("tab", { name: "Memes, 41 symbols" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  },
};

/** `Shift+F10` on a tab: its menu, Rename, Duplicate, Delete…, Manage watchlists… (CMP-041). */
export const TabMenu: Story = {
  play: async ({ canvasElement }) => {
    within(canvasElement).getByRole("tab", { name: "Majors, 12 symbols" }).focus();
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    const menu = await within(document.body).findByRole("menu", { name: "Actions for Majors" });
    await expect(within(menu).getAllByRole("menuitem")).toHaveLength(4);
  },
};

/** Read-only (D13): "+", Rename, Duplicate and Delete… stay, T2 with the notice's sentence; Manage stays live. */
export const ReadOnly: Story = {
  render: () => <Host writeReason={READ_ONLY} />,
  play: async ({ canvasElement }) => {
    const plus = within(canvasElement).getByRole("button", { name: "New watchlist" });
    await expect(plus).toHaveAttribute("aria-disabled", "true");
    within(canvasElement).getByRole("tab", { name: "Majors, 12 symbols" }).focus();
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    const menu = await within(document.body).findByRole("menu", { name: "Actions for Majors" });
    await expect(within(menu).getByRole("menuitem", { name: /^Rename/ })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  },
};

/**
 * Read-only (D13) as SCR-100 draws it: the panel's one notice, which "+" points at (`writeReasonId`; E09-D09 §2.2
 * "one notice, many pointers"); the tab menu's items keep their second line.
 */
export const ReadOnlyNotice: Story = {
  render: () => (
    <>
      <p id="lists-read-only" style={{ margin: "0 0 0.5rem" }}>
        {READ_ONLY}
      </p>
      <Host writeReason={READ_ONLY} writeReasonId="lists-read-only" />
    </>
  ),
  play: async ({ canvasElement }) => {
    const plus = within(canvasElement).getByRole("button", { name: "New watchlist" });
    await expect(plus).toHaveAttribute("aria-describedby", "lists-read-only");
    await expect(within(canvasElement).getAllByText(READ_ONLY)).toHaveLength(1);
  },
};

/** Near the cap (D10): from 180 symbols a tab's name reads against it, "Alts, 187 of 200 symbols". */
export const NearCap: Story = {
  render: () => <Host counts={{ ...COUNTS, alts: 187 }} initial="alts" />,
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("tab", { name: "Alts, 187 of 200 symbols" }),
    ).toBeInTheDocument();
  },
};

/** A long list name: the tab never wraps; a header row too narrow moves tabs into "More lists". */
export const LongName: Story = {
  render: () => (
    <Host
      groups={[{ id: "long", name: "Mid-caps rotating out of the majors this week" }, ...LISTS]}
      counts={{ ...COUNTS, long: 64 }}
      initial="long"
    />
  ),
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("tab", {
        name: "Mid-caps rotating out of the majors this week, 64 symbols",
      }),
    ).toHaveAttribute("aria-selected", "true");
  },
};
