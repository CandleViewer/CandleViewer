/**
 * #1640 S3: SCR-112 sessions section (PROPOSED, no hi-fi). RTL by role and label, axe per state
 * (loading, list, empty, error, confirm), the keyboard path and the current-session marking.
 */
import { createRequire } from "node:module";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { SessionsSection } from "../../../src/features/session/SessionsSection";
import type { SessionsApi, UserSession } from "../../../src/features/session/sessionsApi";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

/** `_view_json` of services/api/candleviewer/api/sessions.py: every field, `current` on one. */
const row = (n: number, current: boolean, device: string | null): UserSession => ({
  id: `00000000-0000-4000-8000-00000000000${n}`,
  device_name: device,
  ip: n === 1 ? "100.64.0.7" : null,
  user_agent: "Mozilla/5.0 (X11; Linux x86_64) Firefox/131.0",
  created_at: "2026-10-27T08:00:00+00:00",
  last_seen_at: `2026-10-27T09:0${n}:00+00:00`,
  expires_at: "2026-10-27T20:00:00+00:00",
  current,
});
const SESSIONS = [row(1, true, "Desktop app"), row(2, false, null)];

function fakeApi(over: Partial<SessionsApi> = {}): SessionsApi {
  return {
    list: vi.fn(() => Promise.resolve({ kind: "ok" as const, items: SESSIONS })),
    revoke: vi.fn(() => Promise.resolve({ kind: "done" as const })),
    signOutEverywhere: vi.fn(() => Promise.resolve({ kind: "done" as const })),
    endSession: vi.fn(),
    ...over,
  };
}

async function noSeriousAxe(): Promise<void> {
  const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
    [],
  );
}

afterEach(cleanup);

describe("SCR-112 sessions: states", () => {
  it("loading, then the list with the current session marked in text", async () => {
    render(<SessionsSection api={fakeApi()} />);
    expect(screen.getByRole("status").textContent).toBe("Loading sessions…"); // announced
    await noSeriousAxe();
    const table = await screen.findByRole("table", { name: "Signed-in sessions" });
    const current = within(table).getByRole("rowheader", { name: /Desktop app/u });
    expect(current.textContent).toContain("This session");
    const other = within(table).getByRole("row", { name: /Firefox/u }); // no device name: the agent
    expect(other.textContent).toContain("Not recorded");
    expect(other.textContent).toContain("2026-10-27 09:02 UTC");
    expect(within(other).queryByText("This session")).toBeNull();
    expect(screen.getByRole("button", { name: "Revoke Desktop app (this session)" })).toBeTruthy();
    await noSeriousAxe();
  });

  it("empty: no rows, sign out everywhere off", async () => {
    render(
      <SessionsSection api={fakeApi({ list: () => Promise.resolve({ kind: "ok", items: [] }) })} />,
    );
    expect(await screen.findByText("No active sessions.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sign out everywhere" })).toHaveProperty(
      "disabled",
      true,
    );
    await noSeriousAxe();
  });

  it.each([
    ["forbidden", "This was refused. Reload the page, then try again."],
    ["unavailable", "Couldn't reach the server. Try again."],
  ] as const)("error %s: fixed copy and a retry", async (kind, copy) => {
    const list = vi.fn(() => Promise.resolve({ kind }));
    render(<SessionsSection api={fakeApi({ list })} />);
    expect((await screen.findByRole("alert")).textContent).toBe(copy);
    await noSeriousAxe();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(list).toHaveBeenCalledTimes(2);
  });
});

describe("SCR-112 sessions: revoke", () => {
  it("keyboard path: confirm opens on Cancel, Esc returns focus to the row's Revoke", async () => {
    const api = fakeApi();
    render(<SessionsSection api={api} />);
    const revoke = await screen.findByRole("button", { name: /^Revoke Mozilla/u });
    revoke.focus();
    fireEvent.click(revoke);
    const dialog = screen.getByRole("alertdialog", { name: "Revoke session?" });
    expect(document.activeElement).toBe(within(dialog).getByRole("button", { name: "Cancel" }));
    await noSeriousAxe();
    within(dialog).getByRole("button", { name: "Revoke" }).focus();
    fireEvent.keyDown(dialog, { key: "Tab" }); // trapped: the last control wraps to Cancel
    expect(document.activeElement).toBe(within(dialog).getByRole("button", { name: "Cancel" }));
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(document.activeElement).toBe(revoke);
    expect(api.revoke).not.toHaveBeenCalled();
  });

  it("another session: DELETE its id, refresh, focus the heading, announce", async () => {
    const api = fakeApi();
    render(<SessionsSection api={api} />);
    fireEvent.click(await screen.findByRole("button", { name: /^Revoke Mozilla/u }));
    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));
    expect(api.revoke).toHaveBeenCalledWith(SESSIONS[1]?.id);
    expect(api.endSession).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Sessions" }));
    expect(screen.getByRole("status").textContent).toBe("Session revoked.");
  });

  it("the current session: the 14 confirm line, then endSession (a logout)", async () => {
    const api = fakeApi();
    render(<SessionsSection api={api} />);
    fireEvent.click(await screen.findByRole("button", { name: /this session/u }));
    expect(screen.getByText("This will sign you out on this device.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Revoke and sign out" }));
    await waitFor(() => expect(api.endSession).toHaveBeenCalledTimes(1));
    expect(api.revoke).toHaveBeenCalledWith(SESSIONS[0]?.id);
  });

  it.each([
    ["forbidden", "This was refused. Reload the page, then try again."],
    ["not_found", "That session has already ended."],
    ["unavailable", "Couldn't reach the server. Try again."],
  ] as const)("%s: fixed copy in the dialog, still signed in", async (kind, copy) => {
    const api = fakeApi({ revoke: () => Promise.resolve({ kind }) });
    render(<SessionsSection api={api} />);
    fireEvent.click(await screen.findByRole("button", { name: /^Revoke Mozilla/u }));
    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    const dialog = screen.getByRole("alertdialog");
    expect((await within(dialog).findByRole("alert")).textContent).toBe(copy);
    expect(api.endSession).not.toHaveBeenCalled();
  });
});

describe("SCR-112 sessions: races", () => {
  it("an older list answer never overwrites a newer one; a newer read and unmount abort", async () => {
    type Out = { kind: "ok"; items: UserSession[] };
    const answers: ((out: Out) => void)[] = [];
    const signals: (AbortSignal | undefined)[] = [];
    const list = vi.fn((signal?: AbortSignal) => {
      signals.push(signal);
      return new Promise<Out>((resolve) => answers.push(resolve));
    });
    const api = fakeApi({ list, revoke: () => Promise.resolve({ kind: "not_found" }) });
    const view = render(<SessionsSection api={api} />);
    answers[0]?.({ kind: "ok", items: SESSIONS });
    fireEvent.click(await screen.findByRole("button", { name: /^Revoke Mozilla/u }));
    const dialog = screen.getByRole("alertdialog");
    const confirm = within(dialog).getByRole("button", { name: "Revoke" });
    fireEvent.click(confirm); // 404: read 2
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(confirm).toHaveProperty("disabled", false));
    fireEvent.click(confirm); // 404 again: read 3 replaces read 2
    await waitFor(() => expect(list).toHaveBeenCalledTimes(3));
    expect(signals[1]?.aborted).toBe(true);
    answers[2]?.({ kind: "ok", items: [SESSIONS[0] as UserSession] });
    await waitFor(() => expect(screen.getAllByRole("row")).toHaveLength(2)); // header + 1
    answers[1]?.({ kind: "ok", items: SESSIONS }); // the older answer, last
    await Promise.resolve();
    expect(screen.getAllByRole("row")).toHaveLength(2);
    view.unmount();
    expect(signals[2]?.aborted).toBe(true);
  });

  it("unmounted mid-request: a done sign-out still ends the session", async () => {
    let answer: (v: { kind: "done" }) => void = () => undefined;
    const api = fakeApi({ signOutEverywhere: () => new Promise((r) => (answer = r)) });
    const view = render(<SessionsSection api={api} />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Sign out everywhere" }));
    const dialog = screen.getByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Sign out everywhere" }));
    view.unmount();
    answer({ kind: "done" });
    await waitFor(() => expect(api.endSession).toHaveBeenCalledTimes(1));
  });

  it("cancel after the opener's row went in a re-read: focus goes to the heading", async () => {
    const list = vi
      .fn<SessionsApi["list"]>()
      .mockResolvedValueOnce({ kind: "ok", items: SESSIONS })
      .mockResolvedValue({ kind: "ok", items: [SESSIONS[0] as UserSession] });
    const api = fakeApi({ list, revoke: () => Promise.resolve({ kind: "not_found" }) });
    render(<SessionsSection api={api} />);
    const revoke = await screen.findByRole("button", { name: /^Revoke Mozilla/u });
    revoke.focus();
    fireEvent.click(revoke);
    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    const dialog = screen.getByRole("alertdialog");
    await within(dialog).findByText("That session has already ended.");
    await waitFor(() => expect(revoke.isConnected).toBe(false));
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Sessions" }));
  });
});

describe("SCR-112 sessions: sign out everywhere", () => {
  it("confirm, then endSession", async () => {
    const api = fakeApi();
    render(<SessionsSection api={api} />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Sign out everywhere" }));
    const dialog = screen.getByRole("alertdialog", { name: "Sign out everywhere?" });
    await noSeriousAxe();
    fireEvent.click(within(dialog).getByRole("button", { name: "Sign out everywhere" }));
    await waitFor(() => expect(api.endSession).toHaveBeenCalledTimes(1));
    expect(api.signOutEverywhere).toHaveBeenCalledTimes(1);
    expect(api.revoke).not.toHaveBeenCalled();
  });

  it("refused (a locked or cookie-only caller): fixed copy, nothing ended", async () => {
    const api = fakeApi({ signOutEverywhere: () => Promise.resolve({ kind: "refused" }) });
    render(<SessionsSection api={api} />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Sign out everywhere" }));
    const dialog = screen.getByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Sign out everywhere" }));
    expect((await within(dialog).findByRole("alert")).textContent).toBe(
      "Signing out everywhere needs a fresh sign-in. Sign in again, then try.",
    );
    expect(api.endSession).not.toHaveBeenCalled();
  });
});
