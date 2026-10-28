import { useLayoutEffect } from "react";

/*
 * The page scroll lock under a modal layer. The root stops scrolling, and the width its scrollbar took
 * is given back as padding, so nothing under the scrim shifts (no layout shift on lock). A page that
 * already reserves the gutter (`scrollbar-gutter: stable`) needs no padding. Locks nest: the first
 * one in sets the styles, the last one out restores them exactly.
 */

/** The custom property carrying the compensation, for a host's fixed bars (they ignore the root's padding). */
export const SCROLL_LOCK_GUTTER = "--cv-scroll-lock-gutter";

let count = 0;
let restore: (() => void) | null = null;

const lock = (): void => {
  count += 1;
  if (count > 1) return;
  const root = document.documentElement;
  const view = root.ownerDocument.defaultView ?? window;
  const gutter = Math.max(0, view.innerWidth - root.clientWidth);
  const reserved = getComputedStyle(root).getPropertyValue("scrollbar-gutter").includes("stable");
  const before = {
    overflow: root.style.overflow,
    paddingRight: root.style.paddingRight,
    gutter: root.style.getPropertyValue(SCROLL_LOCK_GUTTER),
  };
  const pad = reserved ? 0 : gutter;
  if (pad > 0) {
    const current = Number.parseFloat(getComputedStyle(root).paddingRight) || 0;
    root.style.paddingRight = `${String(current + pad)}px`;
  }
  root.style.setProperty(SCROLL_LOCK_GUTTER, `${String(pad)}px`);
  root.style.overflow = "hidden";
  restore = () => {
    root.style.overflow = before.overflow;
    root.style.paddingRight = before.paddingRight;
    if (before.gutter === "") root.style.removeProperty(SCROLL_LOCK_GUTTER);
    else root.style.setProperty(SCROLL_LOCK_GUTTER, before.gutter);
  };
};

const unlock = (): void => {
  count = Math.max(0, count - 1);
  if (count > 0) return;
  restore?.();
  restore = null;
};

/** While `active`, the page under the layer does not scroll. */
export function useScrollLock(active: boolean): void {
  useLayoutEffect(() => {
    if (!active || typeof document === "undefined") return undefined;
    lock();
    return unlock;
  }, [active]);
}
