import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { IconButton } from "./IconButton.js";
import { TreeView, type TreeNode, type TreeViewProps } from "./TreeView.js";

/** SCR-036's objects (E13-D02 §6.2): groups with their indicators, a sub-pane with its child, a drawing. */
const OBJECTS: readonly TreeNode[] = [
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
    children: [{ id: "rsi-pane", label: "RSI pane", children: [{ id: "rsi14", label: "RSI 14" }] }],
  },
  { id: "drawings", label: "Drawings", children: [{ id: "trend1", label: "Trend line 1" }] },
];

/** SCR-088's IR (E36-D03 §5): every label is the node's path and value. */
const IR: readonly TreeNode[] = [
  { id: "trigger", label: "trigger › bar_close: 1m" },
  {
    id: "conditions",
    label: "conditions › op: all",
    children: [
      {
        id: "c0",
        label: "conditions › children › 0 › op: gte",
        children: [
          { id: "c0l", label: "conditions › children › 0 › left › metric: unrealised_r" },
          { id: "c0r", label: "conditions › children › 0 › right › value: 1.0" },
        ],
      },
      { id: "c1", label: "conditions › children › 1 › op: lte" },
      { id: "c2", label: "conditions › children › 2 › op: gte" },
    ],
  },
  { id: "actions", label: "actions › 0 › type: move_stop" },
];

/** Moves `id` to `index` among its siblings, wherever it sits: the host's half of `onMove`. */
const moved = (list: readonly TreeNode[], id: string, index: number): readonly TreeNode[] => {
  const from = list.findIndex((node) => node.id === id);
  if (from >= 0) {
    const rest = list.filter((node) => node.id !== id);
    const node = list[from];
    return node === undefined ? list : [...rest.slice(0, index), node, ...rest.slice(index)];
  }
  return list.map((node) =>
    node.children === undefined ? node : { ...node, children: moved(node.children, id, index) },
  );
};
const renamed = (list: readonly TreeNode[], id: string, label: string): readonly TreeNode[] =>
  list.map((node) => ({
    ...node,
    ...(node.id === id ? { label } : {}),
    ...(node.children === undefined ? {} : { children: renamed(node.children, id, label) }),
  }));

type HostProps = Partial<TreeViewProps> & {
  readonly initialExpanded?: readonly string[];
  readonly initialSelected?: readonly string[];
};

/** A host that owns the expanded set, the selection and the nodes, as SCR-036 and SCR-088 do. */
function TreeHost({
  nodes: initialNodes = OBJECTS,
  initialExpanded = ["overlays"],
  initialSelected = [],
  itemActions = () => null,
  onRename,
  onMove,
  multiSelect,
}: HostProps): JSX.Element {
  const [nodes, setNodes] = useState(initialNodes);
  const [expanded, setExpanded] = useState(initialExpanded);
  const [selected, setSelected] = useState(initialSelected);
  return (
    <TreeView
      aria-label="Objects on BTCUSDT 1m"
      nodes={nodes}
      expanded={expanded}
      onToggle={(id, open) =>
        setExpanded((now) => (open ? [...now, id] : now.filter((e) => e !== id)))
      }
      selected={selected}
      onSelect={setSelected}
      itemActions={itemActions}
      {...(multiSelect === undefined ? {} : { multiSelect })}
      {...(onRename === undefined
        ? {}
        : {
            onRename: (id: string, label: string) => {
              onRename(id, label);
              setNodes((now) => renamed(now, id, label));
            },
          })}
      {...(onMove === undefined
        ? {}
        : {
            onMove: (id: string, index: number) => {
              onMove(id, index);
              setNodes((now) => moved(now, id, index));
            },
          })}
    />
  );
}

const meta: Meta<typeof TreeHost> = {
  title: "Molecules/TreeView",
  component: TreeHost,
  render: (args) => <TreeHost {...args} />,
};
export default meta;
type Story = StoryObj<typeof TreeHost>;

const item = (canvas: HTMLElement, name: string): HTMLElement =>
  within(canvas).getByRole("treeitem", { name });

/** SCR-036's row actions (E13-D02 §6.2): the lock and the item menu, each a named CMP-002 on the roving index. */
const objectActions: TreeViewProps["itemActions"] = (node, { tabIndex }) =>
  node.children === undefined ? (
    <>
      <IconButton icon="lock" label={`Lock ${node.label}`} variant="ghost" tabIndex={tabIndex} />
      <IconButton
        icon="more-horizontal"
        label={`More actions for ${node.label}`}
        variant="ghost"
        tabIndex={tabIndex}
      />
    </>
  ) : null;

/** Single-select: one roving stop; arrows move and the selection follows focus; `→` opens a group. */
export const Default: Story = {
  args: { itemActions: objectActions },
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    const overlays = item(canvasElement, "Overlays");
    await expect(overlays).toHaveFocus();
    await expect(overlays).toHaveAttribute("aria-expanded", "true");
    await userEvent.keyboard("{ArrowDown}");
    await expect(item(canvasElement, "EMA 21")).toHaveFocus();
    await expect(item(canvasElement, "EMA 21")).toHaveAttribute("aria-selected", "true");
  },
};

/**
 * SCR-036's editable object tree: multi-select (`Ctrl+Space` toggles, `Shift+↓` extends, `Esc` clears), the drag
 * handle and its `Alt+↑/↓` twin, the selection fill with its check glyph.
 */
export const MultiSelect: Story = {
  args: {
    multiSelect: true,
    itemActions: objectActions,
    onMove: fn(),
    onRename: fn(),
    initialExpanded: ["overlays", "drawings"],
  },
  play: async ({ canvasElement, args }) => {
    const tree = within(canvasElement).getByRole("tree");
    await expect(tree).toHaveAttribute("aria-multiselectable", "true");
    item(canvasElement, "EMA 21").focus();
    await userEvent.keyboard("{Control>} {/Control}");
    await userEvent.keyboard("{Shift>}{ArrowDown}{/Shift}");
    await expect(item(canvasElement, "EMA 21")).toHaveAttribute("aria-selected", "true");
    await expect(item(canvasElement, "EMA 50")).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{Alt>}{ArrowDown}{/Alt}");
    await expect(args.onMove).toHaveBeenCalledWith("ema50", 2);
    await expect(item(canvasElement, "EMA 50")).toHaveFocus();
  },
};

/** Three levels: a sub-pane group holds a pane, which holds its indicator (`aria-level` 3). */
export const Nested: Story = {
  args: { initialExpanded: ["overlays", "subpanes", "rsi-pane", "drawings"] },
  play: async ({ canvasElement }) => {
    await expect(item(canvasElement, "RSI 14")).toHaveAttribute("aria-level", "3");
    await expect(within(canvasElement).getAllByRole("group")).toHaveLength(4);
  },
};

/** `F2` (or a double-click) renames in place; `Enter` saves, `Esc` cancels, focus returns to the item. */
export const InlineRename: Story = {
  args: { onRename: fn(), itemActions: objectActions },
  play: async ({ canvasElement, args }) => {
    item(canvasElement, "EMA 21").focus();
    await userEvent.keyboard("{F2}");
    const field = within(canvasElement).getByRole("textbox", { name: "Rename EMA 21" });
    await expect(field).toHaveFocus();
    await userEvent.clear(field);
    await userEvent.type(field, "Fast EMA{Enter}");
    await expect(args.onRename).toHaveBeenCalledWith("ema21", "Fast EMA");
    await expect(item(canvasElement, "Fast EMA")).toHaveFocus();
  },
};

/** SCR-088's read-only IR tree: no drag handle, no rename, `aria-level` down to the deepest IR node. */
export const ReadOnlyIr: Story = {
  args: { nodes: IR, initialExpanded: ["conditions", "c0"] },
  play: async ({ canvasElement }) => {
    const deepest = item(canvasElement, "conditions › children › 0 › left › metric: unrealised_r");
    await expect(deepest).toHaveAttribute("aria-level", "3");
    deepest.focus();
    await userEvent.keyboard("{F2}");
    await expect(within(canvasElement).queryByRole("textbox")).toBeNull();
    await expect(canvasElement.querySelector(".cv-tree__handle")).toBeNull();
  },
};

/** SCR-088's Copy path: one CMP-002 per item; Tab reaches the focused item's, then leaves the tree. */
export const CopyPath: Story = {
  args: {
    nodes: IR,
    initialExpanded: ["conditions"],
    itemActions: (_node, { tabIndex }) => (
      <IconButton icon="copy" label="Copy path" variant="ghost" tabIndex={tabIndex} />
    ),
  },
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(item(canvasElement, "trigger › bar_close: 1m")).toHaveFocus();
    await userEvent.tab();
    const copies = within(canvasElement).getAllByRole("button", { name: "Copy path" });
    await expect(copies[0]).toHaveFocus();
    await expect(copies.filter((b) => b.tabIndex === 0)).toHaveLength(1);
  },
};

/**
 * No nodes: the tree draws nothing, so the host's empty state (CMP-026) replaces the body (E13-D02 §6.4 D23). The
 * empty state's copy is the host screen's, so this story shows the tree's half alone.
 */
export const Empty: Story = {
  args: { nodes: [], initialExpanded: [] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("tree")).toBeNull();
    await expect(within(canvasElement).queryByRole("treeitem")).toBeNull();
  },
};

const LONG =
  "conditions › children › 0 › left › metric: unrealised_r_multiple_of_the_initial_risk_at_entry_across_all_legs";

/** A label longer than the row wraps rather than clip (`05` §5 item 7); the item's name is the whole label. */
export const LongLabel: Story = {
  args: {
    nodes: [{ id: "long", label: LONG, children: [{ id: "leaf", label: `${LONG} › value: 1.0` }] }],
    initialExpanded: ["long"],
    itemActions: (_node, { tabIndex }) => (
      <IconButton icon="copy" label="Copy path" variant="ghost" tabIndex={tabIndex} />
    ),
  },
  play: async ({ canvasElement }) => {
    const leaf = item(canvasElement, `${LONG} › value: 1.0`);
    await expect(leaf).toHaveAttribute("aria-level", "2");
    await expect(leaf.querySelector(".cv-tree__label")).toHaveTextContent(`${LONG} › value: 1.0`);
  },
};
