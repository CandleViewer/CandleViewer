import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";
import { tabbables } from "./tabbable.js";

/*
 * Focus primitives shared by every overlay (conventions 32): the modal Tab trap, its focus guard, and
 * the return of focus on close. In-house, as `focus-trap` would do it, without the dependency (plan §3
 * item 1).
 */

/**
 * Hidden by CSS? `tabbable` reads attributes only, so a collapsed section or a hidden panel would still
 * count; where the engine has `checkVisibility()` (Chromium, Electron) it is consulted (plan §3 item 2).
 * Without it (jsdom) the attribute reading stands.
 */
const isRendered = (element: HTMLElement): boolean =>
  typeof element.checkVisibility !== "function" ||
  element.checkVisibility({ checkVisibilityCSS: true, visibilityProperty: true });

/** The tab stops inside `root` that are actually rendered, in DOM order. */
export const visibleTabbables = (root: ParentNode): HTMLElement[] =>
  tabbables(root).filter(isRendered);

/**
 * APG Dialog (Modal): Tab and Shift+Tab cycle inside `container`, in DOM order. Call it from the
 * container's keydown handler; it prevents the default only at the edges (or with nothing to reach).
 */
export const trapTab = (event: KeyboardEvent, container: HTMLElement): void => {
  if (event.key !== "Tab") return;
  const items = visibleTabbables(container);
  const first = items[0];
  const last = items[items.length - 1];
  const active = document.activeElement;
  const onItem = items.some((item) => item === active);
  if (first === undefined || last === undefined) event.preventDefault();
  else if (event.shiftKey && (active === first || !onItem)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (active === last || !onItem)) {
    event.preventDefault();
    first.focus();
  }
};

export interface FocusTrapOptions {
  /** The trap's surface: focus that leaves it for anywhere outside `allow` is taken back. */
  container: RefObject<HTMLElement | null>;
  /** Focus here stays where it went: a nested layer, the layer's own portal root. */
  allow?: (node: Node) => boolean;
  /** While true (a pointer press in progress), the guard waits. */
  paused?: () => boolean;
  /** The last element focused inside, kept by the caller; the guard returns focus there. */
  lastInside: RefObject<HTMLElement | null>;
}

/**
 * The modal guard: while `active`, focus that escapes the container without a Tab (a script, a
 * shortcut, a press the inert page did not stop) is taken back to the last focused element inside.
 * Tab itself is `trapTab`'s.
 */
export function useFocusTrap(active: boolean, options: FocusTrapOptions): void {
  const latest = useRef(options);
  latest.current = options;
  useEffect(() => {
    if (!active) return undefined;
    const onFocusIn = (event: FocusEvent): void => {
      const { container, allow, paused, lastInside } = latest.current;
      const surface = container.current;
      // A closed (hidden) or closing (inert) surface, or one under a stacked modal, guards nothing.
      if (surface === null || surface.hidden || surface.closest("[inert]") !== null) return;
      if (paused?.() === true) return;
      if (!(event.target instanceof Node)) return;
      if (surface.contains(event.target) || allow?.(event.target) === true) return;
      (lastInside.current ?? surface).focus({ preventScroll: true });
    };
    document.addEventListener("focusin", onFocusIn);
    return () => document.removeEventListener("focusin", onFocusIn);
  }, [active]);
}

const focusable = (element: HTMLElement | null | undefined): element is HTMLElement =>
  element !== null &&
  element !== undefined &&
  element.isConnected &&
  element !== element.ownerDocument.body &&
  element.closest("[inert]") === null;

/**
 * Return focus on close (conventions 32): to the element that held focus when the overlay opened, else
 * to the host's fallback, never to `body`. Focus moves only when it is inside the overlay or lost; a
 * close that left focus elsewhere on purpose (an outside press on a control) keeps it there.
 *
 * The opener is read in a layout effect, before an inert page would blur it; the return runs in a
 * passive cleanup, after the layout cleanups (the inert page's among them) have run.
 */
export function useReturnFocus(
  open: boolean,
  container: RefObject<HTMLElement | null>,
  fallback?: RefObject<HTMLElement | null>,
): void {
  const opener = useRef<HTMLElement | null>(null);
  const fallbackRef = useRef(fallback);
  fallbackRef.current = fallback;

  useLayoutEffect(() => {
    if (!open) return;
    const active = document.activeElement;
    const inside = active !== null && (container.current?.contains(active) ?? false);
    // Opened inside itself (a StrictMode re-run, a reopen mid-exit): the opener read earlier stands.
    if (inside) return;
    opener.current = active instanceof HTMLElement && active !== document.body ? active : null;
  }, [open, container]);

  useEffect(() => {
    if (!open) return undefined;
    const root = container.current;
    return () => {
      const active = document.activeElement;
      const lost = active === null || active === document.body || (root?.contains(active) ?? false);
      if (!lost) return;
      const target = [opener.current, fallbackRef.current?.current].find(focusable);
      target?.focus({ preventScroll: true });
    };
  }, [open, container]);
}
