// @vitest-environment node
import { describe, expect, it } from "vitest";
import { ADMIN_EXCEPTIONS, unguardedAdminRoutes } from "../e2e/admin/adminRoutes";
import { ROUTE_MANIFEST, type ManifestEntry } from "../src/routes/manifest";

/**
 * E42-Q02 (#1215) part 1, BQ-6: the ticket's meta-test, repeatable. `admin-routes.spec.ts` fails
 * on an `/admin` route without the admin guard because `unguardedAdminRoutes` returns it: these
 * feed that function the router's manifest and synthetic ones.
 */
const entry = (id: string, path: string, access: ManifestEntry["access"]): ManifestEntry => ({
  id,
  path,
  access,
  owner: null,
});
const guarded = entry("R-300", "/admin", { roles: ["owner"], denyAs: "404" });

describe("the admin route guard walk", () => {
  it("finds no unguarded /admin route in the router's manifest", () => {
    expect(unguardedAdminRoutes(ROUTE_MANIFEST)).toEqual([]);
    expect(ROUTE_MANIFEST.filter((e) => e.path.startsWith("/admin")).length).toBeGreaterThan(20);
  });

  it.each([
    ["public", { roles: "public" }],
    ["open to every role", { roles: ["owner", "manager", "viewer"] }],
    ["owner-only, but answered 403", { roles: ["owner"] }],
    ["owner-only, answered 403 by name", { roles: ["owner"], denyAs: "403" }],
    ["open to a manager, 404 for the rest", { roles: ["owner", "manager"], denyAs: "404" }],
  ] as const)("returns a synthetic /admin route that is %s", (_what, access) => {
    const added = entry("R-399", "/admin/zzz", access);
    expect(unguardedAdminRoutes([...ROUTE_MANIFEST, added])).toEqual([added]);
  });

  it("returns the exception once its access differs from the roles it is excepted for", () => {
    const opened = entry("R-360", "/admin/audit", { roles: ["owner", "manager", "viewer"] });
    const hidden = entry("R-360", "/admin/audit", { roles: ["owner", "manager"], denyAs: "404" });
    expect(unguardedAdminRoutes([guarded, opened, hidden])).toEqual([opened, hidden]);
  });

  it("returns a public /admin itself, not only the paths under it", () => {
    const opened = entry("R-397", "/admin", { roles: "public" });
    expect(unguardedAdminRoutes([...ROUTE_MANIFEST, opened])).toEqual([opened]);
  });

  it("reads /admin and the paths under it, never a look-alike", () => {
    const lookAlike = entry("R-398", "/administrator", { roles: "public" });
    expect(unguardedAdminRoutes([guarded, lookAlike])).toEqual([]);
  });

  it("holds exactly one exception, R-360, so a second cannot pass unseen", () => {
    expect(ADMIN_EXCEPTIONS).toEqual({
      "R-360": { roles: ["owner", "manager"], reason: "owner and manager: S04's own-actions log" },
    });
    const second = entry("R-399", "/admin/zzz", { roles: ["owner", "manager"] });
    expect(unguardedAdminRoutes([guarded, second])).toEqual([second]);
  });
});
