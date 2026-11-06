/**
 * The profile's sync with the server (E10-T05; BQ-9, A55): the HTTP store switched on for the page, the server's
 * profile taken at sign-in, and the queue flushed on a change (`profile.ts`), on `online` and at sign-in.
 *
 * At sign-in, for a session holding `settings:write`, the server wins: the profile `/me/keymap` answered (the call the
 * shell's bootstrap already makes) is applied by an import's rules, so no acknowledgement made elsewhere carries over
 * (CR-305BD-04), and kept on the device, neither sent back nor audited. The device wins only while it holds a change
 * the server has not acknowledged (durable, per user), which is then sent. A failed `/me/keymap` says nothing of the
 * server's profile, and neither does an answer naming no active profile: the device keeps its own. A Viewer stays on
 * the device, and no profile of theirs is read from or sent to the server here (A55). A sign-in is taken once the
 * keymap names its user, which for any user but an Owner waits for the view-as read (`session.ts`).
 */
import { getBindings, receiveBindings, setProfileStore } from "./profile";
import { httpProfileStore, serverProfile, type HttpProfileStore } from "./profileStore";
import {
  readViewAs,
  savesToServer,
  signedIn,
  subscribeKeymapUser,
  subscribeSignIn,
} from "./session";

/** The page's store: one, however often a host mounts, so a remount neither repeats a sign-in nor drops a send. */
let app: HttpProfileStore | null = null;
/** The bootstrap whose answer was last taken: each sign-in is taken once, when `keymapUser()` names its user. */
let taken: object | null = null;

function signIn(store: HttpProfileStore): void {
  const now = signedIn();
  if (now === null || now.run === taken || now.user === null) return;
  taken = now.run;
  const { user, keymap } = now;
  if (!savesToServer()) return;
  if (store.unsent(user)) {
    store.write(user, getBindings()); // the device's change, not yet acknowledged, wins
  } else if (typeof keymap?.hotkey_profile_id === "string") {
    receiveBindings(user, serverProfile(keymap.bindings).applied);
  }
  void store.flush();
}

/**
 * Switches the store on and syncs the signed-in user's profile from now on: the page's store unless a test gives one.
 * The returned function stops the sync; the store, its queue and its requests live on with the page.
 */
export function startProfileSync(
  store: HttpProfileStore = (app ??= httpProfileStore()),
): () => void {
  setProfileStore(store);
  const take = (): void => signIn(store);
  const offSignIn = subscribeSignIn(() => {
    void readViewAs(); // BQ-14: the new sign-in's view-as context
    take();
  });
  const offUser = subscribeKeymapUser(take); // a sign-in taken once the view-as read answers
  void readViewAs();
  take(); // the bootstrap that completed before the host mounted
  const online = (): void => {
    void readViewAs();
    void store.flush();
  };
  window.addEventListener("online", online);
  return () => {
    offSignIn();
    offUser();
    window.removeEventListener("online", online);
    setProfileStore(null);
  };
}
