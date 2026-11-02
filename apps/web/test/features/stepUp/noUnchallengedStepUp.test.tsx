/**
 * #2725 guard: the client never posts step-up credentials without a server-issued `challenge_id`
 * in hand. A `fetch` spy records every `challenge_id` the (stubbed) server issues in a
 * `403 step_up_required` and every `POST /auth/step-up`; each step-up must name a challenge issued
 * before it. Driven through every admin route (no client pre-emption) and the invite flow, plus a
 * source check that the challenge gate is the only sender.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router";
import { PreferencesProvider } from "../../../src/features/a11y-preferences/PreferencesContext";
import { resetMeClaims, setMeClaims } from "../../../src/lib/auth/meCache";
import { ROUTE_MANIFEST } from "../../../src/routes/manifest";
import { buildRoutes } from "../../../src/routes/tree";

const SRC = resolve(import.meta.dirname, "../../../src");

/**
 * R-303 renders behind the admin area's lazy chunk (E42-S01): a busy host can take seconds. A test
 * that waits so long takes a budget above the default 5 s, which would end it first.
 */
const ROUTE_WAIT = { timeout: 5_000 } as const;

interface Wire {
  readonly issued: string[];
  readonly stepUps: { readonly challengeId: unknown; readonly issuedBefore: readonly string[] }[];
}

const respond = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

let wire: Wire;

function stubServer(): void {
  wire = { issued: [], stepUps: [] };
  let n = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = String(input);
      const method = (init.method ?? "GET").toUpperCase();
      if (url.endsWith("/auth/step-up")) {
        const body = JSON.parse(String(init.body)) as { challenge_id?: unknown };
        wire.stepUps.push({ challengeId: body.challenge_id, issuedBefore: [...wire.issued] });
        return respond(200, {
          elevated_until: "2026-09-14T10:40:00Z",
          action_class: "users",
          single_use: false,
        });
      }
      if (method !== "GET" && n === 0) {
        n += 1;
        const id = crypto.randomUUID();
        wire.issued.push(id);
        return respond(403, {
          type: "https://candleviewer.local/errors/step_up_required",
          title: "step-up",
          status: 403,
          code: "step_up_required",
          action_class: "users",
          challenge_id: id,
          challenge_expires_at: new Date(Date.now() + 300_000).toISOString(),
          action_summary: "Invite user 'annie' as viewer",
          target: null,
        });
      }
      if (method !== "GET") {
        return respond(201, {
          id: "u1",
          username: "annie",
          invite_url: "/invite/abc",
          invite_expires_at: "2026-09-17T10:00:00Z",
        });
      }
      return respond(200, { items: [] });
    }),
  );
}

/** The router inside the provider the app wraps it in (`App.tsx`), so every route renders as in the app. */
function mountRouter(router: ReturnType<typeof createMemoryRouter>): ReturnType<typeof render> {
  return render(
    <PreferencesProvider>
      <RouterProvider router={router} />
    </PreferencesProvider>,
  );
}

/** The route rendered its own element: nothing reached the route error boundary. */
function expectNoRouteError(router: ReturnType<typeof createMemoryRouter>, id: string): void {
  expect(router.state.errors, id).toBeNull();
  expect(screen.queryByRole("heading", { name: "Something went wrong" }), id).toBeNull();
}

/** Every step-up named a challenge the server had issued before it was sent. */
function expectEveryStepUpChallenged(): void {
  for (const { challengeId, issuedBefore } of wire.stepUps) {
    expect(typeof challengeId).toBe("string");
    expect(issuedBefore).toContain(challengeId);
  }
}

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

beforeEach(() => {
  resetMeClaims();
  setMeClaims({ authenticated: true, role: "owner", permissions: [] });
  stubServer();
});

afterEach(() => vi.unstubAllGlobals());

describe("test_client_never_posts_step_up_without_a_server_challenge", () => {
  // The walk mounts every admin route in turn, each with the admin area's reads (and SCR-120's at
  // /admin, E42-S01): its time grows with the area, so it has its own budget, as the tree's walk does.
  it(
    "admin routes: no route-level step-up dialog and no step-up post",
    { timeout: 30_000 },
    async () => {
      const admin = ROUTE_MANIFEST.filter(
        (e) => e.path === "/admin" || e.path.startsWith("/admin/"),
      );
      expect(admin.length).toBeGreaterThan(10);
      for (const entry of admin) {
        const router = createMemoryRouter(buildRoutes(), {
          initialEntries: [entry.path.replace(/:[a-zA-Z]+/g, "x")],
        });
        const view = mountRouter(router);
        await act(async () => undefined);
        expectNoRouteError(router, entry.id);
        expect(screen.queryByRole("alertdialog"), entry.id).not.toBeInTheDocument();
        expect(screen.queryByRole("dialog"), entry.id).not.toBeInTheDocument();
        expect(screen.queryByLabelText("Authenticator code"), entry.id).not.toBeInTheDocument();
        view.unmount();
        router.dispose();
      }
      expect(wire.stepUps).toEqual([]);
    },
  );

  it(
    "invite flow: the one step-up names the challenge the server issued",
    { timeout: 30_000 },
    async () => {
      const router = createMemoryRouter(buildRoutes(), { initialEntries: ["/admin/users/new"] });
      mountRouter(router);
      fireEvent.change(await screen.findByLabelText("Username", {}, ROUTE_WAIT), {
        target: { value: "annie" },
      });
      expect(wire.stepUps).toEqual([]);
      fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));
      await screen.findByRole("alertdialog");
      expect(wire.issued).toHaveLength(1);
      expect(wire.stepUps).toEqual([]);
      fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
      fireEvent.change(screen.getByLabelText("Authenticator code"), {
        target: { value: "123456" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
      expect(await screen.findByLabelText("Invite link")).toBeInTheDocument();
      expect(wire.stepUps).toHaveLength(1);
      expect(wire.stepUps[0]?.challengeId).toBe(wire.issued[0]);
      expectEveryStepUpChallenged();
      expectNoRouteError(router, "R-303");
    },
  );

  it("invite flow, cancelled: no step-up is posted at all", { timeout: 30_000 }, async () => {
    const router = createMemoryRouter(buildRoutes(), { initialEntries: ["/admin/users/new"] });
    mountRouter(router);
    fireEvent.change(await screen.findByLabelText("Username", {}, ROUTE_WAIT), {
      target: { value: "annie" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    // scoped to the screen: the shell's status bar is a "System status" region too
    await waitFor(() =>
      expect(within(screen.getByRole("main")).getByRole("status")).toHaveTextContent("Not sent"),
    );
    expect(wire.stepUps).toEqual([]);
    expectNoRouteError(router, "R-303");
  });

  it("source: only the challenge gate sends POST /auth/step-up", () => {
    const sources = files(SRC).filter((f) => /\.(ts|tsx)$/.test(f));
    const naming = sources
      .filter((f) => readFileSync(f, "utf8").includes("/auth/step-up"))
      .map((f) => relative(SRC, f))
      .sort();
    // The path constant, and the token holder's list of calls that mint a session (it adopts the
    // returned token bundle; it never builds a step-up body).
    expect(naming).toEqual(["features/stepUp/challenge.ts", "lib/auth/accessToken.ts"]);
    const senders = sources
      .filter((f) => /\bSTEP_UP_PATH\b/.test(readFileSync(f, "utf8")))
      .map((f) => relative(SRC, f))
      .sort();
    expect(senders).toEqual([
      "features/stepUp/StepUpChallengeGate.tsx",
      "features/stepUp/challenge.ts",
    ]);
    const gate = readFileSync(join(SRC, "features/stepUp/StepUpChallengeGate.tsx"), "utf8");
    expect(gate).toMatch(/challenge_id: challenge\.challengeId/);
  });
});
