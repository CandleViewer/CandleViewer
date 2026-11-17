/**
 * #5561: E09's session dialogs over an open CMP-043 dialog, and over SCR-112's own confirm. Each one takes the
 * focus with no focus loop, every modal under it is inert while it is up (one another owner made inert too),
 * `Esc` is the top dialog's wherever the focus is, and the focus then goes back to the field it left, its typed
 * text kept. Every case runs twice: in jsdom as it is (no `inert`, so CMP-043 hides the page with
 * `aria-hidden`), and with Chromium's native `inert` emulated.
 */
import { createRequire } from "node:module";
import { StrictMode, useState, type JSX, type ReactNode } from "react";
import { Dialog } from "@candleviewer/ui";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { SessionLockDialog } from "../../../src/features/session/SessionLockDialog";
import { SessionLockHost } from "../../../src/features/session/SessionLockHost";
import { SessionTimeoutWarning } from "../../../src/features/session/SessionTimeoutWarning";
import { SessionsSection } from "../../../src/features/session/SessionsSection";
import type { SessionApi, SessionClock } from "../../../src/features/session/sessionApi";
import type { SessionsApi, UserSession } from "../../../src/features/session/sessionsApi";
import { inertMode } from "../../helpers/nativeInert";
import { watchFocus } from "../../helpers/watchFocus";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const NOW = Date.parse("2026-10-27T10:00:00.000Z");
/** Under a session dialog: `inert`, or CMP-043's `aria-hidden` where the engine has no `inert`. */
const BELOW = '[inert], [aria-hidden="true"]';
const MODES = [
  ["no native inert", false],
  ["native inert", true],
] as const;

/** A `GET /auth/session` answer `remainingS` before the idle deadline, as in session.test.tsx. */
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
const ACTIVE = clock(900);
const WARNED = clock(30);
const LOCKED = clock(0, true);

/**
 * The host's api on a fake server: a read answers the session's state; `reach(next)` moves the session there,
 * and the token holder reports it, so the host reads at once. Any password unlocks.
 */
function fakeServer(start: SessionClock = ACTIVE) {
  const server = { clock: start };
  const listeners = new Set<() => void>();
  const api: SessionApi = {
    read: vi.fn(() => Promise.resolve(server.clock)),
    extend: vi.fn(() => Promise.resolve(ACTIVE)),
    unlock: vi.fn(() => {
      server.clock = ACTIVE;
      return Promise.resolve({ kind: "unlocked" as const, clock: ACTIVE });
    }),
    signOut: vi.fn(() => Promise.resolve(true)),
    endSession: vi.fn(),
    onLocked: (listener) => {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
  };
  const reach = (next: SessionClock): Promise<void> =>
    act(async () => {
      server.clock = next;
      listeners.forEach((listener) => listener());
      await vi.advanceTimersByTimeAsync(0);
    });
  return { api, reach };
}

/** SCR-112's api: this session and one other ("Desktop app"). */
function fakeSessions(): SessionsApi {
  const row = (n: number, device: string | null): UserSession => ({
    id: `00000000-0000-4000-8000-00000000000${n}`,
    device_name: device,
    ip: null,
    user_agent: "Mozilla/5.0 (X11; Linux x86_64) Firefox/131.0",
    created_at: "2026-10-27T08:00:00+00:00",
    last_seen_at: "2026-10-27T09:00:00+00:00",
    expires_at: "2026-10-27T20:00:00+00:00",
    current: device === null,
  });
  const items = [row(1, null), row(2, "Desktop app")];
  return {
    list: vi.fn(() => Promise.resolve({ kind: "ok" as const, items })),
    revoke: vi.fn(() => Promise.resolve({ kind: "done" as const })),
    signOutEverywhere: vi.fn(() => Promise.resolve({ kind: "done" as const })),
    endSession: vi.fn(),
  };
}

const tick = (): Promise<void> =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });

/**
 * The page as far as the overlays care: the TopBar (exempt from CMP-043's inert page), the page with the opener
 * of a CMP-043 dialog, then the lock host (mounted before any dialog opens, as App.tsx mounts it) or the
 * warning and the lock on their own.
 */
function Page({
  api,
  open: opened = false,
  warning = false,
  lock = false,
  children,
}: {
  readonly api?: SessionApi;
  readonly open?: boolean;
  readonly warning?: boolean;
  readonly lock?: boolean;
  readonly children?: ReactNode;
}): JSX.Element {
  const [open, setOpen] = useState(opened);
  return (
    <>
      <header data-cv-inert-exempt="">
        <button type="button">Emergency stop</button>
      </header>
      <main>
        <button type="button" onClick={() => setOpen(true)}>
          Invite user
        </button>
        {children}
      </main>
      <Dialog open={open} onOpenChange={setOpen} title="Invite user">
        <label>
          Username
          <input />
        </label>
      </Dialog>
      {api === undefined ? null : <SessionLockHost api={api} enabled />}
      {warning ? (
        <SessionTimeoutWarning expiresInSec={59} onExtend={vi.fn()} onDismiss={vi.fn()} />
      ) : null}
      {lock ? (
        <SessionLockDialog idleMinutes={15} phase="locked" onUnlock={vi.fn()} onSignOut={vi.fn()} />
      ) : null}
    </>
  );
}

/**
 * Two CMP-043 dialogs under the lock: "Invite user", open, and "Version", open while `upper`, opened last
 * beside it or, when `nested`, from inside it.
 */
function Stack({
  upper,
  lock,
  nested = false,
}: {
  readonly upper: boolean;
  readonly lock: boolean;
  readonly nested?: boolean;
}): JSX.Element {
  const top = (
    <Dialog open={upper} onOpenChange={() => undefined} title="Version">
      <label>
        Note
        <input />
      </label>
    </Dialog>
  );
  return (
    <>
      <main>
        <button type="button">page</button>
      </main>
      <Dialog open onOpenChange={() => undefined} title="Invite user">
        <label>
          Username
          <input />
        </label>
        {nested ? top : null}
      </Dialog>
      {nested ? null : top}
      {lock ? <SessionLockDialog idleMinutes={15} phase="locked" onUnlock={vi.fn()} /> : null}
    </>
  );
}

const invite = (): HTMLElement => screen.getByRole("dialog", { name: "Invite user", hidden: true });
const named = (name: string): HTMLElement =>
  screen.getByRole("alertdialog", { name, hidden: true });

/** Opens the CMP-043 dialog from the page and types in it; returns its field, which has the focus. */
function openInvite(): HTMLElement {
  const opener = screen.getByRole("button", { name: "Invite user" });
  opener.focus();
  fireEvent.click(opener);
  const field = screen.getByRole("textbox", { name: "Username" });
  fireEvent.change(field, { target: { value: "annie" } });
  expect(field).toHaveFocus();
  return field;
}

async function unlockWith(password: string): Promise<void> {
  const field = screen.getByLabelText("Password");
  fireEvent.change(field, { target: { value: password } });
  fireEvent.submit(field);
  await tick();
}

/** A press on a session card's own text drops the focus to `body`; then `Esc`, aimed at `body`. */
async function escapeOnBody(): Promise<void> {
  (document.activeElement as HTMLElement).blur();
  expect(document.body).toHaveFocus();
  fireEvent.keyDown(document.body, { key: "Escape" });
  await tick();
}

describe.each(MODES)("E09 session dialogs over a CMP-043 dialog (%s)", (_mode, native) => {
  inertMode(native);
  beforeEach(() => {
    vi.useFakeTimers({
      toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"],
    });
    vi.setSystemTime(NOW);
  });
  afterEach(() => vi.useRealTimers());

  /** The page, the dialog open with "annie" typed, then the lock. */
  async function lockOverInvite(strict = false) {
    const { api, reach } = fakeServer();
    const page = <Page api={api} />;
    render(strict ? <StrictMode>{page}</StrictMode> : page);
    await tick();
    const field = openInvite();
    const watch = watchFocus();
    await reach(LOCKED);
    return { api, field, watch };
  }

  it("the lock takes the focus from the dialog under it, with no loop, and holds it", async () => {
    const { field, watch } = await lockOverInvite();
    const password = screen.getByLabelText("Password");
    expect(watch.errors).toEqual([]);
    expect(watch.count()).toBeLessThan(5);
    expect(password).toHaveFocus();
    expect(invite().closest(BELOW)).not.toBeNull();
    expect(named("Session locked").closest(BELOW)).toBeNull(); // a layer: the dialog's inert page spares it
    fireEvent.keyDown(password, { key: "Escape" });
    expect(screen.getByRole("alertdialog", { name: "Session locked" })).toBeInTheDocument();
    expect(invite()).toBeInTheDocument();
    fireEvent.change(document.activeElement as HTMLElement, { target: { value: "pw" } });
    expect(password).toHaveValue("pw"); // typing reaches the lock, not the dialog
    expect(field).toHaveValue("annie");
  });

  it("Esc with the focus on body leaves the dialog under the lock open, its text kept", async () => {
    const { field, watch } = await lockOverInvite();
    await escapeOnBody();
    expect(named("Session locked")).toBeInTheDocument();
    expect(invite()).toBeInTheDocument();
    expect(field).toHaveValue("annie");
    expect(watch.count()).toBeLessThan(5);
    expect(watch.errors).toEqual([]);
  });

  it("after unlock the dialog is live again, its text kept and the focus back on its field", async () => {
    const { field, watch } = await lockOverInvite();
    await unlockWith("pw");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(invite().closest(BELOW)).toBeNull();
    expect(field).toHaveFocus();
    expect(field).toHaveValue("annie");
    expect(watch.count()).toBeLessThan(5);
    expect(watch.errors).toEqual([]);
  });

  it("under StrictMode the lock still takes the focus with no loop", async () => {
    const { watch } = await lockOverInvite(true);
    expect(watch.errors).toEqual([]);
    expect(watch.count()).toBeLessThan(5);
    expect(screen.getByLabelText("Password")).toHaveFocus();
  });

  it("the warning takes the focus; Esc dismisses only the warning, and the focus goes back", async () => {
    const { api, reach } = fakeServer();
    render(<Page api={api} />);
    await tick();
    const field = openInvite();
    const watch = watchFocus();
    await reach(WARNED);
    const stay = screen.getByRole("button", { name: "Stay signed in" });
    expect(stay).toHaveFocus();
    expect(invite().closest(BELOW)).not.toBeNull();
    expect(named("Your session will lock soon").closest(BELOW)).toBeNull();
    fireEvent.keyDown(stay, { key: "Escape" });
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(invite().closest(BELOW)).toBeNull();
    expect(field).toHaveFocus();
    expect(api.extend).not.toHaveBeenCalled();
    expect(watch.count()).toBeLessThan(5);
    expect(watch.errors).toEqual([]);
  });

  it("Esc with the focus on body dismisses only the warning; the dialog stays open", async () => {
    const { api, reach } = fakeServer();
    render(<Page api={api} />);
    await tick();
    const field = openInvite();
    const watch = watchFocus();
    await reach(WARNED);
    await escapeOnBody();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(invite()).toBeInTheDocument();
    expect(field).toHaveValue("annie");
    expect(api.extend).not.toHaveBeenCalled();
    expect(watch.count()).toBeLessThan(5);
    expect(watch.errors).toEqual([]);
  });

  it("warning, lock, sign-out confirm and back, a wrong password, unlock: the focus ends on the field", async () => {
    const { api, reach } = fakeServer();
    render(<Page api={api} />);
    await tick();
    const field = openInvite();
    const watch = watchFocus();
    await reach(WARNED);
    expect(screen.getByRole("button", { name: "Stay signed in" })).toHaveFocus();
    await reach(LOCKED); // the warning gives way to the lock in one commit
    expect(screen.getByLabelText("Password")).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Sign out instead" }));
    const confirm = screen.getByRole("alertdialog", { name: "Sign out?" });
    expect(screen.getByRole("button", { name: "Back to unlock" })).toHaveFocus();
    fireEvent.keyDown(confirm, { key: "Escape" });
    expect(screen.getByLabelText("Password")).toHaveFocus();
    vi.mocked(api.unlock).mockResolvedValueOnce({ kind: "invalid" });
    await unlockWith("wrong");
    expect(screen.getByRole("alert")).toHaveTextContent("Incorrect password. Try again.");
    expect(screen.getByLabelText("Password")).toHaveFocus();
    await unlockWith("right");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(field).toHaveFocus();
    expect(field).toHaveValue("annie");
    expect(watch.count()).toBeLessThan(10);
    expect(watch.errors).toEqual([]);
  });

  it("the expiry card that replaces the lock takes the focus, with no loop", async () => {
    const { api, watch } = await lockOverInvite();
    vi.mocked(api.unlock).mockResolvedValueOnce({ kind: "revoked", reason: "expired" });
    await unlockWith("pw");
    expect(screen.getByRole("button", { name: "Sign in" })).toHaveFocus();
    expect(invite().closest(BELOW)).not.toBeNull();
    expect(named("Session expired").closest(BELOW)).toBeNull();
    expect(watch.errors).toEqual([]);
    expect(watch.count()).toBeLessThan(5);
  });

  it("Esc with the focus on body leaves the dialog under the expiry card open", async () => {
    const { api, field, watch } = await lockOverInvite();
    vi.mocked(api.unlock).mockResolvedValueOnce({ kind: "revoked", reason: "expired" });
    await unlockWith("pw");
    await escapeOnBody();
    expect(named("Session expired")).toBeInTheDocument();
    expect(invite()).toBeInTheDocument();
    expect(field).toHaveValue("annie");
    expect(watch.count()).toBeLessThan(5);
    expect(watch.errors).toEqual([]);
  });

  it("the lock over SCR-112's revoke confirm takes the focus; after unlock it is back on Cancel", async () => {
    const { api, reach } = fakeServer();
    render(
      <Page api={api}>
        <SessionsSection api={fakeSessions()} />
      </Page>,
    );
    await tick();
    fireEvent.click(screen.getByRole("button", { name: /^Revoke Desktop app/u }));
    const cancel = screen.getByRole("button", { name: "Cancel" });
    expect(cancel).toHaveFocus();
    const watch = watchFocus();
    await reach(LOCKED);
    expect(watch.errors).toEqual([]);
    expect(watch.count()).toBeLessThan(5);
    expect(screen.getByLabelText("Password")).toHaveFocus();
    await unlockWith("pw");
    expect(screen.getByRole("alertdialog", { name: "Revoke session?" })).toBeInTheDocument();
    expect(cancel).toHaveFocus();
  });

  it("a confirm under an inert canvas that lifts while locked stays inert, with no loop", async () => {
    const { api, reach } = fakeServer();
    render(
      <Page api={api}>
        <div data-testid="canvas">
          <SessionsSection api={fakeSessions()} />
        </div>
      </Page>,
    );
    await tick();
    fireEvent.click(screen.getByRole("button", { name: /^Revoke Desktop app/u }));
    const confirm = named("Revoke session?");
    const canvas = screen.getByTestId("canvas");
    canvas.setAttribute("inert", ""); // another owner holds the canvas, as SCR-159's overlay does
    await reach(LOCKED);
    const password = screen.getByLabelText("Password");
    expect(password).toHaveFocus();
    canvas.removeAttribute("inert"); // and lets it go while the lock is up
    const watch = watchFocus();
    password.blur();
    password.focus(); // at once: a focus move inside the lock
    expect(watch.errors).toEqual([]);
    expect(watch.count()).toBeLessThan(5);
    expect(password).toHaveFocus();
    expect(confirm).toHaveAttribute("inert");
  });

  it("a dialog over the confirm closes under the lock: the confirm stays inert, with no loop", async () => {
    const sessions = fakeSessions();
    function Over({ over, lock }: { readonly over: boolean; readonly lock: boolean }): JSX.Element {
      return (
        <>
          <main>
            <SessionsSection api={sessions} />
          </main>
          <Dialog open={over} onOpenChange={() => undefined} title="Version">
            <label>
              Note
              <input />
            </label>
          </Dialog>
          {lock ? <SessionLockDialog idleMinutes={15} phase="locked" onUnlock={vi.fn()} /> : null}
        </>
      );
    }
    const view = render(<Over over={false} lock={false} />);
    await tick();
    fireEvent.click(screen.getByRole("button", { name: /^Revoke Desktop app/u }));
    const confirm = named("Revoke session?");
    view.rerender(<Over over lock={false} />); // CMP-043's inert page holds the confirm
    view.rerender(<Over over lock />);
    const password = screen.getByLabelText("Password");
    expect(password).toHaveFocus();
    view.rerender(<Over over={false} lock />); // the dialog closes on its own while locked
    const watch = watchFocus();
    password.blur();
    password.focus();
    expect(watch.errors).toEqual([]);
    expect(watch.count()).toBeLessThan(5);
    expect(password).toHaveFocus();
    expect(confirm).toHaveAttribute("inert");
  });

  it("the upper of two dialogs closes under the lock: the lower stays inert, with no loop", () => {
    const view = render(<Stack upper lock={false} />);
    view.rerender(<Stack upper lock />);
    const password = screen.getByLabelText("Password");
    expect(password).toHaveFocus();
    view.rerender(<Stack upper={false} lock />); // it closes on its own while locked
    const watch = watchFocus();
    password.blur();
    password.focus();
    expect(watch.errors).toEqual([]);
    expect(watch.count()).toBeLessThan(5);
    expect(password).toHaveFocus();
    expect(invite()).toHaveAttribute("inert");
  });

  it("a nested dialog closes under the lock: its parent is held again, with no loop", async () => {
    const view = render(<Stack nested upper lock={false} />);
    await tick();
    view.rerender(<Stack nested upper lock />);
    await tick();
    const password = screen.getByLabelText("Password");
    expect(password).toHaveFocus();
    view.rerender(<Stack nested upper={false} lock />);
    await tick(); // the parent the nested dialog let go is held again before a later focus move
    const watch = watchFocus();
    password.blur();
    password.focus();
    expect(watch.errors).toEqual([]);
    expect(watch.count()).toBeLessThan(5);
    expect(password).toHaveFocus();
    expect(invite()).toHaveAttribute("inert");
  });

  it("a nested dialog closes under the lock with the focus on body: its parent's opener takes no loop", async () => {
    const shut: { close?: () => void } = {};
    function Opened({ lock }: { readonly lock: boolean }): JSX.Element {
      const [upper, setUpper] = useState(false);
      shut.close = () => setUpper(false);
      return (
        <>
          <Dialog open onOpenChange={() => undefined} title="Invite user">
            <button type="button" onClick={() => setUpper(true)}>
              Open version
            </button>
            <Dialog open={upper} onOpenChange={() => undefined} title="Version">
              <label>
                Note
                <input />
              </label>
            </Dialog>
          </Dialog>
          {lock ? <SessionLockDialog idleMinutes={15} phase="locked" onUnlock={vi.fn()} /> : null}
        </>
      );
    }
    const view = render(<Opened lock={false} />);
    await tick();
    const opener = screen.getByRole("button", { name: "Open version" });
    opener.focus();
    fireEvent.click(opener); // CMP-043 gives the focus back to this button when "Version" closes
    await tick();
    view.rerender(<Opened lock />);
    await tick();
    const password = screen.getByLabelText("Password");
    expect(password).toHaveFocus();
    password.blur(); // a press on the lock's own text
    const watch = watchFocus();
    act(() => shut.close?.()); // its focus return runs in the same task as the release
    expect(watch.errors).toEqual([]);
    expect(watch.count()).toBeLessThan(5);
    await tick();
    expect(invite()).toHaveAttribute("inert");
    expect(invite().contains(document.activeElement)).toBe(false);
    expect(watch.errors).toEqual([]);
  });

  it("two session dialogs up at once: the dialog under them stays inert until the last one goes", () => {
    const view = render(<Page open />);
    view.rerender(<Page open warning />);
    view.rerender(<Page open warning lock />);
    expect(screen.getByLabelText("Password")).toHaveFocus();
    view.rerender(<Page open lock />); // the lower one goes first
    expect(invite().closest(BELOW)).not.toBeNull();
    const watch = watchFocus();
    const unlock = screen.getByRole("button", { name: "Unlock" });
    unlock.focus(); // a Tab inside the lock: nothing below pulls the focus back
    expect(unlock).toHaveFocus();
    expect(watch.count()).toBeLessThan(5);
    expect(watch.errors).toEqual([]);
    view.rerender(<Page open />);
    expect(invite().closest(BELOW)).toBeNull();
  });

  it("the warning and the lock mount in one commit over a dialog: the lock is live and focused", async () => {
    const view = render(<Page open />);
    const watch = watchFocus();
    view.rerender(<Page open warning lock />);
    await tick();
    expect(named("Session locked").closest(BELOW)).toBeNull();
    expect(named("Your session will lock soon").closest(BELOW)).not.toBeNull();
    expect(screen.getByLabelText("Password")).toHaveFocus();
    expect(watch.count()).toBeLessThan(5);
    expect(watch.errors).toEqual([]);
  });

  it("a dialog that opens while locked takes the focus with no loop; its Esc closes it, back to the lock", async () => {
    const { api } = fakeServer(LOCKED);
    render(<Page api={api} />);
    await tick();
    expect(screen.getByLabelText("Password")).toHaveFocus();
    const watch = watchFocus();
    fireEvent.click(screen.getByRole("button", { name: "Invite user" }));
    expect(watch.errors).toEqual([]);
    expect(watch.count()).toBeLessThan(5);
    const username = screen.getByRole("textbox", { name: "Username" });
    expect(username).toHaveFocus();
    expect(named("Session locked").closest(BELOW)).not.toBeNull();
    fireEvent.keyDown(username, { key: "Escape" }); // the dialog on top takes its own Esc
    await tick();
    expect(screen.queryByRole("dialog", { hidden: true })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveFocus();
    expect(watch.count()).toBeLessThan(10);
    expect(watch.errors).toEqual([]);
  });

  it("a dialog opened inside the dialog under the lock is live and focused, the lock held", async () => {
    // above the lock in CMP-043's stack, but it paints under the lock's scrim: its layer is the parent's
    const view = render(<Stack nested upper={false} lock={false} />);
    view.rerender(<Stack nested upper={false} lock />);
    await tick();
    const watch = watchFocus();
    view.rerender(<Stack nested upper lock />); // opened by the page, not by the user
    await tick();
    expect(screen.getByRole("textbox", { name: "Note" })).toHaveFocus();
    expect(screen.getByRole("dialog", { name: "Version", hidden: true }).closest(BELOW)).toBeNull();
    expect(named("Session locked").closest(BELOW)).not.toBeNull();
    expect(watch.count()).toBeLessThan(5);
    expect(watch.errors).toEqual([]);
  });

  it("the lock goes while a dialog that opened over it is up: the focus stays in that dialog", async () => {
    const view = render(<Stack upper={false} lock={false} />);
    view.rerender(<Stack upper={false} lock />);
    view.rerender(<Stack upper lock />);
    await tick();
    const note = screen.getByRole("textbox", { name: "Note" });
    expect(note).toHaveFocus();
    const watch = watchFocus();
    view.rerender(<Stack upper lock={false} />); // unlocked elsewhere: the opener is under "Version"
    await tick();
    expect(note).toHaveFocus();
    expect(watch.count()).toBe(0);
    expect(watch.errors).toEqual([]);
  });

  it("a blur to body before the lock leaves nothing to go back to: after unlock the focus stays there", async () => {
    const { api, reach } = fakeServer();
    render(<Page api={api} />);
    await tick();
    const opener = screen.getByRole("button", { name: "Invite user" });
    opener.focus();
    opener.blur(); // a press on the page's background
    const watch = watchFocus();
    await reach(LOCKED);
    expect(screen.getByLabelText("Password")).toHaveFocus();
    await unlockWith("pw");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(document.body).toHaveFocus(); // as on main: nothing had the focus when the lock came
    expect(watch.count()).toBeLessThan(5);
    expect(watch.errors).toEqual([]);
  });

  it("the host and its lock leave no listener or observer behind when they unmount", async () => {
    const add = vi.spyOn(document, "addEventListener");
    const remove = vi.spyOn(document, "removeEventListener");
    const observe = vi.spyOn(MutationObserver.prototype, "observe");
    const disconnect = vi.spyOn(MutationObserver.prototype, "disconnect");
    onTestFinished(() => {
      add.mockRestore();
      remove.mockRestore();
      observe.mockRestore();
      disconnect.mockRestore();
    });
    const { api } = fakeServer(LOCKED);
    const view = render(<SessionLockHost api={api} enabled />);
    await tick();
    expect(screen.getByLabelText("Password")).toHaveFocus();
    const added = add.mock.calls.filter(([type]) =>
      ["focusin", "focusout", "keydown"].includes(type),
    );
    // the host's focus record (focusin, focusout), the lock's guard and its Esc claim
    expect(added.map(([type]) => type).sort()).toEqual([
      "focusin",
      "focusin",
      "focusout",
      "keydown",
    ]);
    expect(observe).toHaveBeenCalled();
    view.unmount();
    for (const call of added) expect(remove).toHaveBeenCalledWith(...call);
    for (const observer of observe.mock.contexts)
      expect(disconnect.mock.contexts).toContain(observer);
  });
});

describe.each(MODES)("axe: a session dialog over an open CMP-043 dialog (%s)", (_mode, native) => {
  inertMode(native);

  it.each(["warning", "lock"] as const)(
    "the %s has no serious or critical violations",
    async (over) => {
      const view = render(<Page open />);
      const watch = watchFocus();
      view.rerender(<Page open warning={over === "warning"} lock={over === "lock"} />);
      const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
      expect(
        res.violations.filter((v) => v.impact === "serious" || v.impact === "critical"),
      ).toEqual([]);
      expect(watch.count()).toBeLessThan(5);
      expect(watch.errors).toEqual([]);
    },
  );
});
