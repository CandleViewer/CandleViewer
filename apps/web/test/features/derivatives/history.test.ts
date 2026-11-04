// E24-S01 (#776) slice 1: the backfill read against `22` `getOpenInterestHistory` (consumes the
// schema's shape over the recorded 5 min pages; contract test plan item).
import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import {
  fetchOiHistory,
  historyPath,
  parseCoverage,
  parsePoint,
} from "../../../src/features/derivatives/oi/history";
import { coverageOf, page, recordedRestPoints } from "./support/oiFixtures";

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const POINTS = recordedRestPoints();
const FROM = Date.parse(POINTS[0]?.t ?? "");
const TO = Date.parse(POINTS[POINTS.length - 1]?.t ?? "") + 1;
const req = (over: Partial<Parameters<typeof fetchOiHistory>[0]> = {}) => ({
  symbol: "BTCUSDT",
  interval: "5min" as const,
  fromMs: FROM,
  toMs: TO,
  signal: new AbortController().signal,
  ...over,
});

describe("OI history read", () => {
  beforeEach(() => apiFetch.mockReset());

  it("builds the query the contract names, the cursor only when paging", () => {
    const path = historyPath({ symbol: "BTCUSDT", interval: "5min", fromMs: 0, toMs: 1000 }, null);
    const url = new URL(path, "http://x");
    expect(url.pathname).toBe("/api/v1/market/open-interest");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      symbol: "BTCUSDT",
      interval: "5min",
      from: "1970-01-01T00:00:00.000Z",
      to: "1970-01-01T00:00:01.000Z",
      limit: "500",
    });
    expect(new URL(historyPath(req(), "c1"), "http://x").searchParams.get("cursor")).toBe("c1");
  });

  it("follows next_cursor across pages and returns the points ascending, unique by time", async () => {
    const half = Math.floor(POINTS.length / 2);
    const later = POINTS.slice(half);
    const earlier = POINTS.slice(0, half + 1); // one point repeated across the pages
    apiFetch
      .mockResolvedValueOnce(
        json(200, page(later, { has_more: true, next_cursor: "c1", coverage: coverageOf(POINTS) })),
      )
      .mockResolvedValueOnce(json(200, page(earlier, { coverage: coverageOf(POINTS) })));
    const out = await fetchOiHistory(req());
    expect(apiFetch).toHaveBeenCalledTimes(2);
    expect(apiFetch.mock.calls[1]?.[0]).toContain("cursor=c1");
    if (out.kind !== "ok") throw new Error("expected ok");
    expect(out.points).toHaveLength(POINTS.length);
    expect(out.points.map((p) => p.tMs)).toEqual(POINTS.map((p) => Date.parse(p.t)));
    expect(out.points[0]?.base).toBe(POINTS[0]?.open_interest); // the decimal as sent
    expect(out.truncated).toBeNull();
    expect(out.coverage.nativeInterval).toBe("5min");
  });

  it("reads ascending, so it starts late enough for the bound to reach `to`: the older end is what's left out", async () => {
    apiFetch.mockResolvedValueOnce(json(200, page(POINTS.slice(-2))));
    const toMs = Date.parse("2026-10-21T10:00:00Z");
    const out = await fetchOiHistory(req({ fromMs: 0, toMs, maxPages: 2 }));
    const sent = new URL(apiFetch.mock.calls[0]?.[0] ?? "", "http://x").searchParams;
    expect(sent.get("from")).toBe(new Date(toMs - 2 * 500 * 300_000).toISOString());
    expect(sent.get("to")).toBe(new Date(toMs).toISOString());
    expect(out.kind === "ok" && out.truncated).toBe("older");
  });

  it("says older only when the clamp cut stored data (coverage.from before the new start, A3)", async () => {
    const toMs = Date.parse("2026-10-21T10:00:00Z");
    const clampedFrom = toMs - 2 * 500 * 300_000;
    const at = (fromIso: string | null) =>
      json(200, page([], { coverage: { ...coverageOf([]), from: fromIso } }));
    apiFetch
      .mockResolvedValueOnce(at(null))
      .mockResolvedValueOnce(at(new Date(clampedFrom + 60_000).toISOString()))
      .mockResolvedValueOnce(at(new Date(clampedFrom).toISOString()))
      .mockResolvedValueOnce(at(new Date(clampedFrom - 300_000).toISOString()));
    const truncated = async (): Promise<unknown> => {
      const out = await fetchOiHistory(req({ fromMs: 0, toMs, maxPages: 2 }));
      return out.kind === "ok" ? out.truncated : "failed";
    };
    expect(await truncated()).toBeNull(); // nothing stored: nothing cut
    expect(await truncated()).toBeNull(); // the store starts after the clamped start
    expect(await truncated()).toBeNull(); // ... or exactly at it
    expect(await truncated()).toBe("older"); // stored points before it were left out
  });

  it("says the newer end is missing if the pages run out with has_more still true", async () => {
    apiFetch.mockImplementation(async () =>
      json(200, page(POINTS.slice(0, 2), { has_more: true, next_cursor: "again" })),
    );
    const out = await fetchOiHistory(req({ maxPages: 3 }));
    expect(apiFetch).toHaveBeenCalledTimes(3);
    expect(out.kind === "ok" && out.truncated).toBe("newer");
  });

  it("drops and counts a malformed item, never coerces it", async () => {
    const bad = [
      { ...POINTS[0], open_interest: 61180.22 },
      { ...POINTS[1], interval: "2min" },
    ];
    apiFetch.mockResolvedValueOnce(json(200, page([...bad, ...POINTS.slice(2, 4)] as never)));
    const out = await fetchOiHistory(req());
    expect(out.kind === "ok" && out.malformed).toBe(2);
    expect(out.kind === "ok" && out.points).toHaveLength(2);
  });

  it("unions the gaps of every page, the open tail included, and takes the rest from page 0", async () => {
    const half = Math.floor(POINTS.length / 2);
    const t = (i: number): string => POINTS[i]?.t ?? "";
    const first = { from: t(1), to: t(2) };
    const second = { from: t(half + 1), to: t(half + 2) };
    const tail = { from: t(POINTS.length - 1), to: new Date(TO).toISOString() };
    apiFetch
      .mockResolvedValueOnce(
        json(
          200,
          page(POINTS.slice(0, half), {
            has_more: true,
            next_cursor: "c1",
            coverage: coverageOf(POINTS, { gaps: [first] }),
          }),
        ),
      )
      .mockResolvedValueOnce(
        json(
          200,
          page(POINTS.slice(half), {
            coverage: coverageOf(POINTS, { gaps: [second, tail], native_interval: "15min" }),
          }),
        ),
      );
    const out = await fetchOiHistory(req());
    if (out.kind !== "ok") throw new Error("expected ok");
    const span = (g: { from: string; to: string }) => ({
      fromMs: Date.parse(g.from),
      toMs: Date.parse(g.to),
    });
    expect(out.coverage.gaps).toEqual([span(first), span(second), span(tail)]);
    expect(out.coverage.nativeInterval).toBe("5min"); // page 0's
  });

  it("merges gaps that overlap or touch across pages", async () => {
    const t = (i: number): string => POINTS[i]?.t ?? "";
    apiFetch
      .mockResolvedValueOnce(
        json(
          200,
          page(POINTS.slice(0, 2), {
            has_more: true,
            next_cursor: "c1",
            coverage: coverageOf(POINTS, { gaps: [{ from: t(1), to: t(3) }] }),
          }),
        ),
      )
      .mockResolvedValueOnce(
        json(
          200,
          page(POINTS.slice(2, 4), {
            coverage: coverageOf(POINTS, { gaps: [{ from: t(3), to: t(5) }] }),
          }),
        ),
      );
    const out = await fetchOiHistory(req());
    expect(out.kind === "ok" && out.coverage.gaps).toEqual([
      { fromMs: Date.parse(t(1)), toMs: Date.parse(t(5)) },
    ]);
  });

  it("clamps a window past the server's 400-day bound, so it is never refused (1d, 500 days)", async () => {
    const day = 86_400_000;
    const toMs = Date.parse("2026-10-21T00:00:00Z");
    apiFetch.mockResolvedValueOnce(
      json(
        200,
        page([], {
          coverage: { ...coverageOf([]), from: new Date(toMs - 450 * day).toISOString() },
        }),
      ),
    );
    const out = await fetchOiHistory(req({ interval: "1d", fromMs: toMs - 500 * day, toMs }));
    const sent = new URL(apiFetch.mock.calls[0]?.[0] ?? "", "http://x").searchParams;
    expect(Date.parse(sent.get("to") ?? "") - Date.parse(sent.get("from") ?? "")).toBe(400 * day);
    expect(out.kind === "ok" && out.truncated).toBe("older");
  });

  it("adds a gap over a dropped malformed item, so the hole is never a line", async () => {
    const bad = { ...POINTS[1], open_interest: 1 } as never;
    apiFetch.mockResolvedValueOnce(json(200, page([POINTS[0], bad, POINTS[2]] as never)));
    const out = await fetchOiHistory(req());
    if (out.kind !== "ok") throw new Error("expected ok");
    const t = Date.parse(POINTS[1]?.t ?? "");
    expect(out.malformed).toBe(1);
    expect(out.coverage.gaps).toContainEqual({ fromMs: t, toMs: t + 300_000 });
  });

  it("never reads has_more without a usable cursor as a complete read", async () => {
    for (const next_cursor of [null, ""]) {
      apiFetch.mockResolvedValueOnce(
        json(200, page(POINTS.slice(0, 2), { has_more: true, next_cursor })),
      );
      const onAnomaly = vi.fn();
      const out = await fetchOiHistory(req({ onAnomaly }));
      expect(out.kind === "ok" && out.truncated).toBe("newer");
      expect(out.kind === "ok" && out.points).toHaveLength(2); // the valid points are still shown
      expect(onAnomaly).toHaveBeenCalledTimes(1); // once per read
      expect(onAnomaly).toHaveBeenCalledWith("cursor_missing");
    }
    apiFetch.mockResolvedValueOnce(json(200, page(POINTS.slice(0, 2))));
    const quiet = vi.fn();
    await fetchOiHistory(req({ onAnomaly: quiet })); // a clean read reports nothing
    expect(quiet).not.toHaveBeenCalled();
  });

  it("contains a throwing onAnomaly and skips it once the read is aborted", async () => {
    apiFetch.mockResolvedValueOnce(
      json(200, page(POINTS.slice(0, 2), { has_more: true, next_cursor: null })),
    );
    const onAnomaly = vi.fn(() => {
      throw new Error("sink");
    });
    const out = await fetchOiHistory(req({ onAnomaly }));
    expect(out.kind === "ok" && out.points).toHaveLength(2);
    expect(onAnomaly).toHaveBeenCalledTimes(1);

    const ctl = new AbortController();
    apiFetch.mockImplementationOnce(async () => {
      ctl.abort();
      return json(200, page(POINTS.slice(0, 2), { has_more: true, next_cursor: null }));
    });
    const late = vi.fn();
    await fetchOiHistory(req({ onAnomaly: late, signal: ctl.signal }));
    expect(late).not.toHaveBeenCalled();
  });

  it("fails the whole read when a later page fails", async () => {
    apiFetch
      .mockResolvedValueOnce(
        json(200, page(POINTS.slice(0, 2), { has_more: true, next_cursor: "c1" })),
      )
      .mockResolvedValueOnce(json(503, { code: "service_unavailable" }));
    expect(await fetchOiHistory(req())).toEqual({
      kind: "failed",
      status: 503,
      code: "service_unavailable",
    });
    expect(apiFetch).toHaveBeenCalledTimes(2);
  });

  it("ends a read in flight when the caller aborts", async () => {
    const call = new AbortController();
    apiFetch.mockImplementationOnce(
      (_url, init) =>
        new Promise((_res, rej) =>
          init?.signal?.addEventListener("abort", () => rej(new Error("abort"))),
        ),
    );
    const pending = fetchOiHistory(req({ signal: call.signal }));
    await Promise.resolve();
    call.abort();
    expect(await pending).toEqual({ kind: "failed", status: null, code: null });
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it("fails with the status and code on a refusal, and with no status when no answer came", async () => {
    apiFetch.mockResolvedValueOnce(json(503, { code: "service_unavailable" }));
    expect(await fetchOiHistory(req())).toEqual({
      kind: "failed",
      status: 503,
      code: "service_unavailable",
    });
    apiFetch.mockRejectedValueOnce(new TypeError("network"));
    expect(await fetchOiHistory(req())).toEqual({ kind: "failed", status: null, code: null });
    apiFetch.mockResolvedValueOnce(json(200, { items: [], meta: { has_more: false } }));
    expect(await fetchOiHistory(req())).toEqual({ kind: "failed", status: 200, code: "malformed" });
  });

  it("never calls out once the caller has aborted", async () => {
    const call = new AbortController();
    call.abort();
    expect(await fetchOiHistory(req({ signal: call.signal }))).toMatchObject({ kind: "failed" });
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("ends a hung read at the deadline", async () => {
    let fire: (() => void) | undefined;
    const clock = { setTimeout: (run: () => void) => ((fire = run), 1), clearTimeout: vi.fn() };
    apiFetch.mockImplementationOnce(
      (_url, init) =>
        new Promise((_res, rej) =>
          init?.signal?.addEventListener("abort", () => rej(new Error("abort"))),
        ),
    );
    const pending = fetchOiHistory(req({ clock }));
    await Promise.resolve();
    fire?.();
    expect(await pending).toEqual({ kind: "failed", status: null, code: null });
    expect(clock.clearTimeout).toHaveBeenCalled();
  });

  it("parses the contract example's point and coverage (`22` example `oi`)", () => {
    expect(
      parsePoint({
        t: "2026-09-14T10:25:00Z",
        open_interest: "61180.220",
        open_interest_value: null,
        interval: "5min",
        source: "rest",
      }),
    ).toEqual({
      tMs: Date.parse("2026-09-14T10:25:00Z"),
      base: "61180.220",
      interval: "5min",
      source: "rest",
    });
    expect(
      parseCoverage({
        coverage: {
          from: null,
          to: null,
          native_interval: "5min",
          source: "rest",
          gaps: [{ from: "2026-09-14T10:00:00Z", to: "2026-09-14T10:15:00Z" }],
        },
      }),
    ).toEqual({
      fromMs: null,
      toMs: null,
      nativeInterval: "5min",
      source: "rest",
      gaps: [
        { fromMs: Date.parse("2026-09-14T10:00:00Z"), toMs: Date.parse("2026-09-14T10:15:00Z") },
      ],
    });
    expect(
      parseCoverage({
        coverage: { native_interval: "5min", source: "rest", gaps: [{ from: "x" }] },
      }),
    ).toBeNull();
  });
});
