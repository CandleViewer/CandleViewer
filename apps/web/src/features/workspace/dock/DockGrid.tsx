/**
 * CMP-081 DockGrid (E15-T02): renders a `@candleviewer/dock` tree with no GL churn. Each pane
 * renders once, through a portal, into a persistent host element keyed by `paneId`; after every
 * commit the hosts are moved into their slots in reading order (`moveBefore` where the browser has
 * it, keeping focus and state; else `insertBefore` and focus restored), so a move, a tab, a split or
 * a preset is a re-parent of a DOM node and React never unmounts the panel, its canvas or its WebGL
 * context (E15-D02 §8). A hidden tab's host waits in a parking element. Only `close` unmounts.
 *
 * Panels mount lazily on first visibility and are told to unsubscribe after 30 s as a hidden tab
 * (SCR-020). Resizes go to CSS flex fractions; the store commits once per keyboard step or drag.
 */
import {
  allLeaves,
  close,
  equalise,
  activateTab,
  leavesOf,
  minExtent,
  resize,
  separatorId,
  findNode,
  type DockLeaf,
  type DockNode,
  type DockTree,
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
  readonly onClose: () => void;
}

function PaneHost({
  leaf,
  visible,
  name,
  registry,
  timers,
  level,
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
          if (host?.parentNode === previous && parking.current !== null)
            place(parking.current, host);
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
  });

  useEffect(() => {
    const el = root.current;
    if (el === null || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(([entry]) => {
      if (entry !== undefined)
        store.setViewport({ width: entry.contentRect.width, height: entry.contentRect.height });
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

  const minShares = (splitId: string): number[] | undefined => {
    const node = tree.root === null ? null : findNode(tree.root, splitId);
    const extent = root.current?.[node?.type === "row" ? "clientWidth" : "clientHeight"] ?? 0;
    if (node === null || (node.type !== "row" && node.type !== "column") || extent === 0)
      return undefined;
    return node.children.map((child) => minExtent(child, node.type as "row") / extent);
  };

  return (
    <div
      ref={root}
      className="cv-dock-root"
      style={{ display: "flex", width: "100%", height: "100%" }}
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
            onClose={() =>
              store.apply(
                "close",
                (t, c) => close(t, l.paneId, c),
                layoutSummary.closed(paneName(l)),
              )
            }
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
