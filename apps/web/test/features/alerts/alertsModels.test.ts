/** Row model, history/CSV, "until tomorrow" and the WS source (E40-S01). Pure units, injected clocks. */
import { describe, expect, it, vi } from "vitest";
import { chartHref } from "../../../src/features/alerts/AlertsRoute";
import {
  describeCondition,
  failedDesktopAlerts,
  groupOf,
  inTab,
  sortRows,
  statusOf,
} from "../../../src/features/alerts/alertRowModel";
import {
  csvCell,
  groupFirings,
  historyCsv,
  statusWord,
  timeOf,
} from "../../../src/features/alerts/alertHistory";
import { nextLocalMidnightMs } from "../../../src/features/alerts/snoozeTomorrow";
import { createWsAlertsSource, frameFor } from "../../../src/features/alerts/alertsWsSource";
import { alert, delivery, NOW, signal } from "./_fixtures";

describe("statusOf", () => {
  it("follows the design precedence", () => {
    expect(statusOf(alert(1), NOW)).toBe("armed");
    expect(statusOf(alert(1, { snoozed_until: "2026-10-31T15:00:00Z" }), NOW)).toBe("snoozed");
    expect(statusOf(alert(1, { expires_at: "2026-10-31T13:00:00Z" }), NOW)).toBe("expired");
    expect(statusOf(alert(1, { enabled: false }), NOW)).toBe("disabled");
    expect(statusOf(alert(1, { enabled: false, disarm_reason: "source_unavailable" }), NOW)).toBe(
      "disarmed",
    );
    const done = {
      enabled: false,
      trigger_mode: "once",
      fire_count: 1,
      last_fired_at: "2026-10-31T13:00:00Z",
    } as const;
    expect(statusOf(alert(1, { ...done, updated_at: "2026-10-31T13:00:02Z" }), NOW)).toBe("fired");
    expect(statusOf(alert(1, { ...done, updated_at: "2026-10-31T13:30:00Z" }), NOW)).toBe(
      "disabled",
    );
  });

  it("groups, tabs and sorts rows", () => {
    expect(groupOf("disarmed", false)).toBe("attention");
    expect(groupOf("armed", true)).toBe("attention");
    expect(groupOf("fired", false)).toBe("not_armed");
    expect(inTab(alert(1), "fired", NOW)).toBe(false);
    const a = alert(1);
    const b = alert(2, { snoozed_until: "2026-10-31T15:00:00Z" });
    const order = (x: typeof a) => (x === a ? "not_armed" : "armed");
    expect(sortRows([a, b], "all", order)[0]).toBe(b);
    const early = alert(3, { snoozed_until: "2026-10-31T14:10:00Z" });
    expect(sortRows([b, early], "snoozed", () => "snoozed")[0]).toBe(early);
    const recent = alert(4, { last_fired_at: "2026-10-31T13:50:00Z" });
    expect(sortRows([early, recent], "fired", () => "armed")[0]).toBe(recent);
  });
});

describe("describeCondition", () => {
  it("uses display names, cuts long text and counts groups", () => {
    const signals = new Map([
      ["last_price", signal("last_price", { display_name: "Last price", estimated: true })],
    ]);
    expect(describeCondition(alert(1), signals)).toEqual({
      text: "Last price is at or above 64000",
      estimated: true,
    });
    expect(describeCondition(alert(1), null).estimated).toBe(false);
    const group = alert(1, {
      condition_ir: {
        ir_version: 1,
        trigger: { type: "on_price_update" },
        conditions: {
          node_id: "g",
          op: "all_of",
          children: [{ node_id: "a", op: "gt", left: { metric: "x" }, right: { const: 1 } }],
        },
      },
    } as never);
    expect(describeCondition(group, null).text).toBe("1 conditions");
    const long = alert(1, {
      condition_ir: {
        ir_version: 1,
        trigger: { type: "on_price_update" },
        conditions: {
          node_id: "a",
          op: "gt",
          left: { metric: "m".repeat(200) },
          right: { const: 1 },
        },
      },
    } as never);
    expect(describeCondition(long, null).text).toHaveLength(80);
  });

  it("flags only recent failed desktop deliveries", () => {
    const a = alert(1, { last_fired_at: "2026-10-31T13:00:00Z" });
    const rows = [
      delivery(1, a.id as string, "2026-10-31T13:00:01Z", { channel: "desktop", status: "failed" }),
      delivery(2, alert(2).id as string, "2026-10-31T13:00:00Z", {
        channel: "desktop",
        status: "failed",
      }),
      delivery(3, a.id as string, "2026-10-31T13:00:00Z", { channel: "in_app", status: "failed" }),
    ];
    expect([...failedDesktopAlerts(rows, [a])]).toEqual([a.id]);
  });
});

describe("history", () => {
  it("groups channel rows per firing, newest first, and words every status", () => {
    const id = alert(1).id as string;
    const firings = groupFirings([
      delivery(1, id, "2026-10-31T13:00:00Z"),
      delivery(2, id, "2026-10-31T13:00:00Z", { channel: "desktop", status: "queued" }),
      delivery(3, id, "2026-10-31T13:05:00Z", { status: "suppressed", error: "storm" }),
    ]);
    expect(firings.map((f) => f.firedAt)).toEqual(["2026-10-31T13:05:00Z", "2026-10-31T13:00:00Z"]);
    expect(firings[0]?.suppressedStorm).toBe(true);
    expect(firings[1]?.channels.map((c) => c.word)).toEqual([
      "delivered",
      "not shown on the desktop",
    ]);
    expect(statusWord(delivery(1, id, "x", { status: "acked" }))).toBe("delivered, read");
    expect(statusWord(delivery(1, id, "x", { status: "failed" }))).toBe("failed");
    expect(
      statusWord(delivery(1, id, "x", { status: "suppressed", error: "owner_inactive" })),
    ).toBe("suppressed (user disabled)");
    expect(
      statusWord(delivery(1, id, "x", { status: "suppressed", error: "email_relay_off" })),
    ).toBe("suppressed (channel unavailable)");
  });

  it("escapes CSV cells and defuses spreadsheet formulas", () => {
    expect(csvCell('say "hi", ok')).toBe('"say ""hi"", ok"');
    expect(csvCell("=SUM(A1)")).toBe("'=SUM(A1)");
    expect(csvCell("@cmd")).toBe("'@cmd");
    expect(csvCell("  =1+1")).toBe("'  =1+1");
    expect(csvCell("\t=1")).toBe("'\t=1");
    expect(csvCell("+x")).toBe("'+x");
    expect(csvCell("-x")).toBe("'-x");
    expect(csvCell("\r=1")).toBe('"\'\r=1"');
    const csv = historyCsv([delivery(1, "a", "2026-10-31T13:00:00Z", { message: "x,y" })]);
    expect(csv).toBe(
      '\uFEFFfired_at,channel,status,reason,message\r\n2026-10-31T13:00:00Z,in_app,sent,,"x,y"\r\n',
    );
  });
});

describe("groupFirings keys and ordering", () => {
  it("keys a firing by time and lowest id; equal timestamps with a repeated channel stay two firings", () => {
    const at = "2026-10-31T13:00:00Z";
    const two = groupFirings([
      delivery(5, "a", at),
      delivery(4, "a", at, { channel: "desktop" }),
      delivery(9, "a", at),
    ]);
    expect(two.map((f) => f.key)).toEqual([`${at}#4`, `${at}#9`]);
    expect(two[0]?.channels.map((c) => c.channel)).toEqual(["Desktop", "In app"]);
    expect(new Set(two.map((f) => f.key)).size).toBe(2);
  });

  it("sorts an unparseable fired_at last, in the list and the CSV, without NaN", () => {
    const rows = [
      delivery(1, "a", "not-a-date"),
      delivery(2, "a", "2026-10-31T13:00:00Z"),
      delivery(3, "a", "2026-10-31T14:00:00Z"),
    ];
    expect(groupFirings(rows).map((f) => f.firedAt)).toEqual([
      "2026-10-31T14:00:00Z",
      "2026-10-31T13:00:00Z",
      "not-a-date",
    ]);
    const lines = historyCsv(rows).trim().split("\r\n");
    expect(lines[1]).toContain("14:00:00Z");
    expect(lines[3]).toContain("not-a-date");
    expect(timeOf(undefined)).toBe(Number.NEGATIVE_INFINITY);
  });
});

describe("nextLocalMidnightMs", () => {
  it("resolves the next 00:00 in the zone, including a DST day", () => {
    expect(new Date(nextLocalMidnightMs(NOW, "UTC")).toISOString()).toBe(
      "2026-11-01T00:00:00.000Z",
    );
    expect(new Date(nextLocalMidnightMs(NOW, "Europe/Berlin")).toISOString()).toBe(
      "2026-10-31T23:00:00.000Z",
    );
    // Berlin leaves DST on 2026-10-25: the midnight after 2026-10-24 22:30Z is 23:00Z (CEST), the next is 23:00Z-1h later.
    expect(
      new Date(
        nextLocalMidnightMs(Date.parse("2026-10-25T10:00:00Z"), "Europe/Berlin"),
      ).toISOString(),
    ).toBe("2026-10-25T23:00:00.000Z");
    expect(
      new Date(
        nextLocalMidnightMs(Date.parse("2026-10-24T10:00:00Z"), "Europe/Berlin"),
      ).toISOString(),
    ).toBe("2026-10-24T22:00:00.000Z");
  });
});

describe("alerts WS source", () => {
  const body = (p: unknown) => ({ e: "j" as const, p });
  it("maps deltas to fires, snapshots to the unacked count only, and ignores bad bodies", () => {
    const d = { kind: "d", body: body({ deliveries: [{ id: 1 }], unacked_count: 2 }) } as never;
    expect(frameFor(d)).toEqual({ deliveries: [{ id: 1 }], unacked_count: 2 });
    const snap = {
      kind: "snap",
      bodies: [body({ deliveries: [{ id: 9 }], unacked_count: 4 })],
    } as never;
    expect(frameFor(snap)).toEqual({ deliveries: [], unacked_count: 4 });
    expect(frameFor({ kind: "snap", bodies: [body({ deliveries: [] })] } as never)).toEqual({
      deliveries: [],
    });
    expect(frameFor({ kind: "reset", reason: "gap" } as never)).toBeNull();
    expect(
      frameFor({ kind: "d", body: { e: "b64", bytes: new ArrayBuffer(1) } } as never),
    ).toBeNull();
    expect(frameFor({ kind: "d", body: body({}) } as never)).toBeNull();
  });

  it("drains the topic on the timer, asks to resync on a reset and releases on teardown", () => {
    const frames = [
      { kind: "reset", reason: "gap" },
      { kind: "d", body: body({ deliveries: [] }) },
    ];
    const handle = { read: vi.fn(() => frames), release: vi.fn() };
    const consume = vi.fn(() => handle);
    let tick: () => void = () => undefined;
    const stop = vi.fn();
    const onResync = vi.fn();
    const onFrame = vi.fn();
    const source = createWsAlertsSource(() => ({ consume }) as never, onResync, {
      every: (fn) => ((tick = fn), stop),
    });
    const off = source.subscribe(onFrame);
    expect(consume).toHaveBeenCalledWith(
      expect.objectContaining({ ch: "alerts", priority: "private" }),
    );
    tick();
    expect(onResync).toHaveBeenCalledTimes(1);
    expect(onFrame).toHaveBeenCalledTimes(1);
    off();
    expect(stop).toHaveBeenCalled();
    expect(handle.release).toHaveBeenCalled();
  });

  it("is inert without a client", () => {
    const off = createWsAlertsSource(() => null).subscribe(vi.fn());
    expect(off()).toBeUndefined();
  });
});

describe("chartHref", () => {
  it("carries the symbol and the evaluate-on interval", () => {
    expect(chartHref(alert(1))).toBe("/terminal/last?symbol=BTCUSDT");
    expect(chartHref(alert(1, { symbol: null }))).toBe("/terminal/last");
    const bar = alert(1, {
      condition_ir: {
        ir_version: 1,
        trigger: { type: "on_bar_close", timeframe: "5m" },
        conditions: {},
      },
    } as never);
    expect(chartHref(bar)).toBe("/terminal/last?symbol=BTCUSDT&interval=5m");
  });
});
