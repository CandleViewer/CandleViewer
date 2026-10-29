import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { Button } from "./Button.js";
import { CommandPalette, type CommandPaletteProps, type PaletteCommand } from "./CommandPalette.js";

const noop = (): void => undefined;
const cmd = (
  id: string,
  label: string,
  group: string,
  extra: Partial<PaletteCommand> = {},
): PaletteCommand => ({ id, label, group, onRun: noop, ...extra });

/** E10-D03 §6.1's groups, in their order: Navigate · Panel · Symbol · Action · Setting. */
const CHART = cmd("chart", "Go to chart", "Navigate", { shortcut: ["Ctrl", "1"] });
const JOURNAL = cmd("journal", "Go to journal", "Navigate", { shortcut: ["Ctrl", "4"] });
const DOM = cmd("dom", "Add DOM ladder panel", "Panel");
const BTC = cmd("btc", "BTCUSDT", "Symbol");
const ETH = cmd("eth", "ETHUSDT", "Symbol");
const CANCEL = cmd("cancel", "Cancel all orders on this account…", "Action", { destructive: true });
const FLATTEN = cmd("flatten", "Flatten all positions", "Action", {
  destructive: true,
  shortcut: ["Ctrl", "Shift", "F"],
});
const LEVERAGE = cmd("leverage", "Set leverage", "Action", {
  disabledReason: "Your role can't change positions.",
});
const THEME = cmd("theme", "Switch theme", "Setting", { shortcut: ["Ctrl", "Shift", "H"] });
const COMMANDS = [CHART, JOURNAL, DOM, BTC, ETH, CANCEL, FLATTEN, LEVERAGE, THEME];

type HostProps = Partial<Omit<CommandPaletteProps, "open" | "onOpenChange">>;

/** The shell's role: an opener (its `Ctrl+K` binding, #305) and the confirm a destructive row asks for. */
function Host(props: HostProps): JSX.Element {
  const [open, setOpen] = useState(false);
  const [asked, setAsked] = useState("");
  return (
    <div style={{ display: "flex", gap: "var(--space-inset-sm)", alignItems: "center" }}>
      <Button onClick={() => setOpen(true)}>Commands</Button>
      <span>{asked}</span>
      <CommandPalette
        commands={COMMANDS}
        sections={[
          { label: "Recent", commands: [BTC, CHART, FLATTEN] },
          { label: "Suggested", commands: [JOURNAL, THEME] },
        ]}
        placeholder="Type a command or symbol"
        onRequestConfirm={(c) => setAsked(`Confirm asked: ${c.label}`)}
        {...props}
        open={open}
        onOpenChange={setOpen}
      />
    </div>
  );
}

/** Theme and density come from the toolbars; the dialog portals under `body`, so plays query the page. */
const meta: Meta = {
  title: "Molecules/CommandPalette",
  component: CommandPalette,
  render: () => <Host />,
};
export default meta;
type Story = StoryObj;

const page = within(document.body);
const opened = async (canvas: HTMLElement): Promise<HTMLElement> => {
  const opener = within(canvas).getByRole("button", { name: "Commands" });
  await userEvent.click(opener);
  await waitFor(() => expect(page.getByRole("combobox")).toHaveFocus());
  return opener;
};
/** The palette's own region (the page has the theme's too). */
const status = (): HTMLElement =>
  within(document.querySelector<HTMLElement>('[data-cmp="CMP-059"]') ?? document.body).getByRole(
    "status",
  );
const field = (): HTMLElement => page.getByRole("combobox", { name: "Search commands" });
const activeName = (): string | null => {
  const id = field().getAttribute("aria-activedescendant");
  return id === null ? null : (document.getElementById(id)?.getAttribute("aria-label") ?? null);
};

/** Default (the catalogue's EmptyQuery): the host's Recent and Suggested; ↓ wraps; Esc returns to the opener. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const opener = await opened(canvasElement);
    await expect(page.getByRole("group", { name: "Recent" })).toBeVisible();
    await expect(page.getByRole("group", { name: "Suggested" })).toBeVisible();
    await expect(activeName()).toBe("BTCUSDT");
    await userEvent.keyboard("{ArrowUp}");
    await expect(activeName()).toBe("Switch theme");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(opener).toHaveFocus());
    await opened(canvasElement); // left open for axe
  },
};

/** Filtered (the catalogue's Grouped): ranked results under their groups, empty groups dropped, matches in weight. */
export const Filtered: Story = {
  play: async ({ canvasElement }) => {
    await opened(canvasElement);
    await userEvent.type(field(), "go");
    await expect(
      page.getByRole("option", { name: "Go to chart" }).querySelector("mark"),
    ).not.toBeNull();
    await waitFor(() => expect(status()).toHaveTextContent(/results?$/), {
      timeout: 3000,
    });
  },
};

/** NoResults: no listbox, the host's sentence shown and said. */
export const NoResults: Story = {
  play: async ({ canvasElement }) => {
    await opened(canvasElement);
    await userEvent.type(field(), "xyz");
    await expect(page.getByText("No command or symbol matches 'xyz'")).toBeVisible();
    await expect(page.queryByRole("listbox")).toBeNull();
  },
};

/** WithConfirms (the catalogue's Destructive): tagged "confirms"; Enter asks the host's confirm, never runs. */
export const WithConfirms: Story = {
  play: async ({ canvasElement }) => {
    await opened(canvasElement);
    await userEvent.type(field(), "flatten");
    await expect(activeName()).toBe("Flatten all positions, confirms");
    await userEvent.keyboard("{Enter}");
    await expect(
      within(canvasElement).getByText("Confirm asked: Flatten all positions"),
    ).toBeTruthy();
    await expect(field()).toHaveFocus();
  },
};

/** Gated (the catalogue's RbacDisabled): T2, reachable; Enter re-shows the reason once; the group-run footer. */
export const Gated: Story = {
  render: () => <Host onRunGroup={noop} />,
  play: async ({ canvasElement }) => {
    await opened(canvasElement);
    await userEvent.type(field(), "leverage");
    const option = page.getByRole("option", { name: "Set leverage" });
    await expect(option).toHaveAttribute("aria-disabled", "true");
    await expect(option).toHaveAccessibleDescription("Your role can't change positions.");
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(status()).toHaveTextContent("Your role can't change positions."));
    await expect(field()).toHaveFocus();
  },
};

const LONG = [
  cmd(
    "long",
    "Cancel every resting order on every sub-account in the Scalping trade group, including emulated algos",
    "Action",
    { destructive: true, shortcut: ["Ctrl", "Alt", "Shift", "Del"] },
  ),
  cmd("gated-long", "Change the default leverage profile for all managed accounts", "Setting", {
    disabledReason:
      "Your role can't change account settings. Ask the owner to grant settings access for these accounts.",
  }),
  ...COMMANDS,
];

/** LongText: labels wrap to two lines then truncate (the full text is the name); a long reason wraps. */
export const LongText: Story = {
  render: () => (
    <Host commands={LONG} sections={[{ label: "Recent", commands: LONG.slice(0, 3) }]} />
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement);
    await expect(page.getAllByRole("option")).toHaveLength(3);
  },
};
