// E24-S07 (#782) slice 2: the by-price read and the layer model: the boundary check against the generated
// `LiquidationsByPrice` (BQ 7: a stripped `estimated` is refused, the X02 negative), the request, the failures, the
// coverage clamp (BQ 5) and the access rule (BQ 10).
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as read from "../../../../../src/features/derivatives/liquidations/byPrice/byPriceRead";
import * as model from "../../../../../src/features/derivatives/liquidations/byPrice/model";
import * as s from "../../../../../src/features/derivatives/liquidations/byPrice/samples";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

type Body = Record<string, unknown> & { items: Record<string, unknown>[] };
const body = (): Body => JSON.parse(JSON.stringify(s.EXAMPLE)) as Body;
const stripped = (): Body => {
  const b = body();
  delete b["estimated"];
  return b;
};

describe("parseByPrice", () => {
  it("reads the contract's example, Decimal strings kept as strings", () => {
    expect(read.parseByPrice(body(), "BTCUSDT")).toEqual({ kind: "ok", answer: s.EXAMPLE });
  });

  it("refuses an answer whose estimated flag is stripped or not a boolean", () => {
    const refused = { kind: "refused", code: "estimated_missing" };
    expect(read.parseByPrice(stripped(), "BTCUSDT")).toEqual(refused);
    expect(read.parseByPrice({ ...body(), estimated: "false" }, "BTCUSDT")).toEqual(refused);
  });

  it("refuses an answer for another symbol", () => {
    const refused = { kind: "refused", code: "symbol_mismatch" };
    expect(read.parseByPrice(body(), "ETHUSDT")).toEqual(refused);
  });

  it.each<[string, (b: Body) => void]>([
    ["a float notional", (b) => void ((b.items[0] ?? {})["long_notional_usd"] = 1.5)],
    ["a zero print count", (b) => void ((b.items[0] ?? {})["prints"] = 0)],
    ["a bad time", (b) => void (b["from"] = "yesterday")],
    ["no coverage", (b) => void (b["meta"] = {})],
    ["21 items", (b) => void (b.items = Array<Record<string, unknown>>(21).fill(b.items[0] ?? {}))],
    ["no symbol", (b) => void delete b["symbol"]],
    ["bucket_ticks 0", (b) => void (b["bucket_ticks"] = 0)],
  ])("refuses %s as malformed", (_n, mutate) => {
    const b = body();
    mutate(b);
    expect(read.parseByPrice(b, "BTCUSDT")).toEqual({ kind: "refused", code: "malformed" });
  });
});

describe("fetchLiquidationsByPrice", () => {
  beforeEach(() => apiFetch.mockReset());
  const signal = new AbortController().signal;
  const reply = (status: number, b: unknown): void => {
    apiFetch.mockResolvedValueOnce(new Response(JSON.stringify(b), { status }));
  };
  const fetchIt = () => read.fetchLiquidationsByPrice({ symbol: "BTCUSDT", signal });

  it("asks for K01's defaults by name, leaves `from` to the server, and reads the answer", async () => {
    reply(200, s.EXAMPLE);
    expect(await fetchIt()).toEqual({ kind: "ok", answer: s.EXAMPLE });
    const path = "/api/v1/market/liquidations/by-price?symbol=BTCUSDT&bucket_ticks=20&top=5";
    expect(apiFetch.mock.calls[0]?.[0]).toBe(path);
    expect(apiFetch.mock.calls[0]?.[1]?.method).toBe("GET");
  });

  it("refuses a 200 without the flag, returns a refusal's code, and null on no answer", async () => {
    reply(200, stripped());
    expect(await fetchIt()).toEqual({ kind: "refused", code: "estimated_missing" });
    reply(422, { code: "validation_failed" });
    expect(await fetchIt()).toEqual({ kind: "failed", status: 422, code: "validation_failed" });
    apiFetch.mockRejectedValueOnce(new TypeError("down"));
    expect(await fetchIt()).toEqual({ kind: "failed", status: null, code: null });
  });

  it("sends nothing once aborted", async () => {
    const ctl = new AbortController();
    ctl.abort();
    const r = await read.fetchLiquidationsByPrice({ symbol: "BTCUSDT", signal: ctl.signal });
    expect(r.kind).toBe("failed");
    expect(apiFetch).not.toHaveBeenCalled();
  });
});

describe("the layer model", () => {
  it("is off by default and takes the badge from the flag alone", () => {
    expect(model.DEFAULT_LIQ_BY_PRICE).toBe(false);
    expect(model.layerOf(s.FULL).estimated).toBe(false);
    expect(model.layerOf(s.FLAGGED).estimated).toBe(true);
  });

  it("clamps the day to coverage: partial from covered_from, never a full-day claim", () => {
    const partial = { kind: "partial", fromMs: Date.parse("2026-09-14T06:30:00.250Z") };
    expect(model.coverageOf(s.EXAMPLE)).toEqual(partial);
    expect(model.coverageOf(s.FULL)).toEqual({ kind: "full", fromMs: Date.parse(s.FULL.from) });
  });

  it("reads no_coverage as not recorded and draws no bucket even if one is served", () => {
    expect(model.layerOf({ ...s.NOT_RECORDED, items: s.EXAMPLE.items })).toMatchObject({
      coverage: { kind: "not-recorded", firstAvailableMs: Date.parse("2026-09-15T08:00:00Z") },
      buckets: [],
    });
    const never = { kind: "not-recorded", firstAvailableMs: null };
    expect(model.coverageOf(s.NEVER_RECORDED)).toEqual(never);
  });

  it("checks view-as before the permission leg", () => {
    const held = { kind: "held", targetId: "u-2", targetName: "alex", state: "active" } as const;
    const times = { startedAtMs: 0, expiresAtMs: 1, offsetMs: 0 };
    const as = (p: string[]) => model.toggleAccess({ kind: "none" }, p, "n");
    const viewAs = { kind: "view-as", user: "alex", noticeId: "n" };
    expect(model.toggleAccess({ ...held, ...times }, ["settings:write"], "n")).toEqual(viewAs);
    expect(as(["settings:write"])).toEqual({ kind: "persisted" });
    expect(as(["marketdata:read"])).toEqual({ kind: "session" });
  });
});
