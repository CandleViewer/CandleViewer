/**
 * RBAC primitives for the route tree (E10-T01).
 *
 * Source of truth for the role vocabulary and the route RBAC column encoding
 * is `docs/plan/12-sitemap.md` §2 and `docs/plan/10-personas.md` §7. This
 * module only encodes the *client-side* rendering decision — the server is
 * always the authorisation boundary (`docs/plan/04-security-program.md` §7.3).
 */

/** The three persisted roles (`10-personas.md` line 20). Admin is a hat, not a role. */
export type Role = "owner" | "manager" | "viewer";

export const ALL_ROLES: readonly Role[] = ["owner", "manager", "viewer"];

/**
 * Which roles may render a given route, and how a denial should be
 * surfaced. `"public"` routes require no session at all (pre-auth).
 */
export interface RouteAccess {
  /** `"public"` = no auth required. Otherwise the roles allowed to render the route. */
  readonly roles: readonly Role[] | "public";
  /**
   * `/admin/**` denies non-owners with 404, not 403, per sitemap §2 note on
   * R-300..R-360 ("owner-hat"). Every other RBAC-denied route renders 403.
   */
  readonly denyAs?: "403" | "404";
}

/** The claims the app shell caches from `GET /me` (`22-api-openapi.yaml`). */
export interface MeClaims {
  readonly authenticated: boolean;
  readonly role: Role | null;
  /** Flattened effective permission set, e.g. `"rules:author"`. */
  readonly permissions: readonly string[];
}

/*
 * No client-side step-up pre-emption (#2725): entering `/admin/**` asks for no step-up here. Each
 * dangerous action answers the server's own `403 step_up_required` challenge
 * (`features/stepUp/StepUpChallengeGate`), so step-up credentials are only ever sent with a
 * server-issued `challenge_id`. SCR-149's "re-auth on first entry" returns once its contract
 * (the admin re-auth endpoint or an `admin` grace class) lands.
 */

/** Client-side rendering decision for a route + claims pair. Never an authorisation grant. */
export type AccessDecision =
  { kind: "allow" } | { kind: "redirect-login" } | { kind: "deny"; as: "403" | "404" };

export function evaluateAccess(access: RouteAccess, claims: MeClaims): AccessDecision {
  if (access.roles === "public") return { kind: "allow" };
  if (!claims.authenticated || !claims.role) return { kind: "redirect-login" };
  if (!access.roles.includes(claims.role)) {
    return { kind: "deny", as: access.denyAs ?? "403" };
  }
  return { kind: "allow" };
}
