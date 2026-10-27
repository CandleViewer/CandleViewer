/**
 * React Router loaders implementing the guard composition order fixed by
 * the ticket: `requireAuth` -> `requireRole`. There is no client step-up
 * pre-emption (#2725): step-up answers the server's own challenge per action.
 *
 * These are client-side UX guards only (`docs/plan/04-security-program.md`
 * §7.3) — every underlying API call is independently authorised
 * server-side. Denials are logged at info with the route id and reason
 * (never audited client-side; the server-side 403 is the audited event).
 */
import { redirect } from "react-router";
import { getMeClaims } from "../lib/auth/meCache";
import { evaluateAccess, type RouteAccess } from "./rbac";

export class ForbiddenError extends Error {
  readonly as: "403" | "404";
  constructor(as: "403" | "404") {
    super(as === "404" ? "Not found" : "Forbidden");
    this.as = as;
  }
}

function logDenial(routeId: string, reason: string): void {
  console.info(`[route-guard] denied route=${routeId} reason=${reason}`);
}

/**
 * Guards a single route. Throws a Response redirect for unauthenticated
 * users (preserving the intended destination), or a `ForbiddenError` for a
 * role denial.
 */
export function guardRoute(routeId: string, access: RouteAccess, requestUrl: string): void {
  const claims = getMeClaims();
  const decision = evaluateAccess(access, claims);
  // A hidden route (`/admin/**`, `denyAs: "404"`) logs nothing, so the console cannot tell it
  // from an unknown route, which logs nothing either (E09-D09 §6).
  const log = access.denyAs === "404" ? (): void => undefined : logDenial;
  switch (decision.kind) {
    case "allow":
      return;
    case "redirect-login": {
      const url = new URL(requestUrl);
      // Nothing reads `next` yet. Its first reader must use it only when
      // `new URL(next, location.origin)` keeps the same origin.
      const next = encodeURIComponent(url.pathname + url.search);
      log(routeId, "unauthenticated");
      throw redirect(`/login?next=${next}`);
    }
    case "deny":
      log(routeId, `role-denied:${decision.as}`);
      throw new ForbiddenError(decision.as);
    default: {
      const exhaustive: never = decision;
      throw new Error(`unreachable: ${JSON.stringify(exhaustive)}`);
    }
  }
}

/** Every role, denied as a hidden route: the catch-all answers exactly as `/admin/**` does. */
const UNKNOWN: RouteAccess = { roles: ["owner", "manager", "viewer"], denyAs: "404" };

/**
 * The catch-all loader: an unauthenticated session goes to `/login?next=…` and every other one
 * gets the same `ForbiddenError("404")` a hidden route throws, so an unknown route and an admin
 * route the session cannot see take one path to one page (E09-D09 §6).
 */
export function guardUnknownRoute(requestUrl: string): never {
  guardRoute("*", UNKNOWN, requestUrl);
  throw new ForbiddenError("404");
}
