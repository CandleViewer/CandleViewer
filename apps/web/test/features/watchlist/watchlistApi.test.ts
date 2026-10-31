/**
 * E08-S08 (#4702): SCR-100's and SCR-101's `/watchlists` calls (`22` `listWatchlists`, `createWatchlist`,
 * `updateWatchlist`, `deleteWatchlist`; E08-T07) through a faked REST client (no network): the lists read and checked,
 * a replace against the version last read, by `If-Match`, a list created and a list deleted.
 */
import { describe, expect, it, vi } from "vitest";
import {
  WATCHLISTS_PATH,
  createWatchlistApi,
  etagOf,
  isWatchlist,
} from "../../../src/features/watchlist/watchlistApi";
import type { Watchlist } from "../../../src/features/watchlist/listEdits";

const MAJORS: Watchlist = {
  id: "11111111-1111-4111-8111-111111111111",
  name: "Majors",
  symbols: ["BTCUSDT", "ETHUSDT"],
  columns: ["symbol", "last"],
  version: 4,
  created_at: "2026-10-30T10:00:00Z",
  updated_at: "2026-10-30T10:00:00Z",
};
const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const fetcher = (answer: () => Promise<Response>) =>
  vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(answer);

describe("list", () => {
  it("reads the caller's lists and keeps only what is one", async () => {
    const fetch = fetcher(async () => json({ items: [MAJORS, { id: 3 }, null] }));
    expect(await createWatchlistApi(fetch).list()).toEqual([MAJORS]);
    expect(fetch.mock.calls[0]?.[0]).toBe(WATCHLISTS_PATH);
  });

  it("throws when the lists could not be read", async () => {
    await expect(createWatchlistApi(fetcher(async () => json({}, 503))).list()).rejects.toThrow();
  });

  it("answers no list for a body without items", async () => {
    expect(await createWatchlistApi(fetcher(async () => json({}))).list()).toEqual([]);
  });
});

describe("replace", () => {
  it("PUTs the whole list, name kept, against the version last read", async () => {
    const stored = { ...MAJORS, symbols: ["ETHUSDT"], version: 5 };
    const fetch = fetcher(async () => json(stored));
    const outcome = await createWatchlistApi(fetch).replace(MAJORS, {
      symbols: ["ETHUSDT"],
      columns: ["symbol", "last"],
    });
    expect(outcome).toEqual({ kind: "saved", list: stored });
    const [url, init] = fetch.mock.calls[0] ?? [];
    expect(url).toBe(`${WATCHLISTS_PATH}/${MAJORS.id}`);
    expect(init?.method).toBe("PUT");
    expect(new Headers(init?.headers).get("If-Match")).toBe(etagOf(MAJORS));
    expect(etagOf(MAJORS)).toBe(`W/"${MAJORS.id}:4"`);
    expect(JSON.parse(String(init?.body))).toEqual({
      name: "Majors",
      symbols: ["ETHUSDT"],
      columns: ["symbol", "last"],
    });
  });

  it("a rename sends the new name with the whole list", async () => {
    const fetch = fetcher(async () => json({ ...MAJORS, name: "Core", version: 5 }));
    await createWatchlistApi(fetch).replace(MAJORS, {
      name: "Core",
      symbols: MAJORS.symbols,
      columns: MAJORS.columns,
    });
    expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))).toMatchObject({ name: "Core" });
  });

  it("maps the answers: 412 a conflict, 403 a refusal, the rest a failure", async () => {
    const save = (status: number) =>
      createWatchlistApi(fetcher(async () => json({ status }, status))).replace(MAJORS, {
        symbols: MAJORS.symbols,
        columns: MAJORS.columns,
      });
    expect(await save(412)).toEqual({ kind: "conflict" });
    // the list deleted in another window: as a conflict, which Reload settles
    expect(await save(404)).toEqual({ kind: "conflict" });
    expect(await save(409)).toEqual({ kind: "name_taken" });
    expect(await save(403)).toEqual({ kind: "refused" });
    expect(await save(422)).toEqual({ kind: "failed" });
    expect(await save(503)).toEqual({ kind: "failed" });
  });

  it("a network failure or a body that is no list is a failure", async () => {
    const thrown = createWatchlistApi(fetcher(async () => Promise.reject(new TypeError("down"))));
    expect(await thrown.replace(MAJORS, { symbols: [], columns: [] })).toEqual({ kind: "failed" });
    const odd = createWatchlistApi(fetcher(async () => json({ id: "x" })));
    expect(await odd.replace(MAJORS, { symbols: [], columns: [] })).toEqual({ kind: "failed" });
  });
});

describe("create", () => {
  it("POSTs the new list, without columns when none are given, and answers the stored list", async () => {
    const stored = { ...MAJORS, id: "22222222-2222-4222-8222-222222222222", version: 1 };
    const fetch = fetcher(async () => json(stored, 201));
    const outcome = await createWatchlistApi(fetch).create({
      name: "Majors",
      symbols: ["BTCUSDT"],
    });
    expect(outcome).toEqual({ kind: "saved", list: stored });
    const [url, init] = fetch.mock.calls[0] ?? [];
    expect(url).toBe(WATCHLISTS_PATH);
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("If-Match")).toBeNull();
    expect(JSON.parse(String(init?.body))).toEqual({ name: "Majors", symbols: ["BTCUSDT"] });
  });

  it("sends the columns given (a duplicate's)", async () => {
    const fetch = fetcher(async () => json(MAJORS, 201));
    await createWatchlistApi(fetch).create({
      name: "Majors copy",
      symbols: [],
      columns: ["symbol"],
    });
    expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))).toMatchObject({
      columns: ["symbol"],
    });
  });

  it("maps the answers: 409 a taken name, 403 a refusal, the rest (404 too) a failure", async () => {
    const make = (status: number) =>
      createWatchlistApi(fetcher(async () => json({ status }, status))).create({
        name: "Majors",
        symbols: [],
      });
    expect(await make(409)).toEqual({ kind: "name_taken" });
    expect(await make(403)).toEqual({ kind: "refused" });
    expect(await make(404)).toEqual({ kind: "failed" });
    expect(await make(422)).toEqual({ kind: "failed" });
    const down = createWatchlistApi(fetcher(async () => Promise.reject(new TypeError("down"))));
    expect(await down.create({ name: "x", symbols: [] })).toEqual({ kind: "failed" });
  });
});

describe("remove", () => {
  it("DELETEs the list; 204 and 404 (already gone) are deleted, 403 a refusal, the rest a failure", async () => {
    const fetch = fetcher(async () => new Response(null, { status: 204 }));
    expect(await createWatchlistApi(fetch).remove(MAJORS)).toEqual({ kind: "deleted" });
    const [url, init] = fetch.mock.calls[0] ?? [];
    expect(url).toBe(`${WATCHLISTS_PATH}/${MAJORS.id}`);
    expect(init?.method).toBe("DELETE");
    const drop = (status: number) =>
      createWatchlistApi(fetcher(async () => json({ status }, status))).remove(MAJORS);
    expect(await drop(404)).toEqual({ kind: "deleted" });
    expect(await drop(403)).toEqual({ kind: "refused" });
    expect(await drop(503)).toEqual({ kind: "failed" });
    const down = createWatchlistApi(fetcher(async () => Promise.reject(new TypeError("down"))));
    expect(await down.remove(MAJORS)).toEqual({ kind: "failed" });
  });
});

describe("isWatchlist", () => {
  it("takes the contract's members and nothing less", () => {
    expect(isWatchlist(MAJORS)).toBe(true);
    expect(isWatchlist({ ...MAJORS, symbols: [1] })).toBe(false);
    expect(isWatchlist({ ...MAJORS, version: "4" })).toBe(false);
    expect(isWatchlist([])).toBe(false);
  });
});
