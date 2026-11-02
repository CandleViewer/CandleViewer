import { useEffect, type CSSProperties, type JSX, type ReactNode } from "react";
import { ADMIN_COPY, AdminLayout } from "@candleviewer/ui";
import { AdminInviteScreen } from "../../invites/AdminInviteScreen";
import { StubRoute } from "../../../routes/StubRoute";
import { ROUTE_TITLES } from "../../../routes/titles";
import { useShellSelector } from "../../../shell/useShellSelector";
import { OverviewPage } from "../overview/OverviewPage";
import { useAdminHold, useAdminSelector } from "../overview/readStore";
import { areaEntered, denial, STRIP_READS, stripItems } from "../overview/strip";
import { routerLink } from "../routerLink";
import { AdminDenied } from "./AdminDenied";
import { SecurityCentrePlaceholder } from "./SecurityCentrePlaceholder";

/** SCR-120's page header (E42-D03 §6): R-300's page title, "Admin", would read "Admin area · Admin". */
const OVERVIEW = "Overview";

/**
 * E42-D03 D1: the content's `space.inset.lg` padding. The shell's canvas scrolls, so a control
 * flush with its edge would lose one side of CMP-039's 2 px focus ring.
 */
const INSET: CSSProperties = { padding: "var(--space-inset-lg)" };

/**
 * The band's route words, `band.label` "◆ Admin area · {route}" (E42-D03 §14): the route's page title,
 * `12` §2's name for it (`routes/titles.ts`), so the band and the document title name one page.
 */
export function adminRouteLabel(routeId: string): string {
  return routeId === "R-300" ? OVERVIEW : (ROUTE_TITLES[routeId] ?? routeId);
}

/** Each admin route's page: the one that ships today, else the stub naming its owner. */
function pageFor(routeId: string, owner: string | null): ReactNode {
  if (routeId === "R-300") return <OverviewPage />; // SCR-120 (E42-S01)
  if (routeId === "R-303") return <AdminInviteScreen />; // SCR-123 (E09-S05)
  if (routeId === "R-354") return <SecurityCentrePlaceholder />; // until E43's SCR-137
  return <StubRoute routeId={routeId} owner={owner ?? "E42"} />;
}

/**
 * The shell moves focus to the page's `h1` after a route change (`useRouteFocus`, E10-S01). On the
 * first way in this module was still loading, so the shell found no `h1` and focused `main`: finish
 * that move now the page is here. Focus anywhere else (a first load, or the user moved it) stays.
 */
function useCompleteRouteFocus(): void {
  useEffect(() => {
    const main = document.activeElement;
    if (!(main instanceof HTMLElement) || main.tagName !== "MAIN") return;
    const heading = main.querySelector<HTMLElement>("h1");
    if (heading === null) return;
    if (!heading.hasAttribute("tabindex")) {
      heading.setAttribute("tabindex", "-1");
      heading.addEventListener("blur", () => heading.removeAttribute("tabindex"), { once: true });
    }
    heading.focus();
  }, []);
}

export interface AdminAreaProps {
  readonly routeId: string;
  readonly owner: string | null;
}

/**
 * The admin area (E42-S01; E42-D03 §4): each `/admin/*` route's page inside CMP-087, its band naming
 * the route. Per-action step-up (D8): no gate at the door, a protected action answers the server's own
 * challenge. The strip reads the overview's served sources on every admin route (BQ-6), through the
 * store SCR-120 shares, and its `/admin/*` reads are what records the entry, so the footer says so
 * once one was answered (D27). No live region or route announcement of its own: the shell announces
 * each route once (BQ-8). A `403` on any admin read withdraws the area (SCR-154 N-2), which
 * `AdminDenied` says once through the shell's announcer. Later admin pages mount through `pageFor`.
 */
export function AdminArea({ routeId, owner }: AdminAreaProps): JSX.Element {
  useCompleteRouteFocus();
  const env = useShellSelector((s) => s.environment);
  const denied = useAdminSelector(denial);
  useAdminHold(STRIP_READS, denied === null);
  const strip = useAdminSelector((s) => stripItems(s, env));
  const entered = useAdminSelector(areaEntered);
  if (denied !== null) {
    return (
      <div style={INSET}>
        <AdminDenied refId={denied.refId} />
      </div>
    );
  }
  return (
    <div style={INSET}>
      <AdminLayout
        routeLabel={adminRouteLabel(routeId)}
        strip={strip}
        footer={entered ? ADMIN_COPY.footerAreaEntered : undefined}
        linkAs={routerLink}
      >
        {pageFor(routeId, owner)}
      </AdminLayout>
    </div>
  );
}
