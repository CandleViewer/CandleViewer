/**
 * E42-S08 (#1137) §3.1: the inspector's reads. Each is one `GET` the contract serves, under its own
 * 3 s client bound, settling as one outcome: ok (the body vetted to the generated types), not found
 * (a machine or chart `404`), not built (`501`, or the list's `404`), denied (`403`, the problem's
 * instance as the Ref), invalid cursor (`400 invalid_cursor`) or failed. Paths are built from vetted
 * values, each segment and parameter encoded; a value off its pattern is a failed read.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReadTimers } from "../../../../src/features/admin/overview/adminReads";
import {
  detailPath,
  exportPath,
  LIST_LIMIT,
  listPath,
  machineRef,
  readDetail,
  readExport,
  readList,
  vetDetail,
  vetExport,
  vetList,
  type MachineRef,
} from "../../../../src/features/admin/statecharts/inspectorReads";
import {
  DEGRADED_ORDER_LIST,
  KILL_SWITCH_DETAIL,
  KILL_SWITCH_EXPORT,
  KILL_SWITCH_HASH,
  LATCHED_DETAIL,
  LATCHED_KEY,
  ORDER_EXPORT,
} from "./fixtures";

const TIMERS: ReadTimers = {
  setTimeout: (run, ms) => globalThis.setTimeout(run, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};
const LATCHED: MachineRef = { key: LATCHED_KEY, env: "demo" };
const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const signal = (): AbortSignal => new AbortController().signal;

/** Answers every request with `reply`, recording each request's path and init. */
function serve(reply: () => Response | Promise<Response>) {
  const fetch = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
    async () => reply(),
  );
  vi.stubGlobal("fetch", fetch);
  return {
    paths: (): string[] => fetch.mock.calls.map(([input]) => String(input)),
    init: (i = 0): RequestInit => fetch.mock.calls[i]?.[1] ?? {},
  };
}

/** A fetch that never answers, and rejects as a browser's does once its signal aborts. */
function hangingFetch(): { readonly signals: AbortSignal[] } {
  const signals: AbortSignal[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((_input: RequestInfo | URL, init: RequestInit = {}) => {
      const aborted = init.signal as AbortSignal;
      signals.push(aborted);
      return new Promise<Response>((_resolve, reject) => {
        const fail = (): void => reject(new DOMException("aborted", "AbortError"));
        if (aborted.aborted) fail();
        aborted.addEventListener("abort", fail);
      });
    }),
  );
  return { signals };
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("paths and addresses: vetted values only, every part encoded", () => {
  it("test_list_path_reads_200_and_adds_degraded_then_the_cursor", () => {
    expect(LIST_LIMIT).toBe(200);
    expect(listPath({ latchedOnly: false })).toBe("/api/v1/admin/statecharts?limit=200");
    expect(listPath({ latchedOnly: true })).toBe(
      "/api/v1/admin/statecharts?limit=200&degraded=true",
    );
    expect(listPath({ latchedOnly: true, cursor: "a+b/c=" })).toBe(
      "/api/v1/admin/statecharts?limit=200&degraded=true&cursor=a%2Bb%2Fc%3D",
    );
  });

  it("test_detail_path_encodes_the_machine_and_names_its_environment", () => {
    expect(detailPath(LATCHED)).toBe(
      "/api/v1/admin/statecharts/order%3A0a000000-0000-4000-8000-0000000000c7?environment=demo",
    );
    expect(detailPath({ key: "kill_switch", env: "live" })).toBe(
      "/api/v1/admin/statecharts/kill_switch?environment=live",
    );
    expect(detailPath({ key: "order/../users", env: "demo" })).toBeNull();
  });

  it("test_export_path_asks_by_the_bare_kind_and_refuses_an_entity", () => {
    expect(exportPath("oco")).toBe("/api/v1/admin/statecharts/oco/export");
    expect(exportPath("algo:0a000000-0000-4000-8000-000000000001")).toBeNull();
    expect(exportPath("Order")).toBeNull();
  });

  it.each([
    ["kill_switch", "demo", true],
    ["book:BTCUSDT", "live", true],
    [LATCHED_KEY, "testnet", true],
    ["order:0A000000-0000-4000-8000-0000000000C7", "demo", false],
    ["order:not-a-uuid", "demo", false],
    ["kill_switch", "prod", false],
    [`${"a".repeat(33)}`, "demo", false],
    ["algo:", "demo", false],
    [7, "demo", false],
    ["kill_switch", undefined, false],
  ])("test_machine_ref_%s_in_%s_is_vetted_%s", (key, env, valid) => {
    const ref = machineRef(key, env);
    expect(ref === null ? null : [ref.key, ref.env]).toEqual(valid ? [key, env] : null);
  });
});

describe("one read, one outcome", () => {
  it("test_read_list_ok_answers_the_vetted_page_and_asks_for_json_with_get", async () => {
    const wire = serve(() => json(200, DEGRADED_ORDER_LIST));
    const outcome = await readList({ latchedOnly: true }, signal(), TIMERS);
    expect(outcome).toEqual({ kind: "ok", body: DEGRADED_ORDER_LIST });
    expect(wire.paths()).toEqual(["/api/v1/admin/statecharts?limit=200&degraded=true"]);
    expect(wire.init().method ?? "GET").toBe("GET");
    expect(new Headers(wire.init().headers).get("Accept")).toBe("application/json");
  });

  it("test_read_list_404_is_not_built_and_a_machine_or_chart_404_is_not_found", async () => {
    serve(() => json(404, { code: "not_found" }));
    expect(await readList({ latchedOnly: false }, signal(), TIMERS)).toEqual({ kind: "not_built" });
    expect(await readDetail(LATCHED, signal(), TIMERS)).toEqual({ kind: "not_found" });
    expect(await readExport("order", signal(), TIMERS)).toEqual({ kind: "not_found" });
  });

  it("test_read_501_is_not_built_for_every_read", async () => {
    serve(() => json(501, { code: "not_implemented" }));
    expect(await readList({ latchedOnly: false }, signal(), TIMERS)).toEqual({ kind: "not_built" });
    expect(await readDetail(LATCHED, signal(), TIMERS)).toEqual({ kind: "not_built" });
    expect(await readExport("order", signal(), TIMERS)).toEqual({ kind: "not_built" });
  });

  it("test_read_403_is_denied_with_the_problems_instance_only_in_shape", async () => {
    const instance = "urn:cv:req:0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d";
    serve(() => json(403, { code: "forbidden", instance }));
    expect(await readDetail(LATCHED, signal(), TIMERS)).toEqual({
      kind: "denied",
      refId: instance,
    });
    serve(() => json(403, { instance: "<img src=x onerror=1>" }));
    expect(await readList({ latchedOnly: false }, signal(), TIMERS)).toEqual({
      kind: "denied",
      refId: undefined,
    });
    serve(() => new Response("not json", { status: 403 }));
    expect(await readExport("order", signal(), TIMERS)).toEqual({
      kind: "denied",
      refId: undefined,
    });
  });

  it("test_read_400_invalid_cursor_is_its_own_outcome_and_any_other_400_failed", async () => {
    serve(() => json(400, { code: "invalid_cursor", instance: "urn:cv:req:1" }));
    expect(await readList({ latchedOnly: false, cursor: "old" }, signal(), TIMERS)).toEqual({
      kind: "invalid_cursor",
    });
    serve(() => json(400, { code: "validation_failed" }));
    expect(await readList({ latchedOnly: false }, signal(), TIMERS)).toEqual({
      kind: "failed",
      reason: "status",
      status: 400,
    });
  });

  it("test_read_other_refusals_fail_with_their_status_and_a_lost_connection_as_network", async () => {
    serve(() => json(503, { code: "unavailable" }));
    expect(await readDetail(LATCHED, signal(), TIMERS)).toEqual({
      kind: "failed",
      reason: "status",
      status: 503,
    });
    serve(() => Promise.reject(new TypeError("Failed to fetch")));
    expect(await readExport("order", signal(), TIMERS)).toEqual({
      kind: "failed",
      reason: "network",
    });
  });

  it("test_read_a_body_not_json_or_off_its_shape_is_unreadable", async () => {
    serve(() => new Response("<!doctype html>", { status: 200 }));
    expect(await readList({ latchedOnly: false }, signal(), TIMERS)).toEqual({
      kind: "failed",
      reason: "unreadable",
    });
    serve(() => json(200, { ...KILL_SWITCH_EXPORT, machine_kind: "order" }));
    expect(await readExport("kill_switch", signal(), TIMERS)).toEqual({
      kind: "failed",
      reason: "unreadable",
    });
  });

  it("test_read_gives_up_after_3_s_aborting_the_request_and_leaving_no_timer", async () => {
    vi.useFakeTimers();
    const { signals } = hangingFetch();
    const pending = readDetail(LATCHED, signal(), TIMERS);
    await vi.advanceTimersByTimeAsync(2_999);
    expect(signals[0]?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(await pending).toEqual({ kind: "failed", reason: "timeout" });
    expect(signals[0]?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("test_read_stops_when_its_caller_stops_even_before_it_starts", async () => {
    vi.useFakeTimers();
    const { signals } = hangingFetch();
    const caller = new AbortController();
    const pending = readList({ latchedOnly: false }, caller.signal, TIMERS);
    caller.abort();
    expect(await pending).toEqual({ kind: "failed", reason: "network" });
    const stopped = new AbortController();
    stopped.abort();
    expect(await readExport("order", stopped.signal, TIMERS)).toEqual({
      kind: "failed",
      reason: "network",
    });
    expect(signals.map((s) => s.aborted)).toEqual([true, true]);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("test_read_never_asks_for_an_address_off_its_pattern", async () => {
    const wire = serve(() => json(200, {}));
    const bad = { key: "order:../../users", env: "demo" } as const;
    expect(await readDetail(bad, signal(), TIMERS)).toEqual({ kind: "not_found" });
    expect(await readExport("algo:x", signal(), TIMERS)).toEqual({ kind: "not_found" });
    expect(wire.paths()).toEqual([]);
  });
});

/** A list page with `patch` merged into its first item, its first kind or itself. */
const withItem = (patch: object) => ({
  ...DEGRADED_ORDER_LIST,
  items: [{ ...DEGRADED_ORDER_LIST.items[0], ...patch }],
});
const withKind = (patch: object) => ({
  ...DEGRADED_ORDER_LIST,
  kinds: [{ ...DEGRADED_ORDER_LIST.kinds[0], ...patch }],
});

describe("vetList: 22's page or nothing", () => {
  it("test_vet_list_keeps_22s_degraded_order_example_as_served", () => {
    expect(vetList(DEGRADED_ORDER_LIST)).toEqual(DEGRADED_ORDER_LIST);
  });

  it("test_vet_list_an_unknown_slice_status_reads_unavailable_never_ok", () => {
    const body = vetList({
      ...DEGRADED_ORDER_LIST,
      snapshots: { status: "sealed", generated_at: "nope", detail: "x".repeat(201) },
      metrics: { status: "ok", detail: "", extra: { nested: true } },
    });
    expect(body?.snapshots).toEqual({ status: "unavailable" });
    expect(body?.metrics).toEqual({ status: "ok" });
  });

  it("test_vet_list_drops_what_no_row_shows", () => {
    const body = vetList({
      ...withItem({ context_summary: { scope: "global" } }),
      next: "/api/v1/admin/users",
    });
    expect(body?.items[0]).toEqual(DEGRADED_ORDER_LIST.items[0]);
    expect(Object.keys(body ?? {}).sort()).toEqual([
      "items",
      "kinds",
      "meta",
      "metrics",
      "snapshots",
    ]);
  });

  it.each([
    ["a hash off its pattern", withItem({ machine_hash: "A".repeat(64) })],
    ["a short hash", withItem({ machine_hash: KILL_SWITCH_HASH.slice(1) })],
    ["negative chain trips", withItem({ chain_trips: -1 })],
    ["fractional chain trips", withItem({ chain_trips: 1.5 })],
    ["a missing deferred depth", withItem({ deferred_depth: undefined })],
    ["a negative deferred depth", withItem({ deferred_depth: -2 })],
    ["degraded as a word", withItem({ degraded: "true" })],
    ["lock_matches missing", withItem({ lock_matches: undefined })],
    ["an unknown environment", withItem({ environment: "prod" })],
    ["a machine address off its pattern", withItem({ machine_key: "order:<b>" })],
    ["a kind off its pattern", withItem({ machine_kind: "Order" })],
    ["an empty state", withItem({ state: "" })],
    ["a state over 200 characters", withItem({ state: "s".repeat(201) })],
    ["an unparsable update time", withItem({ updated_at: "yesterday" })],
    ["a row that is not an object", { ...DEGRADED_ORDER_LIST, items: ["kill_switch"] }],
    [
      "over 200 rows",
      { ...DEGRADED_ORDER_LIST, items: Array(201).fill(DEGRADED_ORDER_LIST.items[0]) },
    ],
    ["no machines in a kind", withKind({ machines: 0 })],
    ["a negative latched count", withKind({ degraded_machines: -1 })],
    ["negative dropped receipts", withKind({ dropped_receipts: -3 })],
    ["dropped receipts as a word", withKind({ dropped_receipts: "none" })],
    ["a by-state count that is not one", withKind({ by_state: { clear: "1" } })],
    ["an empty by-state name", withKind({ by_state: { "": 1 } })],
    ["a by-state name over 200 characters", withKind({ by_state: { ["s".repeat(201)]: 1 } })],
    ["by state as a list", withKind({ by_state: [1] })],
    ["a kind summary of an unknown environment", withKind({ environment: "staging" })],
    ["no kinds", { ...DEGRADED_ORDER_LIST, kinds: undefined }],
    ["no snapshots slice", { ...DEGRADED_ORDER_LIST, snapshots: undefined }],
    ["no metrics slice", { ...DEGRADED_ORDER_LIST, metrics: "error" }],
    ["no meta", { ...DEGRADED_ORDER_LIST, meta: undefined }],
    ["has_more as a word", { ...DEGRADED_ORDER_LIST, meta: { has_more: "no", count: 2 } }],
    ["a negative count", { ...DEGRADED_ORDER_LIST, meta: { has_more: false, count: -1 } }],
    [
      "a cursor over 512 characters",
      { ...DEGRADED_ORDER_LIST, meta: { has_more: true, count: 2, next_cursor: "c".repeat(513) } },
    ],
    ["a list that is not an object", [DEGRADED_ORDER_LIST]],
  ])("test_vet_list_%s_is_unreadable", (_name, raw) => {
    expect(vetList(raw)).toBeNull();
  });

  it("test_vet_list_reads_any_state_name_up_to_200_characters_as_served", () => {
    // `22` types a state as a plain string and the chart schema constrains no name: React escapes
    // it, and no path is built from it, so only its length is bounded (C-1137-04).
    const long = "s".repeat(200);
    const body = vetList({
      ...withItem({ state: "wait-fill" }),
      kinds: [{ ...DEGRADED_ORDER_LIST.kinds[0], by_state: { "wait-fill": 1, [long]: 2 } }],
    });
    expect(body?.items[0]?.state).toBe("wait-fill");
    expect(body?.kinds[0]?.by_state).toEqual({ "wait-fill": 1, [long]: 2 });
    expect(vetList(withItem({ state: long }))?.items[0]?.state).toBe(long);
    expect(vetList(withItem({ state: "lifecycle.triggered" }))?.items[0]?.state).toBe(
      "lifecycle.triggered",
    );
  });

  it("test_vet_list_keeps_a_null_dropped_receipts_and_a_next_cursor", () => {
    const body = vetList({
      ...DEGRADED_ORDER_LIST,
      meta: { has_more: true, count: 2, next_cursor: "eyJrIjoxfQ", total: 9 },
    });
    expect(body?.kinds.map((kind) => kind.dropped_receipts)).toEqual([null, null, null]);
    expect(body?.meta).toEqual({ has_more: true, count: 2, next_cursor: "eyJrIjoxfQ" });
    expect(vetList(withKind({ dropped_receipts: 4 }))?.kinds[0]?.dropped_receipts).toBe(4);
  });
});

describe("vetDetail: the machine, its configuration and events, never its context", () => {
  it("test_vet_detail_drops_config_and_context_summary_from_22s_example", () => {
    const shown = Object.fromEntries(
      Object.entries(KILL_SWITCH_DETAIL).filter(
        ([name]) => !["config", "context_summary"].includes(name),
      ),
    );
    expect(Object.keys(shown)).toHaveLength(Object.keys(KILL_SWITCH_DETAIL).length - 2);
    expect(vetDetail(KILL_SWITCH_DETAIL)).toEqual(shown);
  });

  it("test_vet_detail_keeps_the_latched_order_and_a_detail_without_a_machine", () => {
    expect(vetDetail(LATCHED_DETAIL)).toEqual(LATCHED_DETAIL);
    const sealed = {
      snapshots: {
        status: "error",
        detail: "snapshot seal did not verify",
        generated_at: "2026-10-15T18:00:05Z",
      },
    };
    expect(vetDetail(sealed)).toEqual(sealed);
  });

  const event = LATCHED_DETAIL.recent_events[0];
  it.each([
    ["no snapshots slice", { ...LATCHED_DETAIL, snapshots: undefined }],
    ["an events slice that is not one", { ...LATCHED_DETAIL, events: "ok" }],
    ["a machine off its shape", { ...LATCHED_DETAIL, machine: { machine_key: LATCHED_KEY } }],
    ["a configuration of 201 ids", { ...LATCHED_DETAIL, configuration: Array(201).fill("order") }],
    [
      "a configuration id over 200 characters",
      { ...LATCHED_DETAIL, configuration: ["o".repeat(201)] },
    ],
    ["a configuration id that is empty", { ...LATCHED_DETAIL, configuration: [""] }],
    ["51 events", { ...LATCHED_DETAIL, recent_events: Array(51).fill(event) }],
    ["an unknown phase", { ...LATCHED_DETAIL, recent_events: [{ ...event, phase: "rollback" }] }],
    ["an event with no type", { ...LATCHED_DETAIL, recent_events: [{ ...event, event_type: "" }] }],
    [
      "an event time unparsable",
      { ...LATCHED_DETAIL, recent_events: [{ ...event, occurred_at: "now" }] },
    ],
    [
      "from states not a list",
      { ...LATCHED_DETAIL, recent_events: [{ ...event, from_states: "a" }] },
    ],
    ["faulted as a word", { ...LATCHED_DETAIL, recent_events: [{ ...event, faulted: "yes" }] }],
    ["an event that is not an object", { ...LATCHED_DETAIL, recent_events: [7] }],
    ["a detail that is not an object", "ok"],
  ])("test_vet_detail_%s_is_unreadable", (_name, raw) => {
    expect(vetDetail(raw)).toBeNull();
  });
});

describe("vetExport: the asked kind's chart, read into the model", () => {
  it("test_vet_export_reads_22s_kill_switch_example_into_its_model", () => {
    const chart = vetExport(KILL_SWITCH_EXPORT, "kill_switch");
    expect(chart?.machine_kind).toBe("kill_switch");
    expect(chart?.machine_hash).toBe(KILL_SWITCH_HASH);
    expect(chart?.model.states.map((s) => s.id)).toEqual(["kill_switch.clear"]);
    expect(Object.keys(chart ?? {}).sort()).toEqual(["machine_hash", "machine_kind", "model"]);
  });

  it("test_vet_export_reads_the_frozen_b01_chart", () => {
    expect(vetExport(ORDER_EXPORT, "order")?.model.states).toHaveLength(23);
  });

  it.each([
    ["another kind", { ...KILL_SWITCH_EXPORT, machine_kind: "live_gate" }],
    ["a hash off its pattern", { ...KILL_SWITCH_EXPORT, machine_hash: "beef" }],
    ["no stately chart", { ...KILL_SWITCH_EXPORT, stately: undefined }],
    [
      "a chart the model refuses",
      { ...KILL_SWITCH_EXPORT, stately: { id: "kill_switch", states: {} } },
    ],
    ["an answer that is not an object", null],
  ])("test_vet_export_%s_is_unreadable", (_name, raw) => {
    expect(vetExport(raw, "kill_switch")).toBeNull();
  });
});
