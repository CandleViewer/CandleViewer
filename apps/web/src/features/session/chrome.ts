/**
 * Temporary feature chrome (#2725): re-base CMP-098 and SCR-005 on CMP-043 / CMP-044 (#266) when
 * they land. Flat scrim, no blur (E09-D06 §1); token values only.
 */
import { useEffect, useRef, type CSSProperties, type RefObject } from "react";

const FOCUSABLE = "input:not([disabled]), button:not([disabled])";

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
export const hidden: CSSProperties = {
  position: "absolute",
  inlineSize: 1,
  blockSize: 1,
  overflow: "hidden",
  clipPath: "inset(50%)",
  whiteSpace: "nowrap",
};

/**
 * Tab cycles inside `node`; Esc calls `onEscape`, or does nothing when it is absent (SCR-005: Esc
 * does not dismiss). Bound on the native element, as StepUpDialog does. `guard` (SCR-005) also pulls
 * focus that lands outside the dialog back to its first control, and a press on the scrim itself
 * takes no focus.
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
    const onFocusIn = (event: FocusEvent): void => {
      if (event.target instanceof Node && !el.contains(event.target)) first()?.focus();
    };
    const scrimEl = el.parentElement;
    const onMouseDown = (event: MouseEvent): void => {
      if (event.target === scrimEl) event.preventDefault();
    };
    el.addEventListener("keydown", onKeyDown);
    if (guard) {
      document.addEventListener("focusin", onFocusIn);
      scrimEl?.addEventListener("mousedown", onMouseDown);
    }
    return () => {
      el.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("focusin", onFocusIn);
      scrimEl?.removeEventListener("mousedown", onMouseDown);
    };
  }, [node, guard]);
}

/** Focus goes back to the element that had it when the dialog opened (E09-D06 §6). */
export function useFocusReturn(): void {
  useEffect(() => {
    const opener = document.activeElement;
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);
}
