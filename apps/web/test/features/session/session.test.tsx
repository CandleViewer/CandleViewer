/**
 * #1640 S1: CMP-098 and SCR-005 (E09-D06), RTL + axe + keyboard. apps/web has no Storybook, so
 * every drawn state is rendered and axe-checked here: CMP-098 warning, SCR-005 locked, verifying
 * and wrong-password.
 */
import { createRequire } from "node:module";
import type { JSX } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import type { SessionApi, SessionClock } from "../../../src/features/session/sessionApi";
import { SessionLockDialog } from "../../../src/features/session/SessionLockDialog";
import { SessionLockHost } from "../../../src/features/session/SessionLockHost";
import { SessionTimeoutWarning } from "../../../src/features/session/SessionTimeoutWarning";
import { KeymapHost, registerCommand } from "../../../src/keymap/KeymapHost";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const NOW = Date.parse("2026-10-27T10:00:00.000Z");

/** A `GET /auth/session` read `remainingS` before its idle deadline (server clock). */
function clock(remainingS: number, locked = false): SessionClock {
  return {
    server_time: new Date(NOW).toISOString(),
    session: {
      id: "5b1f0c3e-7d2a-4c11-9e8f-0a1b2c3d4e5f",
      issued_at: "2026-10-27T09:00:00Z",
      expires_at: "2026-10-27T21:00:00Z",
      idle_deadline: new Date(NOW + remainingS * 1000).toISOString(),
      idle_timeout_s: 900,
      locked,
    },
  };
}

function fakeApi(over: Partial<SessionApi> = {}): SessionApi {
  return {
    read: vi.fn(() => Promise.resolve(clock(900))),
    extend: vi.fn(() => Promise.resolve(clock(900))),
    unlock: vi.fn(() => Promise.resolve({ kind: "unlocked" as const, clock: clock(900) })),
    endSession: vi.fn(),
    ...over,
  };
}

const tick = (ms: number): Promise<void> =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

describe("session dialogs: axe per state", () => {
  const STATES: readonly [string, JSX.Element][] = [
    [
      "CMP-098 warning",
      <SessionTimeoutWarning key="w" expiresInSec={60} onExtend={vi.fn()} onDismiss={vi.fn()} />,
    ],
    [
      "SCR-005 locked",
      <SessionLockDialog key="l" idleMinutes={15} phase="locked" onUnlock={vi.fn()} />,
    ],
    [
      "SCR-005 verifying",
      <SessionLockDialog key="v" idleMinutes={15} phase="verifying" onUnlock={vi.fn()} />,
    ],
    [
      "SCR-005 wrong-password",
      <SessionLockDialog
        key="x"
        idleMinutes={15}
        phase="error"
        failure={{ message: "Incorrect password. Try again.", seq: 1 }}
        onUnlock={vi.fn()}
      />,
    ],
  ];
  it.each(STATES)("%s has no serious or critical axe violations", async (_name, ui) => {
    render(ui);
    const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
    expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
      [],
    );
  });
});

describe("SessionLockHost", () => {
  beforeEach(() => {
    vi.useFakeTimers({
      toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"],
    });
    vi.setSystemTime(NOW);
  });
  afterEach(() => vi.useRealTimers());

  it("reads nothing and renders nothing while signed out", async () => {
    const api = fakeApi();
    const { container } = render(<SessionLockHost api={api} enabled={false} />);
    await tick(0);
    expect(api.read).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });

  it("reads only when due, warns 60 s before the deadline, focus on Stay signed in", async () => {
    const read = vi.fn().mockResolvedValueOnce(clock(120)).mockResolvedValue(clock(60));
    render(<SessionLockHost api={fakeApi({ read })} enabled />);
    fireEvent.keyDown(document.body, { key: "a" });
    await tick(59_000);
    expect(read).toHaveBeenCalledTimes(1); // read when due, never polled
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    await tick(1_000);
    expect(read).toHaveBeenCalledTimes(2);
    const dialog = screen.getByRole("alertdialog", { name: "Your session will lock soon" });
    expect(dialog).toHaveTextContent("Lock in 1:00");
    expect(screen.getByRole("button", { name: "Stay signed in" })).toHaveFocus();
    await tick(1_000);
    expect(dialog).toHaveTextContent("Lock in 0:59");
  });

  it("extends only from Stay signed in: input and time never extend (#2300 scenario 5)", async () => {
    const api = fakeApi({ read: vi.fn().mockResolvedValue(clock(60)) });
    render(<SessionLockHost api={api} enabled />);
    await tick(0);
    fireEvent.keyDown(document.body, { key: "a" });
    fireEvent.pointerDown(document.body);
    await tick(5_000);
    expect(api.extend).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Stay signed in" }));
    await tick(0);
    expect(api.extend).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("Esc dismisses the warning without extending", async () => {
    const api = fakeApi({ read: vi.fn().mockResolvedValue(clock(60)) });
    render(<SessionLockHost api={api} enabled />);
    await tick(0);
    fireEvent.keyDown(screen.getByRole("alertdialog"), { key: "Escape" });
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(api.extend).not.toHaveBeenCalled();
  });

  it("locks at the deadline once the server reports the session locked", async () => {
    const read = vi.fn().mockResolvedValueOnce(clock(30)).mockResolvedValue(clock(0, true));
    render(<SessionLockHost api={fakeApi({ read })} enabled />);
    await tick(0);
    expect(
      screen.getByRole("alertdialog", { name: "Your session will lock soon" }),
    ).toBeInTheDocument();
    await tick(30_000);
    expect(screen.getByRole("alertdialog", { name: "Session locked" })).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveFocus();
  });

  it("keeps the lock on Esc, traps Tab, and announces the lock once", async () => {
    render(
      <SessionLockHost
        api={fakeApi({ read: vi.fn().mockResolvedValue(clock(0, true)) })}
        enabled
      />,
    );
    await tick(0);
    const dialog = screen.getByRole("alertdialog", { name: "Session locked" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleDescription(
      "Screen locked after 15 minutes idle. Market data continues. Order entry is disabled. Enter your password to resume.",
    );
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(dialog).toBeInTheDocument();
    const unlock = screen.getByRole("button", { name: "Unlock" });
    unlock.focus();
    fireEvent.keyDown(unlock, { key: "Tab" });
    expect(screen.getByLabelText("Password")).toHaveFocus();
    fireEvent.keyDown(screen.getByLabelText("Password"), { key: "Tab", shiftKey: true });
    expect(unlock).toHaveFocus();
  });

  it("locked -> verifying -> wrong-password -> unlocked", async () => {
    let answer: (v: Awaited<ReturnType<SessionApi["unlock"]>>) => void = () => undefined;
    const unlock = vi.fn(
      () => new Promise<Awaited<ReturnType<SessionApi["unlock"]>>>((r) => (answer = r)),
    );
    render(
      <SessionLockHost
        api={fakeApi({ read: vi.fn().mockResolvedValue(clock(0, true)), unlock })}
        enabled
      />,
    );
    await tick(0);
    const password = screen.getByLabelText("Password");
    fireEvent.change(password, { target: { value: "wrong" } });
    fireEvent.submit(password);
    expect(unlock).toHaveBeenCalledWith("wrong");
    expect(screen.getByRole("alertdialog")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("button", { name: "Verifying..." })).toBeDisabled();
    await act(async () => answer({ kind: "invalid" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Incorrect password. Try again.");
    expect(password).toHaveValue("");
    expect(password).toHaveFocus();
    fireEvent.change(password, { target: { value: "right" } });
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
    await act(async () => answer({ kind: "unlocked", clock: clock(900) }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("the fifth wrong password revokes the session and routes to sign-in (SCR-001)", async () => {
    const outcomes = ["invalid", "invalid", "invalid", "invalid", "revoked"] as const;
    const unlock = vi.fn();
    for (const kind of outcomes) unlock.mockResolvedValueOnce({ kind });
    const api = fakeApi({ read: vi.fn().mockResolvedValue(clock(0, true)), unlock });
    render(<SessionLockHost api={api} enabled />);
    await tick(0);
    for (let i = 0; i < 5; i += 1) {
      fireEvent.change(screen.getByLabelText("Password"), { target: { value: `bad${i}` } });
      fireEvent.submit(screen.getByLabelText("Password"));
      await tick(0);
    }
    expect(unlock).toHaveBeenCalledTimes(5);
    expect(api.endSession).toHaveBeenCalledTimes(1);
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument(); // the password goes first
  });

  const locked = (): SessionApi["read"] => vi.fn().mockResolvedValue(clock(0, true));
  const submit = (value: string): void => {
    fireEvent.change(screen.getByLabelText("Password"), { target: { value } });
    fireEvent.submit(screen.getByLabelText("Password"));
  };

  it("keeps focus and hotkeys behind the lock: scrim click, outside focus, Ctrl+K", async () => {
    const palette = vi.fn();
    const off = registerCommand("global.palette", palette);
    render(
      <>
        <button type="button">outside</button>
        <KeymapHost />
        <SessionLockHost api={fakeApi({ read: locked() })} enabled />
      </>,
    );
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(palette).toHaveBeenCalledTimes(1); // control: unlocked, the hotkey runs
    await tick(0);
    const password = screen.getByLabelText("Password");
    const scrim = screen.getByRole("alertdialog").parentElement as HTMLElement;
    expect(fireEvent.mouseDown(scrim)).toBe(false);
    expect(fireEvent.mouseDown(password)).toBe(true); // a press inside still focuses its target
    screen.getByRole("button", { name: "outside" }).focus();
    expect(password).toHaveFocus();
    fireEvent.keyDown(password, { key: "Tab", shiftKey: true });
    expect(screen.getByRole("button", { name: "Unlock" })).toHaveFocus();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(palette).toHaveBeenCalledTimes(1);
    submit("pw");
    await tick(0);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(palette).toHaveBeenCalledTimes(2); // hotkeys resume once the lock is gone
    off();
  });

  it("returns focus to the element focused before the lock once unlocked", async () => {
    render(
      <>
        <button type="button">before</button>
        <SessionLockHost api={fakeApi({ read: locked() })} enabled />
      </>,
    );
    screen.getByRole("button", { name: "before" }).focus();
    await tick(0);
    submit("pw");
    await tick(0);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "before" })).toHaveFocus();
  });

  it.each(["Stay signed in", "Escape"])("returns focus after the warning's %s", async (how) => {
    render(
      <>
        <button type="button">before</button>
        <SessionLockHost api={fakeApi({ read: vi.fn().mockResolvedValue(clock(60)) })} enabled />
      </>,
    );
    screen.getByRole("button", { name: "before" }).focus();
    await tick(0);
    if (how === "Escape") fireEvent.keyDown(screen.getByRole("alertdialog"), { key: how });
    else fireEvent.click(screen.getByRole("button", { name: how }));
    await tick(0);
    expect(screen.getByRole("button", { name: "before" })).toHaveFocus();
  });

  it("a 409 whose re-read finds the session locked returns to locked, not verifying", async () => {
    const unlock = vi.fn().mockResolvedValue({ kind: "not_locked" });
    render(<SessionLockHost api={fakeApi({ read: locked(), unlock })} enabled />);
    await tick(0);
    submit("pw");
    await tick(0);
    expect(screen.getByRole("alertdialog")).toHaveAttribute("aria-busy", "false");
    expect(screen.getByRole("button", { name: "Unlock" })).toBeEnabled();
  });

  it.each([
    ["throttled", "Too many attempts. Wait a minute, then try again.", locked()],
    ["unreachable", "Couldn't reach the server. Try again.", locked()],
    [
      "not_locked",
      "Couldn't reach the server. Try again.",
      vi.fn().mockResolvedValueOnce(clock(0, true)).mockResolvedValue(null),
    ],
  ])("%s keeps the password and does not mark it invalid", async (kind, message, read) => {
    render(
      <SessionLockHost
        api={fakeApi({ read, unlock: vi.fn().mockResolvedValue({ kind }) })}
        enabled
      />,
    );
    await tick(0);
    submit("typed");
    await tick(0);
    expect(screen.getByRole("alert")).toHaveTextContent(message);
    expect(screen.getByLabelText("Password")).toHaveValue("typed");
    expect(screen.getByLabelText("Password")).not.toHaveAttribute("aria-invalid");
  });

  it("a double submit sends one unlock", async () => {
    const unlock = vi.fn(() => new Promise<never>(() => undefined));
    render(<SessionLockHost api={fakeApi({ read: locked(), unlock })} enabled />);
    await tick(0);
    submit("pw");
    fireEvent.submit(screen.getByLabelText("Password"));
    expect(unlock).toHaveBeenCalledTimes(1);
  });

  it("backs off an unreadable session: 30, 60, then 120 s", async () => {
    const read = vi.fn().mockResolvedValue(null);
    render(<SessionLockHost api={fakeApi({ read })} enabled />);
    for (const [ms, calls] of [
      [0, 1],
      [29_999, 1],
      [1, 2],
      [60_000, 3],
      [120_000, 4],
      [120_000, 5],
    ]) {
      await tick(ms ?? 0);
      expect(read).toHaveBeenCalledTimes(calls ?? 0);
    }
  });

  it.each([
    ["a past deadline, not locked", clock(-5)],
    ["a NaN deadline", { ...clock(0), session: { ...clock(0).session, idle_deadline: "x" } }],
  ])("%s never re-reads in a tight loop", async (_name, answer) => {
    const read = vi.fn().mockResolvedValue(answer);
    render(<SessionLockHost api={fakeApi({ read })} enabled />);
    await tick(29_000);
    expect(read).toHaveBeenCalledTimes(1);
    await tick(1_000);
    expect(read).toHaveBeenCalledTimes(2);
  });

  it("an extend with no answer re-reads the session and shows the lock", async () => {
    const read = vi.fn().mockResolvedValueOnce(clock(60)).mockResolvedValue(clock(0, true));
    render(
      <SessionLockHost api={fakeApi({ read, extend: vi.fn().mockResolvedValue(null) })} enabled />,
    );
    await tick(0);
    fireEvent.click(screen.getByRole("button", { name: "Stay signed in" }));
    await tick(0);
    expect(screen.getByRole("alertdialog", { name: "Session locked" })).toBeInTheDocument();
  });
});
