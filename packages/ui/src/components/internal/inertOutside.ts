import { useLayoutEffect, type RefObject } from "react";

/*
 * The inert page under a modal layer (conventions 31; plan §3 item 6). Every subtree outside the
 * layer's root is made `inert` (pointer, focus and the accessibility tree), except elements marked
 * `data-cv-inert-exempt` (the shell's TopBar, env band, StatusBar and announcer regions, H23) and the
 * path down to them. The default, with nothing marked, is the whole page (APG). Where the engine lacks
 * `inert` the fallback is `aria-hidden="true"`, which hides the page from assistive technology only.
 *
 * Holds are counted per node, so stacked modals unwind in any order: the first hold hides a node and
 * records its prior state, and only the last release restores it. A node that was already inert or
 * hidden before any layer held it is never held, so no layer ever makes it visible.
 */

export const INERT_EXEMPT = "data-cv-inert-exempt";

const SKIPPED = new Set(["SCRIPT", "STYLE", "LINK", "TEMPLATE", "NOSCRIPT"]);

const supportsInert = (): boolean => "inert" in HTMLElement.prototype;

interface Hold {
  count: number;
  restore: () => void;
}

/** Every node a layer holds hidden, with the number of layers holding it. */
const held = new Map<Element, Hold>();

const hiddenAlready = (element: Element, native: boolean): boolean =>
  native ? element.hasAttribute("inert") : element.getAttribute("aria-hidden") === "true";

const apply = (element: Element, native: boolean): (() => void) => {
  if (native) {
    element.setAttribute("inert", "");
    return () => element.removeAttribute("inert");
  }
  const before = element.getAttribute("aria-hidden");
  element.setAttribute("aria-hidden", "true");
  return () => {
    if (before === null) element.removeAttribute("aria-hidden");
    else element.setAttribute("aria-hidden", before);
  };
};

/** Takes one hold on `element`; false for a node hidden by something else, which is left alone. */
const acquire = (element: Element, native: boolean): boolean => {
  const hold = held.get(element);
  if (hold !== undefined) {
    hold.count += 1;
    return true;
  }
  if (hiddenAlready(element, native)) return false;
  held.set(element, { count: 1, restore: apply(element, native) });
  return true;
};

/** Gives one hold back; the last one out restores the node's prior state. */
const release = (element: Element): void => {
  const hold = held.get(element);
  if (hold === undefined) return;
  hold.count -= 1;
  if (hold.count > 0) return;
  held.delete(element);
  hold.restore();
};

/**
 * Hides every subtree under `from` that holds none of `keep`, walking down the paths (up to `body`)
 * to the kept nodes.
 */
const hideOutside = (
  body: HTMLElement,
  from: Element,
  keep: Element[],
  take: (element: Element) => void,
): void => {
  const paths = new Set<Element>();
  for (const node of keep)
    for (
      let at: Element | null = node.parentElement;
      at !== null && at !== body;
      at = at.parentElement
    )
      paths.add(at);
  const walk = (parent: Element): void => {
    for (const child of parent.children) {
      if (SKIPPED.has(child.tagName) || keep.includes(child)) continue;
      if (paths.has(child)) walk(child);
      else take(child);
    }
  };
  walk(from);
};

/**
 * While `active`, everything outside `root` is inert, the exempt regions aside. A subtree added to
 * `body` meanwhile is made inert too, unless it is a later layer (`data-cv-layer`) or exempt. A layer
 * added later that holds `root` (a parent dialog mounting open in the same commit as its child) is
 * walked like the page: its own surface goes inert, the path to `root` stays live.
 */
export function useInertOutside(active: boolean, root: RefObject<HTMLElement | null>): void {
  useLayoutEffect(() => {
    const layer = root.current;
    if (!active || layer === null) return undefined;
    const body = layer.ownerDocument.body;
    const native = supportsInert();
    const mine = new Set<Element>();
    const take = (element: Element): void => {
      if (!mine.has(element) && acquire(element, native)) mine.add(element);
    };
    const keep = (): Element[] => [layer, ...body.querySelectorAll(`[${INERT_EXEMPT}]`)];
    hideOutside(body, body, keep(), take);
    const observer = new MutationObserver((records) => {
      for (const record of records)
        for (const added of record.addedNodes) {
          if (!(added instanceof Element) || SKIPPED.has(added.tagName)) continue;
          if (added.hasAttribute(INERT_EXEMPT)) continue;
          if (!added.hasAttribute("data-cv-layer")) take(added);
          else if (added !== layer && added.contains(layer)) hideOutside(body, added, keep(), take);
        }
    });
    observer.observe(body, { childList: true });
    return () => {
      observer.disconnect();
      for (const element of [...mine].reverse()) release(element);
      mine.clear();
    };
  }, [active, root]);
}

/**
 * A portalled surface (a Popover panel, a Tooltip) portals to `body` outside any Dialog, so an open
 * Dialog would make it inert. While `active`, a surface whose anchor sits in an exempt region (a
 * TopBar control, H23) is exempt too: marked `data-cv-inert-exempt`, and lifted if a layer holds it.
 */
export function useExemptWithAnchor(
  active: boolean,
  anchor: RefObject<HTMLElement | null>,
  surface: RefObject<HTMLElement | null>,
): void {
  useLayoutEffect(() => {
    const node = surface.current;
    const from = anchor.current;
    if (!active || node === null || from === null) return undefined;
    if (from.closest(`[${INERT_EXEMPT}]`) === null) return undefined;
    node.setAttribute(INERT_EXEMPT, "");
    const hold = held.get(node);
    if (hold !== undefined) {
      // Lifted now; the holders' later releases have nothing left to restore.
      hold.restore();
      hold.restore = () => undefined;
    }
    return () => node.removeAttribute(INERT_EXEMPT);
  }, [active, anchor, surface]);
}
