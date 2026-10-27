import { createRequire } from "node:module";
import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { LoginScreen } from "../../src/features/auth/LoginScreen";
import { ChangePasswordScreen } from "../../src/features/auth/ChangePasswordScreen";
import { formatRemaining } from "../../src/features/auth/authApi";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

async function serious(): Promise<unknown[]> {
  const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  return res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

function reply(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return {
    ok: status < 400,
    status,
    json: async () => body,
    headers: { get: (k: string) => headers[k] ?? null },
  } as unknown as Response;
}

afterEach(() => vi.unstubAllGlobals());

function submit(): void {
  fireEvent.change(screen.getByLabelText("Username or email"), { target: { value: "ann" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("LoginScreen (SCR-001)", () => {
  it("idle state is axe clean with a single h1", async () => {
    render(<LoginScreen />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(await serious()).toEqual([]);
  });

  it("requires a username", () => {
    render(<LoginScreen />);
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(screen.getByRole("alert").textContent).toBe("Enter your username.");
  });

  it("submitting locks the form, then invalid shows uniform message and focuses alert", async () => {
    let resolve: (r: Response) => void = () => undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>((r) => (resolve = r))),
    );
    render(<LoginScreen />);
    submit();
    expect((screen.getByLabelText("Password") as HTMLInputElement).disabled).toBe(true);
    resolve(reply(401, {}));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toBe("Username or password is incorrect"),
    );
    expect(document.activeElement).toBe(screen.getByRole("alert"));
    expect(await serious()).toEqual([]);
  });

  it("disabled account message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(403, {})));
    render(<LoginScreen />);
    submit();
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toBe("Account disabled - contact the owner"),
    );
  });

  it("locked shows remaining time and blocks submit", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(423, {}, { "Retry-After": "872" })));
    render(<LoginScreen />);
    submit();
    await waitFor(() => expect(screen.getByText(/Try again in 14:32/)).toBeTruthy());
    expect((screen.getByRole("button", { name: "Sign in" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it("server unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    render(<LoginScreen />);
    submit();
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/Cannot reach/));
  });

  it("mfa_required advances; password reveal toggles", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(reply(200, { status: "mfa_required", mfa_token: "t", methods: [] })),
    );
    render(<LoginScreen />);
    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect((screen.getByLabelText("Password") as HTMLInputElement).type).toBe("text");
    submit();
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Two-factor code" })).toBeTruthy(),
    );
  });

  it.each([
    ["?next=%2Fterminal&reason=unlock_attempts", "Signed out after too many unlock attempts."],
    ["?reason=%3Cb%3Eany+text%3C%2Fb%3E", null],
    ["?reason=toString", null],
    ["", null],
  ])("the five-strike reason line shows only for its own key (%s)", async (search, line) => {
    window.history.replaceState(null, "", `/login${search}`);
    render(<LoginScreen />);
    const status = screen.queryByText(/Signed out|any text/u);
    expect(status?.textContent ?? null).toBe(line);
    if (line !== null) expect(screen.getByRole("status")).toHaveTextContent(line);
    expect(await serious()).toEqual([]);
    window.history.replaceState(null, "", "/");
  });

  it("formats remaining time", () => {
    expect(formatRemaining(872)).toBe("14:32");
  });
});

describe("ChangePasswordScreen (SCR-004)", () => {
  it("is axe clean, lists rules, and validates", async () => {
    render(<ChangePasswordScreen />);
    expect(screen.getByText(/Not met: at least 12 characters/)).toBeTruthy();
    expect(await serious()).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(screen.getByRole("alert").textContent).toBe("Use at least 12 characters.");
  });

  it("surfaces the reuse error then succeeds", async () => {
    const f = vi
      .fn()
      .mockResolvedValueOnce(reply(422, { code: "password_reused" }))
      .mockResolvedValueOnce(reply(204, null));
    vi.stubGlobal("fetch", f);
    render(<ChangePasswordScreen />);
    const pw = "correct horse battery";
    fireEvent.change(screen.getByLabelText("Current password"), { target: { value: "old" } });
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: pw } });
    fireEvent.change(screen.getByLabelText("Confirm new password"), { target: { value: pw } });
    fireEvent.click(screen.getByRole("button", { name: "Change password" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/last 5/));
    fireEvent.click(screen.getByRole("button", { name: "Change password" }));
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Password changed" })).toBeTruthy(),
    );
  });
});
