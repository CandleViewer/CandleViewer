import { useMemo } from "react";

export interface FocusRingOptions {
  /** Draw the ring inside the element's bounds (H8), for items inside a scrolling container that clips. */
  inset?: boolean;
}

export interface FocusRingProps {
  /** The ring classes to join into the focusable element's `className`. */
  className: string;
}

/** The CMP-039 ring classes: the base ring, plus the inset modifier when `inset` is set. */
function focusRingClassName(inset = false): string {
  return inset ? "cv-focus-ring cv-focus-ring--inset" : "cv-focus-ring";
}

/**
 * CMP-039 FocusRing: the keyboard-only focus ring (`:focus-visible`) as a class for the focusable element.
 * CSS only, so it adds no ARIA and never changes layout; `outline: none` without it is never allowed.
 */
export function useFocusRing({ inset = false }: FocusRingOptions = {}): FocusRingProps {
  return useMemo(() => ({ className: focusRingClassName(inset) }), [inset]);
}
