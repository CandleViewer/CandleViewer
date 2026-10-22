/**
 * React Router loaders implementing the guard composition order fixed by
 * the ticket: `requireAuth` -> `requireRole` -> `requireStepUp`.
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

export class StepUpRequiredError extends Error {
  readonly redirectTo: string;
  constructor(redirectTo: string) {
    super("step_up_required");
    this.redirectTo = redirectTo;
  }
}

function logDenial(routeId: string, reason: string): void {
  console.info(`[route-guard] denied route=${routeId} reason=${reason}`);
}

/**
 * Guards a single route. Throws a Response redirect for unauthenticated
 * users (preserving the intended destination), a `ForbiddenError` for a
 * role denial, or a `StepUpRequiredError` when `/admin/**` step-up has
 * expired.
 */
export function guardRoute(routeId: string, access: RouteAccess, requestUrl: string): void {
  const claims = getMeClaims();
  const decision = evaluateAccess(access, claims);
  switch (decision.kind) {
    case "allow":
      return;
    case "redirect-login": {
      const url = new URL(requestUrl);
      const next = encodeURIComponent(url.pathname + url.search);
      logDenial(routeId, "unauthenticated");
      throw redirect(`/login?next=${next}`);
    }
    case "deny":
      logDenial(routeId, `role-denied:${decision.as}`);
      throw new ForbiddenError(decision.as);
    case "step-up-required": {
      logDenial(routeId, "step-up-expired");
      const url = new URL(requestUrl);
      throw new StepUpRequiredError(url.pathname + url.search);
    }
    default: {
      const exhaustive: never = decision;
      throw new Error(`unreachable: ${JSON.stringify(exhaustive)}`);
    }
  }
}
