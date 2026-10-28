import { useLayoutEffect, type RefObject } from "react";

/*
 * The inert page under a modal layer (conventions 31; plan §3 item 6). Every subtree outside the
 * layer's root is made `inert` (pointer, focus and the accessibility tree), except elements marked
 * `data-cv-inert-exempt` (the shell's TopBar, env band, StatusBar and announcer regions, H23) and the
 * path down to them. The default, with nothing marked, is the whole page (APG). Where the engine lacks
 * `inert` the fallback is `aria-hidden="true"`, which hides the page from assistive technology only.
 * Only what this layer set is restored; a node that was already inert or hidden is left alone, so
 * stacked modals unwind in any order.
 */

export const INERT_EXEMPT = "data-cv-inert-exempt";

const SKIPPED = new Set(["SCRIPT", "STYLE", "LINK", "TEMPLATE", "NOSCRIPT"]);

const supportsInert = (): boolean => "inert" in HTMLElement.prototype;

type Undo = () => void;

const hide = (element: Element, native: boolean): Undo | null => {
  if (native) {
    if (element.hasAttribute("inert")) return null;
    element.setAttribute("inert", "");
    return () => element.removeAttribute("inert");
  }
  if (element.getAttribute("aria-hidden") === "true") return null;
  const before = element.getAttribute("aria-hidden");
  element.setAttribute("aria-hidden", "true");
  return () => {
    if (before === null) element.removeAttribute("aria-hidden");
    else element.setAttribute("aria-hidden", before);
  };
};

/** Hides every subtree of `body` that holds none of `keep`, walking down the paths to the kept nodes. */
const hideOutside = (body: HTMLElement, keep: Element[], native: boolean): Undo[] => {
  const paths = new Set<Element>();
  for (const node of keep)
    for (
      let at: Element | null = node.parentElement;
      at !== null && at !== body;
      at = at.parentElement
    )
      paths.add(at);
  const undo: Undo[] = [];
  const walk = (parent: Element): void => {
    for (const child of parent.children) {
      if (SKIPPED.has(child.tagName) || keep.includes(child)) continue;
      if (paths.has(child)) walk(child);
      else {
        const done = hide(child, native);
        if (done !== null) undo.push(done);
      }
    }
  };
  walk(body);
  return undo;
};

/**
 * While `active`, everything outside `root` is inert, the exempt regions aside. A subtree added to
 * `body` meanwhile is made inert too, unless it is a later layer (`data-cv-layer`) or exempt.
 */
export function useInertOutside(active: boolean, root: RefObject<HTMLElement | null>): void {
  useLayoutEffect(() => {
    const layer = root.current;
    if (!active || layer === null) return undefined;
    const body = layer.ownerDocument.body;
    const native = supportsInert();
    const keep = (): Element[] => [layer, ...body.querySelectorAll(`[${INERT_EXEMPT}]`)];
    const undo = hideOutside(body, keep(), native);
    const observer = new MutationObserver((records) => {
      for (const record of records)
        for (const added of record.addedNodes) {
          if (!(added instanceof Element) || SKIPPED.has(added.tagName)) continue;
          if (added.hasAttribute("data-cv-layer") || added.hasAttribute(INERT_EXEMPT)) continue;
          const done = hide(added, native);
          if (done !== null) undo.push(done);
        }
    });
    observer.observe(body, { childList: true });
    return () => {
      observer.disconnect();
      for (const done of undo.splice(0).reverse()) done();
    };
  }, [active, root]);
}
