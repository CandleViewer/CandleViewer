/**
 * Route tree builder (E10-T01). Declares every route ID R-001..R-903 from
 * `docs/plan/12-sitemap.md` §2 plus the documented redirects.
 *
 * Guard composition order is fixed: `requireAuth` -> `requireRole`,
 * implemented by `guardRoute` reading `RouteAccess` from the manifest. Step-up
 * is answered per action when the server challenges (#2725), never at route entry. Real screens (owned by later epics) render `StubRoute`;
 * routes this ticket owns (login/logout/403/404/settings-hub redirect)
 * render minimal placeholders.
 */
import { createBrowserRouter, redirect, type RouteObject } from "react-router";
import { ROUTE_MANIFEST, type ManifestEntry } from "./manifest";
import { ROUTE_TITLES, type TitleHandle } from "./titles";
import { guardRoute, guardUnknownRoute } from "./guards";
import { RouteErrorElement } from "./RouteErrorElement";
import { StubRoute } from "./StubRoute";
import { ForbiddenState, NotFoundState } from "./ErrorStates";
import { PlaceholderRoute } from "./PlaceholderRoute";
import { PanelErrorBoundary } from "../features/system-states/PanelErrorBoundary";
import { BackendUnreachable } from "../features/system-states/BackendUnreachable";
import { AdminRouteElement, isAdminRoute } from "../features/admin/AdminRouteElement";
import { LoginScreen } from "../features/auth/LoginScreen";
import { ChangePasswordScreen } from "../features/auth/ChangePasswordScreen";
import { InviteAcceptScreen } from "../features/invites/InviteAcceptScreen";
import { AppearanceScreen } from "../features/appearance/AppearanceScreen";
import { SetupChecklistCard } from "../features/onboarding/SetupChecklistCard";
import { HotkeyEditor } from "../keymap/HotkeyEditor";
import { AccessibilitySettingsScreen } from "../features/a11y-preferences/AccessibilitySettingsScreen";
import { SessionsSection } from "../features/session/SessionsSection";
import { getMeClaims } from "../lib/auth/meCache";
import { ShellLayout } from "../features/app-shell/ShellLayout";
import { ScreenRoot } from "../features/app-shell/ScreenRoot";

function elementFor(routeId: string, owner: string | null): RouteObject["element"] {
  if (routeId === "R-900") return <ForbiddenState />;
  if (routeId === "R-901") return <NotFoundState />;
  if (routeId === "R-902") return <BackendUnreachable />; // SCR-159 at boot (#306)
  if (routeId === "R-001") return <LoginScreen />;
  if (routeId === "R-007") return <ChangePasswordScreen />;
  if (routeId === "R-009") return <InviteAcceptScreen />;
  if (routeId === "R-202") return <HotkeyEditor />;
  // R-203 /settings/appearance hosts SCR-116 (palette) and SCR-117 a11y prefs (12-sitemap.md).
  if (routeId === "R-203")
    return (
      <>
        <AppearanceScreen />
        <AccessibilitySettingsScreen />
      </>
    );
  // R-201 /settings/profile hosts SCR-112; its sessions section ships first (#1640 S3), the rest is E11's.
  if (routeId === "R-201")
    return (
      <ScreenRoot>
        <h1>Security settings</h1>
        <SessionsSection />
      </ScreenRoot>
    );
  // E42-S01: each admin route inside CMP-087, its code loaded once the guard let the session in.
  if (isAdminRoute(routeId)) return <AdminRouteElement routeId={routeId} owner={owner} />;
  if (routeId === "R-101") {
    // First sign-in lands on /terminal/last -> here; the card is server-gated (401 => renders nothing).
    return (
      <>
        <PanelErrorBoundary id="setup-checklist">
          <SetupChecklistCard />
        </PanelErrorBoundary>
        <StubRoute routeId={routeId} owner={owner ?? "E15"} />
      </>
    );
  }
  if (owner === null) return <PlaceholderRoute />;
  return <StubRoute routeId={routeId} owner={owner} />;
}

function buildRoutes(): RouteObject[] {
  const toRoute = (entry: ManifestEntry): RouteObject => ({
    id: entry.id,
    path: entry.path,
    element: elementFor(entry.id, entry.owner),
    errorElement: <RouteErrorElement />,
    // D-01 (WCAG 2.4.2): the page title `syncDocumentTitle` applies on every navigation
    handle: { title: ROUTE_TITLES[entry.id] } satisfies TitleHandle,
    loader: ({ request }) => {
      guardRoute(entry.id, entry.access, request.url);
      // R-100 `/terminal` always redirects to the user's last-used or
      // default layout (`12-sitemap.md` §2 note on R-100).
      if (entry.id === "R-100") return redirect("/terminal/last");
      // R-200 `/settings` redirects to the profile tab (`12-sitemap.md` §2).
      if (entry.id === "R-200") return redirect("/settings/profile");
      // R-005 `/locked` is an alias (#1640 ruling 4): the SCR-005 overlay host, mounted over every
      // route, reads the session and opens the lock over the default route; no page of its own.
      if (entry.id === "R-005") return redirect("/terminal");
      // R-002 `/login/2fa`: SCR-002 is a step inside R-001 (#2711 BQ-02); its challenge handle exists
      // only in that step's memory, so a direct load has none and starts at SCR-001, with no query.
      if (entry.id === "R-002") return redirect("/login");
      return null;
    },
  });

  // E10-S01 (#304): every non-public route renders inside the shell layout and its one `main`;
  // public routes keep their own `main` outside it.
  const isPublic = (entry: ManifestEntry): boolean => entry.access.roles === "public";
  const routes: RouteObject[] = [
    {
      id: "shell",
      element: <ShellLayout />,
      errorElement: <RouteErrorElement />,
      children: [
        ...ROUTE_MANIFEST.filter((e) => !isPublic(e)).map(toRoute),
        // The catch-all sits in the shell, beside `/admin/**`: same guard outcome, same element,
        // same landmarks and focus for an unknown route and a hidden one (E09-D09 §6).
        {
          path: "*",
          errorElement: <RouteErrorElement />,
          loader: ({ request }) => guardUnknownRoute(request.url),
        },
      ],
    },
    ...ROUTE_MANIFEST.filter(isPublic).map(toRoute),
  ];

  // Documented redirects (`12-sitemap.md` §8: fresh install / unauthenticated root).
  routes.push({
    path: "/",
    loader: () => {
      const claims = getMeClaims();
      if (claims.role === null && !claims.authenticated) {
        return redirect("/login");
      }
      return redirect("/terminal");
    },
  });

  return routes;
}

export function createRouteTree(): ReturnType<typeof createBrowserRouter> {
  return createBrowserRouter(buildRoutes());
}

export { buildRoutes };
