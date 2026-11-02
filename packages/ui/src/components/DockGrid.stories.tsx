import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, userEvent, within } from "storybook/test";
import { DockGridView, type DockViewNode } from "./DockGridView.js";
import { DockPanel, PanelHeader } from "./DockPanel.js";

const frame = { height: "24rem", display: "flex" } as const;
const NAMES: Record<string, string> = {
  a: "Chart BTCUSDT 1 minute",
  b: "Chart BTCUSDT 15 minutes",
  c: "DOM BTCUSDT",
  d: "Tape BTCUSDT",
};
const name = (paneId: string): string => NAMES[paneId] ?? paneId;
const leaf = (paneId: string): DockViewNode => ({ type: "leaf", id: `leaf-${paneId}`, paneId });

interface PanelProps {
  paneId: string;
  focused?: boolean;
  onFocus?: () => void;
}

function Panel({ paneId, focused = false, onFocus }: PanelProps): JSX.Element {
  const kind = name(paneId).split(" ")[0] ?? "";
  return (
    <DockPanel
      title={name(paneId)}
      focused={focused}
      {...(onFocus === undefined ? {} : { onFocus })}
      header={<PanelHeader kind={kind} title={name(paneId)} onMove={() => {}} onClose={() => {}} />}
    />
  );
}

/** A host holding the tree and the focused pane in state, as the app's DockGrid does. */
function Grid({
  initial,
  initialFocus = null,
}: {
  initial: DockViewNode;
  initialFocus?: string | null;
}): JSX.Element {
  const [root, setRoot] = useState(initial);
  const [focused, setFocused] = useState(initialFocus);
  const resize = (node: DockViewNode, id: string, i: number, d: number): DockViewNode => {
    if (node.type === "leaf" || node.type === "tabset") return node;
    if (node.id !== id) return { ...node, children: node.children.map((c) => resize(c, id, i, d)) };
    return {
      ...node,
      sizes: node.sizes.map((s, k) => (k === i ? s + d : k === i + 1 ? s - d : s)),
    };
  };
  const activate = (node: DockViewNode, id: string, index: number): DockViewNode => {
    if (node.type === "leaf") return node;
    if (node.type === "tabset") return node.id === id ? { ...node, active: index } : node;
    return { ...node, children: node.children.map((c) => activate(c, id, index)) };
  };
  return (
    <div style={frame}>
      <DockGridView
        root={root}
        paneName={name}
        renderSlot={(l) => (
          <Panel
            paneId={l.paneId}
            focused={focused === l.paneId}
            onFocus={() => setFocused(l.paneId)}
          />
        )}
        onResize={(id, i, d) => setRoot((r) => resize(r, id, i, d))}
        onActivateTab={(id, i) => setRoot((r) => activate(r, id, i))}
        minSizes={() => [0.2, 0.2, 0.2]}
      />
    </div>
  );
}

const TWO_BY_TWO: DockViewNode = {
  type: "column",
  id: "col",
  sizes: [0.5, 0.5],
  children: [
    { type: "row", id: "top", sizes: [0.5, 0.5], children: [leaf("a"), leaf("b")] },
    { type: "row", id: "bottom", sizes: [0.5, 0.5], children: [leaf("c"), leaf("d")] },
  ],
};

const meta: Meta<typeof DockGridView> = {
  title: "Organisms/Dock/DockGrid",
  component: DockGridView,
};
export default meta;
type Story = StoryObj<typeof DockGridView>;

export const OnePane: Story = { render: () => <Grid initial={leaf("a")} /> };

export const TwoByTwo: Story = {
  render: () => <Grid initial={TWO_BY_TWO} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByRole("region")).toHaveLength(4);
    await expect(canvas.getAllByRole("separator")).toHaveLength(3);
  },
};

export const OnePlusThree: Story = {
  render: () => (
    <Grid
      initial={{
        type: "row",
        id: "r",
        sizes: [0.6, 0.4],
        children: [
          leaf("a"),
          {
            type: "column",
            id: "c",
            sizes: [1 / 3, 1 / 3, 1 / 3],
            children: [leaf("b"), leaf("c"), leaf("d")],
          },
        ],
      }}
    />
  ),
};

export const NAryRow: Story = {
  render: () => (
    <Grid
      initial={{
        type: "row",
        id: "r",
        sizes: [0.45, 0.33, 0.22],
        children: [leaf("a"), leaf("c"), leaf("d")],
      }}
    />
  ),
};

/** A tab group (E15-D02 tree (c)): arrows move between the tabs and show each. */
export const TabsetLeaf: Story = {
  render: () => (
    <Grid
      initial={{
        type: "row",
        id: "r",
        sizes: [0.65, 0.35],
        children: [
          leaf("a"),
          {
            type: "tabset",
            id: "t",
            active: 0,
            children: [
              { type: "leaf", id: "leaf-c", paneId: "c" },
              { type: "leaf", id: "leaf-d", paneId: "d" },
            ],
          },
        ],
      }}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("tab", { name: name("c") }));
    await userEvent.keyboard("{ArrowRight}");
    await expect(canvas.getByRole("tab", { name: name("d") })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  },
};

/** The focused panel in a grid with a tab group: CMP-080's inset frame and header bar (FM-01). */
export const FocusedPanel: Story = {
  render: () => (
    <Grid
      initialFocus="d"
      initial={{
        type: "row",
        id: "r",
        sizes: [0.5, 0.5],
        children: [
          leaf("a"),
          {
            type: "tabset",
            id: "t",
            active: 1,
            children: [
              { type: "leaf", id: "leaf-c", paneId: "c" },
              { type: "leaf", id: "leaf-d", paneId: "d" },
            ],
          },
        ],
      }}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("region", { name: name("d") })).toHaveAttribute("data-focused");
    await userEvent.click(canvas.getByRole("heading", { name: name("a") }));
    await expect(canvas.getByRole("region", { name: name("a") })).toHaveAttribute("data-focused");
    await expect(canvas.getByRole("region", { name: name("d") })).not.toHaveAttribute(
      "data-focused",
    );
  },
};

/** CMP-083's keyboard resize demo: Tab to a separator, then arrows (2 %), Shift+arrows (10 %), Home. */
export const KeyboardResize: Story = {
  render: () => <Grid initial={TWO_BY_TWO} />,
  play: async ({ canvasElement }) => {
    const separator = within(canvasElement).getByRole("separator", {
      name: `${name("a")} and ${name("c")} splitter`,
    });
    separator.focus();
    await userEvent.keyboard("{ArrowDown}");
    await expect(separator).toHaveAttribute("aria-valuenow", "52");
    await userEvent.keyboard("{Shift>}{ArrowUp}{/Shift}");
    await expect(separator).toHaveAttribute("aria-valuenow", "42");
    await userEvent.keyboard("{Home}");
    await expect(separator).toHaveAttribute("aria-valuenow", "50");
  },
};
