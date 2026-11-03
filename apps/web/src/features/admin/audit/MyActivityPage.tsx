/**
 * R-360 for a Manager: "My activity" (E42-S04; the orchestrator's BQ-8 (a); E42-D04 AL-25, AL-26,
 * AD-7), SCR-135's own view in the plain shell. The server scopes every read to the caller and
 * projects each entry (`22` queryAuditLog, Access): this page only says so, from the session's role
 * (`audit.own_only`), and drops nothing client-side. Actor, IP, Search and Environment, Signed
 * export… and Run tamper check stay, T2 `rbac.owner_only`; Actor, `q` and `ip` are never sent
 * (BQ-3), and the incidents are never read (a Manager holds no `admin:read`, BQ-4).
 *
 * Its own lazy chunk (`AdminRouteElement`): it imports nothing of the admin area or the overview,
 * so a Manager loads no admin code. The shell moves focus to the page's `h1` after a route change;
 * on the first way in this chunk was still loading, so that move is finished here, as the admin
 * area finishes its own.
 */
import { useEffect, type JSX } from "react";
import { AuditLogPage } from "./AuditLogPage";

/** The shell found no `h1` while this chunk loaded: focus left on `main` moves to it now. */
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

export function MyActivityPage(): JSX.Element {
  useCompleteRouteFocus();
  return <AuditLogPage view="own" />;
}
