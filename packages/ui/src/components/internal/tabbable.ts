/*
 * A small tab-stop finder for CMP-017's edges and trap. Its limits: it reads attributes only, so an
 * element hidden by CSS (`display: none`, `visibility: hidden`, a zero size) still counts; a radio
 * group is not collapsed to its checked radio (each radio counts); positive `tabindex` order is not
 * applied (DOM order only); and shadow roots and iframes are not entered.
 */
/** Elements that can be tab stops; `tabbables` then drops the disabled, the hidden and the negative ones. */
const CANDIDATES = [
  "a[href]",
  "button",
  "input:not([type=hidden])",
  "select",
  "textarea",
  "summary",
  "[tabindex]",
  '[contenteditable]:not([contenteditable="false"])',
].join(",");

const isTabStop = (element: HTMLElement): boolean =>
  element.tabIndex >= 0 &&
  !element.matches(":disabled") &&
  element.closest("[hidden], [inert]") === null;

/** The tab stops inside `root`, in DOM order (a T2 control with `aria-disabled` stays one). */
export const tabbables = (root: ParentNode): HTMLElement[] =>
  [...root.querySelectorAll<HTMLElement>(CANDIDATES)].filter(isTabStop);

/** The first tab stop after `from` in document order, outside `from` and outside `skip`. */
export const tabStopAfter = (from: HTMLElement, skip: Node | null): HTMLElement | undefined =>
  tabbables(from.ownerDocument.body).find(
    (element) =>
      (from.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0 &&
      !from.contains(element) &&
      !(skip?.contains(element) ?? false),
  );
