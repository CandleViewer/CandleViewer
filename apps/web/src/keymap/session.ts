/**
 * Whose keymap this device holds, and whether a change of it reaches the server (#305; the orchestrator's ruling A55
 * on #2701, SEC-305B-02). A remap applies on the device for every role, since WCAG 2.1.4 needs a Viewer to remap or
 * turn off the single-character keys. The stored profile and the audit outbox are keyed by the signed-in user, and
 * the audit POST is queued only for a session holding `settings:write`. The server still enforces: the client only
 * avoids sending what it would refuse. The keymap's one read of the session claims, of `/me`'s user, of the shell's
 * sign-in (its bootstrap, with the `/me/keymap` answer it read; E10-T05 BQ-9) and of the session's end (BQ-15).
 *
 * Keymap writes are skipped while a view-as context is active (read-only per the view-as policy, `22` "View-as
 * session"; E42-S03 #1134, #304 gap 13). A `/me` that names an Owner is never answered under one, since `22`
 * `startViewAs` never views as an Owner. Any other user is the keymap's once `22` `getViewAs` answers `204` for them,
 * and not before: while a context, live or held, is found, and while the read is unanswered or failed, `keymapUser()`
 * is null, so the profile is the defaults, a remap holds for the page only, and nothing is stored, queued or marked.
 * Until the read answers, character keys are inert too, so one the user turned off never fires (WCAG 2.1.4).
 * The shell's one view-as source (`lib/auth/viewAsContext`, read with `/me` at boot; E42-S03) is asked first: a context
 * it holds, live or ended, makes `keymapUser()` null as well.
 */
import { accessToken } from "../lib/auth/accessToken";
import { getMeClaims } from "../lib/auth/meCache";
import { isViewing } from "../lib/auth/viewAsContext";
import { apiFetch } from "../lib/http/csrfFetch";
import { getShellState, subscribeShellState, type Keymap, type Me } from "../shell/bootstrap/store";

/** `22` `getViewAs`: the session's view-as context, live or held (`200`), or none (`204`). */
export const VIEW_AS_PATH = "/api/v1/auth/session/view-as";

/** `/me`'s user id; null before sign-in, and for a `/me` without a user (a stub's), which then keeps nothing. */
function meUser(): string | null {
  const user: Partial<Me["user"]> | undefined = getShellState().me?.user;
  return typeof user?.id === "string" && user.id !== "" ? user.id : null;
}
const isOwner = (): boolean => getShellState().me?.role === "owner";

/** The keymap's read of the session's view-as context, for the user `/me` named when it was asked. */
interface ViewAs {
  readonly user: string;
  readonly abort: AbortController;
  /** `none` on `204`, `found` on a context, live or held; `failed` is asked again at a sign-in or on `online`. */
  state: "asking" | "failed" | "none" | "found";
}
let viewAs: ViewAs | null = null;
const viewAsListeners = new Set<() => void>();
/** The user `/me` named when the shell's last bootstrap completed: that sign-in is theirs alone (BQ-9). */
let named: { readonly run: object; readonly user: string | null } = {
  run: getShellState().bootstrap,
  user: meUser(),
};

/** The answer, and its read on the wire, go when `/me` names another user and when the session ends (BQ-15). */
function forgetViewAs(): void {
  if (viewAs === null) return;
  viewAs.abort.abort();
  viewAs = null;
  viewAsListeners.forEach((l) => l());
}
subscribeShellState(() => {
  const { bootstrap } = getShellState();
  if (bootstrap !== named.run) named = { run: bootstrap, user: meUser() };
  if (viewAs !== null && viewAs.user !== meUser()) forgetViewAs();
});
accessToken.onEnded(forgetViewAs);

/**
 * `/me`'s user while the keymap may keep their profile (above); null before sign-in and while it is read-only.
 * Null too while the shell's view-as source holds a context, live or ended (E42-S03; #304 gap 13): `/me` then names
 * the target, so a remap applies to the page only, and nothing is stored under the target's key or anyone's, adopted
 * from the device's legacy profile, written to a server store or queued for audit.
 */
export function keymapUser(): string | null {
  if (isViewing()) return null;
  const user = meUser();
  if (user === null || isOwner()) return user;
  return viewAs?.user === user && viewAs.state === "none" ? user : null;
}

/**
 * Asks `22` `getViewAs` once per sign-in for the user `/me` names, but an Owner (above); a read that failed is asked
 * again. Resolves when it is answered, or not sent.
 */
export async function readViewAs(): Promise<void> {
  const user = meUser();
  if (user === null || isOwner() || (viewAs?.user === user && viewAs.state !== "failed")) return;
  viewAs?.abort.abort();
  const asked: ViewAs = { user, abort: new AbortController(), state: "asking" };
  viewAs = asked;
  let state: ViewAs["state"] = "failed";
  try {
    const res = await apiFetch(VIEW_AS_PATH, {
      credentials: "same-origin",
      signal: asked.abort.signal,
    });
    if (res.status === 204) state = "none";
    else if (res.ok) state = "found";
  } catch {
    /* a network error or an abort: read-only until a later read answers */
  }
  if (viewAs !== asked) return; // `/me` named another user, or the session ended, meanwhile
  asked.state = state;
  viewAsListeners.forEach((l) => l());
}

/**
 * `/me` names a user other than an Owner whose view-as read has not answered for this sign-in: their profile is not
 * known yet, so the dispatcher keeps character keys inert (WCAG 2.1.4) while every other key keeps its default.
 */
export function viewAsPending(): boolean {
  const user = meUser();
  if (user === null || isOwner()) return false;
  return !(viewAs?.user === user && (viewAs.state === "none" || viewAs.state === "found"));
}

/** The keymap's read answered `204` for `user`'s sign-in: their session holds no view-as context. */
export const viewAsNone = (user: string): boolean =>
  viewAs?.user === user && viewAs.state === "none";

/** The session may change its settings on the server (`settings:write`: an Owner or a Manager, never a Viewer). */
export const savesToServer = (): boolean => getMeClaims().permissions.includes("settings:write");

/** Calls `listener` when `keymapUser()` changes (another user, or the view-as answer), not on any other change. */
export function subscribeKeymapUser(listener: () => void): () => void {
  let user = keymapUser();
  const check = (): void => {
    const next = keymapUser();
    if (next === user) return;
    user = next;
    listener();
  };
  const off = subscribeShellState(check);
  viewAsListeners.add(check);
  return () => {
    off();
    viewAsListeners.delete(check);
  };
}

/** A completed bootstrap: `/me`'s user and the `/me/keymap` answer read with it (BQ-9). */
export interface SignIn {
  /** The bootstrap's own mark: a later run, even for the same user, is another sign-in. */
  readonly run: object;
  /** The user it named, once `keymapUser()` names them; null until then, and for a user `/me` names after it. */
  readonly user: string | null;
  /** The answer, or null when the call failed, which says nothing of the server's profile. */
  readonly keymap: Keymap | null;
}

/** The shell's last completed bootstrap; null until one completes. */
export function signedIn(): SignIn | null {
  const { bootstrap, keymap, keymapWarning } = getShellState();
  if (bootstrap.kind !== "ready") return null;
  const user = keymapUser();
  return {
    run: bootstrap,
    user: user === named.user ? user : null,
    keymap: keymapWarning === null ? keymap : null,
  };
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
