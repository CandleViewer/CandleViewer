import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { generated } from "@candleviewer/protocol";
import type { Keymap } from "../src/shell/bootstrap/store";
import type { Role } from "../src/routes/rbac";

/**
 * E10-T05 (#5211), the client wiring of the profile store against `22`'s `/settings/hotkeys*`, with a stubbed server
 * and no network. At sign-in the server wins for a session holding `settings:write`, unless this device holds a change
 * the server has not acknowledged (BQ-9); the queue flushes on a change, on `online` and at sign-in; a refusal is
 * parked, retried or re-synced by its class (BQ-5); the store's requests abort at sign-out and on a change of user
 * (BQ-15, SEC-305C-03); a Viewer (A55) and a view-as session (BQ-14) send nothing. Each test is a page of its own.
 */
type Binding = generated.rest.components["schemas"]["HotkeyBinding"];
type HotkeyProfile = generated.rest.components["schemas"]["HotkeyProfile"];
const load = async () => ({
  ...(await import("../src/keymap/sync")),
  ...(await import("../src/keymap/profileStore")),
  ...(await import("../src/keymap/profile")),
  ...(await import("../src/keymap/audit")),
  ...(await import("../src/keymap/registry")),
  ...(await import("../src/keymap/KeymapHost")),
  ...(await import("../src/keymap/Cheatsheet")),
  ...(await import("../src/features/app-shell/announcer")),
  ...(await import("../src/lib/auth/accessToken")),
  ...(await import("../src/lib/auth/meCache")),
  ...(await import("../src/shell/bootstrap/store")),
});
let m: Awaited<ReturnType<typeof load>>;
/** A new page on this device: the modules load again, the device's storage stays. */
async function reload(): Promise<void> {
  vi.resetModules();
  m = await load();
}

/** Each test's syncs, stopped after it: a page's `online` listener must not outlive its test. */
const stops: (() => void)[] = [];

// The first load transforms the module graph (the UI package's source with it), which a loaded runner can take past
// the 10 s hook budget; each test's own load then evaluates it again.
beforeAll(async () => void (await load()), 60_000);
beforeEach(async () => {
  vi.useFakeTimers();
  window.localStorage.clear();
  await reload();
});
afterEach(() => {
  stops.splice(0).forEach((stop) => stop());
  m.accessToken.clear();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const PROFILES = "/api/v1/settings/hotkeys";
const VIEW_AS = "/api/v1/auth/session/view-as";
const UNSENT = "cv.keymap-profile-unsent.v1";
const DEAD = "cv.keymap-profile-dead.v1";
const DEVICE = "cv.keymap-profile.v1";
const NOTE = "Saved on this device only.";

interface Call {
  readonly method: string;
  readonly url: string;
  readonly body: unknown;
  readonly ifMatch: string | null;
}
interface Row {
  readonly id: string;
  name: string;
  isActive: boolean;
  version: number;
  bindings: Binding[];
}
type Answer = Response | Promise<Response> | undefined;
type Refuse = (method: string, url: string, init?: RequestInit) => Answer;
const noRefusal: Refuse = () => undefined;
/**
 * `22`'s `/settings/hotkeys*` for one user, as the server PR serves it: list, create (inactive, version 1), replace,
 * activate; an unknown id is `404`, and a create or a replace naming a profile another one holds (folded by `lower()`)
 * is `409 name_taken`. `refuse` answers a request first when it returns one, and `view` answers `22` `getViewAs`
 * (`204`: no view). Every request is recorded in order.
 */
function stubServer() {
  const calls: Call[] = [];
  const rows: Row[] = [];
  let made = 0;
  const server = {
    calls,
    rows,
    /** `Hotkey-Bindings-Rewritten` on a create's or a replace's answer, when set. */
    rewritten: null as string | null,
    refuse: noRefusal,
    view: (): Response => new Response(null, { status: 204 }),
    /** The `/me/keymap` answer for the active profile, flattened (`22` getMyKeymap). */
    keymap: (): Keymap => {
      const active = rows.find((r) => r.isActive);
      return active === undefined
        ? { bindings: [] }
        : { hotkey_profile_id: active.id, bindings: active.bindings };
    },
  };
  const profile = (r: Row) =>
    ({
      id: r.id,
      owner_user_id: "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001",
      name: r.name,
      bindings: r.bindings,
      is_active: r.isActive,
      version: r.version,
      created_at: "2026-10-31T00:00:00Z",
      updated_at: "2026-10-31T00:00:00Z",
    }) satisfies HotkeyProfile;
  /** `22` folds names as Postgres `lower()` does: a name another of the user's profiles holds is taken (`name_taken`). */
  const taken = (name: string, except?: Row): boolean =>
    rows.some((r) => r !== except && r.name.toLowerCase() === name.toLowerCase());
  const missing = () => problem(404, "not_found");
  const rewrite = (): Record<string, string> =>
    server.rewritten === null ? {} : { "Hotkey-Bindings-Rewritten": server.rewritten };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      init?.signal?.throwIfAborted();
      const method = init?.method ?? "GET";
      const url = String(input);
      const body: unknown = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, url, body, ifMatch: new Headers(init?.headers).get("if-match") });
      if (url === VIEW_AS) return server.view();
      const refused = server.refuse(method, url, init);
      if (refused !== undefined) return refused;
      const sent = body as { name: string; bindings: Binding[] } | undefined;
      if (url === PROFILES) {
        if (method === "GET") return Response.json({ items: rows.map(profile) });
        if (taken(sent?.name ?? "")) return problem(409, "conflict", "name_taken");
        made += 1;
        const id = `17000000-0000-4000-8000-${String(made).padStart(12, "0")}`;
        const row: Row = {
          id,
          name: sent?.name ?? "",
          isActive: false,
          version: 1,
          bindings: sent?.bindings ?? [],
        };
        rows.push(row);
        return Response.json(profile(row), { status: 201, headers: rewrite() });
      }
      const [, id, verb] = /^\/api\/v1\/settings\/hotkeys\/([^/]+)(\/activate)?$/.exec(url) ?? [];
      const row = rows.find((r) => r.id === id);
      if (row === undefined) return missing();
      if (verb !== undefined) rows.forEach((r) => (r.isActive = r === row));
      else if (sent !== undefined) {
        if (taken(sent.name, row)) return problem(409, "conflict", "name_taken");
        Object.assign(row, { name: sent.name, bindings: sent.bindings, version: row.version + 1 });
      }
      return Response.json(profile(row), { headers: verb === undefined ? rewrite() : {} });
    }),
  );
  return server;
}
const lines = (calls: readonly Call[]): string[] => calls.map((c) => `${c.method} ${c.url}`);
/** A problem document as `22`'s refusals carry it, with `errors[].rule` when the refusal names one. */
const problem = (status: number, code: string, rule?: string): Response =>
  Response.json(
    {
      type: "about:blank",
      title: code,
      status,
      code,
      errors: rule ? [{ field: "bindings", rule }] : [],
    },
    { status },
  );
/** A request that never answers: as a browser's, it is rejected once its signal aborts. */
const held = (init?: RequestInit): Promise<Response> =>
  new Promise((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
  });
/** The keys the last profile sent gave `action`. */
const keysOf = (calls: readonly Call[], action: string): string | undefined =>
  (
    [...calls].reverse().find((c) => c.body !== undefined)?.body as
      { bindings: Binding[] } | undefined
  )?.bindings.find((b) => b.action === action)?.keys;
const stored = (key: string): unknown => JSON.parse(window.localStorage.getItem(key) ?? "null");
const polite = (): Element | null => document.querySelector('[aria-live="polite"] p');

/** A completed bootstrap, as `runBootstrap` applies it: the claims, `/me`, the `/me/keymap` answer, then ready. */
function signIn(id: string, role: Role, keymap: Keymap | "failed" = { bindings: [] }): void {
  const permissions = role === "viewer" ? ["settings:read"] : ["settings:read", "settings:write"];
  act(() => {
    m.setMeClaims({ authenticated: true, role, permissions });
    m.setShellState({
      me: {
        accounts: [],
        permissions,
        role,
        user: { id, email: `${id}@example.test`, username: id, roles: [role], status: "active" },
      },
    });
    m.setShellState(
      keymap === "failed"
        ? { keymapWarning: "Keymap failed to load; hotkeys are unavailable." }
        : { keymap, keymapWarning: null },
    );
    m.setShellState({ bootstrap: { kind: "ready" } });
  });
}
/** The sync, switched on as `KeymapHost` does, with a handle on its store. */
function startSync() {
  const store = m.httpProfileStore();
  const stop = m.startProfileSync(store);
  stops.push(stop);
  return { store, stop };
}
const rebind = (id: string, key: string): void =>
  act(() => m.setBindings(new Map(m.getBindings()).set(id, key)));
const footprintRow = () =>
  within(screen.getByRole("table", { name: "Chart" })).getByRole("row", {
    name: /^Toggle footprint/,
  });

describe("BQ-9: at sign-in the server wins for settings:write, unless this device holds a change it has not acknowledged", () => {
  const remapped: Keymap = {
    hotkey_profile_id: "17000000-0000-4000-8000-000000000009",
    bindings: [
      { action: "chart.footprint_toggle", keys: "Ctrl+Alt+F", scope: "chart" },
      // a bare key acknowledged on another device (E49-S07): the import rules return it to its default
      { action: "dom.cancel_all", keys: "Del", scope: "dom", requires_arm: false, confirm: true },
    ],
  };

  it("the server's profile, from the /me/keymap the shell read, is applied by an import's rules and kept, not sent back and not audited", async () => {
    const server = stubServer();
    const audited = vi.fn();
    m.setAuditSink(audited);
    signIn("u-1", "owner", remapped);
    const { store } = startSync();
    await store.flush();
    expect(m.getBindings().get("chart.footprint_toggle")).toBe("Ctrl+Alt+F");
    expect(m.getBindings().get("dom.cancel_all")).toBe("Ctrl+Shift+X"); // no acknowledgement carries over
    expect(stored(`${DEVICE}:u-1`)).toEqual({ "chart.footprint_toggle": "Ctrl+Alt+F" });
    expect([server.calls, audited.mock.calls]).toEqual([[], []]);
    expect(store.unsent("u-1")).toBe(false);
  });

  it("a change the server has not acknowledged survives a reload and wins the next sign-in: it is sent, the server's is not applied", async () => {
    const server = stubServer();
    server.refuse = () => problem(503, "store_unavailable");
    signIn("u-1", "owner");
    startSync();
    rebind("chart.footprint_toggle", "Alt+Q");
    await vi.advanceTimersByTimeAsync(0);
    expect(m.httpProfileStore().unsent("u-1")).toBe(true); // durable, per user
    await reload(); // the next page: its queue in memory is gone, the mark is not
    server.refuse = noRefusal;
    server.calls.length = 0;
    signIn("u-1", "owner", remapped);
    const { store } = startSync();
    await store.flush();
    expect(m.getBindings().get("chart.footprint_toggle")).toBe("Alt+Q");
    expect(lines(server.calls)).toEqual([
      `GET ${VIEW_AS}`,
      `GET ${PROFILES}`,
      `POST ${PROFILES}`,
      `POST ${PROFILES}/${server.rows[0]?.id}/activate`,
    ]);
    expect(keysOf(server.calls, "chart.footprint_toggle")).toBe("Alt+Q");
    expect(store.unsent("u-1")).toBe(false); // acknowledged: the next sign-in is the server's again
  });

  it("the mark is per user: another user's unacknowledged change never makes this user's device win", async () => {
    window.localStorage.setItem(`${UNSENT}:u-2`, "{}");
    const server = stubServer();
    signIn("u-1", "owner", remapped);
    const { store } = startSync();
    await store.flush();
    expect(m.getBindings().get("chart.footprint_toggle")).toBe("Ctrl+Alt+F");
    expect(server.calls).toEqual([]);
  });

  it("a failed /me/keymap says nothing: the device keeps its profile and nothing is sent", async () => {
    window.localStorage.setItem(
      `${DEVICE}:u-1`,
      JSON.stringify({ "chart.footprint_toggle": "Alt+Q" }),
    );
    const server = stubServer();
    signIn("u-1", "owner", "failed");
    const { store } = startSync();
    await store.flush();
    expect(m.getBindings().get("chart.footprint_toggle")).toBe("Alt+Q");
    expect(server.calls).toEqual([]);
  });

  it("an answer naming no active profile leaves the device's own profile in place, and sends nothing", async () => {
    window.localStorage.setItem(
      `${DEVICE}:u-1`,
      JSON.stringify({ "chart.footprint_toggle": "Alt+Q" }),
    );
    const server = stubServer();
    signIn("u-1", "owner", { bindings: [] });
    const { store } = startSync();
    await store.flush();
    expect(m.getBindings().get("chart.footprint_toggle")).toBe("Alt+Q");
    expect(server.calls).toEqual([]);
  });

  it("each sign-in is taken once: a remount of the host does not apply the same answer over a later change", async () => {
    stubServer();
    signIn("u-1", "owner", remapped);
    const first = startSync();
    first.stop();
    rebind("chart.footprint_toggle", "Alt+W");
    await first.store.flush();
    const again = startSync();
    await again.store.flush();
    expect(m.getBindings().get("chart.footprint_toggle")).toBe("Alt+W");
  });

  it("a later bootstrap is another sign-in: its answer is taken", async () => {
    stubServer();
    signIn("u-1", "owner");
    const { store } = startSync();
    await store.flush();
    signIn("u-1", "owner", remapped);
    await store.flush();
    expect(m.getBindings().get("chart.footprint_toggle")).toBe("Ctrl+Alt+F");
  });
});

describe("flush: on a change, on online and at sign-in; the last write wins, with no If-Match", () => {
  it("on a change: the whole profile replaces the active one, and no request carries If-Match", async () => {
    const server = stubServer();
    signIn("u-1", "owner");
    const { store } = startSync();
    rebind("chart.footprint_toggle", "Alt+Q");
    await store.flush();
    rebind("chart.footprint_toggle", "Alt+W");
    await store.flush();
    const id = server.rows[0]?.id;
    expect(lines(server.calls)).toEqual([
      `GET ${VIEW_AS}`,
      `GET ${PROFILES}`,
      `POST ${PROFILES}`,
      `POST ${PROFILES}/${id}/activate`,
      `GET ${PROFILES}`,
      `PUT ${PROFILES}/${id}`,
    ]);
    expect(server.calls.map((c) => c.ifMatch)).toEqual(server.calls.map(() => null));
    expect(server.rows.map((r) => [r.isActive, r.version])).toEqual([[true, 2]]);
  });

  it("with no active profile, the one the server holds under the default's name in another case is replaced and activated, never created again", async () => {
    const server = stubServer();
    const id = "17000000-0000-4000-8000-000000000001";
    server.rows.push({
      id,
      name: "CANDLEVIEWER DEFAULT",
      isActive: false,
      version: 1,
      bindings: [],
    });
    signIn("u-1", "owner");
    const { store } = startSync();
    rebind("chart.footprint_toggle", "Alt+Q");
    await store.flush();
    expect(lines(server.calls)).toEqual([
      `GET ${VIEW_AS}`,
      `GET ${PROFILES}`,
      `PUT ${PROFILES}/${id}`,
      `POST ${PROFILES}/${id}/activate`,
    ]);
    expect(server.rows.map((r) => [r.name, r.isActive, r.version])).toEqual([
      ["CANDLEVIEWER DEFAULT", true, 2],
    ]);
    expect([keysOf(server.calls, "chart.footprint_toggle"), store.unsent("u-1")]).toEqual([
      "Alt+Q",
      false,
    ]);
  });

  it("on online: a change a transient failure kept is sent, the latest one only", async () => {
    const server = stubServer();
    server.refuse = () => problem(503, "store_unavailable");
    signIn("u-1", "owner");
    const { store } = startSync();
    rebind("chart.footprint_toggle", "Alt+Q");
    await store.flush();
    rebind("chart.footprint_toggle", "Alt+W"); // refused too: kept, in place of the first
    await store.flush();
    server.refuse = noRefusal;
    act(() => void window.dispatchEvent(new Event("online")));
    await store.flush();
    expect(server.rows[0]?.bindings.find((b) => b.action === "chart.footprint_toggle")?.keys).toBe(
      "Alt+W",
    );
    expect(store.unsent("u-1")).toBe(false);
  });

  it("at sign-in: what this page still holds for the user is sent when they sign in again", async () => {
    const server = stubServer();
    server.refuse = () => problem(503, "store_unavailable");
    signIn("u-1", "owner");
    const { store } = startSync();
    rebind("chart.footprint_toggle", "Alt+Q");
    await store.flush();
    server.refuse = noRefusal;
    signIn("u-1", "owner");
    await store.flush();
    expect(keysOf(server.calls, "chart.footprint_toggle")).toBe("Alt+Q");
    expect(server.rows.map((r) => r.isActive)).toEqual([true]);
  });

  it("once stopped, online flushes nothing", async () => {
    const server = stubServer();
    server.refuse = () => problem(503, "store_unavailable");
    signIn("u-1", "owner");
    const { store, stop } = startSync();
    rebind("chart.footprint_toggle", "Alt+Q");
    await store.flush();
    const sent = server.calls.length;
    stop();
    act(() => void window.dispatchEvent(new Event("online")));
    await vi.advanceTimersByTimeAsync(0);
    expect(server.calls).toHaveLength(sent);
  });

  it("KeymapHost switches the sync on: the sign-in's profile applies on mount, and online flushes", async () => {
    const server = stubServer();
    server.refuse = () => problem(503, "store_unavailable");
    signIn("u-1", "owner", {
      hotkey_profile_id: "17000000-0000-4000-8000-000000000009",
      bindings: [{ action: "chart.footprint_toggle", keys: "Ctrl+Alt+F", scope: "chart" }],
    });
    const { unmount } = render(
      <>
        <m.KeymapHost />
        <m.Cheatsheet />
      </>,
    );
    expect(footprintRow()).toHaveTextContent("Ctrl+Alt+F");
    rebind("chart.footprint_toggle", "Alt+Q");
    await vi.advanceTimersByTimeAsync(0);
    server.refuse = noRefusal;
    await act(async () => {
      window.dispatchEvent(new Event("online"));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(server.rows.map((r) => r.isActive)).toEqual([true]);
    unmount();
  });
});

describe("BQ-5: a refusal is parked, retried or re-synced by its class", () => {
  /**
   * An Owner's sync with the shell announcer mounted, and one change (`Alt+Q`) sent to a server that answers `first`
   * once. With `always`, it answers `first` to every send of that same profile, as a server refusing a body does.
   */
  async function refusedOnce(first: () => Response, always = false) {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const server = stubServer();
    let answered = false;
    server.refuse = (method, _url, init) => {
      if (method === "GET") return undefined;
      const body = init?.body ? (JSON.parse(String(init.body)) as { bindings: Binding[] }) : null;
      const same =
        body?.bindings.find((b) => b.action === "chart.footprint_toggle")?.keys === "Alt+Q";
      if (answered && !(always && same)) return undefined;
      answered = true;
      return first();
    };
    render(<m.ShellAnnouncer />);
    signIn("u-1", "owner");
    const { store } = startSync();
    rebind("chart.footprint_toggle", "Alt+Q");
    await act(() => store.flush());
    return { server, store, warn };
  }

  it.each([
    ["413 payload_too_large", () => problem(413, "payload_too_large")],
    [
      "422 validation_failed, invalid_keys",
      () => problem(422, "validation_failed", "invalid_keys"),
    ],
    [
      "422 validation_failed, unknown_action",
      () => problem(422, "validation_failed", "unknown_action"),
    ],
    ["409 conflict, binding_conflict", () => problem(409, "conflict", "binding_conflict")],
    ["409 conflict, limit_reached", () => problem(409, "conflict", "limit_reached")],
  ])(
    "%s refuses the profile itself: parked, said once, and a later change still syncs",
    async (_what, answer) => {
      const { server, store, warn } = await refusedOnce(answer, true); // refused every time it is sent
      const status = answer().status;
      expect(stored(`${DEAD}:u-1`)).toMatchObject({ status });
      expect(polite()).toHaveTextContent(NOTE);
      expect(polite()?.getAttribute("data-seq")).toBe("1");
      expect(warn).toHaveBeenCalledTimes(1);
      expect(store.unsent("u-1")).toBe(false); // parked: it leaves the queue, as an audit record does
      expect(m.getBindings().get("chart.footprint_toggle")).toBe("Alt+Q"); // still on this device
      const before = server.calls.length;
      await act(() => store.flush()); // a parked profile is never sent again
      expect(server.calls).toHaveLength(before);
      expect(polite()?.getAttribute("data-seq")).toBe("1"); // nor said again
      rebind("chart.footprint_toggle", "Alt+W");
      await act(() => store.flush());
      expect(server.calls.length).toBeGreaterThan(before);
      expect(
        server.rows
          .find((r) => r.isActive)
          ?.bindings.find((b) => b.action === "chart.footprint_toggle")?.keys,
      ).toBe("Alt+W");
      expect(polite()?.getAttribute("data-seq")).toBe("1"); // said once, not again
    },
  );

  it("403 forbidden refuses the role: parked, said once, and nothing more is sent this session", async () => {
    const { server, store } = await refusedOnce(() => problem(403, "forbidden"));
    expect(polite()).toHaveTextContent(NOTE);
    const sent = server.calls.length;
    rebind("chart.footprint_toggle", "Alt+W");
    await store.flush();
    act(() => void window.dispatchEvent(new Event("online")));
    await store.flush();
    expect(server.calls).toHaveLength(sent);
    expect(store.unsent("u-1")).toBe(true); // the later change is kept on the device for the next sign-in
  });

  it.each([
    ["500", () => new Response("boom", { status: 500 })],
    ["503 store_unavailable", () => problem(503, "store_unavailable")],
    ["503 audit_unavailable", () => problem(503, "audit_unavailable")],
    ["401 session_idle_locked", () => problem(401, "session_idle_locked")],
    ["403 csrf_token_invalid", () => problem(403, "csrf_token_invalid")],
    ["403 session_read_only", () => problem(403, "session_read_only")],
    ["403 with no readable body", () => new Response("<html>403</html>", { status: 403 })],
    ["408", () => new Response(null, { status: 408 })],
    ["a bare 429, with no problem code", () => new Response(null, { status: 429 })],
    ["429 rate_limited", () => problem(429, "rate_limited")],
    ["409 idempotency_in_flight, a retryable code", () => problem(409, "idempotency_in_flight")],
    [
      "a network error",
      () => {
        throw new TypeError("Failed to fetch");
      },
    ],
  ])(
    "%s is transient: kept, nothing parked or said, and sent in order at the next flush",
    async (_what, answer) => {
      const { server, store, warn } = await refusedOnce(answer);
      expect([stored(`${DEAD}:u-1`), polite(), warn.mock.calls.length]).toEqual([null, null, 0]);
      expect(store.unsent("u-1")).toBe(true);
      await store.flush();
      expect(server.rows.map((r) => r.isActive)).toEqual([true]);
      expect(store.unsent("u-1")).toBe(false);
    },
  );

  it("a 401 the token's renewal cannot cure is transient too", async () => {
    const { server, store } = await refusedOnce(() => problem(401, "unauthenticated"));
    expect(lines(server.calls)).toContain("POST /api/v1/auth/refresh"); // one renewal, answered by the stub's 404
    expect([stored(`${DEAD}:u-1`), store.unsent("u-1")]).toEqual([null, true]);
  });

  const KEPT = "17000000-0000-4000-8000-000000000001";
  /** The server's state when the client lists, and what happened there before the request `on` was answered. */
  it.each<[string, string, () => Response, (rows: Row[]) => void]>([
    [
      "404 on the replace: the profile went",
      "PUT",
      () => problem(404, "not_found"),
      (rows) => void (rows.length = 0),
    ],
    [
      "412 on the replace: another version",
      "PUT",
      () => problem(412, "version_conflict"),
      () => undefined,
    ],
    [
      "404 on the activation: the profile went",
      "ACTIVATE",
      () => problem(404, "not_found"),
      (rows) => void (rows.length = 0),
    ],
    [
      "409 name_taken on the create: another device made it",
      "POST",
      () => problem(409, "conflict", "name_taken"),
      (rows) =>
        void rows.push({
          id: KEPT,
          name: "candleviewer default",
          isActive: false,
          version: 1,
          bindings: [],
        }),
    ],
  ])(
    "%s re-syncs: lists again and replaces or recreates, never parked or said",
    async (_what, on, answer, meanwhile) => {
      const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
      const server = stubServer();
      if (on !== "POST")
        server.rows.push({
          id: KEPT,
          name: "CandleViewer Default",
          isActive: on === "PUT",
          version: 1,
          bindings: [],
        });
      let answered = false;
      server.refuse = (method, url) => {
        const which = url.endsWith("/activate") ? "ACTIVATE" : method;
        if (answered || which !== on) return undefined;
        answered = true;
        meanwhile(server.rows);
        return answer();
      };
      render(<m.ShellAnnouncer />);
      signIn("u-1", "owner");
      const { store } = startSync();
      rebind("chart.footprint_toggle", "Alt+Q");
      await act(() => store.flush());
      expect(lines(server.calls).filter((l) => l === `GET ${PROFILES}`)).toHaveLength(2); // listed again once
      expect(server.rows.filter((r) => r.isActive)).toHaveLength(1);
      expect(keysOf(server.calls, "chart.footprint_toggle")).toBe("Alt+Q");
      expect([
        stored(`${DEAD}:u-1`),
        polite(),
        warn.mock.calls.length,
        store.unsent("u-1"),
      ]).toEqual([null, null, 0, false]);
    },
  );

  it("a server that stays out of sync is listed again twice in a pass, then the change waits, never parked", async () => {
    const server = stubServer();
    server.rows.push({
      id: "17000000-0000-4000-8000-000000000001",
      name: "CandleViewer Default",
      isActive: true,
      version: 1,
      bindings: [],
    });
    server.refuse = (method) => (method === "PUT" ? problem(404, "not_found") : undefined);
    signIn("u-1", "owner");
    const { store } = startSync();
    rebind("chart.footprint_toggle", "Alt+Q");
    await store.flush();
    expect(lines(server.calls).filter((l) => l.startsWith("PUT"))).toHaveLength(3);
    expect([stored(`${DEAD}:u-1`), store.unsent("u-1")]).toEqual([null, true]);
  });
});

describe("BQ-15, SEC-305C-03: the store's requests abort at sign-out and on a change of user", () => {
  /** An Owner's change on its way, the list request held on the wire. */
  async function onTheWire() {
    const server = stubServer();
    server.refuse = (method, url, init) =>
      method === "GET" && url === PROFILES ? held(init) : undefined;
    signIn("u-1", "owner");
    const { store } = startSync();
    rebind("chart.footprint_toggle", "Alt+Q");
    await vi.advanceTimersByTimeAsync(0);
    expect(lines(server.calls)).toEqual([`GET ${VIEW_AS}`, `GET ${PROFILES}`]);
    server.refuse = noRefusal;
    return { server, store };
  }

  it("a sign-out aborts the request on the wire, and nothing more goes this session; the next sign-in sends it", async () => {
    const { server, store } = await onTheWire();
    act(() => m.accessToken.clear()); // a logout's 2xx, a lost session or a sibling tab's sign-out
    await store.flush();
    act(() => void window.dispatchEvent(new Event("online")));
    rebind("chart.footprint_toggle", "Alt+W");
    await store.flush();
    expect(server.calls).toHaveLength(2);
    expect(store.unsent("u-1")).toBe(true);
    await reload();
    signIn("u-1", "owner");
    await startSync().store.flush();
    expect(keysOf(server.calls, "chart.footprint_toggle")).toBe("Alt+W");
  });

  it("a change of user aborts the last user's request on the wire; theirs is never sent under the next user's session", async () => {
    const { server, store } = await onTheWire();
    signIn("u-2", "owner");
    await store.flush();
    expect(server.calls).toHaveLength(2); // u-2 holds no change: nothing goes
    signIn("u-1", "owner"); // u-1 is back: their change goes under their own session
    await store.flush();
    expect(keysOf(server.calls, "chart.footprint_toggle")).toBe("Alt+Q");
  });
});

describe("A55: a Viewer stays on the device", () => {
  it("Scenario: A Viewer stays on the device: the remap applies here and no request reaches /settings/hotkeys", async () => {
    const server = stubServer();
    signIn("u-viewer", "viewer", {
      hotkey_profile_id: "17000000-0000-4000-8000-000000000009",
      bindings: [{ action: "chart.footprint_toggle", keys: "Ctrl+Alt+F", scope: "chart" }],
    });
    const { store } = startSync();
    render(<m.Cheatsheet />);
    expect(footprintRow()).toHaveTextContent(/^Toggle footprintF$/); // a server profile is never applied (A55)
    rebind("chart.footprint_toggle", "Alt+Q"); // as the editor's Save lands it
    expect(footprintRow()).toHaveTextContent("Alt+Q");
    await store.flush();
    act(() => void window.dispatchEvent(new Event("online")));
    await store.flush();
    expect(await store.read()).toBeNull();
    expect(server.calls).toEqual([]);
    expect([stored(`${DEVICE}:u-viewer`), store.unsent("u-viewer")]).toEqual([
      { "chart.footprint_toggle": "Alt+Q" },
      false,
    ]);
  });

  it("a Viewer's sign-in sends nothing, even with a change a role they held before left unacknowledged", async () => {
    window.localStorage.setItem(
      `${UNSENT}:u-1`,
      JSON.stringify({ "chart.footprint_toggle": "Alt+Q" }),
    );
    const server = stubServer();
    signIn("u-1", "viewer");
    await startSync().store.flush();
    expect(server.calls).toEqual([]);
  });
});

describe("BQ-14: nothing is sent while a view is live", () => {
  const context = (state: "active" | "expired") =>
    Response.json({
      target_user_id: "u-target",
      target_username: "target",
      target_display_name: null,
      started_at: "2026-10-31T10:00:00Z",
      expires_at: "2026-10-31T10:30:00Z",
      read_only: true,
      state,
    });

  it.each(["active", "expired"] as const)(
    "a session viewing as another user (%s) sends no write: the change stays on the device and is never queued for the target",
    async (state) => {
      const server = stubServer();
      server.view = () => context(state);
      signIn("u-target", "manager"); // `/me` names the target while the view is live
      const { store } = startSync();
      rebind("chart.footprint_toggle", "Alt+Q");
      rebind("chart.footprint_toggle", "Alt+W"); // both queued before the context is read
      await store.flush();
      rebind("chart.footprint_toggle", "Alt+E"); // once it is read, never queued
      await store.flush();
      act(() => void window.dispatchEvent(new Event("online")));
      await store.flush();
      expect(lines(server.calls)).toEqual([`GET ${VIEW_AS}`]); // read once; nothing reaches /settings/hotkeys
      expect(store.unsent("u-target")).toBe(false); // the target's own next sign-in sends none of it
      expect(m.getBindings().get("chart.footprint_toggle")).toBe("Alt+E");
    },
  );

  it("a view the server reports (403 view_as_read_only) stops this session's sends; the change waits for the next sign-in", async () => {
    const server = stubServer();
    server.refuse = (method) => (method === "GET" ? undefined : problem(403, "view_as_read_only"));
    signIn("u-1", "owner");
    const { store } = startSync();
    rebind("chart.footprint_toggle", "Alt+Q");
    await store.flush();
    const sent = server.calls.length;
    rebind("chart.footprint_toggle", "Alt+W");
    await store.flush();
    expect(server.calls).toHaveLength(sent);
    expect(store.unsent("u-1")).toBe(true);
  });

  it("an unreadable view-as answer sends no write yet: the next flush asks again", async () => {
    const server = stubServer();
    let down = true;
    server.view = () =>
      down ? problem(503, "store_unavailable") : new Response(null, { status: 204 });
    signIn("u-1", "owner");
    const { store } = startSync();
    rebind("chart.footprint_toggle", "Alt+Q");
    await store.flush();
    expect(lines(server.calls)).toEqual([`GET ${VIEW_AS}`]);
    down = false;
    await store.flush();
    expect(keysOf(server.calls, "chart.footprint_toggle")).toBe("Alt+Q");
  });
});

describe("E10-T05's acceptance criteria, client side", () => {
  it("Scenario: A profile follows its owner to another device: read once at sign-in, applied by the import rules, no acknowledgement carried over", async () => {
    const server = stubServer();
    signIn("u-1", "owner"); // the first device
    const first = startSync();
    rebind("chart.footprint_toggle", "Ctrl+Alt+F");
    rebind("dom.cancel_all", "Del"); // a bare key E49-S07's acknowledgement allowed on this device
    await first.store.flush();
    expect(server.keymap().bindings?.find((b) => b.action === "dom.cancel_all")?.keys).toBe("Del");
    window.localStorage.clear(); // the second device holds nothing of theirs
    await reload();
    server.calls.length = 0;
    signIn("u-1", "owner", server.keymap()); // its bootstrap's /me/keymap is the read
    const second = startSync();
    render(<m.Cheatsheet />);
    await second.store.flush();
    expect(footprintRow()).toHaveTextContent("Ctrl+Alt+F");
    const cancelAll = within(screen.getByRole("table", { name: "DOM" })).getByRole("row", {
      name: /^Cancel all working orders for symbol/,
    });
    expect(cancelAll).toHaveTextContent("Ctrl+Shift+X");
    expect(server.calls).toEqual([]); // read once, by the shell; nothing sent back
  });

  it("Scenario: A refusal never stalls the client: parked and said once, later changes still sync, a transient failure retries in order", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const server = stubServer();
    let refusal: Response | null = problem(422, "validation_failed", "shape_mismatch");
    server.refuse = (method) => {
      if (method === "GET" || refusal === null) return undefined;
      const answer = refusal;
      refusal = null;
      return answer;
    };
    render(<m.ShellAnnouncer />);
    signIn("u-1", "owner");
    const { store } = startSync();
    rebind("chart.footprint_toggle", "Alt+Q");
    await act(() => store.flush());
    expect(polite()).toHaveTextContent(NOTE);
    rebind("chart.footprint_toggle", "Alt+W"); // a later change syncs
    await act(() => store.flush());
    const active = () => server.rows.find((r) => r.isActive);
    expect(active()?.bindings.find((b) => b.action === "chart.footprint_toggle")?.keys).toBe(
      "Alt+W",
    );
    refusal = problem(503, "store_unavailable");
    rebind("chart.footprint_toggle", "Alt+E");
    await act(() => store.flush()); // transient: kept
    rebind("chart.footprint_toggle", "Alt+R"); // the latest replaces it in the queue
    await act(() => store.flush());
    expect(active()?.bindings.find((b) => b.action === "chart.footprint_toggle")?.keys).toBe(
      "Alt+R",
    );
    expect(polite()?.getAttribute("data-seq")).toBe("1"); // said once
  });

  it("Scenario: Another user's profile does not exist, client side: the client names only ids its own list gave, and a 404 re-syncs", async () => {
    const server = stubServer();
    signIn("u-1", "owner");
    const { store } = startSync();
    rebind("chart.footprint_toggle", "Alt+Q");
    await store.flush();
    const first = server.rows[0]?.id;
    server.refuse = (method) => {
      if (method !== "PUT") return undefined;
      server.rows.length = 0; // the id is gone: 404, as another user's id answers, never 403
      return problem(404, "not_found");
    };
    rebind("chart.footprint_toggle", "Alt+W");
    await store.flush();
    expect(lines(server.calls).slice(4)).toEqual([
      `GET ${PROFILES}`,
      `PUT ${PROFILES}/${first}`,
      `GET ${PROFILES}`,
      `POST ${PROFILES}`,
      `POST ${PROFILES}/${server.rows[0]?.id}/activate`,
    ]);
    const named = server.calls.flatMap((c) => /hotkeys\/([^/]+)/.exec(c.url)?.slice(1) ?? []);
    expect(new Set(named)).toEqual(new Set([first, server.rows[0]?.id]));
    expect([stored(`${DEAD}:u-1`), store.unsent("u-1")]).toEqual([null, false]);
  });

  it("Scenario: The client's own default profile is accepted, client side: every command is sent at its default, non-chord shapes and locked commands as they are", async () => {
    const server = stubServer();
    signIn("u-1", "owner");
    const { store } = startSync();
    rebind("chart.footprint_toggle", "Alt+Q");
    act(() => m.resetBindings());
    await store.flush();
    const sent = (server.calls.at(-2)?.body as { name: string; bindings: Binding[] }).bindings;
    expect(Object.fromEntries(sent.map((b) => [b.action, b.keys]))).toEqual(
      Object.fromEntries([...m.getBindings()]),
    );
    expect(sent.find((b) => b.action === "global.palette")?.keys).toBe("Ctrl+K");
    expect(new Set(sent.flatMap((b) => Object.keys(b)))).toEqual(
      new Set(["action", "keys", "scope", "requires_arm", "confirm"]), // no member the closed schema refuses
    );
  });

  it("Scenario: The server keeps the arm on an order submit, client side: the five go out armed, and no answer clears the arm here", async () => {
    const server = stubServer();
    server.rewritten = "ticket.submit"; // as if the server had rewritten one: an acknowledgement all the same
    signIn("u-1", "owner", {
      hotkey_profile_id: "17000000-0000-4000-8000-000000000009",
      bindings: [
        {
          action: "ticket.submit",
          keys: "Ctrl+Enter",
          scope: "ticket",
          requires_arm: false,
          confirm: false,
        },
      ],
    });
    const { store } = startSync();
    rebind("chart.footprint_toggle", "Alt+Q");
    await store.flush();
    const sent = (
      server.calls.find((c) => c.method === "PUT" || c.method === "POST")?.body as {
        bindings: Binding[];
      }
    ).bindings;
    expect(
      sent
        .filter((b) => b.requires_arm === true)
        .map((b) => b.action)
        .sort(),
    ).toEqual([
      "chart.limit_at_price",
      "chart.market_order",
      "dom.market_click",
      "dom.stop_click",
      "ticket.submit",
    ]);
    // the profile `/me/keymap` answered with `requires_arm: false` changed no arm: the gate reads the keymap
    expect(store.unsent("u-1")).toBe(false);
    expect(m.commandMeta("ticket.submit")?.requiresArm).toBe(true);
    const ran = vi.fn();
    const off = m.registerCommand("ticket.submit", ran);
    expect(m.runCommand("ticket.submit")).toBe(false); // unarmed: inert, never a second prompt
    off();
  });
});
