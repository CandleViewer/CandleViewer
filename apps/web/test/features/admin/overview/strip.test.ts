/**
 * E42-S01 (#1022) BQ-6: the "Needs your action" strip's items, from the store the overview shares,
 * only for the sources served today (E42-D03 §14 `strip.*`), each linked through the app's route
 * table and never through a path the server sent; the footer once a strip read was answered; the
 * area withdrawn on a `403` (BQ-8).
 */
import { describe, expect, it } from "vitest";
import { ADMIN_LINKS, routePath } from "../../../../src/features/admin/overview/links";
import type { AdminReadState, ReadEntry } from "../../../../src/features/admin/overview/readStore";
import {
  areaEntered,
  denial,
  STRIP_READS,
  stripItems,
} from "../../../../src/features/admin/overview/strip";
import { ROUTE_MANIFEST } from "../../../../src/routes/manifest";

const IDLE = { phase: "idle", inFlight: false } as const;
const AT = "2026-10-22T14:02:11Z";

function state(patch: Partial<Record<keyof AdminReadState, Partial<ReadEntry<unknown>>>> = {}) {
  const ids = ["overview", "capacity", "health", "flags", "audit", "backups", "invites"] as const;
  return Object.fromEntries(
    ids.map((id) => [id, { ...IDLE, ...patch[id] }]),
  ) as unknown as AdminReadState;
}
const ok = (data: unknown): Partial<ReadEntry<unknown>> => ({ phase: "ok", data, okAt: 1 });
const overview = (users: object, accounts: object) =>
  ok({
    users: { status: "ok", generated_at: AT, ...users },
    accounts: { status: "ok", generated_at: AT, ...accounts },
  });
const capacity = (tier_source: string) =>
  ok({ subaccounts: { status: "ok", generated_at: AT, tier_source, used: 3 } });

describe("the strip's items", () => {
  it("reads only the overview and the capacity report, on every admin route", () => {
    expect(STRIP_READS).toEqual(["overview", "capacity"]);
  });

  it("draws no strip while a source is unread and nothing needs the owner (D02 D4)", () => {
    expect(stripItems(state(), "live")).toBeUndefined();
    const half = state({ overview: overview({ without_mfa: 0 }, {}) });
    expect(stripItems(half, "live")).toBeUndefined();
  });

  it("reads Nothing needs your action only once every source was read", () => {
    const clear = state({
      overview: overview({ without_mfa: 0 }, { keys_expiring_30d: 0, keys_invalid: 0 }),
      capacity: capacity("recorded"),
    });
    expect(stripItems(clear, "live")).toEqual([]);
  });

  it("words OV-3's items from the counts, singular for one, LIVE on the accounts' items", () => {
    const s = state({
      overview: overview({ without_mfa: 2 }, { keys_expiring_30d: 1, keys_invalid: 3 }),
      capacity: capacity("unrecorded"),
    });
    const items = stripItems(s, "live");
    expect(items).toEqual([
      {
        id: "no_mfa",
        label: "2 active users without two-factor → Users",
        href: "/admin/users",
        kind: "other",
        severity: "warning",
      },
      {
        id: "key_expiry",
        label: "1 key expires within 30 days → Accounts and keys",
        href: "/admin/accounts",
        kind: "other",
        severity: "warning",
        env: "live",
      },
      {
        id: "keys_invalid",
        label: "3 keys rejected by Bybit → Accounts and keys",
        href: "/admin/accounts",
        kind: "other",
        severity: "warning",
        env: "live",
      },
      {
        id: "tier",
        label: "Tier not recorded → Record tier",
        href: "/admin/users",
        kind: "other",
        severity: "warning",
      },
    ]);
    // A slice's `generated_at` is when it was read, not when its condition was raised: no item is
    // timed, so a re-read never reorders them (C-5330-08).
    expect(items?.map((i) => "at" in i)).toEqual([false, false, false, false]);
  });

  it("shows an item while another source is still unread, with no env for an unknown one", () => {
    const s = state({ overview: overview({ without_mfa: 1 }, {}) });
    expect(stripItems(s, "unknown")?.map((i) => [i.label, i.env])).toEqual([
      ["1 active user without two-factor → Users", undefined],
    ]);
  });

  it("links through the route table, never a path the answer carries", () => {
    // A slice smuggling its own link: the strip's link is still the manifest's.
    const s = state({
      overview: overview(
        { without_mfa: 1, href: "https://example.invalid/x", path: "/elsewhere" },
        { keys_invalid: 1, url: "javascript:alert(1)" },
      ),
      capacity: capacity("recorded"),
    });
    const hrefs = stripItems(s, "live")?.map((i) => i.href);
    expect(hrefs).toEqual(["/admin/users", "/admin/accounts"]);
    const manifest = new Set(ROUTE_MANIFEST.map((e) => e.path));
    for (const link of Object.keys(ADMIN_LINKS) as (keyof typeof ADMIN_LINKS)[]) {
      expect(manifest.has(routePath(link) ?? ""), link).toBe(true);
    }
  });

  // D03 OV-2 limits the all-clear to "every read ok", and D02 D4 marks an old value, which an item
  // cannot carry: a failed read's kept counts speak for nothing (A-5330-06, C-5330-07).
  it("reads only the current answers: no item and no all-clear from a failed read's counts", () => {
    const clear = overview({ without_mfa: 0 }, { keys_expiring_30d: 0, keys_invalid: 0 });
    const failed = (entry: Partial<ReadEntry<unknown>>): Partial<ReadEntry<unknown>> => ({
      ...entry,
      phase: "failed",
      reason: "status",
      status: 503,
    });
    expect(
      stripItems(state({ overview: failed(clear), capacity: capacity("recorded") }), "live"),
    ).toBeUndefined();
    expect(
      stripItems(state({ overview: clear, capacity: failed(capacity("recorded")) }), "live"),
    ).toBeUndefined();
    const kept = overview({ without_mfa: 1 }, { keys_expiring_30d: 2, keys_invalid: 0 });
    const s = state({ overview: failed(kept), capacity: capacity("unrecorded") });
    expect(stripItems(s, "live")?.map((i) => i.id)).toEqual(["tier"]);
    expect(
      stripItems({ ...s, capacity: { ...s.capacity, phase: "not_built" } }, "live"),
    ).toBeUndefined();
  });
});

describe("the footer and the withdrawn area", () => {
  it("says the entry was recorded once a strip read answered 2xx (D27), never before", () => {
    expect(areaEntered(state())).toBe(false);
    expect(
      areaEntered(state({ overview: { phase: "failed", reason: "status", status: 503 } })),
    ).toBe(false);
    expect(areaEntered(state({ capacity: ok({}) }))).toBe(true);
  });

  it("withdraws the area on the first read the server refused, with its Ref", () => {
    expect(denial(state())).toBeNull();
    const refused = state({ health: { phase: "denied", refId: "urn:cv:req:1" } });
    expect(denial(refused)).toEqual({ refId: "urn:cv:req:1" });
  });
});
