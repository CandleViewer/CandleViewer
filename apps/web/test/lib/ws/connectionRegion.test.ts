// E10-S04 (#306) slice 4a: the CMP-077 region's data half (E17-D02 §6, §10 B / D / F / R, §11;
// E17-D01 §4.1 T4). Deterministic: every case passes its own `now`.
import { describe, expect, it } from "vitest";
import * as R from "../../../src/lib/ws/state/connectionRegion";
import { INITIAL_WS_STATE, reduce } from "../../../src/lib/ws/state/reducer";
import type { EngineEvent, OfflineCause, Outage, WsState } from "../../../src/lib/ws/state/types";
import { OFF, ON, authOk, connecting, killSwitch, shutdown, stream } from "./support/engineEvents";

const T0 = 1_000_000;
const LOST: Outage = { sinceMs: T0, lastDataMs: T0 - 12_000 };
const NO_DATA: Outage = { sinceMs: T0, lastDataMs: null };
const run = (...events: EngineEvent[]): WsState => events.reduce(reduce, INITIAL_WS_STATE);
const up = (...more: EngineEvent[]) => run(connecting, authOk(OFF), stream("live"), ...more);
const retry = (lost?: Outage): EngineEvent => ({
  type: "reconnecting",
  attempt: 1,
  nextAttemptAtMs: T0 + 4_000,
  lost,
});
const down = (cause: OfflineCause, closeCode?: number, lost = LOST): EngineEvent => ({
  type: "offline",
  cause,
  closeCode,
  lost,
});
/** Up, then lost at `T0` with data 12 s before; the first attempt is due 4 s later. */
const dropped = (...more: EngineEvent[]) => up(retry(LOST), ...more);
const at = (ws: WsState, ms = 0, privateFeedDown = false) =>
  R.connectionRegion(ws, T0 + ms, { privateFeedDown });
const ORDERS_OFF = "New orders off; cancel and close remain available, confirmed over the server.";
const STOPS = "Exchange-side stops still protect open positions; app-managed rules are paused.";

describe("connectionRegion", () => {
  it("is empty while live, at a session start and while reconciling (§11 row 15, §2 row 16)", () => {
    for (const ws of [up(), run(connecting), run(connecting, authOk())]) expect(at(ws)).toBeNull();
  });

  it("is empty for a session that was never up: SCR-001 owns it (§2 row 7, §10 D)", () => {
    const never = [retry(LOST), down("offline"), down("fatal", 1002), down("fatal", 4403)];
    for (const e of never) expect(at(run(connecting, e), 400_000)).toBeNull();
    expect(R.regionAnnouncement(null, null)).toBeNull();
  });

  it("B1: the counter, the age and the countdown, verbatim", () => {
    expect(at(dropped())).toEqual({
      state: "reconnecting",
      reason: "disconnected",
      title: "Disconnected — reconnecting (1)",
      lines: [`Last data 00:12 ago. ${ORDERS_OFF}`, STOPS],
      controls: ["retry", "details"],
      countdown: "Next try in ~4 s",
      countdownS: 4,
      lastDataAgo: "00:12",
      ageEmphasis: false,
      notifyDue: false,
    });
    expect([1, 3_000, 9_000].map((ms) => at(dropped(), ms)?.countdownS)).toEqual([4, 1, 1]); // never ~0 s
    expect(at(dropped(connecting), 5_000)).toMatchObject({
      title: "Disconnected — reconnecting",
      countdown: "Connecting…",
      countdownS: null,
    });
    expect(at(up(retry(NO_DATA)))?.lines[0]).toBe(ORDERS_OFF);
  });

  it.each([
    ["tailnet_unreachable", "Not connected to the tailnet"],
    ["offline", "You're offline"],
    ["backend_unreachable", "Can't reach the server"],
  ] as const)("B1b: a shell cause %s has no counter and no countdown", (cause, sentence) => {
    expect(at(up(down(cause)))).toMatchObject({
      state: "reconnecting",
      title: "Disconnected — reconnecting",
      lines: [`${sentence} — last data 00:12 ago.`, STOPS], // §6 over B1b: cancel / close are T2
      countdown: null,
    });
    expect(at(up(down(cause, undefined, NO_DATA)))?.lines[0]).toBe(`${sentence}.`);
  });

  it("T4: the OS notification at 10 s, the age step at 30 s, long-outage at 5 min", () => {
    const edge = (ms: number) => [at(dropped(), ms - 1), at(dropped(), ms)];
    expect(edge(10_000).map((v) => v?.notifyDue)).toEqual([false, true]);
    expect(edge(30_000).map((v) => v?.ageEmphasis)).toEqual([false, true]);
    expect(edge(300_000).map((v) => v?.state)).toEqual(["reconnecting", "long-outage"]);
    expect([R.T4_NOTIFY_MS, R.T4_STEP_MS, R.T4_ESCALATE_MS]).toEqual([10_000, 30_000, 300_000]);
    expect(at(dropped(), 300_000)?.title).toBe("Disconnected for 05:00 — escalated");
    expect(at(up(down("offline")), 301_000)).toMatchObject({
      title: "Disconnected for 05:01 — escalated",
      lines: ["You're offline — last data 05:13 ago.", STOPS],
    });
  });

  it("T4 on the stopped states: a fatal close notifies but has no age step; a session end neither", () => {
    const fatal = at(up(down("fatal", 1002)), 30_000);
    expect([fatal?.notifyDue, fatal?.ageEmphasis, fatal?.lastDataAgo]).toEqual([true, false, null]);
    const ended = at(up(down("fatal", 4403)), 30_000);
    expect([ended?.notifyDue, ended?.ageEmphasis, ended?.lastDataAgo]).toEqual([
      false,
      false,
      null,
    ]);
  });

  it.each([
    [
      1002,
      "Can't connect — the app and the server disagree on the protocol. Copy details and report a bug.",
    ],
    [1009, "Can't connect — a message was too large. Copy details and report a bug."],
    [4400, "Can't connect — repeated protocol errors. Copy details and report a bug."],
    [undefined, "Can't connect. Copy details and report a bug."],
    [4401, "Can't connect. Copy details and report a bug."], // `bye.reconnect: false` 4401 until G12
  ])("B4: a fatal %s close stops the retry, unescalated", (code, l1) => {
    expect(at(up(down("fatal", code)), 300_000)).toMatchObject({
      state: "offline",
      title: "Offline — retry stopped",
      lines: [l1, `${ORDERS_OFF} ${STOPS}`],
      controls: ["retry", "details"],
    });
  });

  it("B4b: a bare 4403 ends the session, with Sign in and no Retry now", () => {
    expect(at(up(down("fatal", 4403)))).toMatchObject({
      state: "session-ended",
      title: "Session ended",
      lines: [
        "Your access was removed — contact the owner.",
        "Exchange-side stops still protect open positions; app-managed rules are paused — sign in again to cancel or close.",
      ],
      controls: ["sign-in", "details"],
    });
  });

  it("read-only: R1 > R2 > R5 > R6, one cause removed at a time; Disconnected beats them all", () => {
    const ro = (ws: WsState, privateDown: boolean) => {
      const v = at(ws, 0, privateDown);
      return [v?.reason, v?.title, ...(v?.lines ?? [])];
    };
    // R2 and R6 never hold together: an unknown kill switch is never "engaged" (WS-E06).
    expect(ro(up(shutdown, killSwitch(ON)), true)).toEqual([
      "R1-shutdown",
      "Order entry off — backend restarting",
      "Cancel and close still work; exchange-side stops still protect open positions; app-managed rules are paused.",
    ]);
    const r2 = [
      "R2-kill-switch",
      "Order entry off — trading frozen by the owner.",
      "Cancel still works.",
    ];
    expect(ro(up(killSwitch(ON)), true)).toEqual(r2);
    const r5 = [
      "R5-private-down",
      "Order entry off — private feed down; fills cannot be seen live.",
      "Cancel and close still work, confirmed over REST.",
    ];
    expect([ro(up(), true), ro(up(stream("stale")), true)]).toEqual([r5, r5]);
    expect(ro(up(stream("stale")), false)).toEqual([
      "R6-system-unknown",
      "Order entry off — kill-switch status unknown until the server reports it.",
      "Cancel and close still work.",
    ]);
    expect(at(up(shutdown, killSwitch(ON), retry(LOST)), 0, true)?.reason).toBe("disconnected");
    expect(at(up(), 0, true)).toMatchObject({ state: "read-only", controls: ["details"] });
  });

  it("formats ages: floored, a clock step back is zero, hours past 59:59", () => {
    const ages = [999, 12_999, 272_000, -5_000, 3_599_999, 3_903_000].map(R.formatAge);
    expect(ages.join(" ")).toBe("00:00 00:12 04:32 00:00 59:59 1:05:03");
  });
});

describe("regionAnnouncement (§11)", () => {
  const say = (prev: R.ConnectionRegionView | null, next: R.ConnectionRegionView | null) =>
    R.regionAnnouncement(prev, next)?.text ?? null;

  it("row 1: entering the episode once; ticks, attempts, shell causes and T4 steps say nothing", () => {
    const first = at(dropped());
    expect(R.regionAnnouncement(null, first)).toEqual({
      politeness: "assertive",
      text: "Disconnected. New orders off. Cancel and close still work, confirmed over the server. Exchange-side stops still protect open positions.",
    });
    const later = [
      at(dropped(), 1_000),
      at(dropped(connecting)),
      at(dropped(down("offline"))),
      at(dropped(), 300_000),
    ];
    expect(later.map((v) => say(first, v))).toEqual([null, null, null, null]);
    expect(say(at(up(stream("stale"))), first)).toMatch(/^Disconnected\./); // from a read-only reason
  });

  it("row 14: retry stopped from any state; a manual retry after it is no new episode", () => {
    const fatal = at(dropped(down("fatal", 1002)));
    expect(say(at(dropped()), fatal)).toBe(
      "Offline — retry stopped. New orders off. Cancel and close still work, confirmed over the server.",
    );
    expect(say(null, at(up(down("fatal", 4403))))).toBe(
      "Your access was removed — contact the owner.",
    );
    expect(say(fatal, at(dropped()))).toBeNull();
  });

  it("row 2: once per read-only reason, never per tick; nothing on leaving", () => {
    const r5 = at(up(), 0, true);
    expect(say(null, r5)).toBe(
      "Order entry off — private feed down; fills cannot be seen live. Cancel and close still work, confirmed over REST.",
    );
    expect([say(r5, at(up(), 9_000, true)), say(r5, null)]).toEqual([null, null]);
    expect(say(r5, at(up(killSwitch(ON))))).toBe(
      "Order entry off — trading frozen by the owner. Cancel still works.",
    );
    expect(say(null, at(up(shutdown)))).toMatch(
      /^Order entry off — backend restarting\. Cancel and close/,
    );
  });
});
