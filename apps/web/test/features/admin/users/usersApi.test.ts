/**
 * E42-S02 (#1023): the users client over the served routes (BQ-1, BQ-3, BQ-6). Reads go through the admin read
 * layer (a `403` is the area denied; `GET /users` answering `404`, `405` or `501` is not built). Writes go through
 * the admin write kit: one `Idempotency-Key` per attempt, none on a read or on the tier write (its route ignores
 * it); a write's first send is bounded (no answer in time is status 0); an invite asks for a viewer with two-factor
 * and never for account access; a disable and a delete carry the unknown-positions acknowledgement (D21: no position
 * source is wired), and a two-factor reset only when the owner gave it; a target that is not a served user id is
 * never sent. Nothing reaches browser storage, and the one-time link never reaches the console.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReadTimers } from "../../../../src/features/admin/overview/adminReads";
import {
  readGrants,
  readMfaPreview,
  readPendingInvites,
  readSessionCount,
  readUserPage,
  usersApi,
  WRITE_TIMEOUT_MS,
} from "../../../../src/features/admin/users/usersApi";
import { userIdOf, type UserId } from "../../../../src/features/admin/users/vet";

const TIMERS: ReadTimers = {
  setTimeout: (run, ms) => globalThis.setTimeout(run, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};
const ALEX = userIdOf("0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d") as UserId;
const UUID4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const json = (status: number, body: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const signal = (): AbortSignal => new AbortController().signal;
const USER = {
  id: ALEX,
  username: "alex",
  email: "alex@example.com",
  display_name: "Alex",
  roles: ["manager"],
  status: "active",
  mfa_enabled: true,
  last_login_at: "2026-11-01T09:00:00Z",
};
const PAGE = { items: [USER], meta: { count: 1, has_more: false, next_cursor: null } };

/** A server answering `answer` to everything, recording each call. */
function server(answer: (url: string, init: RequestInit) => Response) {
  const fetch = vi.fn(async (url: string, init: RequestInit = {}) => answer(url, init));
  vi.stubGlobal("fetch", fetch);
  return {
    fetch,
    call: (i = 0) => {
      const [url, init = {}] = fetch.mock.calls[i] as [string, RequestInit?];
      return { url, init, headers: new Headers(init.headers) };
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("reads", () => {
  it("lists a page of 50 with the role, status and q filters, and no idempotency header", async () => {
    const s = server(() => json(200, PAGE));
    const outcome = await readUserPage(
      { role: "manager", status: "active", q: "al" },
      undefined,
      signal(),
      TIMERS,
    );
    expect(outcome).toMatchObject({ kind: "ok", body: { items: [{ id: ALEX }], hasMore: false } });
    const { url, init, headers } = s.call();
    expect(url).toBe("/api/v1/users?limit=50&role=manager&status=active&q=al");
    expect(init.method ?? "GET").toBe("GET");
    expect(headers.has("Idempotency-Key")).toBe(false);
  });

  it("reads the next page by its cursor, encoded", async () => {
    const s = server(() => json(200, PAGE));
    await readUserPage({}, "c/1+2=", signal(), TIMERS);
    expect(s.call().url).toBe("/api/v1/users?limit=50&cursor=c%2F1%2B2%3D");
  });

  it.each([404, 405, 501])("reads a list answered %i as not built (BQ-1)", async (status) => {
    server(() => json(status, { code: "not_implemented" }));
    expect(await readUserPage({}, undefined, signal(), TIMERS)).toEqual({ kind: "not_built" });
  });

  it("reads a 404 on a per-user read as failed, not as not built (22: 404 NotFound)", async () => {
    server(() => json(404, { code: "not_found" }));
    const failed = { kind: "failed", reason: "status", status: 404 };
    expect(await readGrants(ALEX, signal(), TIMERS)).toEqual(failed);
    expect(await readSessionCount(ALEX, signal(), TIMERS)).toEqual(failed);
    expect(await readMfaPreview(ALEX, signal(), TIMERS)).toEqual(failed);
  });

  it("keeps a 404 on the invites read as not built (the list's route may not be mounted)", async () => {
    server(() => json(404, { code: "not_found" }));
    expect(await readPendingInvites(signal(), TIMERS)).toEqual({ kind: "not_built" });
  });

  it("reads a 403 as the area denied, with its Ref", async () => {
    server(() => json(403, { code: "forbidden", instance: "urn:cv:req:7" }));
    expect(await readUserPage({}, undefined, signal(), TIMERS)).toEqual({
      kind: "denied",
      refId: "urn:cv:req:7",
    });
  });

  it("keeps a 503's status for the error line", async () => {
    server(() => json(503, { code: "store_unavailable" }));
    expect(await readUserPage({}, undefined, signal(), TIMERS)).toEqual({
      kind: "failed",
      reason: "status",
      status: 503,
    });
  });

  it("reads the pending invites, a user's grants, their session count and the reset preview", async () => {
    const s = server((url) => {
      if (url.endsWith("/users/invites"))
        return json(200, {
          items: [
            {
              user_id: ALEX,
              username: "alex",
              email: "alex@example.com",
              display_name: null,
              role: "viewer",
              expires_at: "2026-11-04T10:00:00+00:00",
              expired: false,
            },
          ],
        });
      if (url.endsWith("/account-access"))
        return json(200, {
          items: [
            {
              exchange_account_id: ALEX,
              level: "trade",
              account_label: "sub_001",
              environment: "live",
            },
          ],
        });
      if (url.endsWith("/sessions")) return json(200, { items: [{ id: "s1" }, { id: "s2" }] });
      return json(200, {
        message: "x",
        open_position_count: null,
        position_source: "not_deployed",
        positions: "unavailable",
        requires_acknowledge_unknown_positions: true,
        target_user_id: ALEX,
      });
    });
    expect(await readPendingInvites(signal(), TIMERS)).toMatchObject({
      kind: "ok",
      body: [{ user_id: ALEX, username: "alex", expired: false }],
    });
    expect(await readGrants(ALEX, signal(), TIMERS)).toMatchObject({
      kind: "ok",
      body: [{ level: "trade", account_label: "sub_001", environment: "live" }],
    });
    expect(await readSessionCount(ALEX, signal(), TIMERS)).toEqual({ kind: "ok", body: 2 });
    expect(await readMfaPreview(ALEX, signal(), TIMERS)).toMatchObject({
      kind: "ok",
      body: { positions: "unavailable", requiresAcknowledge: true },
    });
    expect(s.fetch.mock.calls.map(([url]) => url)).toEqual([
      "/api/v1/users/invites",
      `/api/v1/users/${ALEX}/account-access`,
      `/api/v1/users/${ALEX}/sessions`,
      `/api/v1/users/${ALEX}/mfa/reset-preview`,
    ]);
    for (let i = 0; i < 4; i += 1) expect(s.call(i).headers.has("Idempotency-Key")).toBe(false);
  });
});

describe("writes", () => {
  it("invites a viewer with two-factor and never asks for account access", async () => {
    const s = server(() =>
      json(201, { id: ALEX, username: "carol", invite_url: "/invite/e2e-link" }),
    );
    await usersApi.invite({
      username: "carol",
      email: "carol@example.com",
      displayName: " Carol ",
    });
    const { url, init, headers } = s.call();
    expect(url).toBe("/api/v1/users");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      username: "carol",
      email: "carol@example.com",
      display_name: "Carol",
      roles: ["viewer"],
      mfa_required: true,
    });
    expect(headers.get("Idempotency-Key")).toMatch(UUID4);
  });

  it("leaves an empty display name out", async () => {
    const s = server(() => json(201, {}));
    await usersApi.invite({ username: "carol", email: "carol@example.com", displayName: "  " });
    expect(JSON.parse(String(s.call().init.body))).not.toHaveProperty("display_name");
  });

  it("disables with the acknowledgement; enables without it", async () => {
    const s = server(() => json(200, USER));
    await usersApi.disable(ALEX);
    await usersApi.enable(ALEX);
    expect(s.call(0).url).toBe(`/api/v1/users/${ALEX}?acknowledge_unknown_positions=true`);
    expect(s.call(0).init.method).toBe("PATCH");
    expect(JSON.parse(String(s.call(0).init.body))).toEqual({ status: "disabled" });
    expect(s.call(1).url).toBe(`/api/v1/users/${ALEX}`);
    expect(JSON.parse(String(s.call(1).init.body))).toEqual({ status: "active" });
  });

  it("deletes with the purge and the acknowledgement, and no body", async () => {
    const s = server(() => new Response(null, { status: 204 }));
    const res = await usersApi.remove(ALEX);
    expect(res).toMatchObject({ ok: true, status: 204 });
    expect(s.call().url).toBe(
      `/api/v1/users/${ALEX}?purge=true&acknowledge_unknown_positions=true`,
    );
    expect(s.call().init.method).toBe("DELETE");
    expect(s.call().init.body ?? null).toBeNull();
  });

  it("resets two-factor with the acknowledgement the owner gave, and none they did not", async () => {
    const s = server(() =>
      json(200, { methods_revoked: 1, sessions_revoked: 2, target_user_id: ALEX }),
    );
    const res = await usersApi.resetMfa(ALEX, true);
    expect(s.call().url).toBe(`/api/v1/users/${ALEX}/mfa/reset`);
    expect(JSON.parse(String(s.call().init.body))).toEqual({ acknowledge_unknown_positions: true });
    expect(res.data).toEqual({ methodsRevoked: 1, sessionsRevoked: 2 });
    await usersApi.resetMfa(ALEX, false);
    expect(JSON.parse(String(s.call(1).init.body))).toEqual({}); // no flag: `22`'s default, false
  });

  it("re-issues and revokes an invite at its user's path", async () => {
    const s = server((_url, init) =>
      init.method === "POST"
        ? json(201, { id: ALEX, username: "dave", invite_url: "/invite/e2e-link-2" })
        : json(200, { user_id: ALEX, revoked: true }),
    );
    await usersApi.reissueInvite(ALEX);
    await usersApi.revokeInvite(ALEX);
    expect(s.call(0)).toMatchObject({
      url: `/api/v1/users/${ALEX}/invite`,
      init: { method: "POST" },
    });
    expect(s.call(1)).toMatchObject({
      url: `/api/v1/users/${ALEX}/invite`,
      init: { method: "DELETE" },
    });
  });

  it("a 403 step_up_required on a users write holds the first send, and its re-send reads through the vet", async () => {
    const challenge = {
      code: "step_up_required",
      action_class: "users",
      challenge_id: "0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d",
      challenge_expires_at: "2026-11-02T10:05:00Z",
      action_summary: "Disable user 'alex'",
      target: null,
    };
    const s = server(() => json(403, challenge));
    const res = await usersApi.disable(ALEX);
    expect(res).toMatchObject({ ok: false, status: 403, code: "step_up_required" });
    expect(res.stepUp).not.toBeNull();
    const held = res.stepUp?.held;
    const first = s.call();
    expect(held?.method).toBe("PATCH");
    expect(held?.url).toBe(first.url);
    expect(held?.body).toBe(String(first.init.body));
    expect(JSON.parse(held?.body ?? "")).toEqual({ status: "disabled" });
    const key = first.headers.get("Idempotency-Key");
    expect(key).toMatch(UUID4);
    expect(held?.headers).toContainEqual(["Idempotency-Key", key]);
    // the re-send's answer goes through the same vet: an unknown status reads unknown, a stray field is dropped
    const again = await res.stepUp?.read(
      json(200, { ...USER, status: "weird", password_hash: "x" }),
    );
    expect(again?.data).toMatchObject({ id: ALEX, status: "unknown" });
    expect(again?.data).not.toHaveProperty("password_hash");
    expect((await res.stepUp?.read(json(200, { id: "bad" })))?.data).toBeNull();
  });

  it("records the sub-account tier with a PUT and no step-up of its own", async () => {
    const s = server(() => json(200, { status: "ok", tier: "regular", cap: 5, used: 3 }));
    const res = await usersApi.setTier("business_kyc");
    expect(res.ok).toBe(true);
    expect(s.call()).toMatchObject({
      url: "/api/v1/admin/capacity/subaccount-tier",
      init: { method: "PUT" },
    });
    expect(JSON.parse(String(s.call().init.body))).toEqual({ tier: "business_kyc" });
    // `x-idempotency: ignored` (`22`): the tier write sends no key
    expect(s.call().headers.has("Idempotency-Key")).toBe(false);
  });

  it("bounds a write's first send: no answer by WRITE_TIMEOUT_MS is status 0, an outcome to read back", async () => {
    vi.useFakeTimers();
    try {
      let signal: AbortSignal | undefined;
      vi.stubGlobal(
        "fetch",
        vi.fn(
          (_url: string, init: RequestInit = {}) =>
            new Promise<Response>((_resolve, reject) => {
              signal = init.signal ?? undefined;
              signal?.addEventListener("abort", () =>
                reject(new DOMException("The operation was aborted.", "AbortError")),
              );
            }),
        ),
      );
      const pending = usersApi.disable(ALEX);
      await vi.advanceTimersByTimeAsync(WRITE_TIMEOUT_MS - 1);
      expect(signal?.aborted).toBe(false);
      await vi.advanceTimersByTimeAsync(1);
      expect(await pending).toMatchObject({ ok: false, status: 0, data: null });
      expect(WRITE_TIMEOUT_MS).toBe(10_000);
    } finally {
      vi.useRealTimers();
    }
  });

  it("a write answered in time leaves no timer behind", async () => {
    vi.useFakeTimers();
    try {
      server(() => json(200, USER));
      await usersApi.enable(ALEX);
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("gives every attempt its own idempotency value", async () => {
    const s = server(() => json(200, USER));
    await usersApi.disable(ALEX);
    await usersApi.disable(ALEX);
    expect(s.call(0).headers.get("Idempotency-Key")).not.toBe(
      s.call(1).headers.get("Idempotency-Key"),
    );
  });

  it("never sends a target that is not a served user id", async () => {
    const s = server(() => json(200, USER));
    const forged = "../../admin/capacity" as unknown as UserId;
    await expect(usersApi.disable(forged)).rejects.toThrow(TypeError);
    await expect(usersApi.remove(forged)).rejects.toThrow(TypeError);
    await expect(readGrants(forged, signal(), TIMERS)).rejects.toThrow(TypeError);
    expect(s.fetch).not.toHaveBeenCalled();
  });

  it("returns the created invite's link to its caller alone: no storage, no console", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const logs = [
      vi.spyOn(console, "log"),
      vi.spyOn(console, "info"),
      vi.spyOn(console, "warn"),
      vi.spyOn(console, "error"),
      vi.spyOn(console, "debug"),
    ];
    server(() =>
      json(201, {
        id: ALEX,
        username: "carol",
        invite_url: "/invite/e2e-link",
        invite_expires_at: "2026-11-05T10:00:00+00:00",
      }),
    );
    const res = await usersApi.invite({ username: "carol", email: "carol@example.com" });
    expect(res.data).toMatchObject({ invite_url: "/invite/e2e-link" });
    expect(setItem).not.toHaveBeenCalled();
    for (const log of logs) expect(log).not.toHaveBeenCalled();
  });
});
