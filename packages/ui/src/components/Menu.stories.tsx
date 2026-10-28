import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { Button } from "./Button.js";
import { Dialog } from "./Dialog.js";
import { IconButton } from "./IconButton.js";
import { Menu, type MenuItem, type MenuProps } from "./Menu.js";

/** Room below and above the trigger, so the preferred placement is the one drawn. */
const stage = {
  display: "grid",
  placeItems: "start center",
  minHeight: "28rem",
  paddingTop: "var(--space-inset-lg)",
} as const;
const noop = (): void => undefined;

/** E14-D02's tree-row menu: Duplicate · Reveal on chart · Move up · Move down, a separator, Remove (`Del`). */
const treeRow: MenuItem[] = [
  { id: "dup", label: "Duplicate", icon: "copy", onSelect: noop },
  { id: "reveal", label: "Reveal on chart", icon: "crosshair", onSelect: noop },
  { id: "up", label: "Move up", icon: "arrow-up", onSelect: noop },
  { id: "down", label: "Move down", icon: "arrow-down", onSelect: noop },
  {
    id: "remove",
    label: "Remove",
    icon: "delete",
    danger: true,
    shortcut: ["Del"],
    onSelect: noop,
  },
];

type DemoProps = Omit<MenuProps, "trigger"> & { label?: string };

function Demo({ label = "Layer actions", ...props }: DemoProps): JSX.Element {
  return (
    <div style={stage}>
      <Menu trigger={<Button>{label}</Button>} {...props} />
    </div>
  );
}

/** E11-D03's price-scale menu: the "Scale mode" radios and four checkboxes, the host holding their state. */
function PriceScale(): JSX.Element {
  const [mode, setMode] = useState("Regular");
  const [flags, setFlags] = useState<Record<string, boolean>>({ "Lock price to bar ratio": true });
  const modes = ["Regular", "Percent", "Indexed to 100", "Logarithmic"];
  const items: MenuItem[] = [
    ...modes.map((label): MenuItem => ({
      id: label,
      label,
      kind: "radio",
      checked: mode === label,
      group: { id: "mode", label: "Scale mode" },
      onSelect: () => setMode(label),
    })),
    ...["Lock price to bar ratio", "Invert scale", "Merge scales", "Scale price only"].map(
      (label): MenuItem => ({
        id: label,
        label,
        kind: "checkbox",
        checked: flags[label] === true,
        group: { id: "options" },
        onSelect: () => setFlags((prev) => ({ ...prev, [label]: prev[label] !== true })),
      }),
    ),
  ];
  return <Demo label="Price scale" items={items} />;
}

/** Theme and density come from the toolbars; the light and high-contrast stories pin the theme for axe. */
const meta: Meta = {
  title: "Molecules/Menu",
  component: Menu,
  render: () => <Demo items={treeRow} />,
};
export default meta;
type Story = StoryObj;

const page = within(document.body);
const opened = async (canvas: HTMLElement, name = "Layer actions"): Promise<HTMLElement> => {
  const trigger = within(canvas).getByRole("button", { name });
  trigger.focus();
  await userEvent.keyboard("{Enter}");
  const menu = page.getByRole("menu", { name });
  await waitFor(() => expect(menu).toHaveAttribute("data-positioned"));
  return trigger;
};

/** ItemState=default: opens on its first item; Esc returns focus to the trigger (conventions 32). */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const trigger = await opened(canvasElement);
    await expect(page.getByRole("menuitem", { name: "Duplicate" })).toHaveFocus();
    await expect(page.getAllByRole("separator")).toHaveLength(1);
    await userEvent.keyboard("{Escape}");
    await expect(trigger).toHaveFocus();
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
  },
};

/** ItemState=hover: the pointer on "Reveal on chart" (surface.hover). */
export const Hover: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Layer actions" }));
    const reveal = page.getByRole("menuitem", { name: "Reveal on chart" });
    await userEvent.hover(reveal);
    await expect(reveal).toHaveFocus();
  },
};

/** ItemState=focus-visible: the keyboard on "Reveal on chart", with the inset ring (H8). */
export const FocusVisible: Story = {
  play: async ({ canvasElement }) => {
    await opened(canvasElement);
    await userEvent.keyboard("{ArrowDown}");
    const reveal = page.getByRole("menuitem", { name: "Reveal on chart" });
    await expect(reveal).toHaveFocus();
    await expect(reveal.matches(":focus-visible")).toBe(true);
    // The ring is drawn on the row, inside it, so the menu's scroll box never clips it.
    const row = reveal.closest(".cv-menu__row");
    if (row === null) throw new Error("no row");
    await expect(Number.parseFloat(getComputedStyle(row).outlineOffset)).toBeLessThan(0);
    await expect(getComputedStyle(row).outlineStyle).toBe("solid");
  },
};

/** ItemState=active: a pointer press (surface.selected); the action runs and focus returns to the trigger. */
export const Active: Story = {
  play: async ({ canvasElement }) => {
    const trigger = await opened(canvasElement);
    await userEvent.click(page.getByRole("menuitem", { name: "Move up" }));
    await expect(trigger).toHaveFocus();
  },
};

/** Shortcuts trail through CMP-022 and `aria-keyshortcuts`. */
export const WithShortcuts: Story = {
  render: () => (
    <Demo
      label="Edit"
      items={[
        { id: "undo", label: "Undo", icon: "undo", shortcut: ["Ctrl", "Z"], onSelect: noop },
        {
          id: "redo",
          label: "Redo",
          icon: "redo",
          shortcut: ["Ctrl", "Shift", "Z"],
          onSelect: noop,
        },
        { id: "copy", label: "Copy", icon: "copy", shortcut: ["Ctrl", "C"], onSelect: noop },
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement, "Edit");
    await expect(page.getByRole("menuitem", { name: "Redo" })).toHaveAttribute(
      "aria-keyshortcuts",
      "Control+Shift+Z",
    );
  },
};

/** ItemState=checked: radios and checkboxes; Space toggles and keeps it open. */
export const Checkable: Story = {
  render: () => <PriceScale />,
  play: async ({ canvasElement }) => {
    await opened(canvasElement, "Price scale");
    await expect(page.getByRole("group", { name: "Scale mode" })).toBeVisible();
    const invert = page.getByRole("menuitemcheckbox", { name: "Invert scale" });
    invert.focus();
    await userEvent.keyboard(" ");
    await expect(invert).toHaveAttribute("aria-checked", "true");
    await expect(invert).toHaveFocus();
  },
};

/** A menu that picks one value opens on its checked item (E12-D03). */
export const PickOne: Story = {
  render: () => (
    <Demo
      label="Timeframe"
      items={["1m", "5m", "15m", "1h", "4h"].map((label) => ({
        id: label,
        label,
        kind: "radio" as const,
        checked: label === "15m",
        onSelect: noop,
      }))}
    />
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement, "Timeframe");
    await expect(page.getByRole("menuitemradio", { name: "15m" })).toHaveFocus();
  },
};

/** ItemState=disabled: plain disabled, at `opacity.disabled`; reached by the arrows, never activated. */
export const Disabled: Story = {
  render: () => (
    <Demo
      items={[
        { id: "dup", label: "Duplicate", icon: "copy", onSelect: noop },
        {
          id: "reveal",
          label: "Reveal on chart",
          icon: "crosshair",
          disabled: true,
          onSelect: noop,
        },
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement);
    await userEvent.keyboard("{ArrowDown}");
    const reveal = page.getByRole("menuitem", { name: "Reveal on chart" });
    await expect(reveal).toHaveFocus();
    await expect(reveal).toHaveAttribute("aria-disabled", "true");
    await userEvent.keyboard("{Enter}");
    await expect(reveal).toBeVisible();
  },
};

/** ItemState=disabled-with-reason: SCR-063's "Edit risk caps" for a manager (T2, rendering 2a). */
export const DisabledWithReason: Story = {
  render: () => (
    <Demo
      label="Account"
      items={[
        { id: "view", label: "View account", onSelect: noop },
        {
          id: "caps",
          label: "Edit risk caps",
          disabledReason: "Only the owner can change account settings.",
          onSelect: noop,
        },
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement, "Account");
    await userEvent.keyboard("{ArrowDown}");
    const caps = page.getByRole("menuitem", { name: "Edit risk caps" });
    await expect(caps).toHaveFocus();
    await expect(caps).toHaveAccessibleDescription("Only the owner can change account settings.");
    await userEvent.keyboard("{Enter}");
    await expect(within(canvasElement).getByRole("status")).toHaveTextContent(
      "Only the owner can change account settings.",
    );
    await expect(caps).toBeVisible();
  },
};

/** ItemState=danger: Remove in the last group, its glyph `status.danger.strong`, "Destructive action". */
export const Danger: Story = {
  render: () => (
    <Demo
      label="Account actions"
      items={[
        {
          id: "flatten",
          label: "Flatten account",
          danger: true,
          opensConfirm: true,
          onSelect: noop,
        },
        { id: "view", label: "View positions", onSelect: noop },
        { id: "orders", label: "View open orders", onSelect: noop },
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement, "Account actions");
    await userEvent.keyboard("{End}");
    const flatten = page.getByRole("menuitem", { name: "Flatten account…" });
    await expect(flatten).toHaveFocus();
    await expect(flatten).toHaveAccessibleDescription("Destructive action");
  },
};

/** ItemState=busy: E29-D02's loading account; CMP-014 leads the label, `aria-busy`, no lock, no reason. */
export const Busy: Story = {
  render: () => (
    <IconButtonDemo
      items={[
        {
          id: "flatten",
          label: "Flatten account",
          busy: true,
          opensConfirm: true,
          danger: true,
          description: "Loading Sub-1 · LIVE…",
          onSelect: noop,
        },
        { id: "details", label: "Account details", onSelect: noop },
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement, "Sub-1 actions");
    await userEvent.keyboard("{End}");
    const flatten = page.getByRole("menuitem", { name: "Flatten account…" });
    await expect(flatten).toHaveAttribute("aria-busy", "true");
    await expect(flatten).not.toHaveAttribute("aria-disabled");
    await expect(flatten).toHaveAccessibleDescription("Loading Sub-1 · LIVE… Destructive action");
  },
};

/** An icon-only trigger (CMP-002, the group header's ⋯), which names the menu. */
function IconButtonDemo({ items }: { items: MenuItem[] }): JSX.Element {
  return (
    <div style={stage}>
      <Menu trigger={<IconButton icon="more-horizontal" label="Sub-1 actions" />} items={items} />
    </div>
  );
}

/** Overflow=scrolls: the menu caps its height to the room below its trigger and scrolls; Tab closes it. */
export const Scrolling: Story = {
  render: () => (
    <Demo
      label="Symbols"
      items={Array.from({ length: 40 }, (_, i) => ({
        id: String(i),
        label: `Symbol ${String(i + 1)}`,
        onSelect: noop,
      }))}
    />
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement, "Symbols");
    const menu = page.getByRole("menu", { name: "Symbols" });
    await expect(menu.getBoundingClientRect().bottom).toBeLessThanOrEqual(window.innerHeight);
    await expect(menu.scrollHeight).toBeGreaterThan(menu.clientHeight);
    await userEvent.keyboard("{End}");
    const last = page.getByRole("menuitem", { name: "Symbol 40" });
    await expect(last.getBoundingClientRect().bottom).toBeLessThanOrEqual(
      menu.getBoundingClientRect().bottom + 0.5,
    );
    await userEvent.tab();
    await expect(menu).not.toBeVisible();
  },
};

/** Esc closes the topmost layer only: the menu, then the dialog it sits in (conventions 32). */
function InDialog(): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <div style={stage}>
      <Button onClick={() => setOpen(true)}>Open settings</Button>
      <Dialog open={open} title="Chart settings" onOpenChange={(next) => setOpen(next)}>
        <Menu trigger={<Button>Layer actions</Button>} items={treeRow} />
      </Dialog>
    </div>
  );
}
export const EscTopmost: Story = {
  render: () => <InDialog />,
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Open settings" }));
    const dialog = await page.findByRole("dialog", { name: "Chart settings" });
    const trigger = within(dialog).getByRole("button", { name: "Layer actions" });
    trigger.focus();
    await userEvent.keyboard("{ArrowDown}");
    await expect(page.getByRole("menuitem", { name: "Duplicate" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    await expect(trigger).toHaveFocus();
    await expect(dialog).toBeVisible();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(page.queryByRole("dialog")).toBeNull());
  },
};

const themed = (theme: string): Story => ({
  render: () => (
    <Demo
      items={[
        ...treeRow,
        {
          id: "caps",
          label: "Edit risk caps",
          disabledReason: "Only the owner can change account settings.",
          onSelect: noop,
        },
        { id: "busy", label: "Export", busy: true, description: "Loading…", onSelect: noop },
        { id: "off", label: "Archive", disabled: true, onSelect: noop },
      ]}
    />
  ),
  globals: { theme },
  play: async ({ canvasElement }) => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
    await opened(canvasElement);
  },
});
export const ContrastLight: Story = themed("light");
export const ContrastHighContrast: Story = themed("high-contrast");
