import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { generated } from "@candleviewer/protocol";
import { DANGEROUS_COMMANDS, KEYMAP } from "../src/keymap/keymap";
import type { TokenBundle } from "../src/lib/auth/accessToken";
import type { Role } from "../src/routes/rbac";

/**
 * #305 (E10-S02) PR C, the profile store's client half (BQ-1, A55). The device store (PR B) stays the active one; the
 * HTTP adapter is written against `22`'s `/settings/hotkeys` as it stands and is wired off until a server exists, so
 * nothing is sent. Switched on, a change is queued only for a session holding `settings:write`, as the whole profile
 * in `22`'s shape, and only under its own user's session. A profile read from the server is checked by an import's
 * rules, so no acknowledgement made elsewhere carries over (CR-305BD-04's server path). Each test loads its own copy.
 */
type ProfileInput = generated.rest.components["schemas"]["HotkeyProfileInput"];
const load = async () => ({
  ...(await import("../src/keymap/profileStore")),
  ...(await import("../src/keymap/profile")),
  ...(await import("../src/keymap/validate")),
  ...(await import("../src/lib/auth/accessToken")),
  ...(await import("../src/lib/auth/meCache")),
  ...(await import("../src/shell/bootstrap/store")),
});
let m: Awaited<ReturnType<typeof load>>;

beforeEach(async () => {
  window.localStorage.clear();
  vi.resetModules();
  m = await load();
});
afterEach(() => {
  m.accessToken.clear(); // a token held by a test would leave its refresh timer behind
  vi.unstubAllGlobals();
});

const PROFILES = "/api/v1/settings/hotkeys";
const FORCED = [
  "chart.limit_at_price",
  "chart.market_order",
  "dom.market_click",
  "dom.stop_click",
  "ticket.submit",
];

/** The rows of `22`'s `HotkeyBinding.scope` table, (`keymap.json` context, `scope`), read from the contract itself. */
function scopeTable(): readonly (readonly [string, string])[] {
  const spec = readFileSync(
    resolve(import.meta.dirname, "../../../docs/plan/22-api-openapi.yaml"),
    "utf8",
  );
  const at = spec.indexOf("\n    HotkeyBinding:\n");
  expect(at, "22 names HotkeyBinding").toBeGreaterThan(-1);
  const schema = spec.slice(at + 1);
  const next = schema.slice(1).search(/\n {4}\S/); // the next schema, one level out
  const block = next === -1 ? schema : schema.slice(0, next + 1);
  return [...block.matchAll(/^ +\| `(\w+)` +\| `(\w+)` +\|$/gm)].map(
    (row) => [row[1] ?? "", row[2] ?? ""] as const,
  );
}

function signIn(id: string, role: Role): void {
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
  });
}

interface Call {
  readonly method: string;
  readonly url: string;
  readonly body: unknown;
  /** The `Authorization` the request went out under, if any. */
  readonly auth: string | null;
}
/**
 * Every request, in order; `answer` replies to each by method and path (default: none kept, so create). As `fetch`
 * does, a request whose signal is already aborted is rejected and never reaches the server.
 */
function stubServer(
  answer: (method: string, url: string) => Response = (method, url) =>
    method === "GET" && url === PROFILES
      ? Response.json({ items: [] })
      : method === "POST" && url === PROFILES
        ? Response.json({ id: "p-1", name: "CandleViewer Default", bindings: [] }, { status: 201 })
        : Response.json({}),
): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      init?.signal?.throwIfAborted();
      const method = init?.method ?? "GET";
      const url = String(input);
      calls.push({
        method,
        url,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
        auth: new Headers(init?.headers).get("Authorization"),
      });
      return answer(method, url);
    }),
  );
  return calls;
}
const lines = (calls: readonly Call[]): string[] => calls.map((c) => `${c.method} ${c.url}`);
const rebind = (id: string, key: string): void =>
  act(() => m.setBindings(new Map(m.getBindings()).set(id, key)));

describe("wired off: the device store stays the active one and nothing is sent", () => {
  it("an Owner's change is kept on the device and no request reaches /settings/hotkeys", async () => {
    const calls = stubServer();
    signIn("u-1", "owner");
    rebind("chart.footprint_toggle", "Alt+Q");
    await act(async () => {
      await Promise.resolve();
    });
    expect(calls).toEqual([]);
    const stored: unknown = JSON.parse(
      window.localStorage.getItem(`cv.keymap-profile.v1:u-1`) ?? "",
    );
    expect(stored).toEqual({ "chart.footprint_toggle": "Alt+Q" });
  });
});

describe("switched on: queued only with settings:write (A55), as the whole profile in 22's shape", () => {
  it("an Owner's first change creates the profile and makes it active; the next replaces it", async () => {
    const calls = stubServer();
    signIn("u-1", "owner");
    const store = m.httpProfileStore();
    m.setProfileStore(store);
    rebind("chart.footprint_toggle", "Alt+Q");
    await store.flush();
    expect(lines(calls)).toEqual([
      `GET ${PROFILES}`,
      `POST ${PROFILES}`,
      `POST ${PROFILES}/p-1/activate`,
    ]);
    const sent = calls[1]?.body as ProfileInput;
    expect(sent.name).toBe("CandleViewer Default");
    expect(sent.bindings.map((b) => b.action)).toEqual(KEYMAP.map((c) => c.id));
    expect(sent.bindings.find((b) => b.action === "chart.footprint_toggle")).toEqual({
      action: "chart.footprint_toggle",
      keys: "Alt+Q",
      scope: "chart",
      requires_arm: false,
      confirm: false,
    });
    // The scope follows the context by `22`'s table, never the id's prefix.
    expect(sent.bindings.find((b) => b.action === "global.auth.submit")?.scope).toBe("auth");
    expect(
      sent.bindings
        .filter((b) => b.requires_arm)
        .map((b) => b.action)
        .sort(),
    ).toEqual(FORCED);
    expect(
      sent.bindings
        .filter((b) => b.confirm)
        .map((b) => b.action)
        .sort(),
    ).toEqual([...DANGEROUS_COMMANDS].sort());
    const kept = stubServer((method, url) =>
      method === "GET" && url === PROFILES
        ? Response.json({
            items: [{ id: "p-1", name: "CandleViewer Default", is_active: true, bindings: [] }],
          })
        : Response.json({}),
    );
    rebind("chart.footprint_toggle", "Alt+W");
    await store.flush();
    expect(lines(kept)).toEqual([`GET ${PROFILES}`, `PUT ${PROFILES}/p-1`]);
    expect((kept[1]?.body as ProfileInput).name).toBe("CandleViewer Default");
  });

  it("21 §10.6's profile, kept but not active, is replaced, then made active; a refusal stays queued", async () => {
    const held = { id: "p-9", name: "CandleViewer Default", is_active: false, bindings: [] };
    let refuse = true;
    const calls = stubServer((method) =>
      method === "GET"
        ? Response.json({ items: [held] })
        : refuse
          ? Response.json({ code: "store_unavailable" }, { status: 503 })
          : Response.json({}),
    );
    signIn("u-1", "owner");
    const store = m.httpProfileStore();
    m.setProfileStore(store);
    rebind("chart.footprint_toggle", "Alt+Q");
    await store.flush();
    refuse = false;
    await store.flush();
    expect(lines(calls)).toEqual([
      `GET ${PROFILES}`,
      `PUT ${PROFILES}/p-9`,
      `GET ${PROFILES}`,
      `PUT ${PROFILES}/p-9`,
      `POST ${PROFILES}/p-9/activate`,
    ]);
  });

  it("a Viewer's change stays on the device and is never queued", async () => {
    const calls = stubServer();
    signIn("u-viewer", "viewer");
    const store = m.httpProfileStore();
    m.setProfileStore(store);
    rebind("chart.footprint_toggle", "Alt+Q");
    await store.flush();
    expect(calls).toEqual([]);
    expect(m.getBindings().get("chart.footprint_toggle")).toBe("Alt+Q");
  });

  it("a profile is sent only under its own user's session: a sign-out first holds it until they return", async () => {
    const calls = stubServer();
    signIn("u-1", "owner");
    const store = m.httpProfileStore();
    m.setProfileStore(store);
    rebind("chart.footprint_toggle", "Alt+Q");
    act(() => m.setShellState({ me: null }));
    await store.flush();
    signIn("u-2", "owner");
    await store.flush();
    expect(calls).toEqual([]);
    signIn("u-1", "owner");
    await store.flush();
    expect(lines(calls)).toContain(`POST ${PROFILES}`);
  });

  it.each([
    ["creates it", { items: [] }],
    [
      "replaces it",
      { items: [{ id: "p-1", name: "CandleViewer Default", is_active: true, bindings: [] }] },
    ],
  ])(
    "CR-305C-02, pin: a sign-out as the GET is answered stops the write that %s",
    async (_what, listing) => {
      const calls = stubServer((method) => {
        if (method !== "GET") return Response.json({ id: "p-1" }, { status: 201 });
        act(() => m.setShellState({ me: null })); // the session ends while the answer is on its way
        return Response.json(listing);
      });
      signIn("u-1", "owner");
      const store = m.httpProfileStore();
      m.setProfileStore(store);
      rebind("chart.footprint_toggle", "Alt+Q");
      await store.flush();
      expect(lines(calls)).toEqual([`GET ${PROFILES}`]);
    },
  );

  it("CR-305C-02, pin: every command is sent with the scope 22's table gives its context", async () => {
    const table = new Map(scopeTable());
    expect(table.size).toBe(11); // the eleven rows: the keymap has commands in nine, the contract pin holds the copy
    const calls = stubServer();
    signIn("u-1", "owner");
    const store = m.httpProfileStore();
    m.setProfileStore(store);
    rebind("chart.footprint_toggle", "Alt+Q");
    await store.flush();
    const sent = (calls[1]?.body as ProfileInput).bindings;
    expect(sent.map((b) => b.scope)).toEqual(KEYMAP.map((c) => table.get(c.context)));
  });

  it("CR-305C-04: a pass that throws leaves the queue usable, so the next flush sends what waits", async () => {
    const calls = stubServer();
    let unreadable = true;
    const store = m.httpProfileStore(undefined, () => {
      if (unreadable) throw new Error("session unreadable");
      return "u-1";
    });
    store.write("u-1", new Map([["chart.footprint_toggle", "Alt+Q"]]));
    await expect(store.flush()).rejects.toThrow("session unreadable");
    unreadable = false;
    await store.flush();
    expect(lines(calls)).toEqual([
      `GET ${PROFILES}`,
      `POST ${PROFILES}`,
      `POST ${PROFILES}/p-1/activate`,
    ]);
  });

  it("CR-305C-07: a store that throws never skips the UI: the listeners hear the change first, the caller never the throw", () => {
    signIn("u-1", "owner");
    const order: string[] = [];
    m.setProfileStore({
      read: () => Promise.resolve(null),
      write: () => {
        order.push("store");
        throw new Error("store down");
      },
      flush: () => Promise.resolve(),
    });
    m.subscribeBindings(() => order.push("ui"));
    expect(() => rebind("chart.footprint_toggle", "Alt+Q")).not.toThrow();
    expect(order).toEqual(["ui", "store"]);
    expect(m.getBindings().get("chart.footprint_toggle")).toBe("Alt+Q");
  });
});

describe("SEC-305C-03: the shared HTTP layer's repeat after a 401 never reaches another user's session", () => {
  /** A token made at run time, so no literal here looks like a credential. */
  const probe = (n: number): TokenBundle => ({
    access_token: ["probe", String(n), "x".repeat(20)].join("-"),
    token_type: "Bearer",
    expires_in: 600,
  });
  const bearer = (n: number): string => `Bearer ${probe(n).access_token}`;
  const held = (isActive: boolean) => ({
    items: [{ id: "p-1", name: "CandleViewer Default", is_active: isActive, bindings: [] }],
  });
  const LIST = `GET ${PROFILES}`;

  it.each([
    ["listing", { items: [] }, [LIST]],
    ["create", { items: [] }, [LIST, `POST ${PROFILES}`]],
    ["replace", held(true), [LIST, `PUT ${PROFILES}/p-1`]],
    ["activation", held(false), [LIST, `PUT ${PROFILES}/p-1`, `POST ${PROFILES}/p-1/activate`]],
  ])(
    "a 401 on the %s, answered as another user signs in, is not repeated under their session",
    async (_what, listing, sent) => {
      signIn("u-1", "owner");
      m.accessToken.set(probe(1));
      let refused = false;
      const calls = stubServer((method, url) => {
        if (`${method} ${url}` === sent.at(-1) && !refused) {
          refused = true;
          signIn("u-2", "owner"); // another user signs in while the 401 is on its way ...
          m.accessToken.set(probe(2)); // ... and the tab now holds their token, which a renewal repeats under
          return Response.json({ code: "unauthenticated" }, { status: 401 });
        }
        return method === "GET"
          ? Response.json(listing)
          : Response.json({ id: "p-1" }, { status: 201 });
      });
      const store = m.httpProfileStore();
      m.setProfileStore(store);
      rebind("chart.footprint_toggle", "Alt+Q");
      await store.flush();
      // Each request went out once, under u-1's session: the repeat, which carries the profile, never went out.
      expect(calls.map((c) => `${c.method} ${c.url} ${c.auth}`)).toEqual(
        sent.map((line) => `${line} ${bearer(1)}`),
      );
    },
  );

  it("pin: a change of user aborts the last session's requests only: the next user's are sent", async () => {
    const calls = stubServer();
    signIn("u-1", "owner");
    const store = m.httpProfileStore();
    m.setProfileStore(store);
    act(() => m.setShellState({ me: null }));
    signIn("u-2", "owner");
    rebind("chart.footprint_toggle", "Alt+Q");
    await store.flush();
    expect(lines(calls)).toEqual([
      `GET ${PROFILES}`,
      `POST ${PROFILES}`,
      `POST ${PROFILES}/p-1/activate`,
    ]);
  });
});

describe("read: the server's profile is checked by an import's rules, so no acknowledgement carries over", () => {
  const active = {
    id: "p-1",
    name: "CandleViewer Default",
    is_active: true,
    bindings: [
      { action: "ticket.submit", keys: "F2", scope: "ticket", requires_arm: true, confirm: true },
      { action: "dom.cancel_all", keys: "Del", scope: "dom", requires_arm: false, confirm: true },
      { action: "chart.footprint_toggle", keys: "Alt+Q", scope: "chart", requires_arm: true },
      { action: "order.flatten_all", keys: "Ctrl+Shift+F", scope: "global", requires_arm: false },
    ],
  };

  it("CR-305BD-04: a bare key acknowledged elsewhere returns to its default, reported as an import's", async () => {
    stubServer(() =>
      Response.json({ items: [{ ...active, id: "p-0", is_active: false, bindings: [] }, active] }),
    );
    signIn("u-1", "owner");
    const report = await m.httpProfileStore().read();
    expect(report?.applied.get("ticket.submit")).toBe("Ctrl+Enter");
    expect(report?.applied.get("dom.cancel_all")).toBe("Ctrl+Shift+X");
    expect(report?.applied.get("chart.footprint_toggle")).toBe("Alt+Q");
    expect(report?.rejected.map((r) => [r.commandId, r.problem.kind])).toEqual([
      ["ticket.submit", "unsafe-destructive"],
      ["dom.cancel_all", "unsafe-destructive"],
      ["order.flatten_all", "unknown-command"],
    ]);
    // The device's stored rules would have kept it: the server path is an import's, by design.
    expect(m.storedProfile({ "ticket.submit": "F2" }).applied.get("ticket.submit")).toBe("F2");
  });

  it("no active profile, an error answer or a network error reads as none", async () => {
    signIn("u-1", "owner");
    const answers: (() => Response)[] = [
      () => Response.json({ items: [{ ...active, is_active: false }] }),
      () => Response.json({ code: "store_unavailable" }, { status: 503 }),
      () => {
        throw new TypeError("Failed to fetch");
      },
    ];
    for (const answer of answers) {
      stubServer(answer);
      expect(await m.httpProfileStore().read()).toBeNull();
    }
  });

  it.each([
    ["another user signs in", () => signIn("u-2", "owner")],
    ["the user signs out", () => act(() => m.setShellState({ me: null }))],
  ])(
    "CR-305C-01: when %s during the GET, the profile it read is handed to no one",
    async (_what, change) => {
      signIn("u-1", "owner");
      stubServer(() => {
        change();
        return Response.json({ items: [active] });
      });
      expect(await m.httpProfileStore().read()).toBeNull();
    },
  );
});
