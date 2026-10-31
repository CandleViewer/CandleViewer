/**
 * E42-S01 (#1022), the amended Gherkin's failure scenario (BQ-1, variant (b)): a protected change
 * challenged while the owner edits, inside the admin area. The forms that hold real drafts are
 * E42-S02/S03's, so it runs on R-303, the one admin form today, through the existing per-action
 * step-up gate (#2725), now inside CMP-087.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetMeClaims, setMeClaims } from "../../../../src/lib/auth/meCache";
import { buildRoutes } from "../../../../src/routes/tree";
import { resetShellState, setShellState, type Me } from "../../../../src/shell/bootstrap/store";

const CHALLENGE_ID = "0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d";
const SUMMARY = "Invite user 'annie' as viewer";

/** A route's render with the admin area's lazy chunk: a busy host can take seconds over it. */
const ROUTE_WAIT = { timeout: 5_000 } as const;

const respond = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** The server: the first invite is refused with a step-up challenge, the re-send is created. */
function stubServer(): { readonly creates: RequestInit[]; readonly stepUps: string[] } {
  const wire = { creates: [] as RequestInit[], stepUps: [] as string[] };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = String(input);
      if (url.endsWith("/auth/step-up")) {
        wire.stepUps.push(String(init.body));
        return respond(200, { elevated_until: "2026-09-14T10:40:00Z", action_class: "users" });
      }
      if (init.method === "POST" && url.endsWith("/users")) {
        wire.creates.push(init);
        return wire.creates.length === 1
          ? respond(403, {
              type: "https://candleviewer.local/errors/step_up_required",
              title: "A dangerous action needs a live step-up elevation for its action class",
              status: 403,
              code: "step_up_required",
              action_class: "users",
              challenge_id: CHALLENGE_ID,
              challenge_expires_at: new Date(Date.now() + 300_000).toISOString(),
              action_summary: SUMMARY,
              target: null,
            })
          : respond(201, {
              id: "u1",
              username: "annie",
              invite_url: "/invite/abc",
              invite_expires_at: "2026-09-17T10:00:00Z",
            });
      }
      return respond(200, { items: [] });
    }),
  );
  return wire;
}

/** The owner on R-303 with the form filled in and submitted once: the band and the form. */
async function submitInsideTheAdminArea(): Promise<HTMLElement> {
  setMeClaims({ authenticated: true, role: "owner", permissions: [] });
  const me = { role: "owner", permissions: [], accounts: [], user: { username: "owner.one" } };
  setShellState({ me: me as unknown as Me, environment: "demo" });
  const router = createMemoryRouter(buildRoutes(), { initialEntries: ["/admin/users/new"] });
  render(<RouterProvider router={router} />);
  const band = await screen.findByRole("region", { name: "Admin area" }, ROUTE_WAIT);
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: "annie" } });
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "annie@example.com" } });
  fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));
  return band;
}

/** The form as the owner left it. */
function expectFormUnchanged(): void {
  expect(screen.getByLabelText("Username")).toHaveValue("annie");
  expect(screen.getByLabelText("Email")).toHaveValue("annie@example.com");
}

const idempotencyKey = (init: RequestInit | undefined): string | null =>
  new Headers(init?.headers).get("Idempotency-Key");

beforeEach(() => {
  resetMeClaims();
  resetShellState();
});

afterEach(() => {
  resetShellState();
  vi.unstubAllGlobals();
});

describe("E42-S01 (failure): a protected change is challenged while the owner edits", () => {
  it(
    "opens the step-up over the page, keeps the band and the form, and re-sends the held request once",
    { timeout: 30_000 },
    async () => {
      const wire = stubServer();
      const band = await submitInsideTheAdminArea();
      const dialog = await screen.findByRole(
        "alertdialog",
        { name: "Confirm with two-factor" },
        ROUTE_WAIT,
      );
      expect(dialog).toHaveAccessibleDescription(SUMMARY);
      expect(band.isConnected).toBe(true);
      expectFormUnchanged();
      fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw-admin-shell" } });
      fireEvent.change(screen.getByLabelText("Authenticator code"), {
        target: { value: "123456" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
      expect(await screen.findByLabelText("Invite link", {}, ROUTE_WAIT)).toHaveValue(
        `${window.location.origin}/invite/abc`,
      );
      expect(wire.stepUps.map((b) => JSON.parse(b) as unknown)).toEqual([
        { password: "pw-admin-shell", code: "123456", challenge_id: CHALLENGE_ID },
      ]);
      const [first, resent, ...more] = wire.creates;
      expect(more).toEqual([]);
      expect(resent?.method).toBe(first?.method);
      expect(resent?.body).toBe(first?.body);
      expect(idempotencyKey(resent)).toBe(idempotencyKey(first));
      expect(idempotencyKey(first)).toMatch(/^[0-9a-f-]{36}$/);
      // the same page all along: the band never remounted
      expect(screen.getByRole("region", { name: "Admin area" })).toBe(band);
    },
  );

  it(
    "Cancel keeps the page and the content, says Not sent, and sends nothing more",
    { timeout: 30_000 },
    async () => {
      const wire = stubServer();
      const band = await submitInsideTheAdminArea();
      await screen.findByRole("alertdialog", { name: "Confirm with two-factor" }, ROUTE_WAIT);
      fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
      // scoped to the page: the shell's status bar is a "System status" region too
      await waitFor(
        () =>
          expect(within(screen.getByRole("main")).getByRole("status")).toHaveTextContent(
            "Not sent",
          ),
        ROUTE_WAIT,
      );
      expect(screen.queryByRole("alertdialog")).toBeNull();
      expect(screen.getByRole("region", { name: "Admin area" })).toBe(band);
      expectFormUnchanged();
      expect(wire.creates).toHaveLength(1);
      expect(wire.stepUps).toEqual([]);
    },
  );
});
