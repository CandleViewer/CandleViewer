// @vitest-environment jsdom
import { act, useState, type JSX } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import { Button, Dialog, Menu, type MenuItem, type MenuProps } from "../src/components/index.js";
import { mount } from "./theme/mount.js";

const page = within(document.body);
const noop = (): void => undefined;

/** E14-D02's tree-row menu: four actions, a separator, then Remove with its shortcut (moved last, H16). */
const treeRow = (onSelect = noop): MenuItem[] => [
  { id: "remove", label: "Remove", danger: true, shortcut: ["Del"], icon: "delete", onSelect },
  { id: "dup", label: "Duplicate", shortcut: ["Ctrl", "D"], onSelect },
  { id: "reveal", label: "Reveal on chart", onSelect },
  { id: "up", label: "Move up", onSelect },
  { id: "down", label: "Move down", onSelect },
];

const renderMenu = async (props: Partial<MenuProps> = {}): Promise<HTMLElement> =>
  mount(
    <div>
      <Button>Before</Button>
      <Menu trigger={<Button>Row actions</Button>} items={treeRow()} {...props} />
      <Button>After</Button>
    </div>,
  );

const trigger = (): HTMLElement => page.getByRole("button", { name: "Row actions" });
const menu = (): HTMLElement => page.getByRole("menu", { name: "Row actions" });
const focused = (): string => document.activeElement?.textContent ?? "";
const press = async (keys: string): Promise<void> => {
  await userEvent.keyboard(keys);
};
const openWith = async (keys: string): Promise<void> => {
  trigger().focus();
  await press(keys);
};

describe("Menu (CMP-041) trigger", () => {
  it("is an APG menu button: haspopup, expanded, controls the menu it names", async () => {
    await renderMenu();
    const button = trigger();
    expect(button).toHaveAttribute("aria-haspopup", "menu");
    expect(button).toHaveAttribute("aria-expanded", "false");
    const list = document.querySelector('[role="menu"]');
    expect(button).toHaveAttribute("aria-controls", list?.id);
    expect(list).toHaveAttribute("hidden");
    await openWith("{Enter}");
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(menu()).toBeVisible();
  });

  it.each([
    ["{Enter}", "Duplicate"],
    [" ", "Duplicate"],
    ["{ArrowDown}", "Duplicate"],
    ["{ArrowUp}", "Remove"],
  ])("%s opens it on the expected item (%s)", async (keys, first) => {
    await renderMenu();
    await openWith(keys);
    expect(focused()).toContain(first);
  });

  it("a pointer press opens it on the first item and a second press closes it", async () => {
    await renderMenu();
    await userEvent.click(trigger());
    expect(focused()).toContain("Duplicate");
    await userEvent.click(trigger());
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    expect(trigger()).toHaveFocus();
  });

  it("a menu that picks one value opens on its checked item", async () => {
    const scale: MenuItem[] = ["Linear", "Log", "Percent"].map((label) => ({
      id: label,
      label,
      kind: "radio",
      checked: label === "Log",
      onSelect: noop,
    }));
    await renderMenu({ items: scale });
    await openWith("{Enter}");
    expect(page.getByRole("menuitemradio", { name: "Log" })).toHaveFocus();
  });

  it("runs the trigger's own handlers first; a prevented click does not open it", async () => {
    const own = fn((event: { preventDefault: () => void }) => event.preventDefault());
    await mount(<Menu trigger={<Button onClick={own}>Row actions</Button>} items={treeRow()} />);
    await userEvent.click(trigger());
    expect(own).toHaveBeenCalledOnce();
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
  });
});

describe("Menu (CMP-041) keyboard", () => {
  it("arrows wrap, Home and End reach the ends; separators and group labels are skipped", async () => {
    await renderMenu();
    await openWith("{Enter}");
    await press("{ArrowUp}");
    expect(focused()).toContain("Remove");
    await press("{ArrowDown}");
    expect(focused()).toContain("Duplicate");
    await press("{End}");
    expect(focused()).toContain("Remove");
    await press("{Home}");
    expect(focused()).toContain("Duplicate");
    await press("{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}");
    expect(focused()).toContain("Remove");
  });

  it("type-ahead moves to the next label that starts with the typed text, on an injected clock", async () => {
    let clock = 1000;
    await renderMenu({ now: () => clock });
    await openWith("{Enter}");
    await press("m");
    expect(focused()).toContain("Move up");
    await press("m");
    expect(focused()).toContain("Move down");
    clock += 100;
    await press("r");
    expect(focused()).toContain("Move down"); // "mmr" matches nothing: focus stays
    clock += 1000;
    await press("r");
    expect(focused()).toContain("Remove"); // the window expired: a fresh "r" from Move down
    await press("r");
    expect(focused()).toContain("Reveal on chart"); // a repeated letter cycles, wrapping
    clock += 1000;
    await press("rem");
    expect(focused()).toContain("Remove");
  });

  it("Enter activates an action, closes it, and returns focus to the trigger before the host runs", async () => {
    let at: Element | null = null;
    const onSelect = fn(() => {
      at = document.activeElement;
    });
    await renderMenu({ items: treeRow(onSelect) });
    await openWith("{Enter}");
    await press("{Enter}");
    expect(onSelect).toHaveBeenCalledOnce();
    expect(at).toBe(trigger());
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
  });

  it("Space toggles a checkable item and keeps the menu open; Enter toggles and closes", async () => {
    const onSelect = fn();
    const items: MenuItem[] = [
      { id: "lock", label: "Lock scale", kind: "checkbox", checked: true, onSelect },
      { id: "inv", label: "Invert scale", kind: "checkbox", onSelect },
    ];
    await renderMenu({ items });
    await openWith("{Enter}");
    const lock = page.getByRole("menuitemcheckbox", { name: "Lock scale" });
    expect(lock).toHaveAttribute("aria-checked", "true");
    expect(page.getByRole("menuitemcheckbox", { name: "Invert scale" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
    await press(" ");
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(lock).toHaveFocus();
    await press("{Enter}");
    expect(onSelect).toHaveBeenCalledTimes(2);
    expect(trigger()).toHaveFocus();
  });

  it("Space activates an action item and closes", async () => {
    const onSelect = fn();
    await renderMenu({ items: treeRow(onSelect) });
    await openWith("{Enter}");
    await press(" ");
    expect(onSelect).toHaveBeenCalledOnce();
    expect(trigger()).toHaveFocus();
  });

  it("Esc closes it and returns focus to the trigger", async () => {
    const onOpenChange = fn();
    await renderMenu({ onOpenChange });
    await openWith("{Enter}");
    await press("{Escape}");
    expect(trigger()).toHaveFocus();
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
  });

  it("Tab closes it and moves on from the trigger; Shift+Tab moves back from it", async () => {
    await renderMenu();
    await openWith("{Enter}");
    await userEvent.tab();
    expect(page.getByRole("button", { name: "After" })).toHaveFocus();
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    await openWith("{Enter}");
    await userEvent.tab({ shift: true });
    expect(page.getByRole("button", { name: "Before" })).toHaveFocus();
  });
});

describe("Menu (CMP-041) items", () => {
  const states: MenuItem[] = [
    { id: "plain", label: "Export", disabled: true, onSelect: noop },
    {
      id: "gated",
      label: "Edit risk caps",
      disabledReason: "Only the owner can change account settings.",
      onSelect: noop,
    },
    {
      id: "busy",
      label: "Flatten account",
      busy: true,
      opensConfirm: true,
      description: "Loading Sub-1 · LIVE…",
      onSelect: noop,
    },
  ];

  it("disabled, busy and gated items are reached by the arrows and never activated", async () => {
    const onSelect = fn();
    await renderMenu({ items: states.map((item) => ({ ...item, onSelect })) });
    await openWith("{Enter}");
    const plain = page.getByRole("menuitem", { name: "Export" });
    expect(plain).toHaveFocus();
    expect(plain).toHaveAttribute("aria-disabled", "true");
    await press("{Enter} ");
    await userEvent.click(plain);
    await press("{ArrowDown}");
    const gated = page.getByRole("menuitem", { name: "Edit risk caps" });
    expect(gated).toHaveFocus();
    await press("{Enter} ");
    await press("{ArrowDown}");
    const busy = page.getByRole("menuitem", { name: "Flatten account…" });
    expect(busy).toHaveFocus();
    expect(busy).toHaveAttribute("aria-busy", "true");
    expect(busy).not.toHaveAttribute("aria-disabled");
    await press("{Enter} ");
    expect(onSelect).not.toHaveBeenCalled();
    expect(menu()).toBeVisible();
  });

  it("a gated item: full name, the reason as its description in the DOM at mount, re-shown once per press", async () => {
    await renderMenu({ items: states });
    const gated = page.getByRole("menuitem", { name: "Edit risk caps", hidden: true });
    expect(gated).toHaveAttribute("aria-disabled", "true");
    expect(gated).toHaveAccessibleDescription("Only the owner can change account settings.");
    const status = page.getByRole("status");
    expect(status).toHaveTextContent("");
    await openWith("{Enter}");
    await press("{ArrowDown}");
    expect(status).toHaveTextContent("");
    await press("{Enter}");
    expect(status).toHaveTextContent("Only the owner can change account settings.");
    await press("{ArrowDown}");
    expect(status).toHaveTextContent("");
  });

  it("a busy item is described by its host's line; the label ends with … when it opens a confirm", async () => {
    await renderMenu({ items: states });
    const busy = page.getByRole("menuitem", { name: "Flatten account…", hidden: true });
    expect(busy).toHaveAccessibleDescription("Loading Sub-1 · LIVE…");
  });

  it("a danger item moves into the last group, after a separator, described 'Destructive action'", async () => {
    await renderMenu();
    await openWith("{Enter}");
    const groups = within(menu()).getAllByRole("group");
    expect(groups).toHaveLength(2);
    expect(within(menu()).getAllByRole("separator")).toHaveLength(1);
    const remove = within(groups[1] as HTMLElement).getByRole("menuitem", { name: "Remove" });
    expect(remove).toHaveAccessibleDescription("Destructive action");
    expect(remove.closest(".cv-menu__row")).toHaveAttribute("data-danger");
  });

  it("shortcuts trail through Kbd (hidden) and aria-keyshortcuts", async () => {
    await renderMenu();
    await openWith("{Enter}");
    const dup = page.getByRole("menuitem", { name: "Duplicate" });
    expect(dup).toHaveAttribute("aria-keyshortcuts", "Control+D");
    expect(page.getByRole("menuitem", { name: "Remove" })).toHaveAttribute(
      "aria-keyshortcuts",
      "Delete",
    );
    expect(dup.closest(".cv-menu__row")?.querySelector("kbd")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
  });

  it("groups are named by their caption", async () => {
    const items: MenuItem[] = [
      {
        id: "lin",
        label: "Linear",
        kind: "radio",
        group: { id: "m", label: "Scale mode" },
        onSelect: noop,
      },
      {
        id: "log",
        label: "Log",
        kind: "radio",
        checked: true,
        group: { id: "m", label: "Scale mode" },
        onSelect: noop,
      },
      { id: "lock", label: "Lock", kind: "checkbox", group: { id: "o" }, onSelect: noop },
    ];
    await renderMenu({ items });
    await openWith("{Enter}");
    expect(within(menu()).getByRole("group", { name: "Scale mode" })).toBeVisible();
    // Not every item is a radio: it opens on its first item.
    expect(page.getByRole("menuitemradio", { name: "Linear" })).toHaveFocus();
  });
});

describe("Menu (CMP-041) dismissal and layers", () => {
  it("an outside press closes it", async () => {
    await renderMenu();
    await openWith("{Enter}");
    await userEvent.click(page.getByRole("button", { name: "After" }));
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
  });

  it("controlled: the host's open state wins, and the change is reported", async () => {
    const changes: boolean[] = [];
    function Host(): JSX.Element {
      const [open, setOpen] = useState(false);
      return (
        <Menu
          open={open}
          onOpenChange={(next) => {
            changes.push(next);
            setOpen(next);
          }}
          trigger={<Button>Row actions</Button>}
          items={treeRow()}
        />
      );
    }
    await mount(<Host />);
    await openWith("{ArrowDown}");
    expect(focused()).toContain("Duplicate");
    await press("{Escape}");
    expect(changes).toEqual([true, false]);
  });

  it("inside a Dialog, Esc closes only the menu; the next Esc closes the dialog", async () => {
    const onDialog = fn();
    await mount(
      <Dialog open title="Chart settings" onOpenChange={onDialog}>
        <Menu trigger={<Button>Row actions</Button>} items={treeRow()} />
      </Dialog>,
    );
    await openWith("{Enter}");
    // It portals into the dialog's layer: inside the trap's scope, outside the inert page.
    expect(menu().closest(".cv-dialog-layer")).not.toBeNull();
    await press("{Escape}");
    expect(trigger()).toHaveFocus();
    expect(onDialog).not.toHaveBeenCalled();
    await act(async () => {
      await press("{Escape}");
    });
    expect(onDialog).toHaveBeenCalledWith(false, "escape");
  });
});
