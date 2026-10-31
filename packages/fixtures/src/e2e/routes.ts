// E10-Q02 role matrix: the declared outcome of every route id (apps/web's route manifest, E10-T01)
// for each of the three roles, signed in on stubs. The web spec iterates the manifest, not this
// table, and fails on a route with no entry here, so a new route cannot join without a declared
// outcome (Gherkin "Role matrix is exhaustive and self-updating"). The client's decision only:
// the server is the authorisation boundary (C-12.4), proven by the backend RBAC tests.

export type Role = "owner" | "manager" | "viewer";
export const ROLES: readonly Role[] = ["owner", "manager", "viewer"];

/**
 * - `render`: the route's own screen (a placeholder names its owning epic);
 * - `forbidden`: SCR-154's "You don't have access to this" (403);
 * - `not-found`: "Page not found" (the `/admin/**` owner-hat rule, 404);
 * - `redirect:<path>`: the shell lands on `<path>` instead (e.g. R-100 to the last layout).
 */
export type Outcome = "render" | "forbidden" | "not-found" | `redirect:${string}`;
export type Expectation = Readonly<Record<Role, Outcome>>;

const every = (o: Outcome): Expectation => ({ owner: o, manager: o, viewer: o });
const R = every("render");
/** OWNER_ONLY: 403 for the other roles. */
const OWNER = { owner: "render", manager: "forbidden", viewer: "forbidden" } as const;
/** Owner and manager: 403 for a viewer. */
const OWNER_MANAGER = { owner: "render", manager: "render", viewer: "forbidden" } as const;
/** `/admin/**` owner-hat: 404 for the other roles (sitemap §2). */
const ADMIN = { owner: "render", manager: "not-found", viewer: "not-found" } as const;

// One row per sitemap group: the table reads as the sitemap does.
// prettier-ignore
export const ROUTE_EXPECTATIONS: Readonly<Record<string, Expectation>> = {
  "R-001": R, "R-002": R, "R-003": R, "R-004": R,
  "R-005": every("redirect:/terminal/last"), // an unlocked session leaves the lock screen
  "R-006": R, "R-007": R, "R-008": R, "R-009": R,
  "R-100": every("redirect:/terminal/last"), // R-100 opens the last-used layout
  "R-101": R, "R-102": R, "R-110": R, "R-111": R, "R-120": R,
  "R-130": R, "R-131": R, "R-132": R, "R-140": R, "R-141": R, "R-142": OWNER,
  "R-150": OWNER, "R-151": R,
  "R-160": OWNER_MANAGER, "R-161": OWNER_MANAGER, "R-162": OWNER_MANAGER, "R-163": OWNER_MANAGER,
  "R-164": R, "R-170": R, "R-171": R, "R-180": R, "R-181": R, "R-182": R, "R-190": R, "R-191": R,
  "R-200": every("redirect:/settings/profile"), // Settings opens its default tab
  "R-201": R, "R-202": R, "R-203": R, "R-204": R, "R-205": R,
  "R-300": ADMIN, "R-301": ADMIN, "R-302": ADMIN, "R-303": ADMIN,
  "R-310": ADMIN, "R-311": ADMIN, "R-312": ADMIN,
  "R-320": ADMIN, "R-321": ADMIN, "R-322": ADMIN, "R-330": ADMIN, "R-331": ADMIN,
  "R-340": ADMIN, "R-350": ADMIN, "R-351": ADMIN, "R-352": ADMIN, "R-353": ADMIN,
  "R-354": ADMIN, "R-355": ADMIN, "R-356": ADMIN,
  "R-360": OWNER_MANAGER, // under /admin but owner and manager: a viewer gets 403, not 404
  "R-900": every("forbidden"), // R-900 *is* the 403 page
  "R-901": every("not-found"), // R-901 *is* the 404 page
  "R-902": R, "R-903": R,
};

/** The URL the matrix visits for a manifest path: every `:param` filled with one fixed value. */
export const concretePath = (path: string): string => path.replace(/:[A-Za-z]+/gu, "x1");

/** The level-1 heading of each denial screen, which is how the matrix classifies a landing. */
export const DENIAL_HEADINGS = {
  forbidden: "You don't have access to this",
  "not-found": "Page not found",
} as const;

/** What a landing shows: the requested path, where the shell ended up, and its level-1 heading. */
export function classify(requested: string, landed: string, heading: string): Outcome {
  if (heading === DENIAL_HEADINGS.forbidden) return "forbidden";
  if (heading === DENIAL_HEADINGS["not-found"]) return "not-found";
  return landed === requested ? "render" : `redirect:${landed}`;
}
