/**
 * Route tree builder (E10-T01). Declares every route ID R-001..R-903 from
 * `docs/plan/12-sitemap.md` §2 plus the documented redirects.
 *
 * Guard composition order is fixed: `requireAuth` -> `requireRole` ->
 * `requireStepUp`, implemented by `guardRoute` reading `RouteAccess` from
 * the manifest. Real screens (owned by later epics) render `StubRoute`;
 * routes this ticket owns (login/logout/403/404/settings-hub redirect)
 * render minimal placeholders.
 */
import { createBrowserRouter, redirect, type RouteObject } from "react-router-dom";
import { ROUTE_MANIFEST } from "./manifest";
import { guardRoute } from "./guards";
import { RouteErrorElement } from "./RouteErrorElement";
import { StubRoute } from "./StubRoute";
import { ForbiddenState, NotFoundState } from "./ErrorStates";
import { PlaceholderRoute } from "./PlaceholderRoute";
import { AdminInviteScreen } from "../features/invites/AdminInviteScreen";
import { LoginScreen } from "../features/auth/LoginScreen";
import { ChangePasswordScreen } from "../features/auth/ChangePasswordScreen";
import { InviteAcceptScreen } from "../features/invites/InviteAcceptScreen";
import { AppearanceScreen } from "../features/appearance/AppearanceScreen";
import { SetupChecklistCard } from "../features/onboarding/SetupChecklistCard";
import { HotkeyEditor } from "../keymap/HotkeyEditor";
import { AccessibilitySettingsScreen } from "../features/a11y-preferences/AccessibilitySettingsScreen";
import { getMeClaims } from "../lib/auth/meCache";

function elementFor(routeId: string, owner: string | null): RouteObject["element"] {
  if (routeId === "R-900") return <ForbiddenState />;
  if (routeId === "R-901") return <NotFoundState />;
  if (routeId === "R-001") return <LoginScreen />;
  if (routeId === "R-007") return <ChangePasswordScreen />;
  if (routeId === "R-009") return <InviteAcceptScreen />;
  if (routeId === "R-202")
    return (
      <main>
        <HotkeyEditor />
      </main>
    );
  // R-203 /settings/appearance hosts SCR-116 (palette) and SCR-117 a11y prefs (12-sitemap.md).
  if (routeId === "R-203")
    return (
      <>
        <AppearanceScreen />
        <AccessibilitySettingsScreen />
      </>
    );
  if (routeId === "R-303") return <AdminInviteScreen />;
  if (routeId === "R-101") {
    // First sign-in lands on /terminal/last -> here; the card is server-gated (401 => renders nothing).
    return (
      <>
        <SetupChecklistCard />
        <StubRoute routeId={routeId} owner={owner ?? "E15"} />
      </>
    );
  }
  if (owner === null) return <PlaceholderRoute />;
  return <StubRoute routeId={routeId} owner={owner} />;
}

function buildRoutes(): RouteObject[] {
  const routes: RouteObject[] = ROUTE_MANIFEST.map((entry) => ({
    id: entry.id,
    path: entry.path,
    element: elementFor(entry.id, entry.owner),
    errorElement: <RouteErrorElement />,
    loader: ({ request }) => {
      guardRoute(entry.id, entry.access, request.url);
      // R-100 `/terminal` always redirects to the user's last-used or
      // default layout (`12-sitemap.md` §2 note on R-100).
      if (entry.id === "R-100") return redirect("/terminal/last");
      // R-200 `/settings` redirects to the profile tab (`12-sitemap.md` §2).
      if (entry.id === "R-200") return redirect("/settings/profile");
      return null;
    },
  }));

  // Documented redirects (`12-sitemap.md` §8: fresh install / unauthenticated root).
  routes.push(
    {
      path: "/",
      loader: () => {
        const claims = getMeClaims();
        if (claims.role === null && !claims.authenticated) {
          return redirect("/login");
        }
        return redirect("/terminal");
      },
    },
    { path: "*", element: <NotFoundState /> },
  );

  return routes;
}

/**
 * TEMPORARY, deleted by the react-router 7 upgrade: the v7 behaviour flags, switched on for 6.30
 * so the app and its tests run the v7 semantics before the version moves.
 */
export const V7_ROUTER_FLAGS = {
  v7_relativeSplatPath: true,
  v7_fetcherPersist: true,
  v7_normalizeFormMethod: true,
  v7_partialHydration: true,
  v7_skipActionErrorRevalidation: true,
} as const;
export const V7_RENDER_FLAGS = { v7_startTransition: true } as const;

export function createRouteTree(): ReturnType<typeof createBrowserRouter> {
  return createBrowserRouter(buildRoutes(), { future: V7_ROUTER_FLAGS });
}

export { buildRoutes };
