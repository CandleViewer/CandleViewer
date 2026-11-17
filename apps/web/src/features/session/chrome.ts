/**
 * Temporary feature chrome (#2725): re-base CMP-098 and SCR-005 on CMP-043 / CMP-044 (#266) when
 * they land. Flat scrim, no blur (E09-D06 §1); token values only.
 *
 * Until then the session dialogs share the stack with CMP-043's layers (#5561): each one paints last
 * (`ModalLayer`), the modals below it are inert while it is up (`useInertModalsBelow`), its focus guard
 * yields to an inert surface, as CMP-043's does, so two guards never pull the focus to and fro, and
 * `Esc` is the top dialog's wherever the focus is (`claimEscape`).
 */
import { useEffect, useLayoutEffect, useRef, type CSSProperties, type RefObject } from "react";

const FOCUSABLE = "input:not([disabled]), button:not([disabled])";
/** Under a later modal: `inert`, or CMP-043's `aria-hidden` where the engine has no `inert`. */
const BELOW = '[inert], [aria-hidden="true"]';

export const scrim: CSSProperties = {
  position: "fixed",
  inset: 0,
  display: "grid",
  placeItems: "center",
  background: "var(--color-surface-overlay)",
};
export const card: CSSProperties = {
  inlineSize: "calc(var(--space-64) + var(--space-48))",
  maxInlineSize: "100%",
  padding: "var(--space-6)",
  display: "flex",
  flexDirection: "column",
  gap: "var(--space-3)",
  background: "var(--color-surface-raised)",
  color: "var(--color-text-primary)",
  border: "1px solid var(--color-border-default)",
  borderRadius: "var(--radius-lg)",
  fontFamily: "var(--font-family-ui)",
};
export const title: CSSProperties = { margin: 0, fontSize: "var(--font-size-xl)" };
export const actions: CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
  gap: "var(--space-3)",
};
export const primary: CSSProperties = {
  minBlockSize: "var(--size-target-min)",
  padding: "var(--space-2) var(--space-4)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border-default)",
  background: "var(--color-action-primary-default)",
  color: "var(--color-text-on-action)",
};
export const secondary: CSSProperties = {
  ...primary,
  background: "transparent",
  color: "var(--color-text-primary)",
};
export const hidden: CSSProperties = {
  position: "absolute",
  inlineSize: 1,
  blockSize: 1,
  overflow: "hidden",
  clipPath: "inset(50%)",
  whiteSpace: "nowrap",
};

/** Holds per surface, so stacked session dialogs release in any order (as `inertOutside.ts` counts). */
const holds = new Map<Element, number>();

/**
 * Takes one hold on `surface`; false for a surface that another owner made `inert` itself (a nested
 * CMP-043 dialog's parent card), left alone. An inert ancestor does not exempt it: its owner may let
 * go while this dialog is up.
 */
const hold = (surface: Element): boolean => {
  const count = holds.get(surface) ?? 0;
  if (count === 0 && surface.hasAttribute("inert")) return false;
  if (count === 0) surface.setAttribute("inert", "");
  holds.set(surface, count + 1);
  return true;
};

/** Gives one hold back; the last one out makes the surface live again. One not held is left alone. */
const release = (surface: Element): void => {
  const count = holds.get(surface);
  if (count === undefined) return;
  if (count > 1) {
    holds.set(surface, count - 1);
    return;
  }
  holds.delete(surface);
  surface.removeAttribute("inert");
};

/**
 * The scan of every session dialog that is up: one that mounts under another is held by it. Also run
 * by a guard before it judges a focus move: the observer's re-hold comes a microtask late.
 */
const scans = new Set<() => void>();

/**
 * While `node` is mounted, every other modal surface earlier in the document (a CMP-043 dialog or
 * drawer, SCR-006, another session dialog) is `inert`: a later layer wins, as in CMP-043's stack, and
 * each guard yields to an inert surface. The page is left alone: the scrim covers it and the guard
 * holds the focus, as before. A layout effect, so it holds before the dialog moves the focus.
 *
 * The scan runs again when a session dialog mounts (SCR-006 that opens under the lock is held by it)
 * and when an `inert` attribute changes (a modal below that another owner made inert is held once
 * that owner lets go). A dialog that a later modal holds takes no new hold: that one is on top. Its
 * own first scan skips that check: at mount nothing is above it yet, but under StrictMode its second
 * mount finds the hold a dialog above took on it, and would leave the modals below it live.
 */
export function useInertModalsBelow(node: RefObject<HTMLElement>): void {
  useLayoutEffect(() => {
    const mine = node.current;
    if (mine === null) return undefined;
    const held = new Set<Element>();
    const scan = (first = false): void => {
      if (!first && mine.closest(BELOW) !== null) return;
      for (const other of document.querySelectorAll('[aria-modal="true"]')) {
        const earlier =
          (other.compareDocumentPosition(mine) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
        // below `mine`: earlier in the document, and not holding it
        if (earlier && !held.has(other) && !other.contains(mine) && hold(other)) held.add(other);
      }
    };
    scan(true);
    scans.forEach((run) => run()); // a dialog that is up holds this one if it opened under it
    const rescan = (): void => scan();
    scans.add(rescan);
    const observer = new MutationObserver(rescan);
    observer.observe(document.body, { subtree: true, attributeFilter: ["inert"] });
    return () => {
      observer.disconnect();
      scans.delete(rescan);
      held.forEach(release);
    };
  }, [node]);
}

/**
 * `Esc` whose target is outside `node` (a press on the card's own text leaves the focus on `body`):
 * while no later modal holds `node`, it is `node`'s, so no modal below takes it. Cancels the key
 * (CMP-043's stack skips a cancelled `Esc`) and says whether `node` took it; one already taken, or one
 * aimed inside the card (its own handler's), is left alone.
 */
export function claimEscape(node: HTMLElement, event: KeyboardEvent): boolean {
  if (event.key !== "Escape" || event.defaultPrevented || event.isComposing) return false;
  if (event.target instanceof Node && node.contains(event.target)) return false;
  if (node.closest(BELOW) !== null) return false; // under a later modal: that one has the key
  event.preventDefault();
  return true;
}

/**
 * Tab cycles inside `node`; Esc calls `onEscape`, or does nothing when it is absent (SCR-005: Esc
 * does not dismiss). Bound on the native element, as StepUpDialog does, and claimed on `document`
 * when the focus is outside `node` (`claimEscape`), in the capture phase, before CMP-043's stack.
 * `guard` (SCR-005) also pulls focus that lands outside the dialog back to its first control, unless
 * a later modal holds the dialog inert, and a press on the scrim itself takes no focus. The modals
 * below go inert.
 */
export function useModalKeys(
  node: RefObject<HTMLElement>,
  onEscape?: () => void,
  guard = false,
): void {
  const escape = useRef(onEscape);
  useEffect(() => {
    escape.current = onEscape;
  });
  useInertModalsBelow(node);
  useEffect(() => {
    const el = node.current;
    if (el === null) return undefined;
    const first = (): HTMLElement | undefined =>
      el.querySelector<HTMLElement>(FOCUSABLE) ?? undefined;
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        event.preventDefault();
        escape.current?.();
        return;
      }
      if (event.key !== "Tab") return;
      const stops = Array.from(el.querySelectorAll<HTMLElement>(FOCUSABLE));
      const head = stops[0];
      const last = stops[stops.length - 1];
      if (head === undefined || last === undefined) return;
      if (document.activeElement === (event.shiftKey ? head : last)) {
        event.preventDefault();
        (event.shiftKey ? last : head).focus();
      }
    };
    const onEscapeOutside = (event: KeyboardEvent): void => {
      if (claimEscape(el, event)) escape.current?.();
    };
    const onFocusIn = (event: FocusEvent): void => {
      // a modal below whose owner let go in this task (a nested CMP-043 dialog closing) is held first
      scans.forEach((run) => run());
      if (el.closest(BELOW) !== null) return; // under a later modal: it guards nothing
      if (event.target instanceof Node && !el.contains(event.target)) first()?.focus();
    };
    const scrimEl = el.parentElement;
    const onMouseDown = (event: MouseEvent): void => {
      if (event.target === scrimEl) event.preventDefault();
    };
    el.addEventListener("keydown", onKeyDown);
    document.addEventListener("keydown", onEscapeOutside, true);
    if (guard) {
      document.addEventListener("focusin", onFocusIn);
      scrimEl?.addEventListener("mousedown", onMouseDown);
    }
    return () => {
      el.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("keydown", onEscapeOutside, true);
      document.removeEventListener("focusin", onFocusIn);
      scrimEl?.removeEventListener("mousedown", onMouseDown);
    };
  }, [node, guard]);
}

/**
 * Can take the focus now: in the document, not `body`, and not under an inert or hidden layer (where
 * the engine has no `inert`, `focus()` would still reach a page CMP-043 only hides).
 */
const focusable = (el: unknown): el is HTMLElement =>
  el instanceof HTMLElement && el !== document.body && el.isConnected && el.closest(BELOW) === null;

/**
 * Focus goes back to the element that had it when the dialog opened (E09-D06 §6), else to `returnTo`:
 * the host's record of the last element focused before its dialogs came up, which holds still while
 * one is up (a warning that gives way to the lock in one commit leaves the lock no opener). With
 * neither able to take the focus, nothing moves.
 */
export function useFocusReturn(returnTo?: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const opener = document.activeElement;
    const recorded = returnTo?.current;
    return () => {
      [opener, recorded].find(focusable)?.focus();
    };
  }, [returnTo]);
}
