/**
 * Whose keymap this device holds, and whether a change of it reaches the server (#305; the orchestrator's ruling A55
 * on #2701, SEC-305B-02). A remap applies on the device for every role, since WCAG 2.1.4 needs a Viewer to remap or
 * turn off the single-character keys. The stored profile and the audit outbox are keyed by the signed-in user, and
 * the audit POST is queued only for a session holding `settings:write`. The server still enforces: the client only
 * avoids sending what it would refuse. The keymap's one read of the session claims and of `/me`'s user.
 */
import { getMeClaims } from "../lib/auth/meCache";
import { getShellState, subscribeShellState, type Me } from "../shell/bootstrap/store";

/** `/me`'s user id; null before sign-in, and for a `/me` without a user (a stub's), which then keeps nothing. */
// View-as (E42-S03 #1134): while a view-as context is live this must return null, with a test (#304 gap 13).
export function keymapUser(): string | null {
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
