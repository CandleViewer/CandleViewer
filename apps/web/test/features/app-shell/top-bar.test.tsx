import { readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { buildRoutes } from "../../../src/routes/tree";
import { resetMeClaims, setMeClaims } from "../../../src/lib/auth/meCache";
import type { Role } from "../../../src/routes/rbac";
import { clearAnnouncements, ShellAnnouncer } from "../../../src/features/app-shell/announcer";
import { ariaKeys, TopBar } from "../../../src/features/app-shell/TopBar";
import {
  badgeLook,
  TopBarEnvBadge,
  type BadgeEnvironment,
} from "../../../src/features/app-shell/TopBarEnvBadge";
import { TopBarSlot } from "../../../src/features/app-shell/TopBarSlot";
import { resetShellState, setShellState, type Me } from "../../../src/shell/bootstrap/store.js";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const WORD = { live: "LIVE", demo: "DEMO", testnet: "TESTNET", unknown: "ENV UNKNOWN" } as const;
const NAME = { live: "Live", demo: "Demo", testnet: "Testnet", unknown: "unknown" } as const;
const ENVS = Object.keys(WORD) as BadgeEnvironment[];
const ROLES: readonly Role[] = ["owner", "manager", "viewer"];
const FAILED = "Couldn't reach the server. Try again.";
const NO_CONTRAST = { rules: { "color-contrast": { enabled: false } } };

const me = (role: Role): Me => ({
  accounts: [],
  permissions: [],
  role,
  user: { id: "u-1", email: "r@example.test", username: "robin", roles: [role], status: "active" },
});

async function shellAt(path: string, env: BadgeEnvironment, role: Role) {
  setMeClaims({ authenticated: true, role, permissions: [] });
  setShellState({ environment: env, me: me(role) });
  const router = createMemoryRouter(buildRoutes(), { initialEntries: [path] });
  const view = render(<RouterProvider router={router} />);
  await screen.findByRole("heading", { level: 1 });
  return { router, view, bar: screen.getByRole("banner") };
}
// every region of that politeness: the degraded banner (#4763) mounts its own pair before the shell's
const live = (p: "polite" | "assertive") => ({
  textContent: [...document.querySelectorAll(`[aria-live="${p}"]`)]
    .map((n) => n.textContent)
    .join(""),
});
beforeEach(() => {
  resetMeClaims();
  resetShellState();
  clearAnnouncements();
});

describe("E10-S01 S2: the env badge (CMP-075) in the top bar", () => {
  for (const env of ENVS)
    it(`shows ${WORD[env]} as a visible word for every role, never DEMO by default, axe-clean`, async () => {
      for (const role of ROLES) {
        const { view, bar } = await shellAt("/journal", env, role);
        const name = `Trading environment: ${NAME[env]}`;
        expect(within(bar).getByRole("img", { name })).toHaveTextContent(WORD[env]);
        if (env !== "demo") expect(within(bar).queryByText("DEMO")).toBeNull();
        const roleWord = role.replace(/^./, (c) => c.toUpperCase());
        expect(within(bar).getByText(`robin · ${roleWord}`)).toBeVisible();
        const res = await axe.run(document.body, NO_CONTRAST); // jsdom has no layout
        expect(res.violations.filter((v) => /serious|critical/.test(v.impact ?? ""))).toEqual([]);
        view.unmount();
      }
    });

  it("has no hide path: no prop, class, preference or shipped stylesheet rule removes it", () => {
    // @ts-expect-error the environment is the badge's only prop
    render(<TopBarEnvBadge env="live" hidden className="sr-only" style={{ display: "none" }} />);
    const lone = screen.getByRole("img", { name: "Trading environment: Live" });
    expect(lone.getAttributeNames().sort().join()).toBe("aria-label,data-cmp,data-env,role,style");
    expect(lone.style.display).toBe("inline-flex");
    const root = document.documentElement;
    for (const pref of [
      "theme=light",
      "theme=high-contrast",
      "density=comfortable",
      "motion=reduce",
    ]) {
      const [attr = "", value = ""] = pref.split("=");
      root.setAttribute(`data-${attr}`, value);
      expect(lone).toBeVisible();
      root.removeAttribute(`data-${attr}`);
    }
    const repo = resolve(import.meta.dirname, "../../../../..");
    for (const dir of ["packages/ui/src", "apps/web/src"])
      for (const f of readdirSync(join(repo, dir), { recursive: true, encoding: "utf8" }))
        if (f.endsWith(".css")) {
          // selectors only: a stylesheet comment naming the badge is not a hide path
          const css = readFileSync(join(repo, dir, f), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
          for (const sel of css.match(/[^{}]+(?=\{)/g) ?? [])
            expect(sel, f).not.toMatch(/CMP-07[45]|data-env|EnvBadge/);
        }
  });

  it("switches unknown between ENV UNKNOWN and no badge in one constant, never DEMO", () => {
    expect(badgeLook("unknown")?.[0]).toBe("ENV UNKNOWN"); // SHOW_UNKNOWN_ENV, pending the ruling
    expect(badgeLook("unknown", false)).toBeNull();
    expect(badgeLook("live", false)?.[0]).toBe("LIVE");
  });

  it("announces the badge politely on a route change, not on first load", async () => {
    const { router } = await shellAt("/journal", "live", "owner");
    expect(live("polite")?.textContent).toBe("");
    await act(() => router.navigate("/risk"));
    await screen.findByRole("heading", { name: /R-150/ });
    expect(live("polite")?.textContent).toBe("Trading environment: Live");
  });
});

describe("E10-S01 S2: the top bar's controls", () => {
  it("keeps the merged focus order and gives each placeholder its reason", async () => {
    const { bar } = await shellAt("/journal", "demo", "owner");
    const sel = "a[href], button:not([disabled]), input:not([disabled]), [tabindex]";
    const stops = [...document.querySelectorAll<HTMLElement>(sel)].filter((e) => e.tabIndex >= 0);
    const names = stops.slice(0, 7).map((e) => e.getAttribute("aria-label") ?? e.textContent);
    expect(names.join(" | ")).toMatch(
      /^Skip to main content \| Account \| Symbol \| Interval \| Search commands Ctrl\+K \| Connection: [^|]+ \| Sign out$/,
    );
    for (const name of ["Account", "Symbol", "Interval"]) {
      const picker = within(bar).getByRole("button", { name });
      expect(picker).toHaveAttribute("aria-disabled", "true");
      expect(picker).toHaveAccessibleDescription("Not available in this build.");
    }
    expect(within(bar).getByText("Pickers: not available in this build.")).toBeVisible();
    const search = within(bar).getByRole("button", { name: "Search commands Ctrl+K" });
    expect(search).not.toHaveAttribute("aria-keyshortcuts"); // only while it does something
    expect(search).toHaveAccessibleDescription(
      "The command palette is not available in this build.",
    );
    expect(within(search).getByText("Ctrl+K").tagName).toBe("KBD");
  });

  it("runs a registered palette from the search trigger", () => {
    const onSearch = vi.fn();
    render(
      <TopBar
        {...{ env: "demo", user: null, connection: null, searchHint: "Ctrl+K", onSearch }}
        {...{ onSignOut: vi.fn(), signingOut: false, signOutFailed: false }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Search commands Ctrl+K" }));
    expect(onSearch).toHaveBeenCalledTimes(1);
    const enabled = screen.getByRole("button", { name: "Search commands Ctrl+K" });
    expect(enabled).toHaveAttribute("aria-keyshortcuts", "Control+K");
    expect([ariaKeys("Cmd+K"), ariaKeys("Meta+Shift+P")]).toEqual(["Meta+K", "Meta+Shift+P"]);
  });
});

describe("E10-S01 S2: Sign out", () => {
  function renderSlot(signOut: () => Promise<boolean>, who: Me = me("owner")) {
    const api = { signOut: vi.fn(signOut), endSession: vi.fn() };
    setShellState({ environment: "demo", me: who });
    const element = <TopBarSlot connection={null} api={api} />;
    render(<ShellAnnouncer />);
    render(<RouterProvider router={createMemoryRouter([{ path: "/", element }])} />);
    return { api, button: screen.getByRole("button", { name: "Sign out" }) };
  }

  it("renders with no name when /me carries no user (regression: the shell crashed)", () => {
    renderSlot(() => Promise.resolve(true), { role: "viewer", permissions: [] } as unknown as Me);
    expect(screen.queryByText(/ · /)).toBeNull();
  });

  it("calls POST /auth/logout once, then ends the session", async () => {
    let answer: (gone: boolean) => void = () => undefined;
    const { api, button } = renderSlot(() => new Promise((r) => (answer = r)));
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-busy", "true");
    fireEvent.click(button);
    expect(api.signOut).toHaveBeenCalledTimes(1);
    await act(async () => answer(true));
    expect(api.endSession).toHaveBeenCalledTimes(1);
  });

  it("keeps the session and says so when the logout revoked nothing", async () => {
    const { api, button } = renderSlot(() => Promise.resolve(false));
    await act(async () => fireEvent.click(button));
    expect(api.endSession).not.toHaveBeenCalled();
    expect(live("assertive")?.textContent).toBe(FAILED);
    expect(screen.getByText(FAILED, { selector: "span" })).toBeVisible();
    expect(button).not.toHaveAttribute("aria-busy");
  });
});
