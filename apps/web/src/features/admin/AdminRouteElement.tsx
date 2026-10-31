import { lazy, Suspense, type JSX } from "react";
import { ROUTE_MANIFEST } from "../../routes/manifest";
import { StubRoute } from "../../routes/StubRoute";
import { useShellSelector } from "../../shell/useShellSelector";

/**
 * The admin area's code (CMP-087 and every admin page) loads only once an admin route's element
 * renders, which is after the route's loader let the session in (E42-S01 BQ-7; E42-D03 §11: the 404
 * with no call and no admin code loaded). `React.lazy` sits in the element on purpose: a route's own
 * `lazy` runs beside its loader, so a manager's 404 would already have fetched the chunk.
 */
const AdminArea = lazy(async () => ({ default: (await import("./shell/AdminArea")).AdminArea }));

/** `/admin` and every route under it, R-300 to R-360 (`12` §2): the routes CMP-087 frames. */
const ADMIN_ROUTE_IDS: ReadonlySet<string> = new Set(
  ROUTE_MANIFEST.filter((e) => e.path === "/admin" || e.path.startsWith("/admin/")).map(
    (e) => e.id,
  ),
);

export function isAdminRoute(routeId: string): boolean {
  return ADMIN_ROUTE_IDS.has(routeId);
}

/** R-360 `/admin/audit` also opens to a manager, outside the admin hat (`12` §2). */
const AUDIT_LOG = "R-360";

export interface AdminRouteElementProps {
  readonly routeId: string;
  /** The manifest's owner of the route's real screen, which a stub names. */
  readonly owner: string | null;
}

/**
 * Every admin route's element (E42-S01): the admin area, lazily. The guard has decided access by
 * then; this decides only R-360's frame, from the shell's `me`: CMP-087 for an owner, the plain shell
 * for a manager, who loads no admin code. No fallback of its own (none is designed): the page comes
 * with its band.
 */
export function AdminRouteElement({ routeId, owner }: AdminRouteElementProps): JSX.Element {
  const isOwner = useShellSelector((state) => state.me?.role === "owner");
  if (routeId === AUDIT_LOG && !isOwner) {
    return <StubRoute routeId={routeId} owner={owner ?? "E42"} />;
  }
  return (
    <Suspense fallback={null}>
      <AdminArea routeId={routeId} owner={owner} />
    </Suspense>
  );
}
