import { createRequire } from "node:module";
import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { AdminInviteScreen } from "../../src/features/invites/AdminInviteScreen";
import { InviteAcceptScreen } from "../../src/features/invites/InviteAcceptScreen";

// axe-core is a transitive dependency of @axe-core/playwright (already a devDependency).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

async function seriousViolations(): Promise<unknown[]> {
  const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } }); // jsdom has no canvas; contrast is covered by the Playwright axe run;
  return res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

function reply(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: async () => body } as unknown as Response;
}

afterEach(() => vi.unstubAllGlobals());

describe("InviteAcceptScreen (SCR-017)", () => {
  function mount(): void {
    render(
      <MemoryRouter initialEntries={["/invite/tok-0123456789abcdef"]}>
        <Routes>
          <Route path="/invite/:inviteToken" element={<InviteAcceptScreen />} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("accepts an invite: password, TOTP, recovery codes", async () => {
    const f = vi
      .fn()
      .mockResolvedValueOnce(reply(200, { display_name: "Ann", role: "viewer", expires_at: "x" }))
      .mockResolvedValueOnce(
        reply(200, { method_id: "m1", otpauth_uri: "otpauth://x", secret_base32: "AAAA" }),
      )
      .mockResolvedValueOnce(
        reply(200, { status: "active", role: "viewer", recovery_codes: ["rc-1"] }),
      );
    vi.stubGlobal("fetch", f);
    mount();
    await screen.findByText(/Welcome, Ann/);
    expect(screen.getByText(/Step 1 of 4/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Accept invitation" }));
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "correct horse battery" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByLabelText("Authenticator code");
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Activate account" }));
    expect(await screen.findByText("rc-1")).toBeInTheDocument();
    expect(await seriousViolations()).toEqual([]);
    expect(screen.getByText(/Step 4 of 4/)).toBeInTheDocument();
    expect(screen.getByText("What happens next")).toBeInTheDocument();
  });

  it("shows the uniform not-valid state for an expired link", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(404, { detail: "x" })));
    mount();
    expect(await screen.findByText("Invitation not valid")).toBeInTheDocument();
    expect(
      screen.getByText("This invitation is no longer valid. Ask the owner for a new one."),
    ).toBeInTheDocument();
  });
});

describe("AdminInviteScreen (SCR-123)", () => {
  it("shows the link once with a copy control and the secret warning", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const f = vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST")
        return reply(201, {
          id: "u1",
          username: "annie",
          invite_url: "/invite/abc",
          invite_expires_at: "2026-10-04T12:00:00+00:00",
        });
      void url;
      return reply(200, {
        items: [
          {
            user_id: "u2",
            username: "old",
            role: "viewer",
            expires_at: "2026-09-01T00:00:00+00:00",
            expired: true,
          },
        ],
      });
    });
    vi.stubGlobal("fetch", f);
    render(<AdminInviteScreen />);
    expect(await screen.findByText(/Expired - re-issue/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "annie" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));
    expect(await screen.findByText(/treat it as a secret/)).toBeInTheDocument();
    expect(await seriousViolations()).toEqual([]);
    expect((screen.getByLabelText("Invite link") as HTMLInputElement).value).toContain(
      "/invite/abc",
    );
    fireEvent.click(screen.getByRole("button", { name: "Copy link" }));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(expect.stringContaining("/invite/abc")),
    );
  });

  it("answers the step-up challenge and re-sends the held invite once (#2725)", async () => {
    const challenge = {
      type: "https://candleviewer.local/errors/step_up_required",
      title: "A dangerous action needs a live step-up elevation for its action class",
      status: 403,
      code: "step_up_required",
      action_class: "users",
      challenge_id: "0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d",
      challenge_expires_at: new Date(Date.now() + 300_000).toISOString(),
      action_summary: "Invite user 'annie' as viewer",
      target: null,
    };
    let creates = 0;
    const f = vi.fn(async (u: string, init?: RequestInit) => {
      if (u.endsWith("/auth/step-up")) {
        return reply(200, {
          elevated_until: "2026-09-14T10:40:00Z",
          action_class: "users",
          single_use: false,
          step_up_expires_at: "2026-09-14T10:40:00Z",
        });
      }
      if (init?.method === "POST") {
        creates += 1;
        return creates === 1
          ? reply(403, challenge)
          : reply(201, {
              id: "u1",
              username: "annie",
              invite_url: "/invite/abc",
              invite_expires_at: "2026-09-17T10:00:00Z",
            });
      }
      return reply(200, { items: [] });
    });
    vi.stubGlobal("fetch", f);
    render(
      <MemoryRouter>
        <AdminInviteScreen />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "annie" } });
    fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveAccessibleDescription("Invite user 'annie' as viewer");
    expect(await seriousViolations()).toEqual([]);
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByLabelText("Invite link")).toHaveValue(
      `${window.location.origin}/invite/abc`,
    );
    const posts = f.mock.calls.filter(([u, i]) => u.endsWith("/users") && i?.method === "POST");
    expect(posts).toHaveLength(2);
    expect(posts[1]?.[1]?.body).toBe(posts[0]?.[1]?.body);
    const key = (i: number): string | null =>
      new Headers(posts[i]?.[1]?.headers).get("Idempotency-Key");
    expect(key(0)).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(key(1)).toBe(key(0));
    const stepUp = f.mock.calls.find(([u]) => u.endsWith("/auth/step-up"));
    expect(JSON.parse(String(stepUp?.[1]?.body))).toMatchObject({
      challenge_id: challenge.challenge_id,
    });
  });

  it("shows Not sent and never re-sends the invite when the step-up is cancelled", async () => {
    const f = vi.fn(async (_u: string, init?: RequestInit) =>
      init?.method === "POST"
        ? reply(403, {
            code: "step_up_required",
            action_class: "users",
            challenge_id: "0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d",
            challenge_expires_at: new Date(Date.now() + 300_000).toISOString(),
          })
        : reply(200, { items: [] }),
    );
    vi.stubGlobal("fetch", f);
    render(
      <MemoryRouter>
        <AdminInviteScreen />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "annie" } });
    fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Not sent");
    expect(f.mock.calls.filter(([, i]) => i?.method === "POST")).toHaveLength(1);
  });

  it("opens at most one new step-up cycle when the re-send is challenged again", async () => {
    const challenge = (id: string) => ({
      code: "step_up_required",
      action_class: "users",
      challenge_id: id,
      challenge_expires_at: new Date(Date.now() + 300_000).toISOString(),
    });
    let creates = 0;
    const f = vi.fn(async (u: string, init?: RequestInit) => {
      if (u.endsWith("/auth/step-up")) {
        return reply(200, { elevated_until: "x", action_class: "users", single_use: false });
      }
      if (init?.method === "POST") {
        creates += 1;
        return reply(403, challenge(`0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c6${creates}`));
      }
      return reply(200, { items: [] });
    });
    vi.stubGlobal("fetch", f);
    render(
      <MemoryRouter>
        <AdminInviteScreen />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "annie" } });
    fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));
    for (let cycle = 1; cycle <= 2; cycle += 1) {
      await screen.findByRole("alertdialog");
      fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
      fireEvent.change(screen.getByLabelText("Authenticator code"), {
        target: { value: "123456" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
      await waitFor(() => expect(creates).toBe(cycle + 1));
    }
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The invitation could not be created.",
    );
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(creates).toBe(3);
  });

  it("renews an expiring challenge as a fresh create, never the held one (A11Y-F-0010)", async () => {
    let creates = 0;
    const f = vi.fn(async (u: string, init?: RequestInit) => {
      if (init?.method === "POST" && u.endsWith("/users")) {
        creates += 1;
        return reply(403, {
          code: "step_up_required",
          action_class: "users",
          challenge_id: `0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c6${creates}`,
          // inside the warning window: the warning shows at once, no fake clock needed
          challenge_expires_at: new Date(Date.now() + 20_000).toISOString(),
        });
      }
      return reply(200, { items: [] });
    });
    vi.stubGlobal("fetch", f);
    render(
      <MemoryRouter>
        <AdminInviteScreen />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "annie" } });
    fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));
    await screen.findByRole("alertdialog");
    expect(await screen.findByRole("alert")).toHaveTextContent(/This confirmation expires in/);
    expect(await seriousViolations()).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Request a new confirmation" }));
    await waitFor(() => expect(creates).toBe(2));
    await screen.findByRole("alertdialog");
    const posts = f.mock.calls.filter(([, i]) => i?.method === "POST");
    expect(posts).toHaveLength(2); // no step-up was sent, and nothing was re-sent
    const [first, second] = posts.map(([, i]) => i as RequestInit);
    expect(second?.body).toBe(first?.body);
    const key = (i?: RequestInit): string | null => new Headers(i?.headers).get("Idempotency-Key");
    expect(key(second)).not.toBeNull();
    expect(key(second)).not.toBe(key(first));
  });

  it("a renewal sends the form as it reads now, not the first submit's values (A11Y-F-0010)", async () => {
    const bodies: string[] = [];
    const f = vi.fn(async (u: string, init?: RequestInit) => {
      if (init?.method === "POST" && u.endsWith("/users")) {
        bodies.push(String(init.body));
        return reply(403, {
          code: "step_up_required",
          action_class: "users",
          challenge_id: `0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c6${bodies.length}`,
          challenge_expires_at: new Date(Date.now() + 20_000).toISOString(),
        });
      }
      return reply(200, { items: [] });
    });
    vi.stubGlobal("fetch", f);
    render(
      <MemoryRouter>
        <AdminInviteScreen />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "annie" } });
    fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));
    await screen.findByRole("alertdialog");
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "bobby" } });
    fireEvent.click(await screen.findByRole("button", { name: "Request a new confirmation" }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(JSON.parse(bodies[1] ?? "{}")).toMatchObject({ username: "bobby" });
  });

  it("sends no Idempotency-Key on a read", async () => {
    const f = vi.fn(async () => reply(200, { items: [] }));
    vi.stubGlobal("fetch", f);
    render(
      <MemoryRouter>
        <AdminInviteScreen />
      </MemoryRouter>,
    );
    await waitFor(() => expect(f).toHaveBeenCalled());
    const [, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(new Headers(init.headers).has("Idempotency-Key")).toBe(false);
  });

  it("re-issues through the step-up challenge too", async () => {
    let reissues = 0;
    const f = vi.fn(async (u: string, init?: RequestInit) => {
      if (u.endsWith("/auth/step-up")) {
        return reply(200, { elevated_until: "x", action_class: "users", single_use: false });
      }
      if (u.endsWith("/invite") && init?.method === "POST") {
        reissues += 1;
        return reissues === 1
          ? reply(403, {
              code: "step_up_required",
              action_class: "users",
              challenge_id: "0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d",
              challenge_expires_at: new Date(Date.now() + 300_000).toISOString(),
            })
          : reply(201, {
              id: "u1",
              username: "bob",
              invite_url: "/invite/def",
              invite_expires_at: "2026-09-17T10:00:00Z",
            });
      }
      return reply(200, {
        items: [{ user_id: "u1", username: "bob", role: "viewer", expires_at: "x", expired: true }],
      });
    });
    vi.stubGlobal("fetch", f);
    render(
      <MemoryRouter>
        <AdminInviteScreen />
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Re-issue" }));
    await screen.findByRole("alertdialog");
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByLabelText("Invite link")).toHaveValue(
      `${window.location.origin}/invite/def`,
    );
  });
});
