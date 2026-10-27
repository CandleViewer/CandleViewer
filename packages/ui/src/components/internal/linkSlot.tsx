import type { JSX, ReactNode } from "react";

/** What a link slot receives: the host renders its router link with these, or a plain anchor. */
export interface LinkSlotProps {
  readonly href: string;
  readonly className: string;
  readonly children: ReactNode;
}

/** A host's link renderer (its router `Link`), so the package stays free of router imports. */
export type RenderLink = (link: LinkSlotProps) => ReactNode;

/** The default slot: a plain anchor, for stories and hosts without a client router. */
export function PlainLink({ href, className, children }: LinkSlotProps): JSX.Element {
  return (
    <a href={href} className={className}>
      {children}
    </a>
  );
}
