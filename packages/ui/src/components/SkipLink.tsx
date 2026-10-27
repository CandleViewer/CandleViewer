import type { JSX, MouseEvent } from "react";

/** One skip link: the id of the element it focuses and its visible, accessible label. */
export interface SkipLinkTarget {
  readonly id: string;
  readonly label: string;
}

/** Default English copy (plan gap 9: packaged components take copy as props, defaults exported beside them). */
export const SKIP_LINK_COPY = {
  main: "Skip to main content",
  orderTicket: "Skip to order ticket",
  chart: "Skip to chart",
} as const;

export interface SkipLinkProps {
  /**
   * The links, in DOM order; the first is always main content (`SKIP_LINK_COPY.main`), further ones
   * only for regions the route mounts (E05-D02 J19). Render before the TopBar: the first link is the
   * first focusable element of the document.
   */
  readonly targets: readonly [SkipLinkTarget, ...SkipLinkTarget[]];
}

/** Marks a target while it holds skip focus, so `skiplink.css` draws the CMP-039 ring on it. */
const TARGET_ATTR = "data-cv-skip-target";

/**
 * Focuses `target` (J20): an element that is not focusable takes `tabindex="-1"` until it loses focus;
 * one that already carries a tabindex keeps it. The next Tab continues from the target.
 */
function focusTarget(target: HTMLElement): void {
  const added = !target.hasAttribute("tabindex");
  if (added) target.setAttribute("tabindex", "-1");
  target.setAttribute(TARGET_ATTR, "");
  target.addEventListener(
    "blur",
    () => {
      target.removeAttribute(TARGET_ATTR);
      if (added) target.removeAttribute("tabindex");
    },
    { once: true },
  );
  target.focus();
}

/**
 * CMP-085: "Skip to main content" and its siblings (WCAG 2.4.1). Each link is visually hidden until
 * focused, then shown as a pill at the top-left of the positioned host. Activation (click, or Enter,
 * which arrives as a click) focuses the target in script and prevents the default, so the hash never
 * reaches the router. Never gated; no motion; no live region.
 */
export function SkipLink({ targets }: SkipLinkProps): JSX.Element {
  const onClick = (event: MouseEvent<HTMLAnchorElement>, id: string): void => {
    event.preventDefault();
    const target = event.currentTarget.ownerDocument.getElementById(id);
    if (target !== null) focusTarget(target);
  };
  return (
    <>
      {targets.map(({ id, label }) => (
        <a
          key={id}
          href={`#${id}`}
          className="cv-skip-link"
          data-cmp="CMP-085"
          onClick={(event) => onClick(event, id)}
        >
          {label}
        </a>
      ))}
    </>
  );
}
