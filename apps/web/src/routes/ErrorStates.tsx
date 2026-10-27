import type { JSX } from "react";
import { Link, useLocation } from "react-router";
import {
  ForbiddenState as ForbiddenStateView,
  NotFoundState as NotFoundStateView,
  type RenderLink,
} from "@candleviewer/ui";
import { ScreenRoot } from "../features/app-shell/ScreenRoot";
import { visibleNavItems } from "../features/app-shell/NavRail";
import { getMeClaims } from "../lib/auth/meCache";

/** The packaged states take the app's router link through their link slot. */
const routerLink: RenderLink = ({ href, className, children }) => (
  <Link to={href} className={className}>
    {children}
  </Link>
);

/**
 * R-900 `/403` and a role-denied route: CMP-089 in its step-3 never-had form. No request was
 * sent, so there is no Ref (D09 §5.1); the 403-body Ref and the withdrawn variant need the
 * server signal and land with it.
 */
export function ForbiddenState(): JSX.Element {
  return (
    <ScreenRoot>
      <ForbiddenStateView homeHref="/terminal" renderLink={routerLink} />
    </ScreenRoot>
  );
}

/**
 * R-901 `/404`, any unknown route and `/admin/**` for a session without `admin:read` (D09 §6):
 * one rendering for all of them. "Try:" lists the session's permitted top-level routes from the
 * nav rail's own `evaluateAccess` filter, so it is never a route that would answer 403.
 */
export function NotFoundState(): JSX.Element {
  const { pathname } = useLocation();
  const tryRoutes = visibleNavItems(getMeClaims()).map((item) => ({
    label: item.label,
    href: item.to,
  }));
  return (
    <ScreenRoot>
      <NotFoundStateView path={pathname} tryRoutes={tryRoutes} renderLink={routerLink} />
    </ScreenRoot>
  );
}
