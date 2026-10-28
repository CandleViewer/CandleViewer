import { autoUpdate, computePosition, flip, offset, shift, size } from "@floating-ui/dom";
import { useEffect, type RefObject } from "react";

/** The four sides an anchored surface can take (conventions 30); alignment is always centred. */
export type AnchoredSide = "top" | "right" | "bottom" | "left";

export interface AnchoredPositionOptions {
  /** Positions only while true: no listener, observer or frame exists while the surface is closed. */
  readonly open: boolean;
  /** The anchor (the trigger). Read when `open` turns true. */
  readonly reference: RefObject<Element | null>;
  /** The floating surface, `position: fixed` in its own CSS. */
  readonly floating: RefObject<HTMLElement | null>;
  /** The preferred side; the surface flips to the opposite side when the viewport has no room. */
  readonly side: AnchoredSide;
  /**
   * The custom property that holds the gap to the anchor and the clearance to the viewport edge
   * (conventions 30: `space.inset.xs`). Read from the floating element, so the theme owns the value.
   */
  readonly gapToken?: string;
  /**
   * Fit the surface to its anchor and the viewport (CMP-017): writes the anchor's width to
   * `--cv-anchor-width` and the room left on the resolved side to `--cv-available-height`, so the
   * surface's CSS can be at least as wide as its trigger and cap its height, then scroll.
   */
  readonly fit?: boolean;
}

const lengthOf = (element: HTMLElement, token: string): number => {
  const value = Number.parseFloat(getComputedStyle(element).getPropertyValue(token));
  return Number.isFinite(value) ? value : 0;
};

/**
 * The one positioning primitive of the anchored overlays (CMP-016, CMP-017): `@floating-ui/dom` for
 * the geometry only (offset, flip, shift), every behaviour and ARIA stays with the component. While
 * open, `autoUpdate` follows scroll, resize and layout shifts of the anchor; on close and on unmount
 * every listener and observer it attached is removed. The resolved side is written to the floating
 * element's `data-side` and `data-positioned` marks the first placement, so CSS can keep the surface
 * invisible until it has a position. Coordinates go through the CSSOM (`style.left` / `style.top`),
 * which a strict CSP allows, and never through React state.
 */
export function useAnchoredPosition({
  open,
  reference,
  floating,
  side,
  gapToken = "--space-inset-xs",
  fit = false,
}: AnchoredPositionOptions): void {
  useEffect(() => {
    const anchor = reference.current;
    const surface = floating.current;
    if (!open || surface === null) return undefined;
    // No anchor to measure: never leave the surface invisible (a focused panel must be seen).
    if (anchor === null) {
      surface.dataset["positioned"] = "";
      return undefined;
    }
    let active = true;
    delete surface.dataset["positioned"];
    const update = (): void => {
      const gap = lengthOf(surface, gapToken);
      const middleware = [offset(gap), flip({ padding: gap }), shift({ padding: gap })];
      if (fit)
        middleware.push(
          size({
            padding: gap,
            apply: ({ rects, availableHeight }) => {
              surface.style.setProperty("--cv-anchor-width", `${rects.reference.width}px`);
              surface.style.setProperty(
                "--cv-available-height",
                `${Math.max(0, availableHeight)}px`,
              );
            },
          }),
        );
      void computePosition(anchor, surface, {
        strategy: "fixed",
        placement: side,
        middleware,
      })
        .then(({ x, y, placement }) => {
          if (!active) return;
          surface.style.left = `${x}px`;
          surface.style.top = `${y}px`;
          surface.dataset["side"] = placement.split("-")[0] ?? side;
          surface.dataset["positioned"] = "";
        })
        .catch(() => {
          // A failed measurement shows the surface where it is rather than keeping it invisible.
          if (active) surface.dataset["positioned"] = "";
        });
    };
    const stop = autoUpdate(anchor, surface, update);
    return () => {
      active = false;
      stop();
      surface.style.removeProperty("--cv-anchor-width");
      surface.style.removeProperty("--cv-available-height");
    };
  }, [open, reference, floating, side, gapToken, fit]);
}
