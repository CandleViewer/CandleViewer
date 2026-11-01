/**
 * The profile store's client half (#305; BQ-1, A55), switched on by E10-T05: `sync.ts` sets it for the page. `profile.ts`
 * queues a change here only for a session holding `settings:write`, as A55 rules for every server write, and every
 * request checks it again; the server still decides (`x-rbac`). A Viewer's remap stays on the device, and no request
 * of theirs reaches `/settings/hotkeys`.
 *
 * Written against `22` (E10-T05). A write sends the whole profile (the ticket's full profile on save): every command
 * with the scope `HotkeyBinding.scope`'s table gives its context, and the keymap's own `requires_arm` and `confirm`,
 * which the server derives and rewrites where they differ (`Hotkey-Bindings-Rewritten`); the arm gate reads the keymap,
 * never a profile (C-2.21). It replaces the active profile, else the one named `DEFAULT_NAME`, else creates that one,
 * and makes it active, with no `If-Match`: the last write wins across devices (BQ-9). A profile read back is checked by
 * an import's rules, so no acknowledgement made elsewhere carries over (CR-305BD-04).
 */
import { ERROR_META, type generated } from "@candleviewer/protocol";
import { announce, forget } from "../features/app-shell/announcer";
import { apiFetch } from "../lib/http/csrfFetch";
import { KEYMAP, requiresArm, type KeymapContext } from "./keymap";
import { keymapUser, savesToServer, subscribeKeymapUser, subscribeSignOut } from "./session";
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
};
const PATH = "/api/v1/settings/hotkeys";
/** `22` `getViewAs`: the session's view-as context, live or held (`200`), or none (`204`). */
const VIEW_AS_PATH = "/api/v1/auth/session/view-as";
/** `21` §10.6: the name the client gives the profile it keeps for a user. */
const DEFAULT_NAME = "CandleViewer Default";
/** The device holds a change of this user's profile the server has not acknowledged (BQ-9): the profile, in a mark. */
const UNSENT_KEY = "cv.keymap-profile-unsent.v1";
/** The last refusal this store parked for the user (BQ-5): its status and code, never the bindings. */
const DEAD_KEY = "cv.keymap-profile-dead.v1";
/** A55's sentence (BQ-16), said once for each profile the server refuses for good. */
export const PARKED_NOTE = "Saved on this device only.";
const PARKED_SAID = "keymap:profile-parked";
/** How many times one pass lists the profiles again after a stale answer before it waits for the next flush. */
const MAX_RESYNCS = 2;

/**
 * Where a user's profile is kept beyond this device (BQ-1, E10-T05). A change is queued for its user, marked on the
 * device until the server acknowledges it, and sent only under that user's session; the latest one wins.
 */
export interface ProfileStorePort {
  /**
   * The signed-in user's active profile, checked by an import's rules; null when there is none, no answer, or the
   * signed-in user is no longer the one it was read for.
   */
  read(): Promise<ImportReport | null>;
  /** Queue `bindings` as `user`'s whole profile: the latest wins, sent only under `user`'s own session. */
  write(user: string, bindings: ReadonlyMap<string, string>): void;
  /** Send what is queued for the signed-in user; resolves once it is sent, parked or kept for a later try. */
  flush(): Promise<void>;
}

/** The HTTP adapter, with the sign-in's question (BQ-9). */
export interface HttpProfileStore extends ProfileStorePort {
  /** This device holds a change of `user`'s profile the server has not acknowledged (durable, per user). */
  unsent(user: string): boolean;
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

/**
 * A server profile's bindings as one import (D4), `HotkeyProfile`'s or `getMyKeymap`'s: their `scope`, `requires_arm`
 * and `confirm` are never read (C-2.6), and an action the keymap does not have is reported, never applied.
 */
export function serverProfile(bindings: unknown): ImportReport {
  const rows: readonly unknown[] = Array.isArray(bindings) ? bindings : [];
  const entries = rows.flatMap((row) => {
    if (row === null || typeof row !== "object") return [];
    const { action, keys } = row as { readonly action?: unknown; readonly keys?: unknown };
    return [[String(action), keys] as const];
  });
  return importProfile(Object.fromEntries(entries));
}

/** A profile's mark: each binding off its default, so a pass clears only the mark of the profile it sent. */
const markOf = (b: ReadonlyMap<string, string>): string =>
  JSON.stringify(
    Object.fromEntries(
      KEYMAP.flatMap((c) => {
        const keys = b.get(c.id) ?? c.defaultBinding;
        return keys === c.defaultBinding ? [] : [[c.id, keys]];
      }),
    ),
  );
const keyed = (base: string, user: string): string => `${base}:${user}`;
/** Storage that is blocked or full keeps no mark: the change still goes this session. */
function save(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable */
  }
}
function saved(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** What an answer means for the profile sent (BQ-5, CR-305C-04; `22` createHotkeyProfile, "Acting on a refusal"). */
type Outcome =
  | { readonly kind: "sent" }
  /** Transient: kept, and sent again in order at the next flush (a change, `online`, a sign-in). */
  | { readonly kind: "retry"; readonly code: string | null }
  /** The device's copy of the profiles is stale: list them again, then replace or recreate. */
  | { readonly kind: "resync" }
  /** The profile itself is refused, or (`stop`) the role: parked and said once; later changes still sync. */
  | {
      readonly kind: "park";
      readonly status: number;
      readonly code: string | null;
      readonly stop: boolean;
    };
const SENT: Outcome = { kind: "sent" };
const RETRY: Outcome = { kind: "retry", code: null };
const RESYNC: Outcome = { kind: "resync" };
/** The 4xx a later attempt can pass: a session to renew, a timeout, the rate limit (as `audit.ts`'s). */
const RETRYABLE_4XX: ReadonlySet<number> = new Set([401, 408, 429]);
/** A profile that went (404) or moved on (412): the list is stale, as is a name taken meanwhile (409 `name_taken`). */
const STALE: ReadonlySet<number> = new Set([404, 412]);

/** The problem's `code` and its `errors[].rule`s, as far as the body can be read. */
async function problemOf(res: Response): Promise<{ code: string | null; rules: string[] }> {
  try {
    const body = (await res.clone().json()) as { code?: unknown; errors?: unknown };
    const errors: readonly unknown[] = Array.isArray(body.errors) ? body.errors : [];
    const rules = errors.flatMap((e) =>
      e !== null && typeof e === "object" && typeof (e as { rule?: unknown }).rule === "string"
        ? [(e as { rule: string }).rule]
        : [],
    );
    return { code: typeof body.code === "string" ? body.code : null, rules };
  } catch {
    return { code: null, rules: [] }; // no JSON body
  }
}

const retryableCode = (code: string): boolean =>
  Object.hasOwn(ERROR_META, code) && ERROR_META[code as keyof typeof ERROR_META].retryable;

/**
 * BQ-5's table. Of the 403s only `forbidden` is the role's, which no later attempt passes; the CSRF guard's, a
 * read-only session's and a view-as context's are the session's (as `audit.ts` `isFinal` reads them). 413, any 422 and
 * a 409 but `name_taken` refuse the profile itself, so resending it unchanged gets the same answer.
 */
async function classify(res: Response): Promise<Outcome> {
  if (res.ok) return SENT;
  const { code, rules } = await problemOf(res);
  const { status } = res;
  if ((code !== null && retryableCode(code)) || status >= 500 || status < 400) {
    return { kind: "retry", code };
  }
  if (RETRYABLE_4XX.has(status)) return { kind: "retry", code };
  if (status === 403) {
    return code === "forbidden"
      ? { kind: "park", status, code, stop: true }
      : { kind: "retry", code };
  }
  if (STALE.has(status) || (status === 409 && rules.includes("name_taken"))) return RESYNC;
  return { kind: "park", status, code, stop: false };
}

/** One user's session, as this store knows it; a new one on each change of user. */
interface Session {
  /** Every request carries its signal: aborted when the user changes or the session ends (SEC-305C-03, BQ-15). */
  readonly abort: AbortController;
  /**
   * BQ-14: whether the session views as another user: not known yet, none, `found` by the session's read of its
   * context (so `/me` names the target, and every change was made under the view), or `reported` by a write's refusal
   * (a view begun after the read: the change it refused was made before it).
   */
  view: "unknown" | "none" | "found" | "reported";
  /** BQ-15: the session ended in this tab; nothing more goes under it. */
  ended: boolean;
  /** BQ-5: the server refused the role (`403 forbidden`); nothing more is sent this session. */
  stopped: boolean;
}
const fresh = (): Session => ({
  abort: new AbortController(),
  view: "unknown",
  ended: false,
  stopped: false,
});

export function httpProfileStore(
  send: typeof apiFetch = apiFetch,
  user: () => string | null = keymapUser,
  may: () => boolean = savesToServer,
): HttpProfileStore {
  const pending = new Map<string, ReadonlyMap<string, string>>();
  let running: Promise<void> | null = null;
  let again = false;
  /**
   * The shared HTTP layer repeats a request once after a 401's renewal, under whatever session the tab holds by then,
   * and checks the signal before it does, so a profile queued for one user is never re-sent under another's
   * (SEC-305C-03), nor after a sign-out (BQ-15). The subscriptions live as long as the store, which is the page's.
   */
  let session = fresh();
  subscribeKeymapUser(() => {
    session.abort.abort();
    session = fresh();
  });
  subscribeSignOut(() => {
    session.abort.abort();
    session.ended = true;
  });

  /** One request under `u`'s session `s`; null when it was not sent: `u` is not signed in, or `s` ended or went. */
  async function call(
    s: Session,
    u: string,
    path: string,
    method = "GET",
    body?: Schemas["HotkeyProfileInput"],
  ): Promise<Response | null> {
    if (s !== session || s.ended || user() !== u || !may()) return null;
    const init: RequestInit = {
      method,
      credentials: "same-origin",
      signal: s.abort.signal,
      ...(body === undefined
        ? {}
        : { headers: { "content-type": "application/json" }, body: JSON.stringify(body) }),
    };
    return send(path, init);
  }
  /** BQ-14: the session's view, read once per session from `22` `getViewAs`, and again while not known. */
  async function viewOf(s: Session, u: string): Promise<Session["view"]> {
    if (s.view !== "unknown") return s.view;
    const res = await call(s, u, VIEW_AS_PATH);
    if (res?.status === 204) s.view = "none";
    else if (res?.ok === true) s.view = "found"; // a live or a held context: the server refuses every write
    return s.view;
  }
  /** Replace `u`'s profile with `b`: the active one, else `DEFAULT_NAME`'s, else a new one; then make it active. */
  async function put(s: Session, u: string, b: ReadonlyMap<string, string>): Promise<Outcome> {
    const listed = await call(s, u, PATH);
    if (listed === null) return RETRY;
    if (!listed.ok) return classify(listed);
    const items: readonly Profile[] = ((await listed.json()) as ProfileList).items ?? [];
    // `22` folds names as Postgres `lower()` does: a name taken in another case is this one.
    const named = (p: Profile): boolean =>
      String(p.name).toLowerCase() === DEFAULT_NAME.toLowerCase();
    const held = items.find((p) => p.is_active === true) ?? items.find(named);
    let id: unknown = held?.id;
    if (held !== undefined && typeof id === "string") {
      const replaced = await call(
        s,
        u,
        `${PATH}/${encodeURIComponent(id)}`,
        "PUT",
        input(held.name, b),
      );
      if (replaced === null) return RETRY;
      if (!replaced.ok || held.is_active === true) return classify(replaced);
    } else {
      const made = await call(s, u, PATH, "POST", input(DEFAULT_NAME, b));
      if (made === null) return RETRY;
      if (!made.ok) return classify(made);
      id = ((await made.json()) as Partial<Profile>).id;
      if (typeof id !== "string") return RETRY; // an answer that names no profile: listed again next time
    }
    const activated = await call(s, u, `${PATH}/${encodeURIComponent(id)}/activate`, "POST");
    return activated === null ? RETRY : classify(activated);
  }
  /** A permanent refusal (BQ-5): kept on the device, its status under the dead-letter key, and said once (BQ-16). */
  function park(u: string, refused: Extract<Outcome, { kind: "park" }>): void {
    save(keyed(DEAD_KEY, u), JSON.stringify({ status: refused.status, code: refused.code }));
    console.warn(`hotkey profile: refused with ${refused.status}, parked under ${DEAD_KEY}`);
    forget(PARKED_SAID);
    announce("polite", PARKED_NOTE, PARKED_SAID);
  }
  /** `b` leaves the queue (sent or parked), and its mark with it, unless a newer change replaced it meanwhile. */
  function settle(u: string, b: ReadonlyMap<string, string>): void {
    if (pending.get(u) === b) pending.delete(u);
    if (saved(keyed(UNSENT_KEY, u)) === markOf(b)) save(keyed(UNSENT_KEY, u), null);
  }
  async function drain(): Promise<void> {
    const u = user();
    const b = u === null ? undefined : pending.get(u);
    if (u === null || b === undefined) return; // another user's profile waits for their own session
    const s = session;
    if (s.ended || s.stopped || !may()) return; // signed out, the role refused, or no `settings:write` (A55)
    let outcome: Outcome = RETRY;
    try {
      const view = await viewOf(s, u);
      // BQ-14: a change made under a view is never sent, and leaves no mark for the target's own next sign-in; one a
      // refusal reported was made before the view, so it waits for the next sign-in, as does one while none is known.
      if (view === "found") settle(u, b);
      if (view !== "none") return;
      for (let resyncs = 0; ; resyncs += 1) {
        outcome = await put(s, u, b);
        if (outcome.kind !== "resync" || resyncs === MAX_RESYNCS) break;
      }
    } catch {
      /* a network error, an abort or an unreadable answer: kept for a later try */
    }
    if (outcome.kind === "sent") settle(u, b);
    else if (outcome.kind === "park") {
      settle(u, b);
      park(u, outcome);
      if (outcome.stop) s.stopped = true;
    } else if (outcome.kind === "retry" && outcome.code?.startsWith("view_as_") === true) {
      s.view = "reported"; // the server says a view is live: nothing more goes this session (BQ-14)
    }
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
        const res = await call(session, u, PATH);
        if (res === null || !res.ok) return null;
        const items = ((await res.json()) as ProfileList).items;
        // The session can change during the GET: a profile read for one user is never handed to another (CR-305C-01).
        if (user() !== u) return null;
        const active = items?.find((p) => p.is_active === true);
        return active === undefined ? null : serverProfile(active.bindings);
      } catch {
        return null;
      }
    },
    write(u, b) {
      const { view } = session;
      if ((view === "found" || view === "reported") && user() === u) return; // BQ-14: nothing is queued under a view
      pending.set(u, b);
      save(keyed(UNSENT_KEY, u), markOf(b)); // durable until the server acknowledges it (BQ-9)
      void flush();
    },
    flush,
    unsent: (u) => saved(keyed(UNSENT_KEY, u)) !== null,
  };
}
