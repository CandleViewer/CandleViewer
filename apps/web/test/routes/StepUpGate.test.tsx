import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { StepUpGate } from "../../src/routes/StepUpGate";
import { resetMeClaims, getMeClaims } from "../../src/lib/auth/meCache";

describe("StepUpGate", () => {
  beforeEach(() => {
    resetMeClaims();
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the TOTP re-entry form", () => {
    render(
      <MemoryRouter>
        <StepUpGate redirectTo="/admin" />
      </MemoryRouter>,
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Authenticator code")).toBeInTheDocument();
  });

  it("renders a masked password field with an accessible label", () => {
    render(
      <MemoryRouter>
        <StepUpGate redirectTo="/admin" />
      </MemoryRouter>,
    );
    const field = screen.getByLabelText("Password");
    expect(field).toHaveAttribute("type", "password");
    expect(field).toHaveAttribute("autocomplete", "current-password");
  });

  it("keeps Confirm disabled until both password and code are entered", () => {
    render(
      <MemoryRouter>
        <StepUpGate redirectTo="/admin" />
      </MemoryRouter>,
    );
    const confirm = screen.getByRole("button", { name: "Confirm" });
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    expect(confirm).toBeEnabled();
  });

  it("shows one generic error and clears the password on refusal", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: false });
    render(
      <MemoryRouter>
        <StepUpGate redirectTo="/admin" />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid password or code.");
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });

  it("shows an error and does not record step-up on a failed code", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: false });
    render(
      <MemoryRouter>
        <StepUpGate redirectTo="/admin" />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "000000" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(getMeClaims().elevatedAt).toBeNull();
  });

  it("records elevatedAt on a successful code", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({ elevated_until: "2026-09-29T12:00:00Z" }),
    });
    render(
      <MemoryRouter>
        <StepUpGate redirectTo="/admin" />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(getMeClaims().elevatedAt).toBe("2026-09-29T12:00:00Z"));
  });

  it("posts password and code only (server derives the challenged action class)", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue({ ok: false });
    render(
      <MemoryRouter>
        <StepUpGate redirectTo="/admin" />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({ code: "123456", password: "pw" });
  });

  it("renders the remaining grace window from step_up_expires_at and counts down", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      vi.setSystemTime(new Date("2026-09-29T12:00:00Z"));
      (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: true,
        json: async () => ({
          elevated_until: "2026-09-29T12:05:00Z",
          step_up_expires_at: "2026-09-29T12:05:00Z",
        }),
      });
      render(
        <MemoryRouter>
          <StepUpGate redirectTo="/admin" />
        </MemoryRouter>,
      );
      fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
      fireEvent.change(screen.getByLabelText("Authenticator code"), {
        target: { value: "123456" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
      const region = await screen.findByText("Grace window: 5:00 remaining");
      expect(region).toHaveAttribute("aria-live", "polite");
      act(() => {
        vi.advanceTimersByTime(61_000);
      });
      expect(screen.getByText("Grace window: 3:59 remaining")).toBeInTheDocument();
      act(() => {
        vi.advanceTimersByTime(240_000);
      });
      expect(screen.getByTestId("step-up-grace")).toHaveTextContent("");
    } finally {
      vi.useRealTimers();
    }
  });
});
