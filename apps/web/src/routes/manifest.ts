/**
 * Route manifest (E10-T01). One entry per route ID in
 * `docs/plan/12-sitemap.md` §2 (R-001..R-903). Consumed by:
 *  - `tree.tsx` to build the React Router data router.
 *  - the command palette, SCR-012 (E10-S05, #5236): its Navigate group.
 *  - the E10-Q01 route-matrix test, which iterates every sitemap route ID
 *    and fails if this manifest is missing one.
 *
 * `owner` on a stub entry names the epic that will replace the placeholder
 * element; it has no runtime effect.
 */
import type { RouteAccess } from "./rbac";

export interface ManifestEntry {
  readonly id: string;
  readonly path: string;
  readonly access: RouteAccess;
  /** Epic that owns the real screen content; `null` once implemented by this ticket. */
  readonly owner: string | null;
}

const ALL: RouteAccess = { roles: ["owner", "manager", "viewer"] };
const OWNER_ONLY: RouteAccess = { roles: ["owner"] };
const ADMIN: RouteAccess = { roles: ["owner"], denyAs: "404" };
const PUBLIC: RouteAccess = { roles: "public" };

export const ROUTE_MANIFEST: readonly ManifestEntry[] = [
  // Auth & session
  { id: "R-001", path: "/login", access: PUBLIC, owner: "E09" },
  { id: "R-002", path: "/login/2fa", access: PUBLIC, owner: "E09" },
  { id: "R-003", path: "/login/first-run", access: PUBLIC, owner: "E09" },
  { id: "R-004", path: "/logout", access: ALL, owner: "E09" },
  { id: "R-005", path: "/locked", access: ALL, owner: "E09" },
  { id: "R-006", path: "/login/2fa/enroll", access: PUBLIC, owner: "E09" },
  { id: "R-007", path: "/login/change-password", access: PUBLIC, owner: "E09" },
  { id: "R-008", path: "/onboarding", access: ALL, owner: "E09" },
  { id: "R-009", path: "/invite/:inviteToken", access: PUBLIC, owner: null },

  // Trading Terminal
  { id: "R-100", path: "/terminal", access: ALL, owner: "E15" },
  { id: "R-101", path: "/terminal/:layoutId", access: ALL, owner: "E15" },
  { id: "R-102", path: "/terminal/:layoutId/pane/:paneId", access: ALL, owner: "E15" },

  // Watchlist / symbol search
  { id: "R-110", path: "/watchlist", access: ALL, owner: "E13" },
  { id: "R-111", path: "/watchlist/:groupId", access: ALL, owner: "E13" },

  // Layouts & workspaces
  { id: "R-120", path: "/layouts", access: ALL, owner: "E15" },

  // Positions & Orders
  { id: "R-130", path: "/positions", access: ALL, owner: "E12" },
  { id: "R-131", path: "/positions/:accountId", access: ALL, owner: "E12" },
  { id: "R-132", path: "/positions/order/:orderId", access: ALL, owner: "E12" },

  // Trade groups
  { id: "R-140", path: "/trade-groups", access: ALL, owner: "E12" },
  { id: "R-141", path: "/trade-groups/:groupId", access: ALL, owner: "E12" },
  { id: "R-142", path: "/trade-groups/new", access: OWNER_ONLY, owner: "E12" },

  // Risk Dashboard
  { id: "R-150", path: "/risk", access: OWNER_ONLY, owner: "E12" },
  { id: "R-151", path: "/risk/:accountId", access: ALL, owner: "E12" },

  // Rule Builder
  { id: "R-160", path: "/rules", access: { roles: ["owner", "manager"] }, owner: "E14" },
  { id: "R-161", path: "/rules/:ruleId", access: { roles: ["owner", "manager"] }, owner: "E14" },
  {
    id: "R-162",
    path: "/rules/:ruleId/graph",
    access: { roles: ["owner", "manager"] },
    owner: "E14",
  },
  { id: "R-163", path: "/rules/new", access: { roles: ["owner", "manager"] }, owner: "E14" },
  { id: "R-164", path: "/rules/:ruleId/history", access: ALL, owner: "E14" },

  // Replay
  { id: "R-170", path: "/replay", access: ALL, owner: "E16" },
  { id: "R-171", path: "/replay/:sessionId", access: ALL, owner: "E16" },

  // Journal & analytics
  { id: "R-180", path: "/journal", access: ALL, owner: "E17" },
  { id: "R-181", path: "/journal/:tradeId", access: ALL, owner: "E17" },
  { id: "R-182", path: "/journal/analytics", access: ALL, owner: "E17" },

  // Alerts
  { id: "R-190", path: "/alerts", access: ALL, owner: "E14" },
  { id: "R-191", path: "/alerts/:alertId", access: ALL, owner: "E14" },

  // Settings
  { id: "R-200", path: "/settings", access: ALL, owner: null },
  { id: "R-201", path: "/settings/profile", access: ALL, owner: "E11" },
  { id: "R-202", path: "/settings/hotkeys", access: ALL, owner: "E10" },
  { id: "R-203", path: "/settings/appearance", access: ALL, owner: "E11" },
  { id: "R-204", path: "/settings/notifications", access: ALL, owner: "E11" },
  { id: "R-205", path: "/settings/windows", access: ALL, owner: "E11" },

  // Admin (owner-hat)
  { id: "R-300", path: "/admin", access: ADMIN, owner: "E18" },
  { id: "R-301", path: "/admin/users", access: ADMIN, owner: "E18" },
  { id: "R-302", path: "/admin/users/:userId", access: ADMIN, owner: "E18" },
  { id: "R-303", path: "/admin/users/new", access: ADMIN, owner: null },
  { id: "R-310", path: "/admin/accounts", access: ADMIN, owner: "E18" },
  { id: "R-311", path: "/admin/accounts/:accountId", access: ADMIN, owner: "E18" },
  { id: "R-312", path: "/admin/accounts/new", access: ADMIN, owner: "E18" },
  { id: "R-320", path: "/admin/keys", access: ADMIN, owner: "E18" },
  { id: "R-321", path: "/admin/keys/:keyId", access: ADMIN, owner: "E18" },
  { id: "R-322", path: "/admin/keys/:keyId/rotate", access: ADMIN, owner: "E18" },
  { id: "R-330", path: "/admin/profiles", access: ADMIN, owner: "E18" },
  { id: "R-331", path: "/admin/profiles/:profileId", access: ADMIN, owner: "E18" },
  { id: "R-340", path: "/admin/recorder", access: ADMIN, owner: "E18" },
  { id: "R-350", path: "/admin/health", access: ADMIN, owner: "E18" },
  { id: "R-351", path: "/admin/flags", access: ADMIN, owner: "E18" },
  { id: "R-352", path: "/admin/trade-groups", access: ADMIN, owner: "E18" },
  { id: "R-353", path: "/admin/risk-policy", access: ADMIN, owner: "E18" },
  { id: "R-354", path: "/admin/security", access: ADMIN, owner: "E18" },
  { id: "R-355", path: "/admin/backups", access: ADMIN, owner: "E18" },
  { id: "R-356", path: "/admin/maintenance", access: ADMIN, owner: "E18" },
  {
    id: "R-360",
    path: "/admin/audit",
    access: { roles: ["owner", "manager"] },
    owner: "E09",
  },

  // Error / system routes
  { id: "R-900", path: "/403", access: ALL, owner: null },
  { id: "R-901", path: "/404", access: PUBLIC, owner: null },
  { id: "R-902", path: "/offline", access: PUBLIC, owner: "E10" },
  { id: "R-903", path: "/maintenance", access: PUBLIC, owner: "E18" },
];
