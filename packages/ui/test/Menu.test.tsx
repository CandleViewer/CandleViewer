// @vitest-environment jsdom
import { act, useRef, useState, type JSX } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { afterEach, describe, it, vi } from "vitest";
import {
  Button,
  Dialog,
  Menu,
  formatRbacReason,
  type MenuActionItem,
  type MenuAnchor,
  type MenuButtonProps,
  type MenuItem,
} from "../src/components/index.js";
import { seriousViolations } from "./axe.js";
import { holdEnter } from "./heldEnter.js";
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

const renderMenu = async (props: Partial<MenuButtonProps> = {}): Promise<HTMLElement> =>
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

/** Lets a macrotask pass (the menu's report and context-key windows end there). */
const tick = async (): Promise<void> => {
  await act(async () => {
    await new Promise<void>((resolve) => {
      setTimeout(resolve, 0);
    });
  });
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

  it("a pointer click on a checkable item behaves like Enter: it toggles and closes", async () => {
    const onSelect = fn();
    const items: MenuItem[] = [
      { id: "lock", label: "Lock scale", kind: "checkbox", checked: true, onSelect },
    ];
    await renderMenu({ items });
    await openWith("{Enter}");
    await userEvent.click(page.getByRole("menuitemcheckbox", { name: "Lock scale" }));
    expect(onSelect).toHaveBeenCalledOnce();
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
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

  it("Shift+Tab with no earlier tab stop closes it and leaves focus on the trigger", async () => {
    await mount(<Menu trigger={<Button>Row actions</Button>} items={treeRow()} />);
    await openWith("{Enter}");
    await userEvent.tab({ shift: true });
    expect(trigger()).toHaveFocus();
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
  });
});

describe("Menu (CMP-041) items", () => {
  const states: MenuActionItem[] = [
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

  it("announceReason: no status region of its own; the host is handed the reason once per press", async () => {
    const announceReason = fn<(reason: string) => void>();
    await renderMenu({ items: states, announceReason });
    expect(page.queryByRole("status")).toBeNull();
    await openWith("{Enter}");
    expect(page.queryByRole("status")).toBeNull();
    await press("{ArrowDown}");
    expect(announceReason).not.toHaveBeenCalled();
    await press("{Enter}{Enter}");
    expect(announceReason.mock.calls).toEqual([
      ["Only the owner can change account settings."],
      ["Only the owner can change account settings."],
    ]);
    expect(page.queryByRole("status")).toBeNull();
  });

  it("a held Enter on a gated item hands the host its reason once, not once per repeat", async () => {
    const announceReason = fn<(reason: string) => void>();
    await renderMenu({ items: states, announceReason });
    await openWith("{Enter}");
    await press("{ArrowDown}");
    const gated = page.getByRole("menuitem", { name: "Edit risk caps", hidden: true });
    expect(gated).toHaveFocus();
    holdEnter(gated, 5);
    expect(announceReason.mock.calls).toEqual([["Only the owner can change account settings."]]);
  });

  it("hovering moves focus to the row's item, gated, disabled and busy rows too, without activating", async () => {
    const onSelect = fn();
    await renderMenu({ items: states.map((item) => ({ ...item, onSelect })) });
    await openWith("{Enter}");
    for (const name of ["Edit risk caps", "Flatten account…", "Export"]) {
      const item = page.getByRole("menuitem", { name });
      await userEvent.hover(item);
      expect(item).toHaveFocus();
    }
    expect(onSelect).not.toHaveBeenCalled();
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
  it("an outside press closes it once and leaves focus where the press lands", async () => {
    const onOpenChange = fn();
    await renderMenu({ onOpenChange });
    await openWith("{Enter}");
    const after = page.getByRole("button", { name: "After" });
    await userEvent.click(after);
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    expect(after).toHaveFocus();
    expect(onOpenChange.mock.calls).toEqual([[true], [false]]);
  });

  it("a press on the trigger while open closes it exactly once", async () => {
    const onOpenChange = fn();
    await renderMenu({ onOpenChange });
    await userEvent.click(trigger());
    await userEvent.click(trigger());
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    expect(onOpenChange.mock.calls).toEqual([[true], [false]]);
  });

  it("focus leaving the menu closes it and stays where it went", async () => {
    const onOpenChange = fn();
    await renderMenu({ onOpenChange });
    await openWith("{Enter}");
    const after = page.getByRole("button", { name: "After" });
    act(() => after.focus());
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    expect(after).toHaveFocus();
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
  });

  it("focus moving into a layer opened above it does not close it", async () => {
    function Host(): JSX.Element {
      const [dialog, setDialog] = useState(false);
      const items: MenuItem[] = [
        { id: "cfg", label: "Configure", kind: "checkbox", onSelect: () => setDialog(true) },
      ];
      return (
        <>
          <Menu trigger={<Button>Row actions</Button>} items={items} />
          <Dialog open={dialog} title="Configure" onOpenChange={setDialog}>
            <Button>Inside</Button>
          </Dialog>
        </>
      );
    }
    await mount(<Host />);
    await openWith("{Enter}");
    await act(async () => {
      await press(" ");
    });
    const dialog = page.getByRole("dialog", { name: "Configure" });
    expect(dialog.contains(document.activeElement)).toBe(true);
    // The page under the dialog is inert, so the trigger is out of the accessibility tree.
    const button = page.getByRole("button", { name: "Row actions", hidden: true });
    expect(button).toHaveAttribute("aria-expanded", "true");
  });

  it("a trigger remounted while a controlled menu is open still takes focus back", async () => {
    let rekey = noop;
    function Host(): JSX.Element {
      const [open, setOpen] = useState(false);
      const [key, setKey] = useState(0);
      rekey = () => setKey((k) => k + 1);
      return (
        <Menu
          open={open}
          onOpenChange={setOpen}
          trigger={<Button key={key}>Row actions</Button>}
          items={treeRow()}
        />
      );
    }
    await mount(<Host />);
    await openWith("{Enter}");
    const first = trigger();
    act(() => rekey());
    expect(trigger()).not.toBe(first);
    await press("{Escape}");
    expect(trigger()).toHaveFocus();
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

  it("controlled: a host that refuses the close still hears the next outside press", async () => {
    const onOpenChange = fn();
    await mount(
      <div>
        <Menu
          open
          onOpenChange={onOpenChange}
          trigger={<Button>Row actions</Button>}
          items={treeRow()}
        />
        <Button>After</Button>
      </div>,
    );
    const after = page.getByRole("button", { name: "After" });
    await userEvent.click(after);
    expect(onOpenChange.mock.calls).toEqual([[false]]);
    await tick();
    await userEvent.click(after);
    expect(onOpenChange.mock.calls).toEqual([[false], [false]]);
    expect(menu()).toBeVisible();
  });

  it("unmounting while open removes its outside-press listener and its layer", async () => {
    const onOpenChange = fn();
    const onDialog = fn();
    let hide = noop;
    function Host(): JSX.Element {
      const [show, setShow] = useState(true);
      hide = () => setShow(false);
      return show ? (
        <Menu
          trigger={<Button>Row actions</Button>}
          items={alertRow()}
          onOpenChange={onOpenChange}
        />
      ) : (
        <Dialog open title="Chart settings" onOpenChange={onDialog}>
          <Button>Inside</Button>
        </Dialog>
      );
    }
    await mount(<Host />);
    await openWith("{Enter}");
    await press("{ArrowDown}{ArrowRight}");
    expect(onOpenChange.mock.calls).toEqual([[true]]);
    await act(async () => hide());
    await userEvent.click(page.getByRole("button", { name: "Inside" }));
    expect(onOpenChange.mock.calls).toEqual([[true]]);
    // Neither menu level is left on the layer stack: Esc reaches the dialog.
    await press("{Escape}");
    expect(onDialog).toHaveBeenCalledWith(false, "escape");
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

/** E40's alert row menu: Snooze opens its presets (KM-5). */
const alertRow = (onSelect = noop, snooze: Partial<MenuItem> = {}): MenuItem[] => [
  { id: "ack", label: "Acknowledge", onSelect },
  {
    id: "snooze",
    label: "Snooze",
    items: [
      { id: "15m", label: "15 m", onSelect },
      { id: "1h", label: "1 h", onSelect },
      { id: "tomorrow", label: "Until tomorrow", onSelect },
    ],
    ...(snooze as object),
  },
  { id: "mute", label: "Mute", onSelect },
];

const keyOn = async (
  target: Element,
  key: string,
  init: KeyboardEventInit = {},
): Promise<boolean> => {
  let passed = true;
  await act(async () => {
    passed = target.dispatchEvent(
      new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init }),
    );
  });
  return passed;
};

describe("Menu (CMP-041) submenus", () => {
  const snoozeItem = (): HTMLElement => page.getByRole("menuitem", { name: "Snooze" });
  const submenu = (): HTMLElement | null => page.queryByRole("menu", { name: "Snooze" });

  it("a submenu item has haspopup and expanded; → opens it on its first item, named by the item", async () => {
    await renderMenu({ items: alertRow() });
    await openWith("{Enter}");
    await press("{ArrowDown}");
    expect(snoozeItem()).toHaveAttribute("aria-haspopup", "menu");
    expect(snoozeItem()).toHaveAttribute("aria-expanded", "false");
    expect(submenu()).toBeNull();
    await press("{ArrowRight}");
    expect(snoozeItem()).toHaveAttribute("aria-expanded", "true");
    expect(snoozeItem()).toHaveAttribute("aria-controls", submenu()?.id);
    expect(page.getByRole("menuitem", { name: "15 m" })).toHaveFocus();
    expect(menu()).toBeVisible();
  });

  it.each(["{Enter}", " "])("%s on a submenu item opens it too", async (key) => {
    await renderMenu({ items: alertRow() });
    await openWith("{Enter}");
    await press("{ArrowDown}");
    await press(key);
    expect(page.getByRole("menuitem", { name: "15 m" })).toHaveFocus();
  });

  it("the arrows wrap inside the submenu; ← closes it alone, focus back on its item", async () => {
    await renderMenu({ items: alertRow() });
    await openWith("{Enter}");
    await press("{ArrowDown}{ArrowRight}{ArrowUp}");
    expect(focused()).toBe("Until tomorrow");
    await press("{ArrowDown}");
    expect(focused()).toBe("15 m");
    await press("{ArrowLeft}");
    expect(submenu()).toBeNull();
    expect(snoozeItem()).toHaveFocus();
    expect(snoozeItem()).toHaveAttribute("aria-expanded", "false");
    expect(menu()).toBeVisible();
  });

  it("Esc closes only the submenu; the next Esc closes the menu, focus on the trigger", async () => {
    const onOpenChange = fn();
    await renderMenu({ items: alertRow(), onOpenChange });
    await openWith("{Enter}");
    await press("{ArrowDown}{ArrowRight}{Escape}");
    expect(submenu()).toBeNull();
    expect(snoozeItem()).toHaveFocus();
    expect(onOpenChange.mock.calls).toEqual([[true]]);
    await press("{Escape}");
    expect(trigger()).toHaveFocus();
    expect(onOpenChange.mock.calls).toEqual([[true], [false]]);
  });

  it("the layer stack: an Esc that reaches the document closes only the submenu", async () => {
    await renderMenu({ items: alertRow() });
    await openWith("{Enter}");
    await press("{ArrowDown}{ArrowRight}");
    await keyOn(document.body, "Escape");
    expect(submenu()).toBeNull();
    expect(snoozeItem()).toHaveFocus();
    expect(menu()).toBeVisible();
  });

  it("→ and ← do nothing on a plain item of the menu itself", async () => {
    await renderMenu({ items: alertRow() });
    await openWith("{Enter}");
    await press("{ArrowRight}");
    expect(focused()).toBe("Acknowledge");
    await press("{ArrowLeft}");
    expect(focused()).toBe("Acknowledge");
    expect(menu()).toBeVisible();
  });

  it("Enter on a submenu item activates it, closes every level and returns focus to the trigger", async () => {
    const onSelect = fn();
    const onOpenChange = fn();
    await renderMenu({ items: alertRow(onSelect), onOpenChange });
    await openWith("{Enter}");
    await press("{ArrowDown}{ArrowRight}{ArrowDown}{Enter}");
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(submenu()).toBeNull();
    expect(trigger()).toHaveFocus();
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    expect(onOpenChange.mock.calls).toEqual([[true], [false]]);
  });

  it("Tab in a submenu closes every level and moves on from the trigger", async () => {
    await renderMenu({ items: alertRow() });
    await openWith("{Enter}");
    await press("{ArrowDown}{ArrowRight}{Tab}");
    expect(submenu()).toBeNull();
    expect(page.getByRole("button", { name: "After" })).toHaveFocus();
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
  });

  it("a click opens it; the pointer on its own row keeps focus inside; another row closes it", async () => {
    await renderMenu({ items: alertRow() });
    await userEvent.click(trigger());
    await userEvent.click(snoozeItem());
    expect(page.getByRole("menuitem", { name: "15 m" })).toHaveFocus();
    await userEvent.hover(snoozeItem());
    expect(page.getByRole("menuitem", { name: "15 m" })).toHaveFocus();
    await userEvent.hover(page.getByRole("menuitem", { name: "Mute" }));
    expect(submenu()).toBeNull();
    expect(page.getByRole("menuitem", { name: "Mute" })).toHaveFocus();
    expect(menu()).toBeVisible();
  });

  it("an outside press with a submenu open closes every level once", async () => {
    const onOpenChange = fn();
    await renderMenu({ items: alertRow(), onOpenChange });
    await openWith("{Enter}");
    await press("{ArrowDown}{ArrowRight}");
    const after = page.getByRole("button", { name: "After" });
    await userEvent.click(after);
    expect(submenu()).toBeNull();
    expect(after).toHaveFocus();
    expect(onOpenChange.mock.calls).toEqual([[true], [false]]);
  });

  it("a gated submenu item never opens; a press re-shows its reason, a plain → does not", async () => {
    await renderMenu({
      items: alertRow(noop, { disabledReason: "Only the owner can snooze shared alerts." }),
    });
    await openWith("{Enter}");
    await press("{ArrowDown}{ArrowRight}");
    expect(submenu()).toBeNull();
    expect(snoozeItem()).toHaveFocus();
    expect(page.getByRole("status")).toHaveTextContent("");
    await press("{Enter}");
    expect(submenu()).toBeNull();
    expect(page.getByRole("status")).toHaveTextContent("Only the owner can snooze shared alerts.");
  });

  it("Home, End and type-ahead work inside a submenu", async () => {
    await renderMenu({ items: alertRow(), now: () => 1000 });
    await openWith("{Enter}");
    await press("{ArrowDown}{ArrowRight}{End}");
    expect(focused()).toBe("Until tomorrow");
    await press("{Home}");
    expect(focused()).toBe("15 m");
    await press("1");
    expect(focused()).toBe("1 h");
    await press("u");
    expect(focused()).toBe("1 h"); // "1u" matches nothing: focus stays
    expect(snoozeItem()).toHaveAttribute("aria-expanded", "true");
  });

  it("a reason inside a submenu still renders the status region", async () => {
    await renderMenu({
      items: [
        {
          id: "move",
          label: "Move to",
          items: [
            { id: "a", label: "Sub-1", disabledReason: "Not assigned to you.", onSelect: noop },
          ],
        },
      ],
    });
    await openWith("{Enter}{ArrowRight}{Enter}");
    expect(page.getByRole("status")).toHaveTextContent("Not assigned to you.");
  });
});

function ContextHost({
  onOpenChange,
  onSelect = noop,
  show = true,
  open,
}: {
  onOpenChange?: (open: boolean) => void;
  onSelect?: () => void;
  show?: boolean;
  open?: boolean;
}): JSX.Element {
  const target = useRef<HTMLDivElement>(null);
  return (
    <div>
      <Button>Before</Button>
      <div role="grid" aria-label="Watchlist">
        <div ref={target} tabIndex={0} role="row" aria-label="BTCUSDT row">
          <span role="gridcell">BTCUSDT</span>
          <span role="gridcell">
            <button type="button">Edit</button>
          </span>
        </div>
      </div>
      <Button>After</Button>
      {show ? (
        <Menu
          contextTarget={target}
          aria-label="BTCUSDT actions"
          items={alertRow(onSelect)}
          {...(onOpenChange === undefined ? {} : { onOpenChange })}
          {...(open === undefined ? {} : { open })}
        />
      ) : null}
    </div>
  );
}

describe("Menu (CMP-041) context menu", () => {
  const row = (): HTMLElement => page.getByRole("row", { name: "BTCUSDT row" });
  const contextMenu = (): HTMLElement | null =>
    page.queryByRole("menu", { name: "BTCUSDT actions" });

  it("renders no trigger; closed, its menu is hidden and named by aria-label", async () => {
    await mount(<ContextHost />);
    expect(page.queryByRole("button", { name: "BTCUSDT actions" })).toBeNull();
    const list = document.querySelector('[role="menu"]');
    expect(list).toHaveAttribute("aria-label", "BTCUSDT actions");
    expect(list).not.toHaveAttribute("aria-labelledby");
    expect(list).not.toBeVisible();
  });

  it("Shift+F10 on the focused element opens it on its first item; Esc returns focus there", async () => {
    await mount(<ContextHost />);
    act(() => row().focus());
    await press("{Shift>}{F10}{/Shift}");
    expect(contextMenu()).toBeVisible();
    expect(focused()).toBe("Acknowledge");
    await press("{Escape}");
    expect(contextMenu()).toBeNull();
    expect(row()).toHaveFocus();
  });

  it("the Menu key opens it, and the contextmenu event the key fires does not open it twice", async () => {
    const onOpenChange = fn();
    await mount(<ContextHost onOpenChange={onOpenChange} />);
    const edit = page.getByRole("button", { name: "Edit" });
    act(() => edit.focus());
    expect(await keyOn(edit, "ContextMenu")).toBe(false);
    expect(focused()).toBe("Acknowledge");
    let passed = true;
    await act(async () => {
      passed = edit.dispatchEvent(
        new MouseEvent("contextmenu", { bubbles: true, cancelable: true }),
      );
    });
    expect(passed).toBe(false);
    expect(onOpenChange.mock.calls).toEqual([[true]]);
    await press("{Escape}");
    expect(edit).toHaveFocus();
  });

  it("a modified F10 or another key does not open it", async () => {
    await mount(<ContextHost />);
    expect(await keyOn(row(), "F10")).toBe(true);
    expect(await keyOn(row(), "F10", { shiftKey: true, ctrlKey: true })).toBe(true);
    expect(contextMenu()).toBeNull();
  });

  it("a right-click opens it at the pointer instead of the browser's menu; focus returns to the pressed control", async () => {
    await mount(<ContextHost />);
    const edit = page.getByRole("button", { name: "Edit" });
    await userEvent.pointer({
      keys: "[MouseRight]",
      target: edit,
      coords: { clientX: 40, clientY: 60 },
    });
    expect(contextMenu()).toBeVisible();
    expect(focused()).toBe("Acknowledge");
    await press("{Escape}");
    expect(edit).toHaveFocus();
  });

  it("a right-click on plain text inside returns focus to the target itself", async () => {
    await mount(<ContextHost />);
    await userEvent.pointer({ keys: "[MouseRight]", target: page.getByText("BTCUSDT") });
    expect(contextMenu()).toBeVisible();
    await press("{Escape}");
    expect(row()).toHaveFocus();
  });

  it("activating an item closes it and returns focus to its origin before the host runs", async () => {
    let during: Element | null = null;
    const onSelect = fn(() => {
      during = document.activeElement;
    });
    await mount(<ContextHost onSelect={onSelect} />);
    act(() => row().focus());
    await press("{Shift>}{F10}{/Shift}{Enter}");
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(during).toBe(row());
    expect(contextMenu()).toBeNull();
  });

  it("Tab closes it and moves on from its origin (past the controls inside it)", async () => {
    await mount(<ContextHost />);
    act(() => row().focus());
    await press("{Shift>}{F10}{/Shift}{Tab}");
    expect(page.getByRole("button", { name: "After" })).toHaveFocus();
    expect(contextMenu()).toBeNull();
  });

  it("a submenu opens inside it, and Esc closes only the submenu", async () => {
    await mount(<ContextHost />);
    act(() => row().focus());
    await press("{Shift>}{F10}{/Shift}{ArrowDown}{ArrowRight}");
    expect(focused()).toBe("15 m");
    await press("{Escape}");
    expect(page.queryByRole("menu", { name: "Snooze" })).toBeNull();
    expect(focused()).toBe("Snooze");
    expect(contextMenu()).toBeVisible();
  });

  it("a second right-click while open closes it and opens it again", async () => {
    const onOpenChange = fn();
    await mount(<ContextHost onOpenChange={onOpenChange} />);
    const edit = page.getByRole("button", { name: "Edit" });
    await userEvent.pointer({ keys: "[MouseRight]", target: edit });
    await userEvent.pointer({ keys: "[MouseRight]", target: page.getByText("BTCUSDT") });
    expect(contextMenu()).toBeVisible();
    expect(onOpenChange.mock.calls).toEqual([[true], [false], [true]]);
  });

  it("controlled open with no event anchors to the target and returns focus to it", async () => {
    let close = noop;
    function Host(): JSX.Element {
      const [open, setOpen] = useState(true);
      close = () => setOpen(false);
      return <ContextHost open={open} onOpenChange={setOpen} />;
    }
    await mount(<Host />);
    expect(focused()).toBe("Acknowledge");
    await act(async () => close());
    expect(row()).toHaveFocus();
  });

  it("after the key is released, a contextmenu with no press is not swallowed", async () => {
    const onOpenChange = fn();
    await mount(<ContextHost onOpenChange={onOpenChange} />);
    act(() => row().focus());
    await press("{Shift>}{F10}{/Shift}");
    await tick();
    await press("{Escape}");
    expect(row()).toHaveFocus();
    await act(async () => {
      row().dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
    });
    expect(contextMenu()).toBeVisible();
    expect(onOpenChange.mock.calls).toEqual([[true], [false], [true]]);
  });

  it("a target mounted after the menu is bound on the menu's next render", async () => {
    function Late(): JSX.Element {
      const target = useRef<HTMLDivElement>(null);
      const [shown, setShown] = useState(false);
      return (
        <div>
          <Button onClick={() => setShown(true)}>Show row</Button>
          {shown ? (
            <div ref={target} tabIndex={0} role="row" aria-label="BTCUSDT row">
              BTCUSDT
            </div>
          ) : null}
          <Menu contextTarget={target} aria-label="BTCUSDT actions" items={alertRow()} />
        </div>
      );
    }
    await mount(<Late />);
    await userEvent.click(page.getByRole("button", { name: "Show row" }));
    act(() => row().focus());
    await press("{Shift>}{F10}{/Shift}");
    expect(contextMenu()).toBeVisible();
  });

  it("unmounting removes its listeners: the keys and the right-click reach the page again", async () => {
    let hide = noop;
    function Host(): JSX.Element {
      const [show, setShow] = useState(true);
      hide = () => setShow(false);
      return <ContextHost show={show} />;
    }
    await mount(<Host />);
    await act(async () => hide());
    expect(await keyOn(row(), "F10", { shiftKey: true })).toBe(true);
    let passed = false;
    await act(async () => {
      passed = row().dispatchEvent(
        new MouseEvent("contextmenu", { bubbles: true, cancelable: true }),
      );
    });
    expect(passed).toBe(true);
  });
});

describe("Menu (CMP-041) host-opened (E08-D05 A-D05-13)", () => {
  const RECORD = formatRbacReason("rbac.owner_only", { verb: "start recording" });
  let openAt: (anchor: MenuAnchor) => void = noop;
  afterEach(() => {
    vi.restoreAllMocks();
  });

  /** SCR-102's shape: focus stays in the input; the host opens the menu at what it names. */
  function Hosted({ onSelect = noop }: { onSelect?: () => void }): JSX.Element {
    const [shown, setShown] = useState<{ anchor: MenuAnchor; open: boolean } | null>(null);
    openAt = (anchor) => setShown({ anchor, open: true });
    const items: MenuItem[] = [
      { id: "open", label: "Open in Chart 1", onSelect },
      { id: "record", label: "Record this symbol…", disabledReason: RECORD, onSelect },
    ];
    return (
      <div>
        <input aria-label="Search symbols" />
        <div>ETHUSDT</div>
        <Button>After</Button>
        {shown === null ? null : (
          <Menu
            anchor={shown.anchor}
            open={shown.open}
            onOpenChange={(next) => setShown({ ...shown, open: next })}
            aria-label="Actions for ETHUSDT"
            items={items}
          />
        )}
      </div>
    );
  }
  const input = (): HTMLElement => page.getByRole("textbox", { name: "Search symbols" });
  const option = (): HTMLElement => page.getByText("ETHUSDT");

  it("no trigger: it opens when the host says; focus returns where it was at each opening", async () => {
    let during: Element | null = null;
    const onSelect = fn(() => {
      during = document.activeElement;
    });
    await mount(<Hosted onSelect={onSelect} />);
    act(() => input().focus());
    await act(async () => openAt(option()));
    expect(page.getByRole("menu", { name: "Actions for ETHUSDT" })).toBeVisible();
    expect(page.queryByRole("button", { name: "Actions for ETHUSDT" })).toBeNull();
    expect(focused()).toBe("Open in Chart 1");
    await press("{Escape}");
    expect(input()).toHaveFocus();
    expect(page.queryByRole("menu", { name: "Actions for ETHUSDT" })).toBeNull();
    const after = page.getByRole("button", { name: "After" });
    act(() => after.focus());
    await act(async () => openAt(option()));
    await press("{Enter}");
    expect([onSelect.mock.calls.length, during, document.activeElement]).toEqual([1, after, after]);
  });

  it("positioned below the anchor's start: an element (the active option), or a rect (the pointer)", async () => {
    // jsdom's viewport is 0 × 0, which would flip and shift every placement: give it a window's room.
    vi.spyOn(document.documentElement, "clientWidth", "get").mockReturnValue(1024);
    vi.spyOn(document.documentElement, "clientHeight", "get").mockReturnValue(768);
    await mount(<Hosted />);
    // jsdom lays nothing out: the option's box, as a host would measure it.
    const box = {
      x: 40,
      y: 100,
      width: 200,
      height: 24,
      top: 100,
      left: 40,
      right: 240,
      bottom: 124,
    };
    vi.spyOn(option(), "getBoundingClientRect").mockReturnValue(box as DOMRect);
    await act(async () => openAt(option()));
    const menu = page.getByRole("menu", { name: "Actions for ETHUSDT" });
    await waitFor(() => expect([menu.style.left, menu.style.top]).toEqual(["40px", "124px"]));
    await press("{Escape}");
    await act(async () => openAt({ x: 300, y: 200, width: 0, height: 0 }));
    await waitFor(() => expect([menu.style.left, menu.style.top]).toEqual(["300px", "200px"]));
  });

  it("a T2 item: reached by the arrows, aria-disabled, described by its reason; inert, re-said per press", async () => {
    const onSelect = fn();
    await mount(<Hosted onSelect={onSelect} />);
    act(() => input().focus());
    await act(async () => openAt(option()));
    await press("{ArrowDown}");
    const record = page.getByRole("menuitem", { name: "Record this symbol…" });
    expect([document.activeElement, record.getAttribute("aria-disabled")]).toEqual([
      record,
      "true",
    ]);
    expect(record).toHaveAccessibleDescription(RECORD);
    await press("{Enter} ");
    expect([onSelect.mock.calls.length, document.activeElement]).toEqual([0, record]);
    expect(page.getByRole("status")).toHaveTextContent(RECORD);
    expect(await seriousViolations(document.body)).toEqual([]);
    await press("{Escape}"); // the press re-rendered the open menu: its origin is still the input
    expect(input()).toHaveFocus();
  });

  it("type: a host-opened menu is controlled and named; an anchor is never a trigger's", () => {
    const el = document.createElement("div");
    // @ts-expect-error the host opens it: `open` is required
    const uncontrolled = <Menu anchor={el} aria-label="x" items={[]} />;
    // @ts-expect-error no trigger names it: `aria-label` is required
    const unnamed = <Menu anchor={el} open items={[]} />;
    // @ts-expect-error an anchor excludes a trigger
    const both = <Menu anchor={el} open aria-label="x" trigger={<Button>x</Button>} items={[]} />;
    expect([uncontrolled, unnamed, both]).toHaveLength(3);
  });
});
