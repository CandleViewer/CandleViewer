/**
 * Whose keymap this device holds, and whether a change of it reaches the server (#305; the orchestrator's ruling A55
 * on #2701, SEC-305B-02). A remap applies on the device for every role, since WCAG 2.1.4 needs a Viewer to remap or
 * turn off the single-character keys. The stored profile and the audit outbox are keyed by the signed-in user, and
 * the audit POST is queued only for a session holding `settings:write`. The server still enforces: the client only
 * avoids sending what it would refuse. The keymap's one read of the session claims, of `/me`'s user, of the shell's
 * sign-in (its bootstrap, with the `/me/keymap` answer it read; E10-T05 BQ-9) and of the session's end (BQ-15).
 */
import { accessToken } from "../lib/auth/accessToken";
import { getMeClaims } from "../lib/auth/meCache";
import { isViewing } from "../lib/auth/viewAsContext";
import { getShellState, subscribeShellState, type Keymap, type Me } from "../shell/bootstrap/store";

/**
 * `/me`'s user id; null before sign-in, and for a `/me` without a user (a stub's), which then keeps nothing.
 * Null too while a view-as context is held, live or ended (E42-S03; #304 gap 13): `/me` then names the target, so a
 * remap applies to the page only, and nothing is stored under the target's key or anyone's, adopted from the device's
 * legacy profile, written to a server store or queued for audit.
 */
export function keymapUser(): string | null {
  if (isViewing()) return null;
  const user: Partial<Me["user"]> | undefined = getShellState().me?.user;
  return typeof user?.id === "string" && user.id !== "" ? user.id : null;
}

/** The session may change its settings on the server (`settings:write`: an Owner or a Manager, never a Viewer). */
export const savesToServer = (): boolean => getMeClaims().permissions.includes("settings:write");

/** Calls `listener` when the signed-in user changes, not on every other change of the shell's state. */
export function subscribeKeymapUser(listener: () => void): () => void {
  let user = keymapUser();
  return subscribeShellState(() => {
    const next = keymapUser();
    if (next === user) return;
    user = next;
    listener();
  });
}

/** A completed bootstrap: `/me`'s user and the `/me/keymap` answer read with it (BQ-9). */
export interface SignIn {
  /** The bootstrap's own mark: a later run, even for the same user, is another sign-in. */
  readonly run: object;
  readonly user: string | null;
  /** The answer, or null when the call failed, which says nothing of the server's profile. */
  readonly keymap: Keymap | null;
}

/** The shell's last completed bootstrap; null until one completes. */
export function signedIn(): SignIn | null {
  const { bootstrap, keymap, keymapWarning } = getShellState();
  if (bootstrap.kind !== "ready") return null;
  return { run: bootstrap, user: keymapUser(), keymap: keymapWarning === null ? keymap : null };
}

/** Calls `listener` each time a bootstrap completes (`/me` and `/me/keymap` answered), not on any other change. */
export function subscribeSignIn(listener: () => void): () => void {
  let run: object = getShellState().bootstrap;
  return subscribeShellState(() => {
    const { bootstrap } = getShellState();
    if (bootstrap === run) return;
    run = bootstrap;
    if (bootstrap.kind === "ready") listener();
  });
}

/** Calls `listener` when the session ends in this tab: a sign-out, a lost session, a sibling tab's sign-out (BQ-15). */
export const subscribeSignOut = (listener: () => void): (() => void) =>
  accessToken.onEnded(listener);
