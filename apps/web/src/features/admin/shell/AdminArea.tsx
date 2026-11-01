import { useEffect, type CSSProperties, type JSX, type ReactNode } from "react";
import { AdminLayout } from "@candleviewer/ui";
import { AdminInviteScreen } from "../../invites/AdminInviteScreen";
import { RecorderScreen } from "../../recorder/RecorderScreen";
import { StubRoute } from "../../../routes/StubRoute";
import { ROUTE_TITLES } from "../../../routes/titles";
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
  if (routeId === "R-303") return <AdminInviteScreen />; // SCR-123 (E09-S05)
  if (routeId === "R-340") return <RecorderScreen />; // SCR-140 (E16-S01), in this chunk: behind the guard
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
 * challenge. No strip until a source feeds it (BQ-6), and no live region or announcement of its own:
 * the shell announces each route once (BQ-8). Later admin pages mount through `pageFor`.
 */
export function AdminArea({ routeId, owner }: AdminAreaProps): JSX.Element {
  useCompleteRouteFocus();
  return (
    <div style={INSET}>
      <AdminLayout routeLabel={adminRouteLabel(routeId)}>{pageFor(routeId, owner)}</AdminLayout>
    </div>
  );
}
