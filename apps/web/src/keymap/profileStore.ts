/**
 * The profile store's client half (#305; BQ-1, A55). `22`'s `/settings/hotkeys` keeps a user's hotkey profiles, but no
 * server implements it yet, so the device store (`profile.ts`) stays the active one and this adapter is wired off:
 * nothing calls `setProfileStore`, so nothing is sent. Switched on, `profile.ts` queues a change here only for a
 * session holding `settings:write`, as A55 rules for every server write; the server still decides (`x-rbac`).
 *
 * Written against `22` as it stands. A write sends the whole profile (the ticket's full profile on save): every
 * command with the scope `HotkeyBinding.scope`'s table gives its context, and the keymap's own `requires_arm` and
 * `confirm`. It replaces the active profile, else the one `21` §10.6 names, else creates that one, and makes it active.
 * A profile read back is checked by an import's rules, so no acknowledgement made elsewhere carries over (CR-305BD-04).
 */
import type { generated } from "@candleviewer/protocol";
import { apiFetch } from "../lib/http/csrfFetch";
import { KEYMAP, requiresArm, type KeymapContext } from "./keymap";
import { keymapUser, subscribeKeymapUser } from "./session";
import { importProfile, type ImportReport } from "./validate";

type Schemas = generated.rest.components["schemas"];
type Profile = Schemas["HotkeyProfile"];
type ProfileList =
  generated.rest.operations["listHotkeyProfiles"]["responses"][200]["content"]["application/json"];

/** `22` `HotkeyBinding.scope`'s fixed table (#5099): by context, never by id prefix. */
const SCOPE: Readonly<Record<KeymapContext, Schemas["HotkeyBinding"]["scope"]>> = {
  Global: "global",
  Auth: "auth",
  Workspace: "workspace",
  Chart: "chart",
  DOM: "dom",
  Ticket: "ticket",
  Positions: "positions",
  Replay: "replay",
  Rules: "rules",
  Admin: "admin",
  Settings: "settings",
  Tape: "tape",
};
const PATH = "/api/v1/settings/hotkeys";
/** `21` §10.6's name for a user's profile. */
const DEFAULT_NAME = "CandleViewer Default";

/**
 * Where a user's profile is kept beyond this device (BQ-1). The adapter leaves three things open, which the wiring and
 * the server ticket decide (CR-305C-04): a refused write stays queued and is retried only when `flush()` runs (a later
 * `write` runs it; no mount, `online` or sign-in does yet); the queue is memory-only, so a reload drops what was not
 * sent; and a permanent 4xx (a 409 or a 422, which no retry changes) is not told from a 503, so it is retried alike.
 */
export interface ProfileStorePort {
  /**
   * The signed-in user's active profile, checked by an import's rules; null when there is none, no answer, or the
   * signed-in user is no longer the one it was read for.
   */
  read(): Promise<ImportReport | null>;
  /** Queue `bindings` as `user`'s whole profile: the latest wins, sent only under `user`'s own session. */
  write(user: string, bindings: ReadonlyMap<string, string>): void;
  /** Send what is queued for the signed-in user; resolves once it is sent or kept for a later try. */
  flush(): Promise<void>;
}

function input(name: string, bindings: ReadonlyMap<string, string>): Schemas["HotkeyProfileInput"] {
  return {
    name,
    bindings: KEYMAP.map((c) => ({
      action: c.id,
      keys: bindings.get(c.id) ?? c.defaultBinding,
      scope: SCOPE[c.context],
      requires_arm: requiresArm(c),
      confirm: c.confirm === true,
    })),
  };
}

/** A profile's bindings as one import (D4); its `scope`, `requires_arm` and `confirm` are never read (C-2.6). */
function checked(bindings: unknown): ImportReport {
  const rows: readonly unknown[] = Array.isArray(bindings) ? bindings : [];
  const entries = rows.flatMap((row) => {
    if (row === null || typeof row !== "object") return [];
    const { action, keys } = row as { readonly action?: unknown; readonly keys?: unknown };
    return [[String(action), keys] as const];
  });
  return importProfile(Object.fromEntries(entries));
}

export function httpProfileStore(
  send: typeof apiFetch = apiFetch,
  user: () => string | null = keymapUser,
): ProfileStorePort {
  const pending = new Map<string, ReadonlyMap<string, string>>();
  let running: Promise<void> | null = null;
  let again = false;
  /**
   * The signal every request carries, aborted when the keymap user changes. The shared HTTP layer repeats a request
   * once after a 401's renewal, under whatever session the tab holds by then, and checks the signal before it does, so
   * a profile queued for one user is never re-sent under another's (SEC-305C-03). A fresh controller serves the next
   * user. The subscription lives as long as the store, which is the page's, as `profile.ts`'s does.
   */
  let session = new AbortController();
  subscribeKeymapUser(() => {
    session.abort();
    session = new AbortController();
  });

  /**
   * One request under `u`'s session, never sent once `u` is not the one signed in, nor repeated under another's (the
   * signal above); null unless it answered 2xx.
   */
  async function call(
    u: string,
    path: string,
    method = "GET",
    body?: Schemas["HotkeyProfileInput"],
  ): Promise<Response | null> {
    if (user() !== u) return null;
    const init: RequestInit = {
      method,
      credentials: "same-origin",
      signal: session.signal,
      ...(body === undefined
        ? {}
        : { headers: { "content-type": "application/json" }, body: JSON.stringify(body) }),
    };
    const res = await send(path, init);
    return res.ok ? res : null;
  }
  async function list(u: string): Promise<readonly Profile[] | null> {
    const res = await call(u, PATH);
    return res === null ? null : (((await res.json()) as ProfileList).items ?? []);
  }
  /** Replace `u`'s profile with `b`: the active one, else §10.6's, else a new one; then make it active. */
  async function store(u: string, b: ReadonlyMap<string, string>): Promise<boolean> {
    const items = await list(u);
    if (items === null) return false;
    const held =
      items.find((p) => p.is_active === true) ?? items.find((p) => p.name === DEFAULT_NAME);
    let id = held?.id;
    if (held !== undefined && id !== undefined) {
      const put = await call(u, `${PATH}/${encodeURIComponent(id)}`, "PUT", input(held.name, b));
      if (put === null) return false;
      if (held.is_active === true) return true;
    } else {
      const made = await call(u, PATH, "POST", input(DEFAULT_NAME, b));
      id = made === null ? undefined : ((await made.json()) as Profile).id;
      if (typeof id !== "string") return false;
    }
    return (await call(u, `${PATH}/${encodeURIComponent(id)}/activate`, "POST")) !== null;
  }
  async function drain(): Promise<void> {
    const u = user();
    const b = u === null ? undefined : pending.get(u);
    if (u === null || b === undefined) return; // another user's profile waits for their own session
    let sent = false;
    try {
      sent = await store(u, b);
    } catch {
      /* a network error or an unreadable answer: kept for a later try */
    }
    if (sent && pending.get(u) === b) pending.delete(u);
  }
  function flush(): Promise<void> {
    if (running !== null) {
      again = true; // a newer profile arrived mid-send: one more pass when this one ends
      return running;
    }
    const run = (async () => {
      await Promise.resolve(); // `running` is assigned before any completion
      try {
        do {
          again = false;
          await drain();
        } while (again);
      } finally {
        running = null; // a pass that throws must not wedge the queue (CR-305C-04)
      }
    })();
    running = run;
    return run;
  }

  return {
    async read() {
      const u = user();
      if (u === null) return null;
      try {
        const items = await list(u);
        // The session can change during the GET: a profile read for one user is never handed to another (CR-305C-01).
        if (user() !== u) return null;
        const active = items?.find((p) => p.is_active === true);
        return active === undefined ? null : checked(active.bindings);
      } catch {
        return null;
      }
    },
    write(u, b) {
      pending.set(u, b);
      void flush();
    },
    flush,
  };
}
