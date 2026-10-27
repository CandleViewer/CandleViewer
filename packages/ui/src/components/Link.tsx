import type { ComponentPropsWithoutRef, ComponentType, JSX, ReactNode } from "react";
import { Icon } from "../icons/Icon.js";
import { cx } from "./internal/cx.js";
import { useFocusRing } from "./FocusRing.js";

/** The visually hidden suffix of an external link's accessible name (CMP-021 A11y line, E25). */
export const EXTERNAL_LINK_TEXT = " (opens externally)";

/**
 * What the router slot receives: the anchor's own attributes plus `to`. A router link component (the app's
 * router, never imported here) renders the `<a>`, so the slot keeps native link semantics.
 */
export type LinkSlotProps = Omit<ComponentPropsWithoutRef<"a">, "href"> & {
  to: string;
  children?: ReactNode;
};

/** A router's link component, passed in by the app: `packages/ui` never imports a router. */
export type LinkSlot = ComponentType<LinkSlotProps>;

interface LinkBase extends Omit<
  ComponentPropsWithoutRef<"a">,
  "href" | "target" | "rel" | "className" | "style" | "children" | "role" | "aria-disabled"
> {
  /** The visible link text: it names the link. */
  children: ReactNode;
  /** Not available (no gating, E27 held): `role="link"` + `aria-disabled`, no href, not focusable. */
  disabled?: boolean;
}

/** A plain `href`; `external` opens it outside the app (a new browsing context the Electron shell routes). */
interface HrefLink extends LinkBase {
  href: string;
  external?: boolean;
  to?: never;
  as?: never;
}

/** An in-app route: `to` through the app's router link component, passed as `as`. */
interface RouteLink extends LinkBase {
  to: string;
  as: LinkSlot;
  href?: never;
  external?: never;
}

export type LinkProps = HrefLink | RouteLink;

/** The external glyph and the hidden suffix; the word joiner keeps the glyph on the last word's line. */
function ExternalMark(): JSX.Element {
  return (
    <>
      <span className="cv-visually-hidden">{EXTERNAL_LINK_TEXT}</span>
      <span className="cv-link__external" aria-hidden="true">
        {"⁠"}
        <Icon name="external-link" />
      </span>
    </>
  );
}

/**
 * CMP-021 Link: a native `<a>`, always underlined (`color.text.link` alone is 2.16:1 against body text,
 * WCAG 1.4.1), with the CMP-039 ring at the link's own square corners (E8). `external` adds
 * `rel="noopener noreferrer"` (E25: no opener handle, no Referer leaking the private host),
 * `target="_blank"`, a decorative glyph and the hidden suffix. Disabled renders `<a role="link" aria-disabled="true">` with no href, so Tab skips it.
 */
export function Link(props: LinkProps): JSX.Element {
  const { children, disabled, href, to, as: Slot, external, onClick, ...rest } = props;
  const ring = useFocusRing();
  const isExternal = external === true;
  const mark = isExternal ? <ExternalMark /> : null;
  const common = {
    ...rest,
    className: cx(ring.className, "cv-link"),
    "data-cmp": "CMP-021",
    "data-external": isExternal ? "" : undefined,
  };
  if (disabled === true) {
    return (
      <a {...common} role="link" aria-disabled="true">
        {children}
        {mark}
      </a>
    );
  }
  if (Slot !== undefined && to !== undefined) {
    return (
      <Slot {...common} to={to} onClick={onClick}>
        {children}
      </Slot>
    );
  }
  if (isExternal) {
    return (
      <a {...common} href={href} onClick={onClick} target="_blank" rel="noopener noreferrer">
        {children}
        {mark}
      </a>
    );
  }
  return (
    <a {...common} href={href} onClick={onClick}>
      {children}
    </a>
  );
}
