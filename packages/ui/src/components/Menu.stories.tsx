import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef, useState, type JSX } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { Button } from "./Button.js";
import { Dialog } from "./Dialog.js";
import { IconButton } from "./IconButton.js";
import { Menu, type MenuAnchor, type MenuButtonProps, type MenuItem } from "./Menu.js";
import { formatRbacReason } from "./rbacReasons.js";

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

type DemoProps = Omit<MenuButtonProps, "trigger" | "contextTarget"> & { label?: string };

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

/** E40's alert row menu: Snooze opens its presets (KM-5). */
const alertRow: MenuItem[] = [
  { id: "ack", label: "Acknowledge", icon: "check", onSelect: noop },
  {
    id: "snooze",
    label: "Snooze",
    icon: "pending",
    items: [
      { id: "15m", label: "15 m", onSelect: noop },
      { id: "1h", label: "1 h", onSelect: noop },
      { id: "tomorrow", label: "Until tomorrow", onSelect: noop },
    ],
  },
  { id: "mute", label: "Mute", onSelect: noop },
];

/** ItemState=submenu: Snooze open on its presets, beside its row; ← or Esc closes it alone. */
export const NestedSubmenu: Story = {
  render: () => <Demo label="Alert actions" items={alertRow} />,
  play: async ({ canvasElement }) => {
    await opened(canvasElement, "Alert actions");
    await userEvent.keyboard("{ArrowDown}{ArrowRight}");
    const snooze = page.getByRole("menuitem", { name: "Snooze" });
    await expect(snooze).toHaveAttribute("aria-expanded", "true");
    const sub = page.getByRole("menu", { name: "Snooze" });
    await waitFor(() => expect(sub).toHaveAttribute("data-positioned"));
    await expect(page.getByRole("menuitem", { name: "15 m" })).toHaveFocus();
    // Beside its row: right of the parent menu (or left at the edge), its top on the row's.
    const parent = page.getByRole("menu", { name: "Alert actions" }).getBoundingClientRect();
    const box = sub.getBoundingClientRect();
    await expect(box.left >= parent.right - 1 || box.right <= parent.left + 1).toBe(true);
    await expect(Math.abs(box.top - snooze.getBoundingClientRect().top)).toBeLessThan(24);
    await userEvent.keyboard("{Escape}");
    await expect(page.queryByRole("menu", { name: "Snooze" })).toBeNull();
    await expect(snooze).toHaveFocus();
  },
};

/** Trigger=context: a grid row whose right-click, Shift+F10 or Menu key opens the row menu. */
function ContextRow(): JSX.Element {
  const row = useRef<HTMLDivElement>(null);
  return (
    <div style={stage}>
      <div role="grid" aria-label="Watchlist">
        <div
          ref={row}
          tabIndex={0}
          role="row"
          aria-label="BTCUSDT row"
          style={{
            padding: "var(--space-inset-md)",
            border: "calc(var(--border-hairline) * 1px) solid var(--color-border-default)",
            borderRadius: "var(--radius-control)",
            color: "var(--color-text-primary)",
          }}
        >
          <span role="gridcell">BTCUSDT · right-click, Shift+F10 or the Menu key</span>
        </div>
      </div>
      <Menu contextTarget={row} aria-label="BTCUSDT actions" items={alertRow} />
    </div>
  );
}

/** Trigger=context (right-click): it opens at the pointer; Esc returns focus to the row. */
export const ContextMenu: Story = {
  render: () => <ContextRow />,
  play: async ({ canvasElement }) => {
    const row = within(canvasElement).getByRole("row", { name: "BTCUSDT row" });
    const at = row.getBoundingClientRect();
    const coords = { clientX: Math.round(at.left + 24), clientY: Math.round(at.top + 8) };
    await userEvent.pointer({ keys: "[MouseRight]", target: row, coords });
    const menu = page.getByRole("menu", { name: "BTCUSDT actions" });
    await waitFor(() => expect(menu).toHaveAttribute("data-positioned"));
    await expect(page.getByRole("menuitem", { name: "Acknowledge" })).toHaveFocus();
    const box = menu.getBoundingClientRect();
    await expect(Math.abs(box.left - coords.clientX)).toBeLessThan(2);
    await expect(box.top).toBeGreaterThanOrEqual(coords.clientY);
    await expect(box.top - coords.clientY).toBeLessThan(16);
    await userEvent.keyboard("{Escape}");
    await expect(row).toHaveFocus();
  },
};

/** Trigger=context (keyboard): Shift+F10 on the focused row opens it below the row's start. */
export const ContextMenuKeyboard: Story = {
  render: () => <ContextRow />,
  play: async ({ canvasElement }) => {
    const row = within(canvasElement).getByRole("row", { name: "BTCUSDT row" });
    row.focus();
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    const menu = page.getByRole("menu", { name: "BTCUSDT actions" });
    await waitFor(() => expect(menu).toHaveAttribute("data-positioned"));
    const box = menu.getBoundingClientRect();
    const at = row.getBoundingClientRect();
    await expect(Math.abs(box.left - at.left)).toBeLessThan(2);
    await expect(box.top).toBeGreaterThanOrEqual(at.bottom);
    await userEvent.keyboard("{ArrowDown}{ArrowRight}");
    await expect(page.getByRole("menuitem", { name: "15 m" })).toHaveFocus();
    await userEvent.keyboard("{Escape}{Escape}");
    await expect(row).toHaveFocus();
  },
};

/** E08-D05 §6.3's actions for ETHUSDT as a Manager sees them: Record is T2, CMP-079's `rbac.owner_only`. */
const RECORD = formatRbacReason("rbac.owner_only", { verb: "start recording" });
const symbolActions: MenuItem[] = [
  { id: "open", label: "Open in Chart 1", shortcut: ["Enter"], onSelect: noop },
  { id: "new", label: "Open in new chart", shortcut: ["Shift", "Enter"], onSelect: noop },
  { id: "record", label: "Record this symbol…", disabledReason: RECORD, onSelect: noop },
];

/** SCR-102's shape: focus stays in the search input, whose `Shift+F10` or Menu key opens the menu at the row. */
function HostOpenedDemo(): JSX.Element {
  const row = useRef<HTMLDivElement>(null);
  const [anchor, setAnchor] = useState<MenuAnchor | null>(null);
  const [open, setOpen] = useState(false);
  return (
    <div style={stage}>
      <div
        style={{
          display: "grid",
          gap: "var(--space-stack-xs)",
          color: "var(--color-text-primary)",
        }}
      >
        <input
          aria-label="Search symbols"
          defaultValue="eth"
          onKeyDown={(event) => {
            if (event.key !== "ContextMenu" && !(event.key === "F10" && event.shiftKey)) return;
            event.preventDefault();
            setAnchor(row.current);
            setOpen(true);
          }}
        />
        <div ref={row}>ETHUSDT · the active option</div>
      </div>
      {anchor === null ? null : (
        <Menu
          anchor={anchor}
          open={open}
          onOpenChange={setOpen}
          aria-label="Actions for ETHUSDT"
          items={symbolActions}
        />
      )}
    </div>
  );
}

/** Host-opened (E08-D05 A-D05-13): at the active option, not the input; the T2 item is reached and inert. */
export const HostOpened: Story = {
  render: () => <HostOpenedDemo />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByRole("textbox", { name: "Search symbols" });
    input.focus();
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    const menu = page.getByRole("menu", { name: "Actions for ETHUSDT" });
    await waitFor(() => expect(menu).toHaveAttribute("data-positioned"));
    const row = canvas.getByText(/ETHUSDT/).getBoundingClientRect();
    await expect(Math.abs(menu.getBoundingClientRect().left - row.left)).toBeLessThan(2);
    await expect(menu.getBoundingClientRect().top).toBeGreaterThanOrEqual(row.bottom);
    await userEvent.keyboard("{End}{Enter}");
    const record = page.getByRole("menuitem", { name: "Record this symbol…" });
    await expect(record).toHaveFocus();
    await expect(canvas.getByRole("status")).toHaveTextContent(RECORD);
    await userEvent.keyboard("{Escape}");
    await expect(input).toHaveFocus();
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
