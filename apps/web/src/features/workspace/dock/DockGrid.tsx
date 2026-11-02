/**
 * CMP-081 DockGrid (E15-T02): renders a `@candleviewer/dock` tree with no GL churn. Each pane
 * renders once, through a portal, into a persistent host element keyed by `paneId`; after every
 * commit the hosts are moved into their slots in reading order (`moveBefore` where the browser has
 * it, keeping focus and state; else `insertBefore` and focus restored), so a move, a tab, a split or
 * a preset is a re-parent of a DOM node and React never unmounts the panel, its canvas or its WebGL
 * context (E15-D02 §8). A hidden tab's host waits in a parking element. Only `close` unmounts.
 *
 * Focus (E15-D15 FM-01..03, FM-11): parking is `hidden`, and a browser drops focus from a node that
 * is not rendered, so when a slot detaches with focus inside its host the focused element is noted
 * and focused again once the host is in its new slot (tabify, split out, maximise, restore). If the
 * pane is now a hidden tab, the shown tab's panel takes focus; on `close`, the panel that takes the
 * space does (its next sibling, else its previous one), else the dock itself. The panel holding
 * focus is drawn focused (CMP-080).
 *
 * Panels mount lazily on first visibility and are told to unsubscribe after 30 s as a hidden tab
 * (SCR-020). Resizes go to CSS flex fractions; the store commits once per keyboard step or drag.
 */
import {
  allLeaves,
  close,
  equalise,
  activateTab,
  layoutRects,
  leavesOf,
  minExtent,
  resize,
  separatorId,
  findNode,
  type DockLeaf,
  type DockNode,
  type DockTree,
  type Size,
} from "@candleviewer/dock";
import { DockGridView, DockPanel, PanelHeader, type DockViewLeaf } from "@candleviewer/ui";
import { useEffect, useLayoutEffect, useRef, useState, type JSX } from "react";
import { createPortal } from "react-dom";
import { useDockTree, type DockStore } from "./dockStore";
import { notePanelMount } from "./glChurnGuard";
import { layoutSummary } from "./layoutSummary";
import type { PaneRegistry } from "./paneRegistry";

/** SCR-020: a hidden tab unsubscribes after 30 s. */
export const HIDDEN_UNSUBSCRIBE_MS = 30_000;

export interface Timers {
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
}

export interface DockGridProps {
  readonly store: DockStore;
  readonly registry: PaneRegistry;
  /** A pane's region name: kind, symbol and the spelled interval (E15-D03 D-5). */
  readonly paneName: (leaf: DockLeaf) => string;
  readonly onAnnounce?: (text: string) => void;
  readonly timers?: Timers;
}

const GLOBAL_TIMERS: Timers = {
  setTimeout: (fn, ms) => globalThis.setTimeout(fn, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/** The panes drawn this commit: the maximised one alone, else every active tab and lone leaf. */
function visiblePanes(tree: DockTree): Set<string> {
  if (tree.maximised !== null) return new Set([tree.maximised]);
  const out = new Set<string>();
  const walk = (node: DockNode): void => {
    if (node.type === "leaf") out.add(node.paneId);
    else if (node.type === "tabset") {
      const active = node.children[node.active];
      if (active !== undefined) out.add(active.paneId);
    } else node.children.forEach(walk);
  };
  if (tree.root !== null) walk(tree.root);
  return out;
}

/** The pane shown first in `node`'s reading order: a leaf, a group's active tab, a split's first. */
function shownPane(node: DockNode): string | null {
  if (node.type === "leaf") return node.paneId;
  const child = node.type === "tabset" ? node.children[node.active] : node.children[0];
  return child === undefined ? null : shownPane(child);
}

/** The pane that takes `paneId`'s space when it closes: its next sibling's, else its previous. */
function heirOf(node: DockNode | null, paneId: string): string | null {
  if (node === null || node.type === "leaf") return null;
  const index = node.children.findIndex((c) => c.type === "leaf" && c.paneId === paneId);
  if (index !== -1) {
    const heir = node.children[index + 1] ?? node.children[index - 1];
    return heir === undefined ? null : shownPane(heir);
  }
  if (node.type === "tabset") return null;
  for (const child of node.children) {
    const found = heirOf(child, paneId);
    if (found !== null) return found;
  }
  return null;
}

/** The tab group holding `paneId`, if it is a tab. */
function groupOf(node: DockNode | null, paneId: string): DockNode | null {
  if (node === null || node.type === "leaf") return null;
  if (node.type === "tabset") return node.children.some((l) => l.paneId === paneId) ? node : null;
  for (const child of node.children) {
    const found = groupOf(child, paneId);
    if (found !== null) return found;
  }
  return null;
}

/** Where focus goes after this commit: an element to keep, or a pane's panel (null: the dock). */
type FocusIntent =
  | { readonly kind: "keep"; readonly el: HTMLElement; readonly paneId: string }
  | { readonly kind: "pane"; readonly paneId: string | null };

/** Moves `host` to the end of `slot`, keeping the focused element focused. */
function place(slot: Element, host: HTMLElement): void {
  type Mover = { moveBefore?: (node: Node, child: Node | null) => void };
  const mover = slot as unknown as Mover;
  if (host.isConnected && slot.isConnected && typeof mover.moveBefore === "function") {
    mover.moveBefore(host, null);
    return;
  }
  const active = host.ownerDocument.activeElement;
  const focused = active instanceof HTMLElement && host.contains(active) ? active : null;
  slot.insertBefore(host, null);
  focused?.focus();
}

interface PaneHostProps {
  readonly leaf: DockLeaf;
  readonly visible: boolean;
  readonly name: string;
  readonly registry: PaneRegistry;
  readonly timers: Timers;
  readonly level: 2 | 3;
  readonly focused: boolean;
  readonly onFocus: () => void;
  readonly onClose: () => void;
}

function PaneHost({
  leaf,
  visible,
  name,
  registry,
  timers,
  level,
  focused,
  onFocus,
  onClose,
}: PaneHostProps): JSX.Element {
  const [seen, setSeen] = useState(visible);
  const [subscribed, setSubscribed] = useState(visible);
  useEffect(() => {
    notePanelMount(1);
    return () => notePanelMount(-1);
  }, []);
  useEffect(() => {
    if (visible) {
      setSeen(true);
      setSubscribed(true);
      return undefined;
    }
    const handle = timers.setTimeout(() => setSubscribed(false), HIDDEN_UNSUBSCRIBE_MS);
    return () => timers.clearTimeout(handle);
  }, [visible, timers]);
  // The kind is checked here, before any mount: an unknown kind renders no component at all.
  const entry = registry.get(leaf.kind);
  const label = entry?.label ?? leaf.kind;
  const Body = entry?.disabledReason === undefined ? entry?.component : undefined;
  return (
    <DockPanel
      title={name}
      focused={focused}
      onFocus={onFocus}
      {...(entry === undefined ? { state: "error" as const } : {})}
      header={<PanelHeader kind={label} title={name} level={level} onClose={onClose} />}
    >
      {Body !== undefined && seen ? <Body paneId={leaf.paneId} subscribed={subscribed} /> : null}
      {entry?.disabledReason === undefined ? null : <p>{entry.disabledReason}</p>}
    </DockPanel>
  );
}

export function DockGrid({
  store,
  registry,
  paneName,
  onAnnounce,
  timers = GLOBAL_TIMERS,
}: DockGridProps): JSX.Element {
  const tree = useDockTree(store);
  const hosts = useRef(new Map<string, HTMLDivElement>());
  const slots = useRef(new Map<string, HTMLElement>());
  const parking = useRef<HTMLDivElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const focusIntent = useRef<FocusIntent | null>(null);
  const [focusedPane, setFocusedPane] = useState<string | null>(null);
  const [dockSize, setDockSize] = useState<Size>({ width: 0, height: 0 });
  const leaves = allLeaves(tree);
  const visible = visiblePanes(tree);

  // One stable ref callback per pane, so React calls it only when the slot itself comes or goes.
  // A slot's ref detaches before React removes the slot from the document: its host is parked
  // first, so it stays connected and the next placement can be a `moveBefore`.
  const slotRefs = useRef(new Map<string, (el: HTMLElement | null) => void>());
  const slotRef = (paneId: string): ((el: HTMLElement | null) => void) => {
    let ref = slotRefs.current.get(paneId);
    if (ref === undefined) {
      ref = (el) => {
        const previous = slots.current.get(paneId);
        const host = hosts.current.get(paneId);
        if (el !== null) slots.current.set(paneId, el);
        else if (previous !== undefined) {
          slots.current.delete(paneId);
          if (host?.parentNode === previous && parking.current !== null) {
            // Parking is not rendered, so focus inside the host is lost there: note it first.
            const active = host.ownerDocument.activeElement;
            if (
              focusIntent.current === null &&
              active instanceof HTMLElement &&
              host.contains(active)
            )
              focusIntent.current = { kind: "keep", el: active, paneId };
            place(parking.current, host);
          }
        }
      };
      slotRefs.current.set(paneId, ref);
    }
    return ref;
  };

  // A host per pane, made once and kept until the pane closes: the portal target never changes.
  const hostOf = (paneId: string): HTMLDivElement => {
    let host = hosts.current.get(paneId);
    if (host === undefined) {
      host = document.createElement("div");
      host.className = "cv-dock-host";
      host.dataset["paneId"] = paneId;
      hosts.current.set(paneId, host);
    }
    return host;
  };

  useLayoutEffect(() => {
    const live = new Set(leaves.map((l) => l.paneId));
    for (const [paneId, host] of hosts.current) {
      if (live.has(paneId)) continue;
      host.remove();
      hosts.current.delete(paneId);
      slotRefs.current.delete(paneId);
    }
    // Reading order: the DOM order of the visible panels is their visual order (FM rows, D02 §8).
    for (const l of leaves) {
      const slot = slots.current.get(l.paneId) ?? parking.current;
      const host = hosts.current.get(l.paneId);
      if (slot !== null && host !== undefined && host.parentNode !== slot) place(slot, host);
    }
    const intent = focusIntent.current;
    focusIntent.current = null;
    if (intent === null) return;
    const shown = (el: Element): boolean =>
      el.isConnected && parking.current?.contains(el) !== true;
    if (intent.kind === "keep" && shown(intent.el)) {
      if (intent.el.ownerDocument.activeElement !== intent.el) intent.el.focus();
      return;
    }
    // A hidden tab hands focus to the tab shown in its place; a closed pane to its heir.
    const group = intent.kind === "keep" ? groupOf(tree.root, intent.paneId) : null;
    const paneId = intent.kind === "pane" ? intent.paneId : group && shownPane(group);
    const panel =
      paneId === null
        ? null
        : hosts.current.get(paneId)?.querySelector<HTMLElement>(".cv-dockpanel");
    (panel !== null && panel !== undefined && shown(panel) ? panel : root.current)?.focus();
  });

  // The first measure, before paint, so the separators' minimums are right from the first frame.
  useLayoutEffect(() => {
    const el = root.current;
    if (el !== null) setDockSize({ width: el.clientWidth, height: el.clientHeight });
  }, []);

  useEffect(() => {
    const el = root.current;
    if (el === null || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(([entry]) => {
      if (entry === undefined) return;
      const next = { width: entry.contentRect.width, height: entry.contentRect.height };
      store.setViewport(next);
      setDockSize((was) => (was.width === next.width && was.height === next.height ? was : next));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [store]);

  const name = (paneId: string): string => {
    const l = leaves.find((x) => x.paneId === paneId);
    return l === undefined ? paneId : paneName(l);
  };
  const viewRoot: DockNode | null =
    tree.maximised === null
      ? tree.root
      : (leavesOf(tree.root).find((l) => l.paneId === tree.maximised) ?? null);

  // A split's minimum shares are of the split's own px extent (a nested split is smaller than the
  // dock), from the same rects the dock's normal form fits minimums against.
  const minShares = (splitId: string): number[] | undefined => {
    const node = tree.root === null ? null : findNode(tree.root, splitId);
    if (node === null || (node.type !== "row" && node.type !== "column")) return undefined;
    const rect = layoutRects(tree, dockSize).get(splitId);
    const extent = rect === undefined ? 0 : node.type === "row" ? rect.width : rect.height;
    if (!(extent > 0)) return undefined;
    return node.children.map((child) => minExtent(child, node.type as "row") / extent);
  };

  return (
    <div
      ref={root}
      className="cv-dock-root"
      // The focus target of last resort (FM-11: closing the last pane); never a Tab stop.
      tabIndex={-1}
      style={{ display: "flex", width: "100%", height: "100%" }}
      onBlur={(event) => {
        const next = event.relatedTarget;
        if (!(next instanceof Node && event.currentTarget.contains(next))) setFocusedPane(null);
      }}
    >
      <DockGridView
        root={viewRoot}
        paneName={name}
        renderSlot={(l: DockViewLeaf) => (
          <div
            key={l.paneId}
            className="cv-dock-slot"
            style={{ display: "flex", flex: "1 1 0", minWidth: 0, minHeight: 0 }}
            ref={slotRef(l.paneId)}
          />
        )}
        onResize={(splitId, index, delta) =>
          store.apply("resize", (t, c) => resize(t, separatorId(splitId, index), delta, c))
        }
        onEqualise={(splitId) => store.apply("equalise", (t, c) => equalise(t, splitId, c))}
        onActivateTab={(tabsetId, index) =>
          store.apply("activate_tab", (t, c) => activateTab(t, tabsetId, index, c))
        }
        minSizes={minShares}
        {...(onAnnounce === undefined ? {} : { onAnnounce })}
      />
      <div ref={parking} hidden className="cv-dock-parking" />
      {leaves.map((l) =>
        createPortal(
          <PaneHost
            leaf={l}
            visible={visible.has(l.paneId)}
            name={paneName(l)}
            registry={registry}
            timers={timers}
            level={isTab(tree.root, l) ? 3 : 2}
            focused={focusedPane === l.paneId}
            onFocus={() => setFocusedPane(l.paneId)}
            onClose={() => {
              const heir = heirOf(tree.root, l.paneId);
              focusIntent.current = { kind: "pane", paneId: heir };
              const closed = store.apply(
                "close",
                (t, c) => close(t, l.paneId, c),
                layoutSummary.closed(paneName(l)),
              );
              if (!closed) focusIntent.current = null;
            }}
          />,
          hostOf(l.paneId),
          l.paneId,
        ),
      )}
    </div>
  );
}

/** Whether the leaf is a tab of a tab group (its heading is an h3, CMP-082). */
function isTab(node: DockNode | null, leaf: DockLeaf): boolean {
  if (node === null || node.type === "leaf") return false;
  if (node.type === "tabset") return node.children.includes(leaf);
  return node.children.some((child) => isTab(child, leaf));
}
