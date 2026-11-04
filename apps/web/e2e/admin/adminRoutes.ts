import type { ManifestEntry } from "../../src/routes/manifest";
import type { RouteAccess } from "../../src/routes/rbac";

// E42-Q02 (#1215) part 1, BQ-6: which `/admin` routes of the router's own manifest (the list
// `tree.tsx` builds the router from) lack the admin guard. Pure, so `test/e2e-admin-routes.test.ts`
// feeds it synthetic manifests: a new admin route without the guard fails `admin-routes.spec.ts`
// and that test, never only a list a route's author edits.

/** The admin guard (`manifest.ts` ADMIN): owners only; everyone else gets the 404. */
export const ADMIN_GUARD: RouteAccess = { roles: ["owner"], denyAs: "404" };

/** The closed exceptions: each route id, the roles it must admit, and why. Pinned whole. */
export const ADMIN_EXCEPTIONS: Readonly<
  Record<
    string,
    { readonly roles: readonly ("owner" | "manager" | "viewer")[]; readonly reason: string }
  >
> = {
  "R-360": { roles: ["owner", "manager"], reason: "owner and manager: S04's own-actions log" },
};

/** `/admin` and the paths under it, never a look-alike such as `/administrator`. */
export const isAdminPath = (path: string): boolean =>
  path === "/admin" || path.startsWith("/admin/");

const shape = (access: RouteAccess): string =>
  JSON.stringify([
    access.roles === "public" ? "public" : [...access.roles].sort(),
    access.denyAs ?? null,
  ]);

/**
 * The `/admin` entries whose access is not the admin guard, or, for an exception, not exactly
 * the roles it is excepted for.
 */
export function unguardedAdminRoutes(
  manifest: readonly ManifestEntry[],
  exceptions: typeof ADMIN_EXCEPTIONS = ADMIN_EXCEPTIONS,
): ManifestEntry[] {
  return manifest.filter((entry) => {
    if (!isAdminPath(entry.path)) return false;
    const excepted = exceptions[entry.id];
    const expected = excepted === undefined ? ADMIN_GUARD : { roles: excepted.roles };
    return shape(entry.access) !== shape(expected);
  });
}
