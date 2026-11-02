import type { JSX, ReactNode } from "react";
import { cx } from "./internal/cx.js";
import { SplitPane } from "./SplitPane.js";
import { Tabs } from "./Tabs.js";

/** The view's input: structurally `@candleviewer/dock`'s tree (this package imports no dock). */
export interface DockViewLeaf {
  readonly type: "leaf";
  readonly id: string;
  readonly paneId: string;
}
export type DockViewNode =
  | {
      readonly type: "row" | "column";
      readonly id: string;
      readonly children: readonly DockViewNode[];
      readonly sizes: readonly number[];
    }
  | {
      readonly type: "tabset";
      readonly id: string;
      readonly children: readonly DockViewLeaf[];
      readonly active: number;
    }
  | DockViewLeaf;

export interface DockGridViewProps {
  root: DockViewNode | null;
  /** The slot of one visible pane: the host it renders, or a placeholder in a story. */
  renderSlot: (leaf: DockViewLeaf) => ReactNode;
  /** A pane's region name: tab labels and separator names are made from it. */
  paneName: (paneId: string) => string;
  onResize: (splitId: string, index: number, delta: number) => void;
  onActivateTab: (tabsetId: string, index: number) => void;
  /** `Home` on a separator: equal sizes for the whole split. */
  onEqualise?: (splitId: string) => void;
  /** A split's per-child minimum shares (CMP-083 `aria-valuemin` / `aria-valuemax`). */
  minSizes?: (splitId: string) => readonly number[] | undefined;
  onAnnounce?: (text: string) => void;
  className?: string;
}

function firstPane(node: DockViewNode): string {
  if (node.type === "leaf") return node.paneId;
  const child = node.type === "tabset" ? node.children[node.active] : node.children[0];
  return child === undefined ? "" : firstPane(child);
}

/**
 * CMP-081's view: the tree as nested CMP-083 splits on the `space.dockgrid.gutter`, tab groups as a
 * CMP-042 tablist, and one slot per visible pane. A layout change is a cut (E15-D14 §2). The view
 * owns no panel: the host renders panels once and moves them between slots (E15-D02 §8).
 */
export function DockGridView(props: DockGridViewProps): JSX.Element {
  const { root, renderSlot, paneName, onResize, onActivateTab, onEqualise, minSizes, onAnnounce } =
    props;
  const render = (node: DockViewNode): ReactNode => {
    if (node.type === "leaf") return renderSlot(node);
    if (node.type === "tabset") {
      const names = node.children.map((leaf) => paneName(leaf.paneId));
      return (
        <Tabs
          aria-label={names.join(", ")}
          tabs={node.children.map((leaf, i) => ({ id: leaf.id, label: names[i] ?? "" }))}
          value={node.children[node.active]?.id ?? ""}
          onChange={(id) =>
            onActivateTab(
              node.id,
              node.children.findIndex((l) => l.id === id),
            )
          }
          renderPanel={(id) => {
            const leaf = node.children.find((l) => l.id === id);
            return leaf === undefined ? null : renderSlot(leaf);
          }}
        />
      );
    }
    const minimums = minSizes?.(node.id);
    return (
      <SplitPane
        direction={node.type}
        sizes={node.sizes}
        {...(minimums === undefined ? {} : { minSizes: minimums })}
        cells={node.children.map((child) => ({ key: child.id, content: render(child) }))}
        labels={node.children
          .slice(1)
          .map(
            (child, i) =>
              `${paneName(firstPane(node.children[i] as DockViewNode))} and ${paneName(firstPane(child))} splitter`,
          )}
        onResize={(index, delta) => onResize(node.id, index, delta)}
        {...(onEqualise === undefined ? {} : { onEqualise: () => onEqualise(node.id) })}
        {...(onAnnounce === undefined ? {} : { onAnnounce })}
      />
    );
  };
  return (
    <div className={cx("cv-dockgrid", props.className)} data-cmp="CMP-081">
      {root === null ? null : render(root)}
    </div>
  );
}
