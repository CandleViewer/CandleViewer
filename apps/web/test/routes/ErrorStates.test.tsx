import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildRoutes } from "../../src/routes/tree";
import { resetMeClaims, setMeClaims } from "../../src/lib/auth/meCache";
import type { Role } from "../../src/routes/rbac";

function renderAt(path: string, role: Role) {
  setMeClaims({ authenticated: true, role, permissions: [] });
  const router = createMemoryRouter(buildRoutes(), { initialEntries: [path] });
  const view = render(<RouterProvider router={router} />);
  return { router, ...view };
}

/** The 404 page's own content: h1, sentence and the "Try:" links, without the shell around it. */
async function notFoundPage(): Promise<{ sentence: string; tryLinks: string[] }> {
  const h1 = await screen.findByRole("heading", { name: "Page not found", level: 1 });
  const page = h1.parentElement as HTMLElement;
  const list = within(page).getByRole("list", { name: "Try:" });
  return {
    sentence: page.querySelector("p")?.textContent ?? "",
    tryLinks: within(list)
      .getAllByRole("link")
      .map((a) => `${a.textContent ?? ""} ${a.getAttribute("href") ?? ""}`),
  };
}

beforeEach(() => resetMeClaims());
afterEach(() => vi.restoreAllMocks());

const guardLines = (spy: { mock: { calls: unknown[][] } }): unknown[][] =>
  spy.mock.calls.filter(([line]) => String(line).startsWith("[route-guard]"));

/** A viewer navigates from the journal to `path`: the whole document, the focus and the console. */
async function viewerLandsOn(path: string) {
  const info = vi.spyOn(console, "info");
  const { router } = renderAt("/journal", "viewer");
  await screen.findByRole("heading", { name: /R-180/ });
  await act(() => router.navigate(path));
  const h1 = await screen.findByRole("heading", { name: "Page not found", level: 1 });
  const landmarks = [...document.querySelectorAll("header, nav, main, aside, footer, [role]")].map(
    (el) => `${el.tagName} ${el.getAttribute("role") ?? ""} ${el.getAttribute("aria-label") ?? ""}`,
  );
  const result = {
    // The echoed route is the one difference the page may show; React's client `useId` counter is
    // process-global, so it differs between mounts in one test run, never between the two routes.
    html: document.body.innerHTML.replaceAll(path, "{path}").replace(/:r[0-9a-z]+:/g, ":id:"),
    landmarks,
    focusOnH1: document.activeElement === h1,
    guardLines: guardLines(info),
  };
  cleanup();
  router.dispose();
  info.mockRestore();
  return result;
}

/** An unauthenticated session opens `path` directly: where it lands, and the console. */
async function signedOutOpens(path: string) {
  const info = vi.spyOn(console, "info");
  resetMeClaims();
  const router = createMemoryRouter(buildRoutes(), { initialEntries: [path] });
  const { unmount } = render(<RouterProvider router={router} />);
  await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
  const result = {
    search: router.state.location.search.replace(encodeURIComponent(path), "{path}"),
    guardLines: guardLines(info),
  };
  unmount();
  router.dispose();
  info.mockRestore();
  return result;
}

describe("ErrorStates: CMP-089 and CMP-090 mounted on the routes", () => {
  it("an admin route for a viewer renders the same 404 as an unknown route, path echoed as text", async () => {
    const admin = renderAt("/admin/users", "viewer");
    const a = await notFoundPage();
    expect(screen.getByText("/admin/users").closest("a")).toBeNull();
    admin.unmount();
    renderAt("/nowhere", "viewer");
    const b = await notFoundPage();
    expect(a.sentence).toBe("There's nothing at /admin/users.");
    expect(b.sentence).toBe("There's nothing at /nowhere.");
    // The session's permitted top-level routes: a viewer gets no Rules and no Admin.
    expect(a.tryLinks).toEqual(b.tryLinks);
    expect(b.tryLinks).toEqual([
      "Terminal /terminal",
      "Journal /journal",
      "Replay /replay",
      "Alerts /alerts",
      "Settings /settings",
    ]);
  });

  it("a role-denied route renders the never-had 403 with no Ref and a link home", async () => {
    renderAt("/risk", "viewer");
    const h1 = await screen.findByRole("heading", {
      name: "You don't have access to this",
      level: 1,
    });
    expect(h1).toHaveAttribute("tabindex", "-1");
    screen.getByText("Your role can't see this. Ask the owner if you need it.");
    expect(screen.queryByText(/^Ref /)).toBeNull();
    expect(screen.getByRole("link", { name: "Back to your workspace" })).toHaveAttribute(
      "href",
      "/terminal",
    );
  });

  it("the shell's route focus lands on the 403 h1 after navigation", async () => {
    const { router } = renderAt("/journal", "viewer");
    await screen.findByRole("heading", { name: /R-180/ });
    await act(() => router.navigate("/risk"));
    const h1 = await screen.findByRole("heading", {
      name: "You don't have access to this",
      level: 1,
    });
    expect(document.activeElement).toBe(h1);
    // The h1 owns its tabindex, so leaving it keeps the attribute.
    act(() => h1.blur());
    expect(h1).toHaveAttribute("tabindex", "-1");
  });

  it("an unknown route and a hidden admin route render the same whole document (E09-D09 §6)", async () => {
    const unknown = await viewerLandsOn("/nowhere");
    const admin = await viewerLandsOn("/admin/users");
    const adminUnknown = await viewerLandsOn("/admin/zzz");
    expect(unknown.landmarks).toContain("MAIN  ");
    expect(unknown.landmarks.some((l) => l.startsWith("NAV ") && l.endsWith("Primary"))).toBe(true);
    expect(admin.html).toBe(unknown.html);
    expect(adminUnknown.html).toBe(unknown.html);
    expect(admin.landmarks).toEqual(unknown.landmarks);
    expect([unknown.focusOnH1, admin.focusOnH1, adminUnknown.focusOnH1]).toEqual([
      true,
      true,
      true,
    ]);
    expect([unknown.guardLines, admin.guardLines, adminUnknown.guardLines]).toEqual([[], [], []]);
  });

  it("before sign-in, an unknown route and a hidden admin route both go to the login", async () => {
    const unknown = await signedOutOpens("/nowhere");
    const admin = await signedOutOpens("/admin/users");
    expect(unknown).toEqual({ search: "?next={path}", guardLines: [] });
    expect(admin).toEqual(unknown);
  });
});
