/**
 * E08-S08 (#4702): SCR-100's `/watchlists` calls (`22` `listWatchlists`, `updateWatchlist`; E08-T07) through a faked
 * REST client (no network): the lists read and checked, and a replace against the version last read, by `If-Match`.
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

  it("maps the answers: 412 a conflict, 403 a refusal, the rest a failure", async () => {
    const save = (status: number) =>
      createWatchlistApi(fetcher(async () => json({ status }, status))).replace(MAJORS, {
        symbols: MAJORS.symbols,
        columns: MAJORS.columns,
      });
    expect(await save(412)).toEqual({ kind: "conflict" });
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

describe("isWatchlist", () => {
  it("takes the contract's members and nothing less", () => {
    expect(isWatchlist(MAJORS)).toBe(true);
    expect(isWatchlist({ ...MAJORS, symbols: [1] })).toBe(false);
    expect(isWatchlist({ ...MAJORS, version: "4" })).toBe(false);
    expect(isWatchlist([])).toBe(false);
  });
});
