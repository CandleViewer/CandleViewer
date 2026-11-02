/**
 * E42-S01 (#1022): the admin area module (the lazy chunk): CMP-087 around each admin route's page, the
 * band's route words, the Security centre placeholder, and the route focus it completes on arrival.
 */
import { createRequire } from "node:module";
import { act, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { isAdminRoute } from "../../../../src/features/admin/AdminRouteElement";
import { AdminArea, adminRouteLabel } from "../../../../src/features/admin/shell/AdminArea";
import { SecurityCentrePlaceholder } from "../../../../src/features/admin/shell/SecurityCentrePlaceholder";
import { InShellProvider } from "../../../../src/features/app-shell/ScreenRoot";
import { ROUTE_MANIFEST } from "../../../../src/routes/manifest";
import { ROUTE_TITLES } from "../../../../src/routes/titles";

// axe-core is a transitive dependency of @axe-core/playwright (as in test/features/invites.test.tsx).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

async function seriousViolations(): Promise<unknown[]> {
  // jsdom has no layout: contrast is the Playwright axe run's
  const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  return res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

const ADMIN_IDS = ROUTE_MANIFEST.filter(
  (e) => e.path === "/admin" || e.path.startsWith("/admin/"),
).map((e) => e.id);

// The invite screen lists the pending invites on mount: answered here, never by the network.
beforeEach(() => {
  const body = JSON.stringify({ items: [] });
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(body, { headers: { "Content-Type": "application/json" } })),
  );
});
afterEach(() => vi.unstubAllGlobals());

/** The area as the shell holds it: inside its `main`, a router around it. */
function Shell({
  routeId,
  owner = "E18",
  show = true,
}: {
  routeId: string;
  owner?: string | null;
  show?: boolean;
}) {
  return (
    <MemoryRouter>
      <InShellProvider>
        <main tabIndex={-1}>{show ? <AdminArea routeId={routeId} owner={owner} /> : null}</main>
      </InShellProvider>
    </MemoryRouter>
  );
}

describe("the admin routes and the band's route words", () => {
  it("counts R-300 to R-360 as the admin area, and no other route", () => {
    expect(ADMIN_IDS).toHaveLength(21);
    expect(ROUTE_MANIFEST.filter((e) => isAdminRoute(e.id)).map((e) => e.id)).toEqual(ADMIN_IDS);
    expect(["R-100", "R-150", "R-201", "R-900", "R-901"].some(isAdminRoute)).toBe(false);
  });

  it("names each route by its page title, and /admin by SCR-120's Overview (E42-D03 §6)", () => {
    expect(adminRouteLabel("R-300")).toBe("Overview");
    expect(adminRouteLabel("R-301")).toBe("Users and roles");
    expect(adminRouteLabel("R-303")).toBe("Invite user");
    expect(adminRouteLabel("R-354")).toBe("Security centre");
    expect(adminRouteLabel("R-360")).toBe("Audit log");
    for (const id of ADMIN_IDS.filter((id) => id !== "R-300")) {
      expect(adminRouteLabel(id), id).toBe(ROUTE_TITLES[id]);
    }
  });
});

describe("AdminArea: CMP-087 around the route's page", () => {
  it("draws the band, then the page with its one h1, at comfortable density", () => {
    render(<Shell routeId="R-301" />);
    const main = screen.getByRole("main");
    const band = within(main).getByRole("region", { name: "Admin area" });
    expect(band.textContent).toBe("◆ Admin area · Users and roles");
    const root = band.parentElement as HTMLElement;
    expect(root).toHaveAttribute("data-cmp", "CMP-087");
    expect(root).toHaveAttribute("data-density", "comfortable");
    expect(root.firstElementChild).toBe(band);
    expect(within(main).getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1 })).toHaveAccessibleName("R-301 — owned by E18");
    // no strip without a source (BQ-6), no live region of its own, nothing focusable in the band
    expect(screen.queryByRole("region", { name: "Needs your action" })).toBeNull();
    expect(main.querySelector("[aria-live], [role='status'], [role='alert']")).toBeNull();
    expect(band.querySelector("a, button, input, [tabindex]")).toBeNull();
  });

  it("pads the area by D1's space.inset.lg: an edge control keeps its whole focus ring", () => {
    render(<Shell routeId="R-301" />);
    // E42-D03 D1: the content's `space.inset.lg` padding inside the shell's scrolling canvas, which
    // would clip one side of CMP-039's 2 px ring on a control flush with its edge. A token, no px.
    const area = screen.getByRole("main").firstElementChild as HTMLElement;
    expect(area.firstElementChild).toHaveAttribute("data-cmp", "CMP-087");
    expect(area.style.padding).toBe("var(--space-inset-lg)");
  });

  it("holds the invite screen on R-303 and the Security centre placeholder on R-354", () => {
    const invite = render(<Shell routeId="R-303" owner={null} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveAccessibleName("Invite user");
    expect(screen.getByRole("button", { name: "Create invitation" })).toBeInTheDocument();
    invite.unmount();
    render(<Shell routeId="R-354" />);
    const band = screen.getByRole("region", { name: "Admin area" });
    expect(band.textContent).toBe("◆ Admin area · Security centre");
    expect(screen.getByRole("heading", { level: 1 })).toHaveAccessibleName("Security centre");
  });

  it("holds SCR-140 on R-340, its band naming the route (E16-S01)", () => {
    render(<Shell routeId="R-340" />);
    const band = screen.getByRole("region", { name: "Admin area" });
    expect(band.textContent).toBe("◆ Admin area · Recorder and retention");
    expect(screen.getByRole("heading", { level: 1 })).toHaveAccessibleName("Recorder");
  });

  it("names a stub with no owner as E42's", () => {
    render(<Shell routeId="R-310" owner={null} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveAccessibleName("R-310 — owned by E42");
  });

  it("finishes the shell's route focus: from main to the page h1 once the page is in", () => {
    const view = render(<Shell routeId="R-301" show={false} />);
    act(() => screen.getByRole("main").focus());
    view.rerender(<Shell routeId="R-301" />);
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(document.activeElement).toBe(h1);
    expect(h1).toHaveAttribute("tabindex", "-1");
    act(() => h1.blur()); // the heading lends its tabindex for the move only, as the shell's does
    expect(h1).not.toHaveAttribute("tabindex");
  });

  it("leaves focus where it is when the shell's move did not end on main", () => {
    const view = render(
      <>
        <button type="button">Elsewhere</button>
        <Shell routeId="R-301" show={false} />
      </>,
    );
    const elsewhere = screen.getByRole("button", { name: "Elsewhere" });
    act(() => elsewhere.focus());
    view.rerender(
      <>
        <button type="button">Elsewhere</button>
        <Shell routeId="R-301" />
      </>,
    );
    expect(document.activeElement).toBe(elsewhere);
    expect(screen.getByRole("heading", { level: 1 })).not.toHaveAttribute("tabindex");
  });
});

describe("SecurityCentrePlaceholder: R-354 until E43's SCR-137 mounts here", () => {
  it("shows the title, the R4 line and a link to the audit log, with no axe violation", async () => {
    render(
      <MemoryRouter>
        <SecurityCentrePlaceholder />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveAccessibleName("Security centre");
    // The title is CMP-088's: one PageHeader, its h1 the page's only one.
    expect(document.querySelectorAll('[data-cmp="CMP-088"]')).toHaveLength(1);
    expect(screen.getByText("Security posture checks ship in R4 (E43)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Audit log" })).toHaveAttribute("href", "/admin/audit");
    expect(await seriousViolations()).toEqual([]);
  });
});
