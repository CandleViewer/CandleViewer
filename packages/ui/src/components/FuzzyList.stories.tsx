import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { FROZEN } from "../../.storybook/copy.js";
import { EmptyState } from "./EmptyState.js";
import { FuzzyList, fuzzyOptionId, type FuzzyListItem, type FuzzyListProps } from "./FuzzyList.js";

/** A symbol's row: its base / quote hint and "—" for 24 h values the client does not hold (E08-D05 D-8). */
const symbol = (label: string, more: Partial<FuzzyListItem> = {}): FuzzyListItem => ({
  id: label,
  label,
  hint: `${label.slice(0, -4)} / USDT`,
  values: ["—", "—"],
  ...more,
});
/** E08-D05's rows (§4, §6.1): the fixture symbols, BTCUSDT's recorded 24 h values; ETHFIUSDT is illustrative. */
const BTC = symbol("BTCUSDT", {
  matchRanges: [[0, 3]],
  values: ["▲ +1.23 %", "3.41 B USDT"],
  chip: { label: "Recording" },
  description: "24 hours up 1.23 percent, turnover 3.41 billion USDT",
});
const NOT_RECORDED = { label: "Not recorded" };
const ETH = symbol("ETHUSDT", { matchRanges: [[0, 3]], chip: NOT_RECORDED, tags: ["recent"] });
const ETHFI = symbol("ETHFIUSDT", { matchRanges: [[0, 3]], chip: NOT_RECORDED });
const SOL = symbol("SOLUSDT", { tags: ["favourite"] });
const LUNA = symbol("LUNAUSDT", {
  values: [],
  chip: { label: "Delisted by the exchange", icon: "cancelled" },
  tags: ["recent"],
  disabled: true,
  delisted: true,
  reason: "LUNAUSDT is not trading on Bybit.",
});
/** 1,000 illustrative rows: `15` CMP-213's performance case. */
const MANY: FuzzyListItem[] = Array.from({ length: 1000 }, (_, i) => ({
  id: `S${String(i).padStart(4, "0")}`,
  label: `S${String(i).padStart(4, "0")}USDT`,
  matchRanges: [[0, 1]],
  hint: `S${String(i).padStart(4, "0")} / USDT`,
}));

const list = (props: Partial<FuzzyListProps>): FuzzyListProps => ({
  id: "symbols",
  "aria-label": "Symbols",
  items: [BTC, ETH, ETHFI],
  onActivate: fn(),
  ...props,
});

type Reorder = (items: readonly FuzzyListItem[]) => FuzzyListItem[];

/**
 * A host combobox, as CMP-160 composes this list: its input keeps focus, names the list (`aria-controls`) and moves
 * the active option with ↓ ↑ PageDown PageUp. A list that scrolls is a combobox's popup, so axe's
 * scrollable-region-focusable passes it. `reorder` adds a button that re-ranks the list (E08-D05 §9.2).
 */
function Host({ reorder, ...props }: FuzzyListProps & { readonly reorder?: Reorder }): JSX.Element {
  const [items, setItems] = useState(props.items);
  const [activeId, setActiveId] = useState(props.activeId);
  const at = items.findIndex((item) => item.id === activeId);
  const page = props.visibleRows ?? 8;
  const moves: Readonly<Record<string, number>> = {
    ArrowDown: at + 1,
    ArrowUp: at - 1,
    PageDown: at + page,
    PageUp: at - page,
  };
  return (
    <>
      <input
        type="text"
        role="combobox"
        aria-label="Search symbols"
        aria-autocomplete="list"
        aria-expanded="true"
        aria-controls={props.id}
        aria-activedescendant={
          activeId === undefined ? undefined : fuzzyOptionId(props.id, activeId)
        }
        onKeyDown={(event) => {
          const next = moves[event.key];
          if (next === undefined) return;
          event.preventDefault();
          setActiveId(items[Math.min(Math.max(next, 0), items.length - 1)]?.id);
        }}
      />
      {reorder === undefined ? null : (
        <button type="button" onClick={() => setItems(reorder)}>
          Re-rank
        </button>
      )}
      <FuzzyList
        {...props}
        items={items}
        activeId={activeId}
        onActivate={(item) => {
          setActiveId(item.id);
          props.onActivate(item);
        }}
      />
    </>
  );
}

/** Theme and density come from the toolbars; every row is one `size.row.height`. */
const meta: Meta<typeof FuzzyList> = {
  title: "Molecules/FuzzyList",
  component: FuzzyList,
  decorators: [
    (Story) => (
      <div style={{ maxWidth: "45rem" }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof FuzzyList>;

const box = (canvasElement: HTMLElement) => within(canvasElement);
const name = (item: FuzzyListItem): RegExp => new RegExp(`^${item.label},`);

/** At rest: ranked rows, nothing active; a hover only tints the row, it never takes the active option. */
export const Default: Story = {
  args: list({}),
  play: async ({ canvasElement }) => {
    const ui = box(canvasElement);
    await expect(ui.getByRole("listbox", { name: "Symbols" })).toBeVisible();
    await userEvent.hover(ui.getByRole("option", { name: name(ETH) }));
    await expect(ui.queryByRole("option", { selected: true })).toBeNull();
  },
};

/** Ranked (typed "eth"): the matched characters semibold primary, the active option's bar and fill. */
export const Ranked: Story = {
  args: list({ items: [ETH, ETHFI], activeId: "ETHUSDT" }),
  play: async ({ canvasElement }) => {
    const active = box(canvasElement).getByRole("option", { name: name(ETH) });
    await expect(active).toHaveAttribute("aria-selected", "true");
    await expect(active.querySelector("mark")).toHaveTextContent("ETH");
  },
};

/** WithColumns (E08-D05 §6.1): the column header in the options' own cells, hidden from AT (the names hold the words). */
export const WithColumns: Story = {
  args: list({
    items: [BTC, ETH, ETHFI],
    columns: {
      label: "Symbol",
      hint: "Base / quote",
      values: ["24 h", "24 h turnover"],
      chip: "Recording",
    },
  }),
  play: async ({ canvasElement }) => {
    const head = canvasElement.querySelector(".cv-fuzzylist__columns");
    await expect(head).toHaveAttribute("aria-hidden", "true");
    await expect(head?.closest("[role=listbox]")).toBeNull();
    // Every cell in the header's caption type, never its column's data font (the cascade is Chromium's to show).
    const type = (node: Element): string[] => {
      const style = getComputedStyle(node);
      return [style.fontFamily, style.fontSize, style.fontWeight];
    };
    for (const cell of [...(head?.children ?? [])])
      await expect(type(cell)).toEqual(head === null ? [] : type(head));
  },
};

/** Grouped (an empty query, E08-D05 V11): Recent, then Favourites, each a named `role="group"`. */
export const Grouped: Story = {
  args: list({
    items: [
      { ...ETH, group: "Recent" },
      { ...LUNA, group: "Recent" },
      { ...SOL, group: "Favourites" },
    ],
  }),
  play: async ({ canvasElement }) => {
    const groups = box(canvasElement).getAllByRole("group");
    await expect(groups.map((g) => g.getAttribute("aria-label"))).toEqual(["Recent", "Favourites"]);
  },
};

/** Tags: ★ favourite and ↺ recent, words in the option's name. */
export const WithTags: Story = {
  args: list({ items: [ETH, SOL] }),
  play: async ({ canvasElement }) => {
    const ui = box(canvasElement);
    await expect(ui.getByRole("option", { name: /^ETHUSDT, .*, recent$/ })).toBeVisible();
    await expect(ui.getByRole("option", { name: /^SOLUSDT, .*, favourite$/ })).toBeVisible();
  },
};

/** Delisted (E08-D05 §6.4), active: struck, its chip, `aria-disabled`, described by the status sentence. */
export const DelistedItem: Story = {
  args: list({ items: [LUNA, ETH], activeId: "LUNAUSDT" }),
  play: async ({ canvasElement }) => {
    const luna = box(canvasElement).getByRole("option", { name: name(LUNA) });
    await expect(luna).toHaveAttribute("aria-disabled", "true");
    await expect(luna).toHaveAccessibleDescription("LUNAUSDT is not trading on Bybit.");
  },
};

/**
 * A 24-character symbol in a 16rem column never truncates and the row never overflows: its hint gives way, cut with
 * an ellipsis. A T2 option's long reason is its description (the host's detail bar shows it, E08-D05 §6.4).
 */
export const LongSymbolAndReason: Story = {
  decorators: [
    (Story) => (
      <div style={{ maxWidth: "16rem" }}>
        <Story />
      </div>
    ),
  ],
  args: list({
    items: [
      { id: "LONG", label: "ABCDEFGHIJKLMNOPQRSTUSDT", hint: "ABCDEFGHIJKLMNOPQRST / USDT" },
      {
        id: "GATED",
        label: "XRPUSDT",
        hint: "XRP / USDT",
        disabled: true,
        reason: FROZEN,
      },
    ],
    activeId: "GATED",
  }),
  play: async ({ canvasElement }) => {
    const ui = box(canvasElement);
    const long = ui.getByRole("option", { name: /^ABCDEFGHIJKLMNOPQRSTUSDT,/ });
    const label = long.querySelector<HTMLElement>(".cv-fuzzylist__label");
    const hint = long.querySelector<HTMLElement>(".cv-fuzzylist__hint");
    await expect(label).toHaveTextContent("ABCDEFGHIJKLMNOPQRSTUSDT");
    await expect(label?.scrollWidth).toBeLessThanOrEqual(label?.clientWidth ?? 0);
    await expect(long.scrollWidth).toBeLessThanOrEqual(long.clientWidth);
    // jsdom lays nothing out (every width 0); in Chromium the hint is the one cut.
    if (long.clientWidth > 0)
      await expect(hint?.scrollWidth).toBeGreaterThan(hint?.clientWidth ?? 0);
    await expect(ui.getByRole("option", { name: /^XRPUSDT/ })).toHaveAccessibleDescription(
      /Cancel and close still work\.$/,
    );
  },
};

/** LongList (virtualised): 1,000 rows at 16 visible through a host combobox; its keys move the window: ≤ 24 nodes. */
export const LongList: Story = {
  args: list({ items: MANY, visibleRows: 16, activeId: "S0500" }),
  render: (args) => <Host {...args} />,
  play: async ({ canvasElement }) => {
    const ui = box(canvasElement);
    const input = ui.getByRole("combobox", { name: "Search symbols" });
    input.focus();
    await userEvent.keyboard("{PageDown}{ArrowDown}");
    const active = ui.getByRole("option", { selected: true });
    await expect(input).toHaveAttribute("aria-activedescendant", active.id);
    await expect([
      active.getAttribute("aria-posinset"),
      active.getAttribute("aria-setsize"),
    ]).toEqual(["518", "1000"]);
    await expect(ui.getAllByRole("option").length).toBeLessThanOrEqual(24);
  },
};

/** 50 rows, 16 shown: the host re-ranks and the active option, the 31st, is now the 3rd: still in view (§9.2). */
export const ReRankKeepsActive: Story = {
  args: list({ items: MANY.slice(0, 50), visibleRows: 16, activeId: "S0030" }),
  render: (args) => (
    <Host {...args} reorder={(items) => [...items.slice(28), ...items.slice(0, 28)]} />
  ),
  play: async ({ canvasElement }) => {
    const ui = box(canvasElement);
    await userEvent.click(ui.getByRole("button", { name: "Re-rank" }));
    const active = ui.getByRole("option", { selected: true });
    await expect(active).toHaveAttribute("aria-posinset", "3");
    // The scroll offset followed the window to it (jsdom measures zeros, so this holds there trivially).
    const view = ui.getByRole("listbox").getBoundingClientRect();
    const row = active.getBoundingClientRect();
    await expect(row.top).toBeGreaterThanOrEqual(view.top - 0.5);
    await expect(row.bottom).toBeLessThanOrEqual(view.bottom + 0.5);
  },
};

/** Loading: six static skeleton rows, the listbox busy; no option yet. */
export const Loading: Story = {
  args: list({ items: [], loading: true }),
  play: async ({ canvasElement }) => {
    await expect(box(canvasElement).getByRole("listbox")).toHaveAttribute("aria-busy", "true");
    await expect(box(canvasElement).queryAllByRole("option")).toHaveLength(0);
  },
};

/** NoResults: CMP-026 with E08-D05 §6.2's copy in the list's place; no empty listbox. */
export const NoResults: Story = {
  args: list({
    items: [],
    emptyMessage: (
      <EmptyState
        variant="filtered-empty"
        title="No USDT perpetual matches 'xyzzy'."
        description="v1 supports Bybit USDT linear perpetuals only. Search by base asset, for example BTC."
        actions={[{ label: "Clear search", onClick: fn(), variant: "secondary" }]}
      />
    ),
  }),
  play: async ({ canvasElement }) => {
    await expect(box(canvasElement).queryByRole("listbox")).toBeNull();
    await expect(box(canvasElement).getByRole("heading")).toHaveTextContent("xyzzy");
  },
};

/** The light and high-contrast themes (dark is every other story's): headers, a match, the active row, delisted. */
const themed = (theme: string): Story => ({
  globals: { theme },
  args: list({
    items: [
      { ...ETH, group: "Recent" },
      { ...LUNA, group: "Recent" },
      { ...BTC, group: "Favourites" },
    ],
    activeId: "ETHUSDT",
  }),
  play: async ({ canvasElement }) => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
    await userEvent.hover(box(canvasElement).getByRole("option", { name: name(BTC) }));
    await expect(box(canvasElement).getByRole("option", { selected: true })).toHaveAttribute(
      "data-active",
    );
  },
});
export const ContrastLight: Story = themed("light");
export const ContrastHighContrast: Story = themed("high-contrast");

/**
 * E08-D05 §5's keystroke budget over `15`'s 1,000 rows: a re-render with a new list and active option, the median
 * of 20 warmed renders within 50 ms. Tagged `perf`: a wall-clock budget is no pass/fail check on a shared runner,
 * so the storybook project skips it (#269) unless `CV_STORYBOOK_PERF=1`.
 */
export const Perf1000Items: Story = {
  tags: ["perf"],
  render: () => <p>1,000-row benchmark: the play function renders and times the list.</p>,
  play: async ({ canvasElement }) => {
    const root = createRoot(canvasElement.appendChild(document.createElement("div")));
    const samples: number[] = [];
    for (let i = 0; i < 25; i += 1) {
      const items = i % 2 === 0 ? MANY : MANY.slice().reverse();
      const start = performance.now();
      flushSync(() =>
        root.render(<FuzzyList {...list({ items, activeId: `S0${String(400 + i)}` })} />),
      );
      samples.push(performance.now() - start);
    }
    root.unmount();
    const median = samples.slice(5).sort((a, b) => a - b)[10] ?? Infinity;
    await expect(median).toBeLessThanOrEqual(50);
  },
};
