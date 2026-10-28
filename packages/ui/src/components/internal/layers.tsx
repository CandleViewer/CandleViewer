import { createContext, useContext, useLayoutEffect, useRef, type RefObject } from "react";

/*
 * The overlay layer stack (conventions 32): one for every overlay. A layer registers while it is open;
 * `Esc` closes the topmost layer only and stops there. A tooltip takes `Esc` first through its own capture
 * listener (it never holds focus); a layer whose own handler takes `Esc` (a focused popover panel) stops it
 * before it reaches the stack's document listener. Modal layers are counted, so a timer host (the toast
 * region) can pause while one is open.
 */

interface Layer {
  readonly modal: boolean;
  readonly element: () => HTMLElement | null;
  readonly escape: () => void;
  readonly claimsEscape?: () => boolean;
}

const stack: Layer[] = [];
const watchers = new Set<() => void>();

/**
 * `Esc` goes to the topmost layer that claims it. A layer that stays open while focus works on the page
 * (a non-modal drawer) claims it only while focus is inside it; otherwise `Esc` passes to the layer under
 * it, or to the page untouched.
 */
const onKeyDown = (event: KeyboardEvent): void => {
  if (event.key !== "Escape" || event.defaultPrevented || event.isComposing) return;
  const top = [...stack].reverse().find((layer) => layer.claimsEscape?.() ?? true);
  if (top === undefined) return;
  event.preventDefault();
  event.stopPropagation();
  top.escape();
};

const notify = (): void => {
  for (const watcher of [...watchers]) watcher();
};

/**
 * Opens a layer on top, except below any open layer whose root its own root holds: layout effects
 * run children first, so a parent mounting open in the same commit as its child registers after it,
 * and still goes under it (`Esc` reaches the child first).
 */
const push = (layer: Layer): void => {
  if (stack.length === 0) document.addEventListener("keydown", onKeyDown);
  const root = layer.element();
  const below =
    root === null
      ? -1
      : stack.findIndex((other) => {
          const node = other.element();
          return node !== null && node !== root && root.contains(node);
        });
  if (below === -1) stack.push(layer);
  else stack.splice(below, 0, layer);
  notify();
};

const remove = (layer: Layer): void => {
  const index = stack.indexOf(layer);
  if (index === -1) return;
  stack.splice(index, 1);
  if (stack.length === 0) document.removeEventListener("keydown", onKeyDown);
  notify();
};

/** True while any modal layer (a Dialog, a modal Popover) is open. */
export const modalLayerOpen = (): boolean => stack.some((layer) => layer.modal);

/** Calls `watcher` whenever a layer opens or closes; returns the unsubscribe. */
export const watchLayers = (watcher: () => void): (() => void) => {
  watchers.add(watcher);
  return () => {
    watchers.delete(watcher);
  };
};

export interface LayerHandle {
  /** True while this layer is open and no layer sits above it. */
  isTopmost: () => boolean;
  /** True when `node` is inside a layer opened above this one (a menu from a popover, a nested dialog). */
  inLayerAbove: (node: Node | null) => boolean;
}

export interface UseLayerOptions {
  /** The layer's root element: its surface, or the portal root holding it and its nested layers. */
  element: RefObject<HTMLElement | null>;
  modal: boolean;
  /** Called when `Esc` reaches the stack with this layer on top. */
  onEscape: () => void;
  /**
   * Whether this layer takes `Esc` now (default: always). A non-modal drawer answers "focus is inside
   * me", so `Esc` on the live chart beside it stays the chart's.
   */
  claimsEscape?: (() => boolean) | undefined;
}

/** Registers an open overlay in the stack; the handle answers "am I on top?" and "is this node above me?". */
export function useLayer(
  open: boolean,
  { element, modal, onEscape, claimsEscape }: UseLayerOptions,
): LayerHandle {
  const escape = useRef(onEscape);
  escape.current = onEscape;
  const claims = useRef(claimsEscape);
  claims.current = claimsEscape;
  const current = useRef<Layer | null>(null);
  const handle = useRef<LayerHandle | null>(null);
  handle.current ??= {
    isTopmost: () => current.current !== null && stack[stack.length - 1] === current.current,
    inLayerAbove: (node) => {
      const layer = current.current;
      if (layer === null || node === null) return false;
      const from = stack.indexOf(layer);
      return stack.slice(from + 1).some((above) => above.element()?.contains(node) ?? false);
    },
  };

  useLayoutEffect(() => {
    if (!open) return undefined;
    const layer: Layer = {
      modal,
      element: () => element.current,
      escape: () => escape.current(),
      claimsEscape: () => claims.current?.() ?? true,
    };
    current.current = layer;
    push(layer);
    return () => {
      remove(layer);
      if (current.current === layer) current.current = null;
    };
  }, [open, modal, element]);

  return handle.current;
}

/**
 * Where a layer portals: `document.body`, or inside the modal layer that renders it, so a Popover, a
 * Tooltip or a nested Dialog inside a Dialog stays inside that dialog's live, non-inert subtree.
 */
const LayerPortalContext = createContext<HTMLElement | null>(null);

export const LayerPortalProvider = LayerPortalContext.Provider;

/** The element an overlay portals into (null during server rendering). */
export function useLayerPortal(): HTMLElement | null {
  const root = useContext(LayerPortalContext);
  if (root !== null) return root;
  return typeof document === "undefined" ? null : document.body;
}
