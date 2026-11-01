/**
 * #5254: regression tests for the E09 design-QA Blocking rows on the built auth surfaces (E09-D11
 * DF-1, DF-2, DF-3, DF-4, DF-5, DF-14, DF-35, DF-38; E09-D10 F-26). Frozen strings are read from the
 * deck itself (E09-D12 §8.2), so a drift on either side fails here; focus is asserted through the
 * accessibility tree (role and name).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { useState, type JSX } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { LoginScreen } from "../../src/features/auth/LoginScreen";
import { InviteAcceptScreen } from "../../src/features/invites/InviteAcceptScreen";
import { SetupChecklistCard } from "../../src/features/onboarding/SetupChecklistCard";
import { SessionLockDialog } from "../../src/features/session/SessionLockDialog";
import { StepUpDialog } from "../../src/features/stepUp/StepUpDialog";

interface DeckEntry {
  readonly string: string;
}

/** A deck key's string, from `docs/design/E09/E09-D12-copy.json`, wherever the deck groups it. */
function deck(key: string): string {
  const raw = readFileSync(
    resolve(import.meta.dirname, "../../../../docs/design/E09/E09-D12-copy.json"),
    "utf8",
  );
  const find = (node: unknown): DeckEntry | undefined => {
    if (node === null || typeof node !== "object") return undefined;
    const record = node as Record<string, unknown>;
    const hit = record[key];
    if (hit !== undefined) return hit as DeckEntry;
    for (const value of Object.values(record)) {
      const found = find(value);
      if (found !== undefined) return found;
    }
    return undefined;
  };
  const entry = find(JSON.parse(raw) as unknown);
  expect(entry, `the deck has ${key}`).toBeDefined();
  return entry?.string ?? "";
}

function reply(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return {
    ok: status < 400,
    status,
    json: async () => body,
    headers: { get: (k: string) => headers[k] ?? null },
  } as unknown as Response;
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function signIn(): void {
  fireEvent.change(screen.getByRole("textbox", { name: "Username or email" }), {
    target: { value: "ann" },
  });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("SCR-001 (#5254)", () => {
  it("DF-1: a refused sign-in renders the frozen auth.login.failed byte for byte", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(401, {})));
    render(<LoginScreen />);
    signIn();
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(deck("auth.login.failed")),
    );
    expect(screen.getByRole("alert").textContent).toBe(deck("auth.login.failed"));
  });

  it("DF-4: R-001's arrival focuses the identifier field (T-1)", () => {
    render(<LoginScreen />);
    expect(screen.getByRole("textbox", { name: "Username or email" })).toHaveFocus();
  });

  it("DF-5: a 429 moves focus to the rate-limit line, once per episode (T-4)", async () => {
    // only the countdown's interval is faked, so the finders' own timeouts still run
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(429, {}, { "Retry-After": "90" })));
    render(<LoginScreen />);
    signIn();
    const line = await screen.findByRole("status");
    expect(line).toHaveTextContent("Too many attempts. Try again in");
    expect(line).toHaveFocus();
    // once per episode: a countdown tick re-renders the line but never retakes focus
    const field = screen.getByRole("textbox", { name: "Username or email" });
    field.focus();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(line).toHaveTextContent("1:29");
    expect(field).toHaveFocus();
  });
});

describe("SCR-017 (#5254)", () => {
  function mount(): void {
    render(
      <MemoryRouter initialEntries={["/invite/tok-0123456789abcdef"]}>
        <Routes>
          <Route path="/invite/:inviteToken" element={<InviteAcceptScreen />} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("DF-2: every invalid invite renders the frozen invite.invalid, naming no cause", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(404, { detail: "expired" })));
    mount();
    expect(await screen.findByText(deck("invite.invalid"))).toBeInTheDocument();
    expect(screen.queryByText(/expired|already been used/i)).not.toBeInTheDocument();
  });

  it("DF-35 and DF-3: each phase change lands on the step's first control; the frozen acknowledgement gates the way on", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(reply(200, { display_name: "Ann", role: "viewer", expires_at: "x" }))
        .mockResolvedValueOnce(
          reply(200, { method_id: "m1", otpauth_uri: "otpauth://x", secret_base32: "AAAA" }),
        )
        .mockResolvedValueOnce(
          reply(200, { status: "active", role: "viewer", recovery_codes: ["rc-1"] }),
        ),
    );
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Accept invitation" }));
    expect(screen.getByLabelText("New password")).toHaveFocus(); // T-30
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "correct horse battery" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    const code = await screen.findByRole("textbox", { name: "Authenticator code" });
    expect(code).toHaveFocus();
    fireEvent.change(code, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Activate account" }));
    const ack = await screen.findByRole("checkbox", { name: deck("enrol.codes.ack") });
    expect(ack).toHaveFocus(); // T-24: the new step's first control
    expect(ack).not.toBeChecked();
    const onward = screen.getByRole("button", { name: "Go to sign in" });
    expect(onward).toHaveAttribute("aria-disabled", "true");
    expect(onward).toHaveAccessibleDescription(deck("enrol.codes.ack")); // the spoken cue
    expect(screen.queryByRole("link", { name: "Go to sign in" })).not.toBeInTheDocument();
    onward.focus();
    fireEvent.click(onward); // not acknowledged: nothing moves on, focus returns to the gate
    expect(ack).toHaveFocus();
    fireEvent.click(ack);
    expect(ack).toBeChecked();
    expect(onward).toHaveAttribute("aria-disabled", "false");
    expect(onward).not.toHaveAttribute("aria-describedby");
  });
});

describe("SCR-005 and SCR-006 busy states (#5254 DF-14, R-5)", () => {
  it("the pressed Unlock stays focusable and inert while verifying (T-44)", () => {
    const onUnlock = vi.fn();
    let verify: () => void = () => undefined;
    function Harness(): JSX.Element {
      const [phase, setPhase] = useState<"locked" | "verifying">("locked");
      verify = () => setPhase("verifying");
      return <SessionLockDialog idleMinutes={15} phase={phase} onUnlock={onUnlock} />;
    }
    render(<Harness />);
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    const unlock = screen.getByRole("button", { name: "Unlock" });
    unlock.focus();
    fireEvent.click(unlock);
    expect(onUnlock).toHaveBeenCalledTimes(1);
    act(() => verify());
    const busy = screen.getByRole("button", { name: "Verifying..." });
    expect(busy).not.toBeDisabled();
    expect(busy).toHaveAttribute("aria-disabled", "true");
    expect(busy).toHaveFocus();
    fireEvent.click(busy);
    expect(onUnlock).toHaveBeenCalledTimes(1);
  });

  it("the pressed Confirm stays focusable; the fields go readonly while submitting (T-56)", () => {
    const onSubmit = vi.fn();
    let send: () => void = () => undefined;
    function Harness(): JSX.Element {
      const [submitting, setSubmitting] = useState(false);
      send = () => setSubmitting(true);
      return (
        <StepUpDialog
          actionSummary="Release kill switch, scope global"
          target={null}
          submitting={submitting}
          onSubmit={onSubmit}
          onCancel={() => undefined}
        />
      );
    }
    render(<Harness />);
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    const confirm = screen.getByRole("button", { name: "Confirm" });
    confirm.focus();
    fireEvent.click(confirm);
    expect(onSubmit).toHaveBeenCalledTimes(1);
    act(() => send());
    expect(confirm).not.toBeDisabled();
    expect(confirm).toHaveAttribute("aria-disabled", "true");
    expect(confirm).toHaveFocus();
    expect(screen.getByLabelText("Password")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("Authenticator code")).toHaveAttribute("readonly");
    fireEvent.click(confirm);
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("F-26: SCR-006's code control is one input, never a group of cells (E09-D10 §5.2)", () => {
    render(
      <StepUpDialog
        actionSummary={null}
        target={null}
        onSubmit={() => undefined}
        onCancel={() => undefined}
      />,
    );
    const dialog = screen.getByRole("alertdialog");
    expect(dialog.querySelectorAll('[autocomplete="one-time-code"]')).toHaveLength(1);
    expect(screen.getAllByRole("textbox", { name: /code/i })).toHaveLength(1);
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Authenticator code" })).toHaveAttribute(
      "inputmode",
      "numeric",
    );
  });
});

describe("SCR-019 (#5254 DF-38)", () => {
  it("never renders a task's free-text reason raw; the state word stands", async () => {
    const items = [
      "tailscale",
      "totp",
      "sub_account",
      "api_key",
      "profile_limits",
      "demo_session",
    ].map((key) => ({
      key,
      state: key === "api_key" ? "blocked" : "ok",
      reason: key === "api_key" ? "server free text 7f3a" : null,
      unblock_at: null,
      action_route: "/x",
    }));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(reply(200, { complete: false, dismissed: false, items })),
    );
    render(<SetupChecklistCard />);
    expect(await screen.findByText("Blocked")).toBeInTheDocument();
    expect(screen.queryByText(/server free text/)).not.toBeInTheDocument();
  });
});
