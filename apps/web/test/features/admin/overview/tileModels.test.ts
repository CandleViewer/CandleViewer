/**
 * E42-S01 (#1022): SCR-120's nine tiles as data (E42-D03 §6, D8; E42-D02 D4's "old" and "down").
 * Each tile resolves on its own read: loading until it answers, fresh with its "as of", old with
 * "stale since" after a failed re-read, down with no number for a field not received, and
 * "Unavailable — not built yet" for a source not served or not mounted.
 */
import { describe, expect, it } from "vitest";
import type { ReadEntry, AdminReadState } from "../../../../src/features/admin/overview/readStore";
import {
  accountsTile,
  allAnswered,
  auditTile,
  BANDS,
  failureWords,
  flagsTile,
  healthTile,
  profilesTile,
  recorderTile,
  securityTile,
  tileModel,
  tradingTile,
  usersTile,
} from "../../../../src/features/admin/overview/tileModels";

const T0 = Date.UTC(2026, 9, 22, 14, 2, 11);
const AT = "2026-10-22T14:02:11Z";
const IDLE = { phase: "idle", inFlight: false } as const;

/** A store state: every read idle unless `patch` says otherwise. */
function state(patch: Partial<Record<keyof AdminReadState, Partial<ReadEntry<unknown>>>> = {}) {
  const ids = ["overview", "capacity", "health", "flags", "audit", "backups", "invites"] as const;
  return Object.fromEntries(
    ids.map((id) => [id, { ...IDLE, ...patch[id] }]),
  ) as unknown as AdminReadState;
}
const ok = (data: unknown, okAt = T0): Partial<ReadEntry<unknown>> => ({ phase: "ok", data, okAt });
const OVERVIEW = {
  generated_at: AT,
  users: { status: "ok", generated_at: AT, total: 9, active: 6, without_mfa: 0 },
  accounts: {
    status: "ok",
    generated_at: AT,
    total: 5,
    enabled: 5,
    keys_expiring_30d: 1,
    keys_invalid: 0,
  },
  recorder: { status: "unavailable", detail: "recorder: no provider wired", generated_at: AT },
  storage: {
    status: "ok",
    generated_at: AT,
    used_bytes: 44_023_414_784,
    free_bytes: 402_653_184_000,
    days_until_full: null,
  },
  // Today's main: no OMS port is wired, so the slice serves none of its fields (E42-D03 §6).
  trading: { status: "unavailable", detail: "trading: no provider wired", generated_at: AT },
  incidents: { status: "ok", generated_at: AT, open: 1 },
};
const FLAGS = {
  resolution: "stored",
  items: [
    { key: "maintenance.mode", kind: "boolean", value: false },
    { key: "rules.graph_editor", kind: "boolean", value: true },
    { key: "heatmap.v2", kind: "percentage", value: true },
  ],
};
const row = (label: string, value: string | number | null) => ({ label, value });

describe("the tile list", () => {
  it("draws nine tiles in three bands, in §6's order", () => {
    expect(BANDS).toEqual([
      ["trading", "health", "recorder"],
      ["users", "accounts", "profiles"],
      ["audit", "security", "flags"],
    ]);
  });

  it("loads every tile until its own read answers, and links each heading to its screen", () => {
    const s = state();
    const hrefs = BANDS.flat().map((key) => {
      const model = tileModel(key, s, "live");
      if (key !== "profiles" && key !== "security") expect(model.state, key).toBe("loading");
      return model.href;
    });
    expect(hrefs).toEqual([
      ...["/risk", "/admin/health", "/admin/recorder"],
      ...["/admin/users", "/admin/accounts", "/admin/profiles"],
      ...["/admin/audit", "/admin/security", "/admin/flags"],
    ]);
    expect(allAnswered(s)).toBe(false);
  });

  it("is answered once every read the page shows has answered, in any state", () => {
    const answered = state({
      overview: ok(OVERVIEW),
      capacity: { phase: "failed", reason: "network" },
      health: { phase: "not_built" },
      flags: ok(FLAGS),
      audit: ok({ items: [] }),
      backups: { phase: "not_built" },
      invites: ok({ count: 0 }),
    });
    expect(allAnswered(answered)).toBe(true);
  });
});

describe("Trading safety: never an old or a guessed switch state", () => {
  it("reads today's main: unavailable, no value but the flags read's maintenance line (OV-6)", () => {
    const model = tradingTile(state({ overview: ok(OVERVIEW), flags: ok(FLAGS) }), "live");
    expect(model).toMatchObject({
      state: "unavailable",
      detail: "trading: no provider wired",
      env: "live",
      retry: [],
    });
    expect(model.rows).toEqual([
      row("Live trading", null),
      row("Kill switch", "unknown"),
      row("Open positions", null),
      { ...row("Maintenance", "off (flags read)"), asOf: T0 }, // its own read's time (C-5330-11)
    ]);
  });

  it("reads the served switch when the slice is ok, with its as-of", () => {
    const trading = {
      status: "ok",
      generated_at: AT,
      live_enabled: true,
      kill_switch_engaged: false,
      open_positions: 2,
    };
    const model = tradingTile(state({ overview: ok({ ...OVERVIEW, trading }) }), "unknown");
    expect(model).toMatchObject({ state: "ready", tone: "ok", asOf: T0, env: undefined });
    expect(model.rows.slice(0, 3)).toEqual([
      row("Live trading", "on"),
      row("Kill switch", "off"),
      row("Open positions", 2),
    ]);
    expect(model.rows[3]).toEqual(row("Maintenance", null)); // the flags read has not answered
  });

  it("shows no switch state from an old read: a failed re-read is an error, not a stale 'off'", () => {
    for (const status of ["ok", "error"]) {
      const trading = { status, generated_at: AT, live_enabled: true, kill_switch_engaged: true };
      const s = state({
        overview: { phase: "failed", data: { trading }, failedAt: T0, reason: "timeout" },
      });
      const model = tradingTile(s, "live");
      expect(model, status).toMatchObject({
        state: "error",
        detail: "no answer within 3 s",
        retry: ["overview"],
      });
      expect(model.rows.slice(0, 2), status).toEqual([
        row("Live trading", null),
        row("Kill switch", "unknown"),
      ]);
    }
  });

  // E42-D03 preface (7) and §6: the server reads the kill switch first and returns every part it
  // read, so a field the current answer served shows whatever the slice's status (C-5330-01).
  it("shows each field the current answer served, whatever the slice's status (22's example)", () => {
    // `22` getAdminOverview `degraded`: positions have no provider, both switches were read.
    const trading = {
      status: "unavailable",
      detail: "open_positions: no provider wired",
      generated_at: AT,
      live_enabled: false,
      kill_switch_engaged: false,
    };
    const model = tradingTile(state({ overview: ok({ ...OVERVIEW, trading }) }), "live");
    expect(model).toMatchObject({
      state: "unavailable",
      detail: "open_positions: no provider wired",
      retry: [],
    });
    expect(model.rows.slice(0, 3)).toEqual([
      row("Live trading", "off"),
      row("Kill switch", "off"),
      row("Open positions", null),
    ]);
  });

  it("reads an engaged switch from a slice that erred after reading it, with Retry", () => {
    const trading = {
      status: "error",
      detail: "timed out after 300 ms",
      generated_at: AT,
      kill_switch_engaged: true,
    };
    const model = tradingTile(state({ overview: ok({ ...OVERVIEW, trading }) }), "demo");
    expect(model).toMatchObject({ state: "error", detail: "timed out after 300 ms" });
    expect(model.retry).toEqual(["overview"]);
    expect(model.rows.slice(0, 3)).toEqual([
      row("Live trading", null),
      row("Kill switch", "on"),
      row("Open positions", null),
    ]);
  });

  it("links maintenance ON to its screen with its time, and blanks it unless the flags read stands", () => {
    const on = {
      resolution: "stored",
      items: [{ key: "maintenance.mode", value: true, updated_at: "2026-10-22T14:02:00Z" }],
    };
    const model = tradingTile(state({ overview: ok(OVERVIEW), flags: ok(on) }), "live");
    expect(model.rows[3]).toEqual({
      label: "Maintenance",
      value: "ON since 14:02 UTC → Maintenance",
      href: "/admin/maintenance",
      asOf: T0, // the flags read's own time (C-5330-11)
    });
    const failClosed = {
      resolution: "fail_closed",
      items: [{ key: "maintenance.mode", value: true }],
    };
    const blank = tradingTile(state({ overview: ok(OVERVIEW), flags: ok(failClosed) }), "live");
    expect(blank.rows[3]).toEqual(row("Maintenance", null));
  });
});

describe("Health: the worst component speaks, not_deployed is never healthy", () => {
  const report = (components: unknown[], overall = "degraded") => ({
    overall,
    server_time: AT,
    components,
  });

  it("reads a degraded component's words, its last good, and what stops working (OV-4)", () => {
    const s = state({
      health: ok(
        report([
          { name: "postgres", state: "healthy" },
          {
            name: "bybit_private_ws",
            state: "degraded",
            detail: "reconnected 3× in the last hour",
            last_good_at: "2026-10-22T14:01:40Z",
          },
        ]),
      ),
      overview: ok(OVERVIEW),
    });
    expect(healthTile(s)).toMatchObject({
      state: "ready",
      tone: "warning",
      stateWord: "Degraded",
      detail: "bybit_private_ws reconnected 3× in the last hour",
      lastGoodAt: Date.UTC(2026, 9, 22, 14, 1, 40),
      stopsWorking: "order and position updates may lag; REST reconcile runs.",
      asOf: T0,
      rows: [row("bybit_private_ws", "degraded"), row("Open incidents", 1)],
    });
  });

  it("puts down ahead of degraded, and never doubles a name its detail already starts with", () => {
    const s = state({
      health: ok(
        report(
          [
            { name: "oms", state: "degraded" },
            { name: "postgres", state: "down", detail: "postgres unreachable" },
          ],
          "down",
        ),
      ),
    });
    expect(healthTile(s)).toMatchObject({
      tone: "danger",
      stateWord: "Down",
      detail: "postgres unreachable",
      stopsWorking: "new orders are off; cancel and close still work.",
    });
  });

  it("counts components not deployed, in the neutral ring, never as healthy (OV-6)", () => {
    const s = state({
      health: ok(
        report(
          [
            { name: "postgres", state: "healthy" },
            { name: "bars_writer", state: "not_deployed" },
            { name: "rule_engine", state: "not_deployed" },
          ],
          "healthy",
        ),
      ),
    });
    expect(healthTile(s)).toMatchObject({
      state: "ready",
      tone: "neutral",
      stateWord: "2 components not deployed — showing live frames only",
      rows: [],
    });
    const one = state({
      health: ok(report([{ name: "bars_writer", state: "not_deployed" }], "healthy")),
    });
    expect(healthTile(one).stateWord).toBe("1 component not deployed — showing live frames only");
  });

  it("reads open incidents from the current overview only: '— not received' after it failed", () => {
    const fine = ok(report([{ name: "postgres", state: "healthy" }], "healthy"));
    const incidents = (overview: Partial<ReadEntry<unknown>>) =>
      healthTile(state({ health: fine, overview })).rows.filter(
        (r) => r.label === "Open incidents",
      );
    expect(incidents(ok(OVERVIEW))).toEqual([row("Open incidents", 1)]);
    expect(incidents({ phase: "failed", data: OVERVIEW, failedAt: T0, reason: "network" })).toEqual(
      [row("Open incidents", null)],
    );
    expect(incidents({ phase: "not_built" })).toEqual([row("Open incidents", null)]);
    expect(incidents({ phase: "idle", inFlight: true })).toEqual([]); // not answered yet: no line
  });

  it("ranks a component only by its own state words, never an inherited name", () => {
    const s = state({
      health: ok(
        report(
          [
            { name: "probe", state: "constructor" },
            { name: "postgres", state: "down", detail: "postgres unreachable" },
          ],
          "down",
        ),
      ),
    });
    expect(healthTile(s)).toMatchObject({
      tone: "danger",
      stateWord: "Down",
      detail: "postgres unreachable",
      stopsWorking: "new orders are off; cancel and close still work.",
      rows: [row("postgres", "down")],
    });
  });

  it("reads ok when every component is healthy, and old after a failed re-read", () => {
    const fine = ok(report([{ name: "postgres", state: "healthy" }], "healthy"));
    expect(healthTile(state({ health: fine }))).toMatchObject({ state: "ready", tone: "ok" });
    const old = state({ health: { ...fine, phase: "failed", failedAt: T0, reason: "network" } });
    expect(healthTile(old)).toMatchObject({
      state: "ready",
      tone: "stale",
      staleSince: T0,
      retry: ["health"],
    });
    const down = state({ health: { phase: "failed", reason: "status", status: 503 } });
    expect(healthTile(down)).toMatchObject({
      state: "error",
      detail: "the server answered 503",
      retry: ["health"],
    });
  });
});

describe("the overview-fed tiles: each slice resolves on its own (D8)", () => {
  it("shows the recorder's own error with Retry while every other slice reads normally (AC3)", () => {
    const failing = {
      ...OVERVIEW,
      recorder: { status: "error", detail: "timed out after 300 ms", generated_at: AT },
    };
    const s = state({
      overview: { ...ok(failing), sliceGoodAt: { recorder: Date.UTC(2026, 9, 22, 14, 1, 40) } },
    });
    expect(recorderTile(s)).toMatchObject({
      state: "error",
      detail: "timed out after 300 ms",
      lastGoodAt: Date.UTC(2026, 9, 22, 14, 1, 40),
      retry: ["overview"],
    });
    expect(usersTile(s)).toMatchObject({ state: "ready", tone: "ok", asOf: T0 });
    expect(accountsTile(s, "live")).toMatchObject({ state: "ready", tone: "ok" });
  });

  it("reads the recorder unavailable over fresh storage lines, the storage's as-of kept (OV-6)", () => {
    const model = recorderTile(state({ overview: ok(OVERVIEW) }));
    expect(model).toMatchObject({
      state: "unavailable",
      detail: "recorder: no provider wired",
      asOf: T0,
      retry: [],
    });
    expect(model.rows).toEqual([
      row("Disk used", "44.0 GB"),
      row("Disk free", "402.7 GB"),
      row("Days until full", "not measured"),
    ]);
  });

  it("keeps the last-known values after a failed re-read, marked stale, with Retry (AC5)", () => {
    const s = state({
      overview: {
        phase: "failed",
        data: OVERVIEW,
        okAt: T0,
        failedAt: T0 + 30_000,
        reason: "status",
        status: 503,
      },
      invites: ok({ count: 1 }),
    });
    expect(usersTile(s)).toMatchObject({
      state: "ready",
      tone: "stale",
      staleSince: T0 + 30_000,
      retry: ["overview"],
      rows: [
        row("Total", 9),
        row("Active", 6),
        row("Without two-factor", 0),
        row("Invites pending", 1),
      ],
    });
    expect(usersTile(s).asOf).toBeUndefined(); // "stale since" replaces the "as of" (D02 D4)
  });

  it("is down with no number when a failed read kept nothing, and says why", () => {
    const s = state({ overview: { phase: "failed", reason: "unreadable" } });
    expect(usersTile(s)).toMatchObject({
      state: "error",
      detail: "the answer could not be read",
      rows: [],
      retry: ["overview"],
    });
  });

  it("reads a slice the answer left out as unavailable, not received", () => {
    expect(usersTile(state({ overview: ok({ items: [] }) }))).toMatchObject({
      state: "unavailable",
      detail: "not received",
      retry: [],
    });
  });

  it("loads only the tile whose Retry runs, and leaves the others showing their state", () => {
    const s = state({
      overview: { phase: "failed", reason: "network", inFlight: true, retriedBy: "users" },
    });
    expect(usersTile(s).state).toBe("loading");
    expect(accountsTile(s, "live").state).toBe("error");
  });

  it("keeps a running Retry on its tile, busy, so it keeps focus; a first load has none (A-5330-01)", () => {
    const retried = { phase: "failed", reason: "network", inFlight: true } as const;
    const s = state({
      overview: { ...retried, retriedBy: "users" },
      health: { ...retried, retriedBy: "health" },
      flags: { ...ok(FLAGS), inFlight: true, retriedBy: "flags" },
    });
    expect(usersTile(s)).toMatchObject({ state: "loading", retry: ["overview"] });
    expect(healthTile(s)).toMatchObject({ state: "loading", retry: ["health"] });
    expect(flagsTile(s)).toMatchObject({ state: "loading", retry: ["flags"] });
    const first = state({ overview: { phase: "idle", inFlight: true } });
    expect(usersTile(first)).toMatchObject({ state: "loading", retry: [] });
  });
});

describe("Accounts and keys: the slice, the capacity line, the withdrawal line", () => {
  const cap = (subaccounts: unknown) =>
    state({ overview: ok(OVERVIEW), capacity: ok({ subaccounts }) });

  it("reads the counts, the recorded tier's line and the unmounted withdrawal read (OV-6)", () => {
    const model = accountsTile(
      cap({
        status: "ok",
        tier: "regular",
        cap: 5,
        used: 3,
        tier_source: "recorded",
        recorded_at: "2026-09-12T09:00:00Z",
      }),
      "live",
    );
    expect(model).toMatchObject({ env: "live", state: "ready" });
    expect(model.rows).toEqual([
      row("Total", 5),
      row("Enabled", 5),
      row("Keys expiring within 30 days", 1),
      row("Keys rejected by Bybit", 0),
      row("Withdrawal permission", "Unavailable — not built yet"),
    ]);
    expect(model.note).toBe("3 of 5 sub-accounts used · Regular tier, recorded 2026-09-12");
  });

  it.each([
    [
      { status: "ok", tier: null, cap: null, used: 3, tier_source: "unrecorded" },
      "3 sub-accounts in use · Tier not recorded — record it to see your cap",
    ],
    [
      { status: "ok", tier: "regular", cap: 5, used: 6, tier_source: "recorded" },
      "6 sub-accounts in use · Regular tier allows 5. Bybit lets accounts keep sub-accounts made " +
        "before 14 August 2026 — or the recorded tier may be wrong.",
    ],
    [
      { status: "error", tier: "business_kyc", cap: 20, tier_source: "recorded" },
      "Business KYC tier allows 20 · sub-accounts in use: unavailable right now",
    ],
    [
      { status: "error", used: 4, tier_source: "recorded" },
      "4 sub-accounts in use · cap unavailable right now",
    ],
    [{ status: "error" }, "Sub-account capacity unavailable right now"],
  ])("words the capacity line as §14's cap.* does: %j", (subaccounts, note) => {
    expect(accountsTile(cap(subaccounts), "demo").note).toBe(note);
  });

  it("reads not built yet for a capacity or invites read answered 404 or 501 (C-5330-04)", () => {
    const s = state({
      overview: ok(OVERVIEW),
      capacity: { phase: "not_built" },
      invites: { phase: "not_built" },
    });
    expect(accountsTile(s, "live")).toMatchObject({
      note: "Sub-account capacity: Unavailable — not built yet",
      retry: [],
    });
    expect(usersTile(s).rows.at(-1)).toEqual(row("Invites pending", "Unavailable — not built yet"));
    expect(usersTile(s).retry).toEqual([]);
  });

  it("names a tier the copy does not know as served, never an inherited name (C-5330-06)", () => {
    for (const tier of ["constructor", "toString", "pro"]) {
      const subaccounts = { status: "ok", tier, cap: 5, used: 3, tier_source: "recorded" };
      expect(accountsTile(cap(subaccounts), "live").note, tier).toBe(
        `3 of 5 sub-accounts used · ${tier} tier`,
      );
    }
  });

  it("says capacity is down when its read failed, and puts it on the tile's Retry", () => {
    const s = state({ overview: ok(OVERVIEW), capacity: { phase: "failed", reason: "network" } });
    expect(accountsTile(s, "live")).toMatchObject({
      note: "Sub-account capacity unavailable right now",
      retry: ["capacity"],
    });
  });
});

// C-5330-11: Maintenance reads `flags`, Invites pending reads `invites` and the capacity line reads
// `capacity`: each is asked once per entry, under a tile whose "as of" is the cycled overview's. Five
// minutes into a visit the overview has answered again, so each of the three says when its own read
// answered, never the tile's time.
describe("a line fed by an entry snapshot prints its own read time (C-5330-11)", () => {
  const LATE = T0 + 300_000;
  const STAMP = new Date(LATE).toISOString();
  const cycled = {
    ...OVERVIEW,
    generated_at: STAMP,
    users: { ...OVERVIEW.users, generated_at: STAMP },
    accounts: { ...OVERVIEW.accounts, generated_at: STAMP },
    trading: {
      status: "ok",
      generated_at: STAMP,
      live_enabled: false,
      kill_switch_engaged: false,
      open_positions: 0,
    },
  };
  /** A store state five minutes in: the overview just answered, `patch` is what was read at T0. */
  const later = (patch: Parameters<typeof state>[0]) =>
    state({ overview: ok(cycled, LATE), ...patch });
  const maintenance = (flags: Partial<ReadEntry<unknown>>) =>
    tradingTile(later({ flags }), "live").rows[3];

  it.each([
    ["off", FLAGS],
    ["on", { resolution: "stored", items: [{ key: "maintenance.mode", value: true }] }],
  ])("prints the flags read's own time on the Maintenance line that reads %s", (_name, flags) => {
    const model = tradingTile(later({ flags: ok(flags, T0) }), "live");
    expect(model).toMatchObject({ state: "ready", tone: "ok", asOf: LATE }); // the overview's
    expect(model.rows[3]?.asOf).toBe(T0); // the flags read's
  });

  it("prints no time where the Maintenance line reads '—'", () => {
    const failClosed = {
      resolution: "fail_closed",
      items: [{ key: "maintenance.mode", value: true }],
    };
    const failedAfterOk = {
      ...ok(FLAGS, T0),
      phase: "failed",
      failedAt: LATE,
      reason: "network",
    } as const;
    for (const flags of [
      {},
      ok({ resolution: "stored", items: [] }, T0),
      ok(failClosed, T0),
      failedAfterOk,
      { phase: "not_built" },
    ] as const) {
      expect(maintenance(flags), JSON.stringify(flags)).toEqual(row("Maintenance", null));
    }
  });

  it("prints the invites read's own time on Invites pending, never the tile's", () => {
    const model = usersTile(later({ invites: ok({ count: 2 }, T0) }));
    expect(model).toMatchObject({ state: "ready", tone: "ok", asOf: LATE });
    expect(model.rows.at(-1)).toEqual({ ...row("Invites pending", 2), asOf: T0 });
  });

  it("prints no time where Invites pending reads '—' or not built yet", () => {
    const failedAfterOk = { ...ok({ count: 2 }, T0), phase: "failed", failedAt: LATE } as const;
    for (const invites of [failedAfterOk, { phase: "failed", reason: "network" }] as const) {
      expect(usersTile(later({ invites })).rows.at(-1)).toEqual(row("Invites pending", null));
    }
    const notBuilt = usersTile(later({ invites: { phase: "not_built" } })).rows.at(-1);
    expect(notBuilt).toEqual(row("Invites pending", "Unavailable — not built yet"));
  });

  it.each([
    ["recorded", { status: "ok", tier: "regular", cap: 5, used: 3, tier_source: "recorded" }],
    ["unrecorded", { status: "ok", tier: null, cap: null, used: 3, tier_source: "unrecorded" }],
    ["over the cap", { status: "ok", tier: "regular", cap: 5, used: 6, tier_source: "recorded" }],
    [
      "used unavailable",
      { status: "error", tier: "business_kyc", cap: 20, tier_source: "recorded" },
    ],
    ["tier unavailable", { status: "error", used: 4, tier_source: "recorded" }],
  ])("prints the capacity read's own time after the %s line", (_name, subaccounts) => {
    const model = accountsTile(later({ capacity: ok({ subaccounts }, T0) }), "live");
    expect(model).toMatchObject({ state: "ready", tone: "ok", asOf: LATE });
    expect(model.noteAsOf).toBe(T0);
  });

  it("prints no time where the capacity line reads down, not built yet or not asked yet", () => {
    for (const capacity of [
      ok({ subaccounts: { status: "error" } }, T0), // nothing readable: "unavailable right now"
      { phase: "failed", reason: "network" },
      { phase: "not_built" },
      {},
    ] as const) {
      const model = accountsTile(later({ capacity }), "live");
      expect(model.noteAsOf, JSON.stringify(capacity)).toBeUndefined();
    }
  });
});

describe("the other tiles", () => {
  it("Profiles and limits: no slice serves it, so it is not built yet (CG-6)", () => {
    expect(profilesTile()).toMatchObject({
      state: "unavailable",
      detail: "not built yet",
      rows: [],
      retry: [],
    });
  });

  it("Flags: counts the list and the flags on; a fail-closed list is not the stored state", () => {
    expect(flagsTile(state({ flags: ok(FLAGS) }))).toMatchObject({
      state: "ready",
      tone: "ok",
      rows: [row("Total", 3), row("Enabled", 2)],
    });
    expect(flagsTile(state({ flags: ok({ resolution: "fail_closed", items: [] }) }))).toMatchObject(
      {
        state: "unavailable",
        detail: "flag store unreachable — every flag shows its fail-closed value",
        rows: [],
        retry: ["flags"],
      },
    );
  });

  it("Flags: a fail-closed list kept through a failed re-read is still no count (C-5330-07)", () => {
    const failClosed = { resolution: "fail_closed", items: FLAGS.items };
    const kept = { ...ok(failClosed), phase: "failed", failedAt: T0, reason: "network" } as const;
    expect(flagsTile(state({ flags: kept }))).toMatchObject({
      state: "unavailable",
      detail: "flag store unreachable — every flag shows its fail-closed value",
      rows: [],
      retry: ["flags"],
    });
  });

  it("Audit: the three latest entries and the audited-read marker, no event count (D9)", () => {
    const entry = (id: number) => ({
      id,
      ts: AT,
      action: "x",
      outcome: "success",
      severity: "info",
    });
    const model = auditTile(state({ audit: ok({ items: [1, 2, 3, 4].map(entry) }) }));
    expect(model.audit?.map((e) => e.id)).toEqual([1, 2, 3]);
    expect(model.marker).toBe("Viewing this log is recorded — Audit log viewed (admin.audit_read)");
    expect(auditTile(state()).audit).toBeUndefined();
  });

  it("Security and backups: the summary is not built; the backups read speaks for its line", () => {
    expect(securityTile(state({ backups: { phase: "not_built" } }))).toMatchObject({
      state: "unavailable",
      detail: "not built yet",
      rows: [row("Last backup", "Unavailable — not built yet")],
      retry: [],
    });
    const runs = {
      items: [
        { status: "ok", finished_at: "2026-10-22T04:00:00Z" },
        { status: "failed", finished_at: "2026-10-21T04:00:00Z" },
      ],
    };
    expect(securityTile(state({ backups: ok(runs) })).rows).toEqual([
      row("Last backup", "04:00 UTC · ok"),
    ]);
    expect(securityTile(state({ backups: ok({ items: [] }) })).rows).toEqual([
      row("Last backup", "none yet"),
    ]);
    expect(securityTile(state({ backups: { phase: "failed", reason: "network" } }))).toMatchObject({
      rows: [row("Last backup", null)],
      retry: ["backups"],
    });
  });
});

describe("failureWords", () => {
  it("names a failed read in the client's own words, never the server's message", () => {
    expect(failureWords("timeout", undefined)).toBe("no answer within 3 s");
    expect(failureWords("network", undefined)).toBe("the server could not be reached");
    expect(failureWords("status", 429)).toBe("the server answered 429");
    expect(failureWords("unreadable", undefined)).toBe("the answer could not be read");
  });
});
