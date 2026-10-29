import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, fn, mocked, userEvent, waitFor, within } from "storybook/test";
import { EmptyState } from "./EmptyState.js";
import type { FuzzyListItem } from "./FuzzyList.js";
import { Menu } from "./Menu.js";
import { SymbolSearchInput, type SymbolSearchInputProps } from "./SymbolSearchInput.js";

/** E08-D05's fixture symbols (§4, §6.1); ETHFIUSDT is illustrative. */
const ETH: FuzzyListItem = {
  id: "ETHUSDT",
  label: "ETHUSDT",
  hint: "ETH / USDT",
  values: ["—", "—"],
};
const ROWS: readonly FuzzyListItem[] = [
  { id: "BTCUSDT", label: "BTCUSDT", hint: "BTC / USDT", values: ["▲ +1.23 %", "3.41 B USDT"] },
  { ...ETH, tags: ["recent"] },
  { id: "ETHFIUSDT", label: "ETHFIUSDT", hint: "ETHFI / USDT", values: ["—", "—"] },
  { id: "SOLUSDT", label: "SOLUSDT", hint: "SOL / USDT", values: ["—", "—"], tags: ["favourite"] },
];
const LUNA: FuzzyListItem = {
  id: "LUNAUSDT",
  label: "LUNAUSDT",
  hint: "LUNA / USDT",
  chip: { label: "Delisted by the exchange", icon: "cancelled" },
  disabled: true,
  delisted: true,
  reason: "LUNAUSDT is not trading on Bybit.",
};
const STATUS = "LUNAUSDT is not trading on Bybit.";

/** An illustrative substring rank: the host's real ranking is E08-D05 §4's (apps/web), never this package's. */
const rank = (query: string): FuzzyListItem[] => {
  const q = query
    .trim()
    .toUpperCase()
    .replace(/[\s/_-]/g, "");
  return q === ""
    ? []
    : ROWS.flatMap((row) => {
        const at = row.label.indexOf(q);
        return at < 0 ? [] : [{ ...row, matchRanges: [[at, at + q.length] as const] }];
      });
};

/** A host that owns the query and ranks on every keystroke, as SCR-102 does. */
function Host({
  initial = "",
  ...props
}: Partial<SymbolSearchInputProps> & { readonly initial?: string }): JSX.Element {
  const [value, setValue] = useState(initial);
  const items = rank(value);
  return (
    <SymbolSearchInput
      value={value}
      onChange={setValue}
      onSelect={fn()}
      items={items}
      emptyMessage={
        value.trim() === "" ? undefined : (
          <EmptyState
            variant="filtered-empty"
            title={`No USDT perpetual matches '${value.trim()}'.`}
            description="v1 supports Bybit USDT linear perpetuals only. Search by base asset, for example BTC."
          />
        )
      }
      {...props}
    />
  );
}

/** Theme and density come from the toolbars; the list is in place, so plays query the canvas. */
const meta: Meta<typeof SymbolSearchInput> = {
  title: "Molecules/SymbolSearchInput",
  component: SymbolSearchInput,
  args: { onSelect: fn() },
  render: (args) => <Host {...args} />,
  decorators: [
    (Story) => (
      <div style={{ maxWidth: "45rem" }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof SymbolSearchInput>;

const ui = (canvasElement: HTMLElement) => within(canvasElement);
const input = (canvasElement: HTMLElement): HTMLElement =>
  ui(canvasElement).getByRole("combobox", { name: "Search symbols" });
const activeName = (canvasElement: HTMLElement): string | null =>
  document
    .getElementById(input(canvasElement).getAttribute("aria-activedescendant") ?? "")
    ?.getAttribute("aria-label") ?? null;

/** Typing ranks on each keystroke; ↓ moves, Enter chooses; the count is said once the query rests 300 ms. */
export const Default: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.type(input(canvasElement), "eth");
    await expect(ui(canvasElement).getAllByRole("option")).toHaveLength(2);
    await userEvent.keyboard("{ArrowDown}{ArrowDown}");
    await expect(activeName(canvasElement)).toMatch(/^ETHFIUSDT,/);
    await waitFor(() =>
      expect(ui(canvasElement).getByRole("status")).toHaveTextContent("2 results"),
    );
    await userEvent.keyboard("{Enter}");
    await expect(args.onSelect).toHaveBeenCalledWith(
      "ETHFIUSDT",
      expect.objectContaining({ id: "ETHFIUSDT" }),
    );
  },
};

/** WithRecents (empty query): Recent leads; a delisted recent is reached, never chosen, and Enter says why. */
export const WithRecents: Story = {
  args: { recentSymbols: [ETH, LUNA], onSelect: fn() },
  play: async ({ canvasElement, args }) => {
    await expect(ui(canvasElement).getByRole("group", { name: "Recent" })).toBeVisible();
    input(canvasElement).focus();
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{Enter}");
    await expect(ui(canvasElement).getByRole("status")).toHaveTextContent(STATUS);
    await expect(args.onSelect).not.toHaveBeenCalled();
  },
};

/** NoResults: CMP-026 in the list's place, with E08-D05 §6.2's copy; the combobox is not expanded. */
export const NoResults: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.type(input(canvasElement), "xyzzy");
    await expect(ui(canvasElement).getByRole("heading")).toHaveTextContent("'xyzzy'");
    await expect(input(canvasElement)).toHaveAttribute("aria-expanded", "false");
  },
};

/** WithTarget (E08-D05 D-10): the chip names the pane a commit changes. */
export const WithTarget: Story = {
  args: { target: { label: "Changes Chart 1 · BTCUSDT 1m", id: "target" } },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector("#target")).toHaveTextContent(
      "Changes Chart 1 · BTCUSDT 1m",
    );
  },
};

/** ArmedTarget: E30-D02's ARMED pill (word and glyph) joins the chip. */
export const ArmedTarget: Story = {
  args: { target: { label: "Changes Chart 1 · BTCUSDT 1m", armed: true, id: "target" } },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector("#target")).toHaveTextContent(/1m ARMED$/);
  },
};

/**
 * Loading (E08-D05 §6.2): it opens with an empty query and the host's sentence is said at once; the list is busy over
 * static skeleton rows. Typing keeps the query and says nothing again.
 */
export const Loading: Story = {
  args: { loading: true, message: "Loading the instrument list…", items: [] },
  play: async ({ canvasElement }) => {
    const status = ui(canvasElement).getByRole("status");
    await waitFor(() => expect(status).toHaveTextContent("Loading the instrument list…"));
    await expect(ui(canvasElement).getByRole("listbox")).toHaveAttribute("aria-busy", "true");
    const said = status.firstElementChild;
    await userEvent.type(input(canvasElement), "btc");
    await expect(input(canvasElement)).toHaveValue("btc");
    await expect(status.firstElementChild).toBe(said);
  },
};

/** T2 (E08-D07 §6.6, `watchlist.cap_full`): the lock leads, the list is not shown, keys say the reason once. */
export const DisabledWithReason: Story = {
  args: { disabledReason: "Watching 200 symbols — remove some to add more" },
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(input(canvasElement)).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}x");
    await expect(input(canvasElement)).toHaveAttribute("aria-disabled", "true");
    await expect(ui(canvasElement).queryByRole("listbox")).toBeNull();
    await expect(ui(canvasElement).getByRole("status")).toHaveTextContent(/^Watching 200 symbols/);
  },
};

/**
 * E08-D05 §6.3: a host's `Shift+F10` menu on the active option; `Esc` returns to the input, same option. The host's
 * `onKeyDown` sees every key of the input first: a second `Esc` is its own (SCR-102 closes on it).
 */
function WithMenu({ onKeyDown, ...props }: Partial<SymbolSearchInputProps>): JSX.Element {
  const [anchor, setAnchor] = useState<Element | null>(null);
  return (
    <>
      <Host
        initial="eth"
        {...props}
        onKeyDown={(event, active) => {
          onKeyDown?.(event, active);
          if (event.key !== "ContextMenu" && !(event.key === "F10" && event.shiftKey)) return;
          const id = event.currentTarget.getAttribute("aria-activedescendant") ?? "";
          const option = document.getElementById(id);
          if (option === null) return;
          event.preventDefault();
          setAnchor(option);
        }}
      />
      <Menu
        open={anchor !== null}
        anchor={anchor ?? document.body}
        aria-label="Actions for ETHUSDT"
        onOpenChange={(open) => {
          if (!open) setAnchor(null);
        }}
        items={[
          { id: "open", label: "Open in Chart 1", onSelect: fn() },
          {
            id: "record",
            label: "Record this symbol…",
            disabledReason: "Only the owner can start recording.",
            onSelect: fn(),
          },
        ]}
      />
    </>
  );
}

export const HostMenu: Story = {
  args: { onKeyDown: fn() },
  render: (args) => <WithMenu {...args} />,
  play: async ({ canvasElement, args }) => {
    const escapes = (): number =>
      mocked(args.onKeyDown)?.mock.calls.filter(([event]) => event.key === "Escape").length ?? 0;
    input(canvasElement).focus();
    await userEvent.keyboard("{ArrowDown}");
    const before = input(canvasElement).getAttribute("aria-activedescendant");
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    await waitFor(() =>
      expect(
        within(document.body).getByRole("menuitem", { name: "Open in Chart 1" }),
      ).toHaveFocus(),
    );
    const ahead = escapes();
    await userEvent.keyboard("{Escape}");
    await expect(input(canvasElement)).toHaveFocus();
    await expect(input(canvasElement)).toHaveAttribute("aria-activedescendant", before ?? "");
    await expect(ui(canvasElement).getByRole("listbox")).toBeVisible();
    await expect(escapes()).toBe(ahead); // that one was the menu's
    await userEvent.keyboard("{Escape}");
    await expect(escapes()).toBe(ahead + 1); // the second is the host's, on the same option
    await expect(args.onKeyDown).toHaveBeenLastCalledWith(
      expect.objectContaining({ key: "Escape" }),
      expect.objectContaining({ id: "ETHUSDT" }),
    );
  },
};
