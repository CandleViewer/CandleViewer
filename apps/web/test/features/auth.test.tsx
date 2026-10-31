import { createRequire } from "node:module";
import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { LoginScreen } from "../../src/features/auth/LoginScreen";
import { ChangePasswordScreen } from "../../src/features/auth/ChangePasswordScreen";
import { formatRemaining, login } from "../../src/features/auth/authApi";

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

  it("every refusal but a 429 or a 5xx is the one failure, whatever its body and headers", async () => {
    // SR-014 (#4961): the client keys on the status alone, never on a code, title or detail
    const body = { code: "any_code", title: "Any title", detail: "Any detail" };
    for (let status = 400; status < 500; status += 1) {
      if (status === 429) continue;
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(reply(status, body, { "Retry-After": "60" })),
      );
      expect(await login("ann", "pw"), String(status)).toEqual({ kind: "invalid" });
    }
  });

  it("a 5xx is unreachable, whatever its body", async () => {
    for (let status = 500; status < 600; status += 1) {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(status, { code: "any_code" })));
      expect(await login("ann", "pw"), String(status)).toEqual({ kind: "unreachable" });
    }
  });

  it("a 429 without a usable Retry-After counts down from 15 minutes", async () => {
    for (const header of [undefined, "0", "-5", "soon"]) {
      const headers: Record<string, string> = header === undefined ? {} : { "Retry-After": header };
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(429, {}, headers)));
      expect(await login("ann", "pw"), String(header)).toEqual({
        kind: "rate_limited",
        retryAfterS: 15 * 60,
      });
    }
  });

  it("a 429 shows the remaining time and blocks submit", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(429, {}, { "Retry-After": "872" })));
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
    const toggle = screen.getByRole("button", { name: "Show password" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);
    // A11Y-F-0003: the name stays put; only aria-pressed flips (CMP-201)
    expect(screen.getByRole("button", { name: "Show password" })).toBe(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: /Hide password/ })).toBeNull();
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
    if (line !== null) {
      expect(screen.getByRole("alert")).toHaveTextContent(line); // in the summary, read on arrival
      expect(screen.getByRole("alert")).toHaveFocus();
    } else expect(screen.getByRole("alert")).toBeEmptyDOMElement();
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

  it("the reveal toggle keeps one name while aria-pressed flips (A11Y-F-0003)", async () => {
    render(<ChangePasswordScreen />);
    const toggle = screen.getByRole("button", { name: "Show passwords" });
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Show passwords" })).toBe(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect((screen.getByLabelText("New password") as HTMLInputElement).type).toBe("text");
    expect(await serious()).toEqual([]);
  });

  function fill(current: string, next: string, confirm: string): void {
    fireEvent.change(screen.getByLabelText("Current password"), { target: { value: current } });
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: next } });
    fireEvent.change(screen.getByLabelText("Confirm new password"), { target: { value: confirm } });
    fireEvent.click(screen.getByRole("button", { name: "Change password" }));
  }

  it("a too-short new password marks, describes and focuses that field (A11Y-F-0006)", async () => {
    render(<ChangePasswordScreen />);
    fill("old", "short", "short");
    const field = screen.getByLabelText("New password");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAccessibleDescription(/Use at least 12 characters\./);
    expect(field).toHaveFocus();
    expect(screen.getByLabelText("Confirm new password")).not.toHaveAttribute("aria-invalid");
    expect(await serious()).toEqual([]);
  });

  it("editing the field in error clears its mark and message (A11Y-F-0006)", () => {
    render(<ChangePasswordScreen />);
    fill("old", "short", "short");
    const field = screen.getByLabelText("New password");
    fireEvent.change(field, { target: { value: "shorter" } });
    expect(field).not.toHaveAttribute("aria-invalid");
    expect(field).not.toHaveAccessibleDescription(/Use at least 12 characters/);
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
  });

  it("a mismatch marks, describes and focuses the confirm field (A11Y-F-0006)", async () => {
    render(<ChangePasswordScreen />);
    fill("old", "correct horse battery", "correct horse batterz");
    const field = screen.getByLabelText("Confirm new password");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAccessibleDescription("Passwords don't match.");
    expect(field).toHaveFocus();
    expect(screen.getByLabelText("New password")).not.toHaveAttribute("aria-invalid");
    expect(await serious()).toEqual([]);
  });

  it.each([
    ["password_reused", /last 5 passwords/],
    ["password_breached", /known breach list/],
  ])("a %s refusal marks and focuses the new field (A11Y-F-0006)", async (code, text) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(422, { code })));
    render(<ChangePasswordScreen />);
    fill("old", "correct horse battery", "correct horse battery");
    const field = screen.getByLabelText("New password");
    await waitFor(() => expect(field).toHaveFocus());
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAccessibleDescription(text);
    expect(await serious()).toEqual([]);
  });

  it("an error no field owns focuses the summary and marks no field (A11Y-F-0006)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    render(<ChangePasswordScreen />);
    fill("old", "correct horse battery", "correct horse battery");
    await waitFor(() => expect(screen.getByRole("alert")).toHaveFocus());
    expect(screen.getByRole("alert")).toHaveTextContent(/Cannot reach/);
    for (const name of ["Current password", "New password", "Confirm new password"]) {
      expect(screen.getByLabelText(name)).not.toHaveAttribute("aria-invalid");
    }
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
