import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { SymbolInfoPopover } from "./SymbolInfoPopover.js";

/** Room below the trigger, so the preferred placement is the one drawn. */
const stage = { display: "grid", placeItems: "start center", minHeight: "30rem" } as const;

const contract = {
  tickSize: "0.1",
  quantityStep: "0.001",
  minimumOrderValue: "5",
  maximumLeverage: "100×",
} as const;
const live = { last: "82,782.40", fundingRate: "+0.0100%" } as const;

const meta: Meta<typeof SymbolInfoPopover> = {
  title: "Molecules/SymbolInfoPopover",
  component: SymbolInfoPopover,
  args: {
    symbol: "BTCUSDT",
    contract,
    live,
    recording: "Not recorded",
    onOpenFullDetails: fn(),
    defaultOpen: true,
  },
  decorators: [
    (Story) => (
      <div style={stage}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof SymbolInfoPopover>;

/** The popover lives in a portal on `document.body`, outside the story canvas. */
const dialog = (): HTMLElement => within(document.body).getByRole("dialog");
const isOpen = async (): Promise<void> =>
  waitFor(() => {
    expect(document.body.querySelector<HTMLElement>(".cv-popover")?.hidden).toBe(false);
  });
const bands = (): string[] =>
  within(dialog())
    .getAllByRole("heading", { level: 3 })
    .map((h) => h.textContent ?? "");

/** The three band labels in their fixed order, the rows as the host formatted them, one action. */
export const Default: Story = {
  play: async ({ args }) => {
    await isOpen();
    await expect(dialog()).toHaveAccessibleName("BTCUSDT");
    await expect(bands()).toEqual(["Contract rules", "Live market", "Recording in CandleViewer"]);
    await expect(within(dialog()).getByText("Tick size")).toBeTruthy();
    await userEvent.click(within(dialog()).getByRole("button", { name: "Open full details" }));
    await expect(args.onOpenFullDetails).toHaveBeenCalledTimes(1);
  },
};

/** Closed: the explicit info trigger alone, `aria-haspopup="dialog"`; never opened by hover. */
export const Trigger: Story = {
  args: { defaultOpen: false },
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole("button", { name: "Symbol info for BTCUSDT" });
    await expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await userEvent.hover(trigger);
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(trigger);
    await isOpen();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(trigger).toHaveFocus());
  },
};

/** Stale: the marker sits in the live band's head only; the contract rows stay undimmed. */
export const Stale: Story = {
  args: { state: "stale", staleAgeMs: 7_000 },
  play: async () => {
    await isOpen();
    await expect(within(dialog()).getByText("Stale, 7 seconds")).toBeTruthy();
  },
};

export const StaleEscalated: Story = {
  args: { state: "stale", staleAgeMs: 15_000, staleEscalated: true },
};

/** Not trading: the status heading replaces the live rows. */
export const NotTrading: Story = {
  args: { state: "not-trading", notTradingHeading: "BTCUSDT is not trading on Bybit." },
  play: async () => {
    await isOpen();
    await expect(within(dialog()).getByText("BTCUSDT is not trading on Bybit.")).toBeTruthy();
    await expect(within(dialog()).queryByText("Last")).toBeNull();
  },
};

/** Unavailable: the sentence and "Open full details"; no rows. */
export const Unavailable: Story = {
  args: { state: "unavailable" },
  play: async () => {
    await isOpen();
    await expect(within(dialog()).getByText("Contract rules not loaded")).toBeTruthy();
    await expect(within(dialog()).getByRole("button", { name: "Open full details" })).toBeTruthy();
  },
};

/** A value the host could not format reads "not available", never an empty cell or a zero. */
export const MissingValues: Story = {
  args: { contract: { tickSize: "0.1" }, live: {}, recording: undefined },
};

/** A long symbol and long values wrap at 200 % zoom rather than clipping. */
export const LongText: Story = {
  args: {
    symbol: "1000000BABYDOGEUSDT-PERPETUAL-CONTRACT-EXAMPLE",
    contract: { ...contract, minimumOrderValue: "0.0000000001234567890123456789" },
  },
};
