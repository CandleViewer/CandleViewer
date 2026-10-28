import { useEffect, useState, type RefObject } from "react";
import { visibleTabbables } from "./focusTrap.js";

/**
 * Overflow=scrolls with no control inside: the scrolling body of an overlay (Dialog, Drawer) takes a Tab
 * stop, so the keyboard can scroll it (WCAG 2.1.1; axe scrollable-region-focusable). True while `body`
 * scrolls and holds no tab stop. Re-measured as the body or its content resizes, and as content is added
 * or removed (a child added later is observed too: a capped body itself does not resize).
 */
export function useReadableScroll(open: boolean, body: RefObject<HTMLElement | null>): boolean {
  const [readable, setReadable] = useState(false);
  useEffect(() => {
    const node = body.current;
    if (!open || node === null) return undefined;
    const measure = (): void => {
      setReadable(node.scrollHeight > node.clientHeight && visibleTabbables(node).length === 0);
    };
    const resize = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    const observeChildren = (): void => {
      if (resize === null) return;
      resize.observe(node);
      for (const child of node.children) resize.observe(child);
    };
    const mutation =
      typeof MutationObserver === "undefined"
        ? null
        : new MutationObserver(() => {
            observeChildren();
            measure();
          });
    observeChildren();
    mutation?.observe(node, { childList: true, subtree: true });
    measure();
    return () => {
      resize?.disconnect();
      mutation?.disconnect();
    };
  }, [open, body]);
  return readable;
}
