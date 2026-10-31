import { KEYMAP } from "./keymap";
import { parseProfile, resetAll } from "./profileIo";
import type { ProfileStorePort } from "./profileStore";
import { keymapUser, savesToServer, subscribeKeymapUser } from "./session";
import { importProfile, storedProfile } from "./validate";

/**
 * Live keymap profile (current bindings). Rebinds take effect without reload (SCR-113). It is the signed-in user's on
 * this device (#305, A55): stored under `cv.keymap-profile.v1:<user id>`, and kept by no one while no one is signed in.
 */
const STORE_KEY = "cv.keymap-profile.v1"; // alone: the one profile a device kept before A55
const keyOf = (user: string): string => `${STORE_KEY}:${user}`;
const defaults = (): Map<string, string> => new Map(KEYMAP.map((c) => [c.id, c.defaultBinding]));

/** What a profile stores: each binding that is not its command's default. */
function overridesOf(b: ReadonlyMap<string, string>): Record<string, string> {
  const overrides: Record<string, string> = {};
  for (const c of KEYMAP) {
    const cur = b.get(c.id);
    if (cur !== undefined && cur !== c.defaultBinding) overrides[c.id] = cur;
  }
  return overrides;
}

/**
 * A legacy unkeyed profile as its adopting user keeps it (A55), checked by an import's rules: the acknowledgement that
 * kept a bare key on a dangerous command was its maker's, the device's earlier user's, so none carries over
 * (SEC-305BF-01). Text that is no profile adopts nothing.
 */
function adopt(legacy: string): string {
  const parsed = parseProfile(legacy);
  return JSON.stringify(
    overridesOf(parsed.ok ? importProfile(parsed.profile).applied : defaults()),
  );
}

/**
 * The user's stored profile, checked as one profile, by an import's rules (#305: CR-305B-05, SEC-305B-01). Unknown
 * command ids and bindings that are not strings are ignored, and an empty one is an unbound command (WCAG 2.1.4). A
 * binding that fails on its own (a locked command's override, a legacy reserved key, a key outside the vocabulary, a
 * single letter on a dangerous command) or against the rest of the profile (a Global on a view's chord, a key two
 * commands share, which the first keeps) returns to its default. A legacy unkeyed profile is adopted once, by the
 * first user who loads with none of their own, by an import's rules (no acknowledgement carries over: SEC-305BF-01),
 * kept under that user's key, and removed (A55).
 */
function loadPersisted(user: string | null): ReadonlyMap<string, string> {
  if (user === null || typeof window === "undefined") return defaults();
  try {
    const store = window.localStorage;
    let raw = store.getItem(keyOf(user));
    const legacy = store.getItem(STORE_KEY);
    if (legacy !== null) {
      if (raw === null) {
        raw = adopt(legacy);
        store.setItem(keyOf(user), raw);
      }
      store.removeItem(STORE_KEY); // never handed to a second user
    }
    const v: unknown = raw ? JSON.parse(raw) : null;
    if (v && typeof v === "object" && !Array.isArray(v)) {
      return storedProfile(v as Readonly<Record<string, unknown>>).applied;
    }
  } catch {
    /* corrupt or unavailable storage: fall back to defaults */
  }
  return defaults();
}
function persist(user: string | null, b: ReadonlyMap<string, string>): void {
  if (user === null) return; // no one signed in: the change holds for this page only
  try {
    window.localStorage.setItem(keyOf(user), JSON.stringify(overridesOf(b)));
  } catch {
    /* storage unavailable: in-memory profile still applies this session */
  }
}

/**
 * The server's profile store (BQ-1): none until a server implements `22`'s `/settings/hotkeys`, so nothing is sent.
 * The device store above stays the active one; a store set here also gets each change made by a session holding
 * `settings:write` (A55), and the server still decides.
 */
let serverStore: ProfileStorePort | null = null;
export function setProfileStore(store: ProfileStorePort | null): void {
  serverStore = store;
}

let profileUser = keymapUser();
let bindings: ReadonlyMap<string, string> = loadPersisted(profileUser);
const listeners = new Set<() => void>();

// A55: the profile follows the signed-in user, whether `/me` names them after this module loads or another user signs
// in on this device; it lives as long as the page, as this module does.
subscribeKeymapUser(() => {
  profileUser = keymapUser();
  bindings = loadPersisted(profileUser);
  listeners.forEach((l) => l());
});

export const getBindings = (): ReadonlyMap<string, string> => bindings;
export function setBindings(next: ReadonlyMap<string, string>): void {
  bindings = next;
  persist(profileUser, next);
  listeners.forEach((l) => l()); // the UI first: a store that throws never skips it (CR-305C-07)
  if (serverStore !== null && profileUser !== null && savesToServer()) {
    try {
      serverStore.write(profileUser, next);
    } catch {
      /* a store that throws: the change stays on this device */
    }
  }
}
export function subscribeBindings(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}
/** SCR-113's Reset all, through the audited rebind (D10). */
export function resetBindings(): void {
  setBindings(resetAll(bindings));
}
