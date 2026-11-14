// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useState, type JSX } from "react";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { describe, expectTypeOf, it, onTestFinished, vi } from "vitest";
import * as Entry from "../src/index.js";
import { IconButton } from "../src/components/IconButton.js";
import { TreeView, type TreeNode, type TreeViewProps } from "../src/components/TreeView.js";
import * as stories from "../src/components/TreeView.stories.js";
import { seriousViolations } from "./axe.js";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";
import { mount } from "./theme/mount.js";

const NODES: readonly TreeNode[] = [
  {
    id: "overlays",
    label: "Overlays",
    children: [
      { id: "ema21", label: "EMA 21" },
      { id: "ema50", label: "EMA 50" },
      { id: "vwap", label: "VWAP" },
    ],
  },
  {
    id: "subpanes",
    label: "Sub-panes",
    children: [{ id: "pane", label: "RSI pane", children: [{ id: "rsi", label: "RSI 14" }] }],
  },
  { id: "drawings", label: "Drawings", children: [{ id: "trend", label: "Trend line" }] },
];

type Spies = Pick<TreeViewProps, "onToggle" | "onSelect" | "onRename" | "onMove">;

/** A host that owns `expanded` and `selected` and reports every call to the spies. */
function Host(
  props: Partial<Omit<TreeViewProps, "aria-label" | "aria-labelledby">> & {
    readonly spies: Spies;
    readonly open?: readonly string[];
  },
): JSX.Element {
  const { spies, open = ["overlays"], ...rest } = props;
  const [expanded, setExpanded] = useState(open);
  const [selected, setSelected] = useState<readonly string[]>(rest.selected ?? []);
  return (
    <TreeView
      aria-label="Objects"
      nodes={NODES}
      itemActions={() => null}
      {...rest}
      expanded={expanded}
      selected={selected}
      onToggle={(id, next) => {
        spies.onToggle(id, next);
        setExpanded((now) => (next ? [...now, id] : now.filter((e) => e !== id)));
      }}
      onSelect={(ids) => {
        spies.onSelect(ids);
        setSelected(ids);
      }}
    />
  );
}

const spies = (): Spies & { onToggle: ReturnType<typeof fn>; onSelect: ReturnType<typeof fn> } => ({
  onToggle: fn(),
  onSelect: fn(),
});
const item = (host: HTMLElement, name: string): HTMLElement =>
  within(host).getByRole("treeitem", { name });
const selectedNames = (host: HTMLElement): string[] =>
  within(host)
    .getAllByRole("treeitem")
    .filter((el) => el.getAttribute("aria-selected") === "true")
    .map((el) => el.querySelector(".cv-tree__label")?.textContent ?? "");

/** Records the keys that reach the host above the tree (a native listener on the body, removed after the test). */
const keysAbove = (): ReturnType<typeof fn> => {
  const onKey = fn();
  const listener = (event: KeyboardEvent): void => onKey(event.key, event.defaultPrevented);
  document.body.addEventListener("keydown", listener);
  onTestFinished(() => document.body.removeEventListener("keydown", listener));
  return onKey;
};

describe("TreeView (CMP-240): APG tree semantics", () => {
  it("is exported from the package entry", () => {
    expect(Entry.TreeView).toBe(TreeView);
  });

  it("names the tree and gives each item its level, set size, position, expansion and selection", async () => {
    const host = await mount(<Host spies={spies()} open={["overlays", "subpanes", "pane"]} />);
    const tree = within(host).getByRole("tree", { name: "Objects" });
    expect(tree).toHaveAttribute("data-cmp", "CMP-240");
    expect(tree).not.toHaveAttribute("aria-multiselectable");
    const ema50 = item(host, "EMA 50");
    expect([
      ema50.getAttribute("aria-level"),
      ema50.getAttribute("aria-setsize"),
      ema50.getAttribute("aria-posinset"),
      ema50.getAttribute("aria-selected"),
      ema50.hasAttribute("aria-expanded"),
    ]).toEqual(["2", "3", "2", "false", false]);
    expect(item(host, "RSI 14")).toHaveAttribute("aria-level", "3");
    expect(item(host, "Overlays")).toHaveAttribute("aria-expanded", "true");
    expect(item(host, "Drawings")).toHaveAttribute("aria-expanded", "false");
    expect(within(host).getAllByRole("group")).toHaveLength(3);
  });

  it("is one roving Tab stop: the first item, and Tab leaves the tree", async () => {
    const host = await mount(
      <div>
        <Host spies={spies()} />
        <button type="button">After</button>
      </div>,
    );
    expect(
      within(host)
        .getAllByRole("treeitem")
        .filter((el) => el.tabIndex === 0),
    ).toHaveLength(1);
    await userEvent.tab();
    expect(item(host, "Overlays")).toHaveFocus();
    await userEvent.tab();
    expect(within(host).getByRole("button", { name: "After" })).toHaveFocus();
  });

  it("draws nothing for no nodes: the host's empty state replaces the body (D23)", async () => {
    const host = await mount(
      <TreeView
        aria-label="Objects"
        nodes={[]}
        expanded={[]}
        onToggle={fn()}
        selected={[]}
        onSelect={fn()}
        itemActions={() => null}
      />,
    );
    expect(host.querySelector('[role="tree"]')).toBeNull();
  });
});

describe("TreeView: the APG keys", () => {
  it("↓ / ↑ move between visible items, Home / End jump; single-select follows focus", async () => {
    const s = spies();
    const host = await mount(<Host spies={s} />);
    item(host, "Overlays").focus();
    await userEvent.keyboard("{ArrowDown}{ArrowDown}");
    expect(item(host, "EMA 50")).toHaveFocus();
    expect(s.onSelect).toHaveBeenLastCalledWith(["ema50"]);
    await userEvent.keyboard("{ArrowUp}");
    expect(item(host, "EMA 21")).toHaveFocus();
    await userEvent.keyboard("{End}");
    expect(item(host, "Drawings")).toHaveFocus();
    await userEvent.keyboard("{Home}");
    expect(item(host, "Overlays")).toHaveFocus();
    expect(item(host, "Overlays").tabIndex).toBe(0);
    expect(item(host, "EMA 21").tabIndex).toBe(-1);
  });

  it("→ opens a closed parent, then moves to its first child; ← closes it, and from a child goes to the parent", async () => {
    const s = spies();
    const host = await mount(<Host spies={s} open={[]} />);
    item(host, "Sub-panes").focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(s.onToggle).toHaveBeenLastCalledWith("subpanes", true);
    expect(item(host, "Sub-panes")).toHaveFocus();
    await userEvent.keyboard("{ArrowRight}");
    expect(item(host, "RSI pane")).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(item(host, "Sub-panes")).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(s.onToggle).toHaveBeenLastCalledWith("subpanes", false);
    expect(within(host).queryByRole("treeitem", { name: "RSI pane" })).toBeNull();
  });

  it("→ and ← on a leaf open nothing", async () => {
    const s = spies();
    const host = await mount(<Host spies={s} />);
    item(host, "VWAP").focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(s.onToggle).not.toHaveBeenCalled();
    expect(item(host, "VWAP")).toHaveFocus();
  });

  it("* opens every closed sibling parent of the focused item", async () => {
    const s = spies();
    const host = await mount(<Host spies={s} open={[]} />);
    item(host, "Overlays").focus();
    await userEvent.keyboard("*");
    expect(s.onToggle.mock.calls).toEqual([
      ["overlays", true],
      ["subpanes", true],
      ["drawings", true],
    ]);
  });

  /** A frozen clock: every key lands inside the 500 ms type-ahead window, however slow the machine. */
  const freezeClock = (): void => {
    const now = vi.spyOn(Date, "now").mockReturnValue(1_000);
    onTestFinished(() => now.mockRestore());
  };

  it("type-ahead focuses the next item whose label starts with the typed characters", async () => {
    freezeClock();
    const host = await mount(<Host spies={spies()} />);
    item(host, "Overlays").focus();
    await userEvent.keyboard("e");
    expect(item(host, "EMA 21")).toHaveFocus();
    await userEvent.keyboard("e");
    expect(item(host, "EMA 50")).toHaveFocus();
  });

  it("type-ahead joins characters typed together into one search string, and a pause starts afresh", async () => {
    const now = vi.spyOn(Date, "now").mockReturnValue(1_000);
    onTestFinished(() => now.mockRestore());
    const host = await mount(<Host spies={spies()} />);
    item(host, "Overlays").focus();
    await userEvent.keyboard("dr");
    expect(item(host, "Drawings")).toHaveFocus();
    now.mockReturnValue(2_000);
    await userEvent.keyboard("v");
    expect(item(host, "VWAP")).toHaveFocus();
  });

  it("a press on a parent's disclosure toggles it; a press on a row selects and focuses it", async () => {
    const s = spies();
    const host = await mount(<Host spies={s} />);
    const disclosure = item(host, "Drawings").querySelector(".cv-tree__disclosure");
    await userEvent.click(disclosure ?? host);
    expect(s.onToggle).toHaveBeenLastCalledWith("drawings", true);
    await userEvent.click(within(host).getByText("VWAP"));
    expect(s.onSelect).toHaveBeenLastCalledWith(["vwap"]);
    expect(item(host, "VWAP")).toHaveFocus();
  });

  it("a parent closed over the focused item hands the roving stop to that parent", async () => {
    const host = await mount(<Host spies={spies()} />);
    item(host, "EMA 21").focus();
    await userEvent.click(item(host, "Overlays").querySelector(".cv-tree__disclosure") ?? host);
    expect(item(host, "Overlays").tabIndex).toBe(0);
  });
});

describe("TreeView: platform chords keep their defaults", () => {
  /** Fires one key on the item; true when its default survived (`dispatchEvent` returns false once prevented). */
  const press = async (
    el: HTMLElement,
    key: string,
    init: KeyboardEventInit = {},
  ): Promise<boolean> => fireEvent.keyDown(el, { key, ...init });

  it("Alt/Cmd+←/→, Ctrl/Cmd+Home/End and Alt+↑/↓ without onMove act on nothing and keep their default", async () => {
    const s = spies();
    const host = await mount(<Host spies={s} open={["overlays", "subpanes"]} />);
    const overlays = item(host, "Overlays");
    overlays.focus();
    const chords: [string, KeyboardEventInit][] = [
      ["ArrowLeft", { altKey: true }],
      ["ArrowRight", { altKey: true }],
      ["ArrowLeft", { metaKey: true }],
      ["ArrowRight", { metaKey: true }],
      ["Home", { ctrlKey: true }],
      ["End", { ctrlKey: true }],
      ["Home", { metaKey: true }],
      ["End", { metaKey: true }],
      ["ArrowDown", { altKey: true }],
      ["ArrowUp", { altKey: true }],
      ["ArrowDown", { ctrlKey: true }],
      ["*", { ctrlKey: true }],
      ["F2", { altKey: true }],
    ];
    const kept = [];
    for (const [key, init] of chords) kept.push(await press(overlays, key, init));
    expect(kept).toEqual(chords.map(() => true));
    expect(s.onToggle).not.toHaveBeenCalled();
    expect(s.onSelect).not.toHaveBeenCalled();
    expect(overlays).toHaveFocus();
  });

  it("Ctrl/Alt/Cmd+letter is the platform's shortcut, never type-ahead", async () => {
    const s = spies();
    const host = await mount(<Host spies={s} />);
    const overlays = item(host, "Overlays");
    overlays.focus();
    for (const init of [{ ctrlKey: true }, { altKey: true }, { metaKey: true }]) {
      expect(await press(overlays, "e", init)).toBe(true);
    }
    expect(overlays).toHaveFocus();
    expect(s.onSelect).not.toHaveBeenCalled();
  });

  it("in multi-select, Ctrl/Alt/Cmd+letter other than Ctrl/Cmd+A keeps its default and selects nothing", async () => {
    const s = spies();
    const host = await mount(<Host spies={s} multiSelect />);
    const overlays = item(host, "Overlays");
    overlays.focus();
    const chords: [string, KeyboardEventInit][] = [
      ["c", { ctrlKey: true }],
      ["c", { metaKey: true }],
      ["e", { ctrlKey: true }],
      ["v", { metaKey: true }],
      ["a", { altKey: true }],
      ["a", { ctrlKey: true, altKey: true }],
    ];
    const kept = [];
    for (const [key, init] of chords) kept.push(await press(overlays, key, init));
    expect(kept).toEqual(chords.map(() => true));
    expect(overlays).toHaveFocus();
    expect(s.onSelect).not.toHaveBeenCalled();
  });

  it("Ctrl/Cmd+Shift+A is not Ctrl+A: it keeps its default and selects nothing", async () => {
    const s = spies();
    const host = await mount(<Host spies={s} multiSelect />);
    const ema = item(host, "EMA 21");
    ema.focus();
    const kept = [
      await press(ema, "A", { ctrlKey: true, shiftKey: true }),
      await press(ema, "A", { metaKey: true, shiftKey: true }),
      await press(ema, "a", { metaKey: true, shiftKey: true }),
    ];
    expect(kept).toEqual([true, true, true]);
    expect(s.onSelect).not.toHaveBeenCalled();
  });

  it("Ctrl+Space and Ctrl+A belong to multi-select alone: in single-select they keep their default", async () => {
    const s = spies();
    const host = await mount(<Host spies={s} />);
    const ema = item(host, "EMA 21");
    ema.focus();
    expect(await press(ema, " ", { ctrlKey: true })).toBe(true);
    expect(await press(ema, "a", { ctrlKey: true })).toBe(true);
    expect(s.onSelect).not.toHaveBeenCalled();
  });

  it("the keys the tree acts on, and its declared chords, are prevented", async () => {
    const onMove = fn();
    const s = spies();
    const host = await mount(<Host spies={s} multiSelect onMove={onMove} />);
    const ema = item(host, "EMA 50");
    ema.focus();
    const kept = [
      await press(ema, "ArrowDown", { altKey: true }),
      await press(ema, " ", { ctrlKey: true }),
      await press(ema, "a", { metaKey: true }),
      await press(item(host, "EMA 50"), "Home"),
    ];
    expect(kept).toEqual([false, false, false, false]);
    expect(onMove).toHaveBeenCalledWith("ema50", 2);
    expect(s.onSelect.mock.calls).toEqual([[["ema50"]], [["ema21", "ema50", "vwap"]]]);
  });
});

describe("TreeView: SCR-036's multi-select (D22)", () => {
  it("marks the tree multiselectable; arrows move without selecting", async () => {
    const s = spies();
    const host = await mount(<Host spies={s} multiSelect />);
    expect(within(host).getByRole("tree")).toHaveAttribute("aria-multiselectable", "true");
    item(host, "EMA 21").focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(item(host, "EMA 50")).toHaveFocus();
    expect(s.onSelect).not.toHaveBeenCalled();
  });

  it("Ctrl+Space toggles the focused item; Shift+↓ extends from the anchor; Shift+Space selects a range", async () => {
    const host = await mount(<Host spies={spies()} multiSelect />);
    item(host, "EMA 21").focus();
    await userEvent.keyboard("{Control>} {/Control}");
    expect(selectedNames(host)).toEqual(["EMA 21"]);
    await userEvent.keyboard("{Shift>}{ArrowDown}{/Shift}");
    expect(selectedNames(host)).toEqual(["EMA 21", "EMA 50"]);
    await userEvent.keyboard("{ArrowDown}{Shift>} {/Shift}");
    expect(selectedNames(host)).toEqual(["EMA 21", "EMA 50", "VWAP"]);
    await userEvent.keyboard("{Control>} {/Control}");
    expect(selectedNames(host)).toEqual(["EMA 21", "EMA 50"]);
  });

  it("plain Space is the host's: the tree selects nothing and lets the key through", async () => {
    const onKey = keysAbove();
    const s = spies();
    const host = await mount(<Host spies={s} multiSelect />);
    item(host, "EMA 21").focus();
    await userEvent.keyboard(" ");
    expect(s.onSelect).not.toHaveBeenCalled();
    expect(onKey).toHaveBeenCalledWith(" ", false);
  });

  it("Ctrl+A selects the focused item's group; Esc clears a selection and stops there", async () => {
    const onKey = keysAbove();
    const host = await mount(<Host spies={spies()} multiSelect />);
    item(host, "EMA 50").focus();
    await userEvent.keyboard("{Control>}a{/Control}");
    expect(selectedNames(host)).toEqual(["EMA 21", "EMA 50", "VWAP"]);
    await userEvent.keyboard("{Escape}");
    expect(selectedNames(host)).toEqual([]);
    expect(onKey.mock.calls.map(([key]) => key)).not.toContain("Escape");
    await userEvent.keyboard("{Escape}");
    expect(onKey).toHaveBeenCalledWith("Escape", false);
  });

  it("Ctrl+click toggles, Shift+click selects a range, a plain click selects one", async () => {
    const host = await mount(<Host spies={spies()} multiSelect />);
    await userEvent.click(within(host).getByText("EMA 21"));
    await act(async () => fireEvent.click(within(host).getByText("VWAP"), { shiftKey: true }));
    expect(selectedNames(host)).toEqual(["EMA 21", "EMA 50", "VWAP"]);
    await act(async () => fireEvent.click(within(host).getByText("EMA 50"), { ctrlKey: true }));
    expect(selectedNames(host)).toEqual(["EMA 21", "VWAP"]);
    await userEvent.click(within(host).getByText("Drawings"));
    expect(selectedNames(host)).toEqual(["Drawings"]);
  });

  it("a selected item shows the check glyph beside the fill", async () => {
    const host = await mount(<Host spies={spies()} multiSelect selected={["ema50"]} />);
    expect(item(host, "EMA 50").querySelector(".cv-tree__check svg")).not.toBeNull();
    expect(item(host, "EMA 21").querySelector(".cv-tree__check svg")).toBeNull();
  });
});

describe("TreeView: rename and move exist only with their callbacks", () => {
  it("without onRename and onMove: F2 and Alt+↓ do nothing and no drag handle is drawn", async () => {
    const host = await mount(<Host spies={spies()} />);
    item(host, "EMA 21").focus();
    await userEvent.keyboard("{F2}{Alt>}{ArrowDown}{/Alt}");
    expect(within(host).queryByRole("textbox")).toBeNull();
    expect(host.querySelector(".cv-tree__handle")).toBeNull();
    expect(item(host, "EMA 21")).toHaveFocus();
  });

  it("F2 opens the field; Enter saves a changed, trimmed label and focus returns to the item", async () => {
    const onRename = fn();
    const host = await mount(<Host spies={spies()} onRename={onRename} />);
    item(host, "EMA 21").focus();
    await userEvent.keyboard("{F2}");
    const field = within(host).getByRole("textbox", { name: "Rename EMA 21" });
    expect(field).toHaveFocus();
    await userEvent.clear(field);
    await userEvent.type(field, "  Fast EMA {Enter}");
    expect(onRename).toHaveBeenCalledWith("ema21", "Fast EMA");
    expect(within(host).queryByRole("textbox")).toBeNull();
    expect(item(host, "EMA 21")).toHaveFocus();
  });

  it("Esc cancels without renaming and keeps the key from the host; a blank label is not saved", async () => {
    const onRename = fn();
    const onKey = keysAbove();
    const host = await mount(<Host spies={spies()} onRename={onRename} />);
    await userEvent.dblClick(within(host).getByText("EMA 21"));
    await userEvent.keyboard("{Escape}");
    expect(onKey.mock.calls.map(([key]) => key)).not.toContain("Escape");
    expect(item(host, "EMA 21")).toHaveFocus();
    await userEvent.keyboard("{F2}");
    await userEvent.clear(within(host).getByRole("textbox"));
    await userEvent.keyboard("{Enter}");
    expect(onRename).not.toHaveBeenCalled();
  });

  it("a blur fired as the field unmounts after Enter keeps focus on the item (Chrome blurs a removed node)", async () => {
    // jsdom drops focus silently when a node leaves the DOM; Chrome fires `blur` first. Model Chrome's order: the
    // field's blur must not cancel the saved rename's refocus.
    const removeChild = Node.prototype.removeChild;
    const spy = vi.spyOn(Node.prototype, "removeChild").mockImplementation(function <
      T extends Node,
    >(this: Node, child: T): T {
      const focused = document.activeElement;
      if (focused instanceof HTMLElement && child.contains(focused)) focused.blur();
      return removeChild.call(this, child) as T;
    });
    onTestFinished(() => spy.mockRestore());
    const onRename = fn();
    const host = await mount(<Host spies={spies()} onRename={onRename} />);
    item(host, "EMA 21").focus();
    await userEvent.keyboard("{F2}");
    await userEvent.type(within(host).getByRole("textbox"), "x{Enter}");
    expect(onRename).toHaveBeenCalledWith("ema21", "EMA 21x");
    expect(within(host).queryByRole("textbox")).toBeNull();
    expect(item(host, "EMA 21")).toHaveFocus();
  });

  it("a blur elsewhere cancels the rename", async () => {
    const onRename = fn();
    const host = await mount(
      <div>
        <Host spies={spies()} onRename={onRename} />
        <button type="button">After</button>
      </div>,
    );
    item(host, "EMA 21").focus();
    await userEvent.keyboard("{F2}x");
    await userEvent.click(within(host).getByRole("button", { name: "After" }));
    expect(within(host).queryByRole("textbox")).toBeNull();
    expect(onRename).not.toHaveBeenCalled();
  });

  it("a move the host ignores does not pull focus back on a later render, when focus is on an item action", async () => {
    const onMove = fn();
    function Ticking(): JSX.Element {
      const [ticks, setTicks] = useState(0);
      return (
        <Host
          spies={spies()}
          onMove={onMove}
          itemActions={(_node, { tabIndex }) => (
            <IconButton
              icon="copy"
              label={`Copy path ${String(ticks)}`}
              variant="ghost"
              tabIndex={tabIndex}
              onClick={() => setTicks((n) => n + 1)}
            />
          )}
        />
      );
    }
    const host = await mount(<Ticking />);
    const ema = item(host, "EMA 21");
    ema.focus();
    await userEvent.keyboard("{Alt>}{ArrowDown}{/Alt}");
    expect(onMove).toHaveBeenCalledTimes(1);
    await userEvent.tab();
    const copy = within(host).getAllByRole("button", { name: /^Copy path/ })[1];
    expect(copy).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(copy).toHaveFocus();
    expect(ema).not.toHaveFocus();
  });

  it("Alt+↑/↓ asks to move the item within its group, never past either end", async () => {
    const onMove = fn();
    const host = await mount(<Host spies={spies()} onMove={onMove} />);
    item(host, "EMA 21").focus();
    await userEvent.keyboard("{Alt>}{ArrowUp}{/Alt}");
    expect(onMove).not.toHaveBeenCalled();
    await userEvent.keyboard("{Alt>}{ArrowDown}{/Alt}");
    expect(onMove).toHaveBeenLastCalledWith("ema21", 1);
    item(host, "VWAP").focus();
    await userEvent.keyboard("{Alt>}{ArrowDown}{/Alt}{Alt>}{ArrowUp}{/Alt}");
    expect(onMove.mock.calls).toEqual([
      ["ema21", 1],
      ["vwap", 1],
    ]);
  });

  it("the drag handle drops an item on a sibling's place, never into another group", async () => {
    const onMove = fn();
    const host = await mount(
      <Host spies={spies()} onMove={onMove} open={["overlays", "drawings"]} />,
    );
    const handle = item(host, "VWAP").querySelector(".cv-tree__handle");
    const row = (name: string): Element => item(host, name).querySelector(".cv-tree__row") ?? host;
    const dataTransfer = { setData: fn(), effectAllowed: "" };
    expect(handle).toHaveAttribute("draggable", "true");
    expect(handle).toHaveAttribute("aria-hidden", "true");
    fireEvent.dragStart(handle ?? host, { dataTransfer });
    fireEvent.dragOver(row("Trend line"), { dataTransfer });
    fireEvent.drop(row("Trend line"), { dataTransfer });
    expect(onMove).not.toHaveBeenCalled();
    fireEvent.dragStart(handle ?? host, { dataTransfer });
    fireEvent.dragOver(row("EMA 21"), { dataTransfer });
    fireEvent.drop(row("EMA 21"), { dataTransfer });
    expect(onMove).toHaveBeenCalledWith("vwap", 0);
  });
});

describe("TreeView: the per-item action slot", () => {
  const copyPath: TreeViewProps["itemActions"] = (_node, { tabIndex }) => (
    <IconButton icon="copy" label="Copy path" variant="ghost" tabIndex={tabIndex} />
  );

  it("renders the slot per item; only the focused item's actions are in the Tab order", async () => {
    const host = await mount(<Host spies={spies()} itemActions={copyPath} />);
    const copies = within(host).getAllByRole("button", { name: "Copy path" });
    expect(copies).toHaveLength(6);
    expect(copies.map((b) => b.tabIndex)).toEqual([0, -1, -1, -1, -1, -1]);
    await userEvent.tab();
    await userEvent.tab();
    expect(copies[0]).toHaveFocus();
  });

  it("an action's press and keys are its own: no selection, no tree key handling", async () => {
    const s = spies();
    const onCopy = fn();
    const host = await mount(
      <Host
        spies={s}
        itemActions={(node) => (
          <IconButton icon="copy" label={`Copy ${node.label}`} onClick={() => onCopy(node.id)} />
        )}
      />,
    );
    await userEvent.click(within(host).getByRole("button", { name: "Copy VWAP" }));
    expect(onCopy).toHaveBeenCalledWith("vwap");
    expect(s.onSelect).not.toHaveBeenCalled();
    await userEvent.keyboard("{ArrowDown}");
    expect(within(host).getByRole("button", { name: "Copy VWAP" })).toHaveFocus();
  });

  it("an item's name is its label alone, never its actions' names", async () => {
    const host = await mount(<Host spies={spies()} itemActions={copyPath} />);
    expect(item(host, "VWAP")).toBeInTheDocument();
  });

  it("the type-level contract: a name is required, and only one of the two (tsc checks this file)", () => {
    const base = {
      nodes: NODES,
      expanded: [],
      onToggle: () => undefined,
      selected: [],
      onSelect: () => undefined,
      itemActions: () => null,
    };
    expectTypeOf({ ...base, "aria-label": "IR tree" }).toExtend<TreeViewProps>();
    expectTypeOf(base).not.toExtend<TreeViewProps>();
    expectTypeOf({
      ...base,
      "aria-label": "a",
      "aria-labelledby": "b",
    }).not.toExtend<TreeViewProps>();
  });
});

describe("TreeView: axe", () => {
  it("has no serious or critical violation, single and multi, nested and with actions", async () => {
    const host = await mount(
      <div>
        <Host spies={spies()} open={["overlays", "subpanes", "pane", "drawings"]} />
        <Host
          spies={spies()}
          multiSelect
          selected={["ema21"]}
          onRename={fn()}
          onMove={fn()}
          itemActions={(_node, { tabIndex }) => (
            <IconButton icon="lock" label="Lock" variant="ghost" tabIndex={tabIndex} />
          )}
        />
      </div>,
    );
    expect(await seriousViolations(host)).toEqual([]);
  });
});

describe("treeview.css contract (A-8, A-10)", () => {
  const css = loadCss("treeview.css");
  itIsTokenOnlyAndStatic(css);

  it("binds the item text, the disclosure ink and the focus ring to their A-8 tokens", () => {
    expect(find(css.normal, ".cv-tree__row", "color")).toContain("var(--color-text-primary)");
    expect(find(css.normal, ".cv-tree__disclosure", "color")).toContain(
      "var(--color-text-tertiary)",
    );
    expect(find(css.normal, ".cv-tree__item:focus-visible > .cv-tree__row", "outline")).toContain(
      "var(--color-focus-ring)",
    );
  });

  it("indents each level by space.inset.lg and sizes a row by the density's row height", () => {
    const row = find(css.normal, ".cv-tree__row", "padding-inline");
    expect(row).toContain("var(--cv-tree-depth, 0) * var(--space-inset-lg)");
    expect(row).toContain("min-block-size: var(--size-row-height)");
  });
});

describe("TreeView stories", () => {
  it.each(Object.entries(composeStories(stories)))(
    "%s renders one tree (Empty: none, D23)",
    async (name, Story) => {
      const host = await mount(<Story />);
      expect(host.querySelectorAll('[data-cmp="CMP-240"]')).toHaveLength(name === "Empty" ? 0 : 1);
    },
  );

  it("names every catalogue story that is buildable now (Loading stays TBD in `15`)", () => {
    expect(Object.keys(composeStories(stories))).toEqual(
      expect.arrayContaining([
        "Default",
        "MultiSelect",
        "Nested",
        "InlineRename",
        "Empty",
        "LongLabel",
      ]),
    );
  });

  // The storybook project runs each play in Chromium; here in jsdom too, so a wrong name fails without a browser.
  it("runs each story's play function", { timeout: 20_000 }, async () => {
    for (const [name, Story] of Object.entries(composeStories(stories))) {
      const canvasElement = document.body.appendChild(document.createElement("div"));
      await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
    }
  });
});
