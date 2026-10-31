/**
 * Page titles (D-01 / A11Y-F-0025, WCAG 2.4.2): one unique, descriptive title per route ID, from the
 * "Screen" column of `docs/plan/12-sitemap.md` §2, applied on every navigation as
 * "<page> - CandleViewer". Kept beside the manifest, not in it, so the manifest's entries stay
 * untouched (E10-S01 #304 owns the shell). PROPOSED wording (#5196).
 */
import { isRouteErrorResponse, type createBrowserRouter } from "react-router";
import { ForbiddenError } from "./guards";

export const PRODUCT_NAME = "CandleViewer";

export const ROUTE_TITLES: Readonly<Record<string, string>> = {
  "R-001": "Login",
  "R-002": "Two-factor code",
  "R-003": "First-run setup",
  "R-004": "Sign out",
  "R-005": "Session locked",
  "R-006": "Two-factor enrolment",
  "R-007": "Forced password change",
  "R-008": "Onboarding",
  "R-009": "Invitation acceptance",
  "R-100": "Terminal default layout",
  "R-101": "Terminal",
  "R-102": "Terminal pane",
  "R-110": "Watchlists",
  "R-111": "Watchlist group",
  "R-120": "Layouts",
  "R-130": "Positions and orders",
  "R-131": "Account positions and orders",
  "R-132": "Order detail",
  "R-140": "Trade groups",
  "R-141": "Trade group detail",
  "R-142": "New trade group",
  "R-150": "Risk dashboard",
  "R-151": "Account risk",
  "R-160": "Rules",
  "R-161": "Rule editor",
  "R-162": "Rule graph editor",
  "R-163": "New rule",
  "R-164": "Rule history",
  "R-170": "Replay sessions",
  "R-171": "Replay",
  "R-180": "Journal",
  "R-181": "Trade record",
  "R-182": "Journal analytics",
  "R-190": "Alerts",
  "R-191": "Alert detail",
  "R-200": "Settings",
  "R-201": "Profile and security",
  "R-202": "Hotkeys",
  "R-203": "Appearance",
  "R-204": "Notification settings",
  "R-205": "Window settings",
  "R-300": "Admin",
  "R-301": "Users and roles",
  "R-302": "User detail",
  "R-303": "Invite user",
  "R-310": "Exchange accounts",
  "R-311": "Exchange account detail",
  "R-312": "Add exchange account",
  "R-320": "API keys",
  "R-321": "API key detail",
  "R-322": "Rotate API key",
  "R-330": "Account profiles",
  "R-331": "Account profile editor",
  "R-340": "Recorder and retention",
  "R-350": "System health",
  "R-351": "Feature flags",
  "R-352": "Trade-group administration",
  "R-353": "Global risk policy",
  "R-354": "Security centre",
  "R-355": "Backups and restore",
  "R-356": "Maintenance mode control",
  "R-360": "Audit log",
  "R-900": "Forbidden",
  "R-901": "Not found",
  "R-902": "Backend unreachable",
  "R-903": "Maintenance",
};

/** The route's `handle`: its page title (every manifest ID has one; `manifest.test.ts`). */
export interface TitleHandle {
  readonly title: string | undefined;
}

export function documentTitle(page: string | undefined): string {
  return page === undefined ? PRODUCT_NAME : `${page} - ${PRODUCT_NAME}`;
}

type Router = ReturnType<typeof createBrowserRouter>;
type RouterState = Router["state"];

const titleOf = (handle: unknown): string | undefined =>
  typeof handle === "object" && handle !== null && typeof Reflect.get(handle, "title") === "string"
    ? (Reflect.get(handle, "title") as string)
    : undefined;

/** The page a settled router state shows: the error a guard threw, else the deepest titled match. */
export function pageTitle(state: RouterState): string | undefined {
  const error = state.errors === null ? undefined : Object.values(state.errors)[0];
  if (state.errors !== null) {
    if (error instanceof ForbiddenError) return error.as === "404" ? "Not found" : "Forbidden";
    if (isRouteErrorResponse(error)) {
      if (error.status === 404) return "Not found";
      return error.status === 403 ? "Forbidden" : "Something went wrong";
    }
    return "Something went wrong";
  }
  // the deepest match with a title names the page
  let title: string | undefined;
  for (const match of state.matches) title = titleOf(match.route.handle) ?? title;
  return title;
}

/** Sets `document.title` now and after every settled navigation; returns the unsubscribe. */
export function syncDocumentTitle(router: Router): () => void {
  const apply = (state: RouterState): void => {
    if (state.navigation.state !== "idle" || !state.initialized) return;
    document.title = documentTitle(pageTitle(state));
  };
  apply(router.state);
  return router.subscribe(apply);
}
