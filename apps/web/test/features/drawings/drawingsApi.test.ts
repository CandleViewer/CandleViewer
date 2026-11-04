import { describe, expect, it, vi } from "vitest";
import {
  createDrawingsApi,
  serializeBatch,
  type FetchLike,
} from "../../../src/features/drawings/store/drawingsApi.js";
import { input, row } from "./fixtures.js";

const json = (status: number, body: unknown, headers: Record<string, string> = {}): Response =>
  new Response(body === undefined ? "not json" : JSON.stringify(body), { status, headers });

describe("drawings api", () => {
  it("lists a symbol with limit 500 and follows the cursor", async () => {
    const calls: string[] = [];
    const fetchImpl: FetchLike = (url) => {
      calls.push(url);
      return Promise.resolve(
        calls.length === 1
          ? json(200, {
              items: [row("a", input())],
              meta: { count: 1, has_more: true, next_cursor: "c1" },
            })
          : json(200, { items: [row("b", input())], meta: { count: 1, has_more: false } }),
      );
    };
    const out = await createDrawingsApi(fetchImpl).list("BTCUSDT");
    expect(out.ok && out.items.map((d) => d.id)).toEqual(["a", "b"]);
    expect(calls).toEqual([
      "/api/v1/drawings?symbol=BTCUSDT&limit=500",
      "/api/v1/drawings?symbol=BTCUSDT&limit=500&cursor=c1",
    ]);
  });

  it("list fails at the page cap and on a 200 that is not a page", async () => {
    const looping: FetchLike = () =>
      Promise.resolve(
        json(200, { items: [], meta: { count: 0, has_more: true, next_cursor: "x" } }),
      );
    expect(await createDrawingsApi(looping).list("BTCUSDT")).toEqual({ ok: false, status: 0 });
    const bad: FetchLike = () => Promise.resolve(json(503, {}));
    expect(await createDrawingsApi(bad).list("BTCUSDT")).toEqual({ ok: false, status: 503 });
    const down: FetchLike = () => Promise.reject(new TypeError("offline"));
    expect(await createDrawingsApi(down).list("BTCUSDT")).toEqual({ ok: false, status: 0 });
    const empty: FetchLike = () => Promise.resolve(json(200, undefined));
    expect(await createDrawingsApi(empty).list("BTCUSDT")).toEqual({ ok: false, status: 200 });
    for (const body of [
      null,
      {},
      { items: [] },
      { items: [], meta: null },
      { items: {}, meta: {} },
    ]) {
      const odd: FetchLike = () => Promise.resolve(json(200, body));
      expect(await createDrawingsApi(odd).list("BTCUSDT")).toEqual({ ok: false, status: 200 });
    }
  });

  it("posts the body byte-exact with the Idempotency-Key; if_match is never re-serialised", async () => {
    const token = "2026-09-13T12:00:00.100000Z";
    const body = serializeBatch([{ op: "delete", id: "a", if_match: token }]);
    expect(body).toContain(`"if_match":"${token}"`);
    const fetchImpl = vi.fn<FetchLike>(() =>
      Promise.resolve(json(200, { created: [], updated: [], deleted: ["a"] })),
    );
    const out = await createDrawingsApi(fetchImpl).batch(body, "key-1");
    expect(out).toEqual({ kind: "ok", result: { created: [], updated: [], deleted: ["a"] } });
    const [url, init] = fetchImpl.mock.calls[0] ?? [];
    expect(url).toBe("/api/v1/drawings/batch");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(body);
    expect(new Headers(init?.headers).get("Idempotency-Key")).toBe("key-1");
  });

  it("maps every batch status to an outcome", async () => {
    const run = (res: Response | Error) =>
      createDrawingsApi(() =>
        res instanceof Error ? Promise.reject(res) : Promise.resolve(res),
      ).batch("{}", "k");
    // An unreadable 2xx confirms nothing: it is re-sent, never taken as saved.
    expect(await run(json(200, undefined))).toEqual({ kind: "retryable", status: 200 });
    expect(await run(json(200, null))).toEqual({ kind: "retryable", status: 200 });
    expect(await run(json(201, { created: [], updated: [] }))).toEqual({
      kind: "retryable",
      status: 201,
    });
    expect(await run(new Error("net"))).toEqual({ kind: "retryable", status: 0 });
    expect(await run(json(503, {}))).toEqual({ kind: "retryable", status: 503 });
    expect(await run(json(408, {}))).toEqual({ kind: "retryable", status: 408 });
    expect(await run(json(429, {}, { "Retry-After": "7" }))).toEqual({
      kind: "rate_limited",
      retryAfterS: 7,
    });
    expect(await run(json(429, {}, { "Retry-After": "9999" }))).toEqual({
      kind: "rate_limited",
      retryAfterS: 60,
    });
    expect(await run(json(429, {}, { "Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT" }))).toEqual({
      kind: "rate_limited",
      retryAfterS: null,
    });
    expect(await run(json(429, {}))).toEqual({ kind: "rate_limited", retryAfterS: null });
    expect(
      await run(
        json(409, {
          code: "conflict",
          errors: [{ field: "operations.3", rule: "target_unavailable", message: "x" }],
        }),
      ),
    ).toEqual({ kind: "conflict", rule: "target_unavailable", index: 3 });
    expect(await run(json(409, { code: "drawings_quota_exceeded" }))).toEqual({
      kind: "conflict",
      rule: "drawings_quota_exceeded",
      index: null,
    });
    expect(await run(json(409, undefined))).toEqual({
      kind: "conflict",
      rule: "conflict",
      index: null,
    });
    expect(await run(json(403, { code: "forbidden" }))).toEqual({
      kind: "rejected",
      status: 403,
      code: "forbidden",
    });
    expect(await run(json(422, undefined))).toEqual({ kind: "rejected", status: 422, code: null });
  });
});
