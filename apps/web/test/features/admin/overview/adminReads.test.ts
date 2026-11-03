/**
 * E42-S01 (#1022): the admin read layer. Each read settles as one of four outcomes under its own 3 s
 * client bound (BQ-5), a `403` is the area withdrawn (BQ-8), a `404` or `501` is a source not built
 * yet (BQ-4), and every body is vetted to the fields a tile reads before anything shows it.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  READ_TIMEOUT_MS,
  readAdmin,
  vetAudit,
  vetCapacity,
  vetFlags,
  vetHealth,
  vetInvites,
  vetOverview,
  type ReadTimers,
} from "../../../../src/features/admin/overview/adminReads";

const TIMERS: ReadTimers = {
  setTimeout: (run, ms) => globalThis.setTimeout(run, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};
const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const read = (signal = new AbortController().signal) =>
  readAdmin("/api/v1/admin/overview", vetOverview, signal, TIMERS);

/** A fetch that never answers, and rejects as a browser does once its signal aborts. */
function hangingFetch(): { readonly signals: AbortSignal[] } {
  const signals: AbortSignal[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((_input: RequestInfo | URL, init: RequestInit = {}) => {
      const signal = init.signal as AbortSignal;
      signals.push(signal);
      return new Promise<Response>((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      });
    }),
  );
  return { signals };
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("readAdmin: one read, four outcomes", () => {
  it("answers ok with the vetted body, asking for JSON with GET", async () => {
    const fetch = vi.fn(async () => json(200, { users: { status: "ok", total: 4 } }));
    vi.stubGlobal("fetch", fetch);
    expect(await read()).toEqual({ kind: "ok", body: { users: { status: "ok", total: 4 } } });
    const [input, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(input).toBe("/api/v1/admin/overview");
    expect(init.method ?? "GET").toBe("GET");
    expect(new Headers(init.headers).get("Accept")).toBe("application/json");
  });

  it.each([404, 501])("reads %i as a source not built yet (BQ-4)", async (status) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(status, { code: "not_implemented" })),
    );
    expect(await read()).toEqual({ kind: "not_built" });
  });

  it("reads 403 as the area withdrawn, with the problem's instance as its Ref", async () => {
    const instance = "urn:cv:req:0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(403, { code: "forbidden", instance })),
    );
    expect(await read()).toEqual({ kind: "denied", refId: instance });
  });

  it("shows no Ref for a 403 without one, or with one that is not an id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("", { status: 403 })),
    );
    expect(await read()).toEqual({ kind: "denied", refId: undefined });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(403, { instance: "<img src=x onerror=1>" })),
    );
    expect(await read()).toEqual({ kind: "denied", refId: undefined });
  });

  it("reads any other refusal as failed with its status, and a lost connection as network", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(503, { code: "audit_unavailable" })),
    );
    expect(await read()).toEqual({ kind: "failed", reason: "status", status: 503 });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))),
    );
    expect(await read()).toEqual({ kind: "failed", reason: "network" });
  });

  it("reads a body that is not JSON, or not the shape, as unreadable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<!doctype html>", { status: 200 })),
    );
    expect(await read()).toEqual({ kind: "failed", reason: "unreadable" });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(200, [1, 2])),
    );
    expect(await read()).toEqual({ kind: "failed", reason: "unreadable" });
  });

  it("gives up after 3 s of no answer: the request is aborted and the read failed by timeout", async () => {
    vi.useFakeTimers();
    const { signals } = hangingFetch();
    const pending = read();
    await vi.advanceTimersByTimeAsync(READ_TIMEOUT_MS - 1);
    expect(signals[0]?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(await pending).toEqual({ kind: "failed", reason: "timeout" });
    expect(signals[0]?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("stops when its caller stops waiting, and leaves no timer behind", async () => {
    vi.useFakeTimers();
    const { signals } = hangingFetch();
    const caller = new AbortController();
    const pending = read(caller.signal);
    caller.abort();
    expect(await pending).toEqual({ kind: "failed", reason: "network" });
    expect(signals[0]?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("the vetters keep only what a tile reads", () => {
  it("keeps each overview slice's scalars, and an unknown status is not ok (open-ended, 22)", () => {
    const body = vetOverview({
      generated_at: "2026-10-22T12:00:00Z",
      users: { status: "ok", total: 4, without_mfa: 1, extra: { nested: true }, list: [1] },
      recorder: { status: "paused", detail: "recorder: maintenance" },
      trading: "not an object",
      stranger: { status: "ok" },
    });
    expect(body).toEqual({
      generated_at: "2026-10-22T12:00:00Z",
      users: { status: "ok", total: 4, without_mfa: 1 },
      recorder: { status: "unavailable", detail: "recorder: maintenance" },
    });
    expect(vetOverview(null)).toBeNull();
    expect(vetOverview([])).toBeNull();
  });

  it("keeps the capacity report's sub-account slice only", () => {
    const sub = { status: "ok", tier: "regular", cap: 5, used: 3, tier_source: "recorded" };
    expect(vetCapacity({ storage: { status: "ok" }, subaccounts: sub })).toEqual({
      subaccounts: sub,
    });
    expect(vetCapacity({})).toEqual({});
  });

  it("keeps the health components that have a name and a state", () => {
    const body = vetHealth({
      overall: "degraded",
      server_time: "2026-10-22T12:00:00Z",
      components: [{ name: "oms", state: "degraded", detail: "x" }, { state: "down" }, "junk"],
    });
    expect(body).toEqual({
      overall: "degraded",
      server_time: "2026-10-22T12:00:00Z",
      components: [{ name: "oms", state: "degraded", detail: "x" }],
    });
  });

  it("needs a flag list's resolution and keys its items", () => {
    expect(vetFlags({ items: [] })).toBeNull();
    expect(
      vetFlags({
        resolution: "stored",
        items: [{ key: "maintenance.mode", value: false, overrides: [] }, { value: true }],
      }),
    ).toEqual({ resolution: "stored", items: [{ key: "maintenance.mode", value: false }] });
  });

  it("keeps an audit entry's compact fields, never a hash, an IP or the detail's states", () => {
    const entry = {
      id: 7,
      ts: "2026-10-22T12:00:00.123456Z",
      action: "admin.area_entered",
      outcome: "success",
      severity: "info",
      actor_user_id: "u1",
      actor_username: "basiltt",
      subject_id: null,
      subject_type: null,
      entry_hash: "a".repeat(64),
      prev_hash: "b".repeat(64),
      ip: "100.64.0.7",
      detail: { before: { secret: "no" }, after: { phase: "intent", other: "no" } },
    };
    const page = vetAudit({ chain_verified: true, items: [entry, { id: 8 }] });
    expect(page?.items).toHaveLength(1);
    const [kept] = page?.items ?? [];
    expect(kept?.detail).toEqual({ after: { phase: "intent" } });
    expect(kept?.actor_username).toBe("basiltt");
    expect(JSON.stringify(kept)).not.toMatch(/secret|100\.64|aaaa/);
  });

  it("counts the pending invites, whose items are untyped (CG-14)", () => {
    expect(vetInvites({ items: [{}, {}] })).toEqual({ count: 2 });
    expect(vetInvites({ items: "x" })).toBeNull();
  });

  it("drops a slice field longer than any the contract serves", () => {
    const long = "x".repeat(501);
    expect(vetOverview({ users: { status: "error", detail: long } })).toEqual({
      users: { status: "error" },
    });
  });
});
