import type { JSX } from "react";
import { Link as RouterLink } from "react-router";
import type { LinkRoute, RenderLink } from "@candleviewer/ui";

/** CMP-021's router slot: the app's router link, given the `to` and the anchor props CMP-021 hands it. */
export const routerLink: LinkRoute = ({ to, ...anchor }) => <RouterLink to={to} {...anchor} />;

/** CMP-089's link slot, as `routes/ErrorStates.tsx` fills it. */
export const routerRenderLink: RenderLink = ({ href, className, children }): JSX.Element => (
  <RouterLink to={href} className={className}>
    {children}
  </RouterLink>
);
