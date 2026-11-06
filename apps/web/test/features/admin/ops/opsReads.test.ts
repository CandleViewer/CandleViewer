/**
 * E42-S06 (#1084) part 1: the ops read layer (the plan's §1.1, §2): `ok`, `refused`, `not_built`
 * (`501` alone), `failed`; a `403` is denied (BQ-10); no problem words kept (BQ-14); the vets.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReadTimers } from "../../../../src/features/admin/overview/adminReads";
import {
  HEALTH_TIMEOUT_MS,
  LIST_TIMEOUT_MS,
  OPS_PATHS,
  readOps,
  vetHealthReport,
  vetIncidentPage,
  vetProtection,
  type Incident,
} from "../../../../src/features/admin/ops/opsReads";

const TIMERS: ReadTimers = {
  setTimeout: (run, ms) => globalThis.setTimeout(run, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};
const REF = "urn:cv:req:5b1f0c3e-7d2a-4c11-9e8f-0a1b2c3d4e5f";
const keep = (raw: unknown): unknown => raw;
const read = (vet = keep, ms = 1_000, signal = new AbortController().signal) =>
  readOps("/api/v1/admin/health", vet, ms, { signal, timers: TIMERS, now: () => 42 });

function reply(status: number, body: unknown) {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  const fetch = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(
    async () => new Response(text, { status }),
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

/** A fetch that answers only by rejecting once its signal aborts, as a browser's does. */
function hang(): void {
  const stopped = (signal?: AbortSignal | null) =>
    new Promise<never>((_resolve, reject) => {
      const abort = (): void => reject(new DOMException("", "AbortError"));
      if (signal?.aborted === true) abort();
      else signal?.addEventListener("abort", abort);
    });
  vi.stubGlobal(
    "fetch",
    vi.fn((_input: unknown, init: RequestInit = {}) => stopped(init.signal)),
  );
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("readOps: four kinds of answer", () => {
  it("test_readOps_ok_carries_the_vetted_body_and_the_answer_time", async () => {
    const fetch = reply(200, { overall: "healthy", components: [], alerts_active: 2 });
    const body = { overall: "healthy", components: [] };
    expect(await read(vetHealthReport)).toEqual({ kind: "ok", body, at: 42 });
    expect(String(fetch.mock.calls[0]?.[0])).toBe("/api/v1/admin/health");
  });

  it("test_readOps_501_alone_is_not_built_a_404_is_a_refusal_and_a_403_is_denied", async () => {
    reply(501, { code: "not_implemented" });
    expect(await read()).toEqual({ kind: "not_built" });
    reply(404, { code: "not_found" });
    const refused = { kind: "refused", status: 404, code: "not_found", denied: false };
    expect(await read()).toEqual(refused);
    reply(403, { code: "forbidden", instance: REF });
    const denied = { kind: "refused", status: 403, code: "forbidden", refId: REF, denied: true };
    expect(await read()).toEqual(denied);
  });

  it("test_readOps_refusal_keeps_a_registered_code_and_never_the_problem_words", async () => {
    reply(503, { code: "audit_unavailable", detail: "db-1.internal refused", instance: "x y" });
    const refused = { kind: "refused", status: 503, code: "audit_unavailable", denied: false };
    expect(await read()).toEqual(refused);
    // The Ref is a `urn:cv:req:` id (`22` Problem.instance); a host-like token is not one.
    reply(503, { code: "audit_unavailable", instance: "db-1.internal:5432" });
    expect(await read()).toEqual(refused);
    reply(503, { code: "made_up_code" });
    expect(await read()).toMatchObject({ code: null });
    reply(503, "<html>");
    expect(await read()).toMatchObject({ status: 503, code: null });
  });

  it("test_readOps_unreadable_json_or_a_refused_vet_is_failed_unreadable", async () => {
    const unreadable = { kind: "failed", reason: "unreadable" };
    reply(200, "{nope");
    expect(await read()).toEqual(unreadable);
    reply(200, { overall: "rebooting" });
    expect(await read(vetHealthReport)).toEqual(unreadable);
  });

  it("test_readOps_network_error_and_the_callers_abort_are_failed_network", async () => {
    const network = { kind: "failed", reason: "network" };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Promise.reject(new TypeError("offline"))),
    );
    expect(await read()).toEqual(network);
    hang();
    const caller = new AbortController();
    const pending = read(keep, 1_000, caller.signal);
    caller.abort();
    expect(await pending).toEqual(network);
    expect(await read(keep, 1_000, caller.signal)).toEqual(network);
  });

  it("test_readOps_times_out_at_its_bound_3_s_for_health_and_6_s_for_the_lists", async () => {
    expect([HEALTH_TIMEOUT_MS, LIST_TIMEOUT_MS]).toEqual([3_000, 6_000]);
    vi.useFakeTimers();
    hang();
    const pending = read(keep, LIST_TIMEOUT_MS);
    await vi.advanceTimersByTimeAsync(LIST_TIMEOUT_MS - 1);
    expect(vi.mocked(fetch).mock.calls[0]?.[1]?.signal?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(await pending).toEqual({ kind: "failed", reason: "timeout" });
  });

  it("test_ops_paths_are_the_contract_operations", () => {
    expect(OPS_PATHS.incidents("acknowledged")).toBe(
      "/api/v1/admin/incidents?status=acknowledged&limit=100",
    );
    expect(OPS_PATHS.protection).toBe("/api/v1/admin/statecharts?kind=position_protection");
  });
});

describe("vetHealthReport", () => {
  const component = { name: "oms", state: "healthy", latency_ms: 3, latency_unit: "ms" };

  it("test_vetHealthReport_keeps_the_members_the_page_reads_and_drops_the_rest", () => {
    const report = { overall: "warning", version: "1.2.3", clock_offset_ms: null };
    const raw = { ...report, alerts_active: 1, hostname: "db-1.internal" };
    const components = [{ ...component, detail: "ok", connection: "postgres://x" }];
    expect(vetHealthReport({ ...raw, components })).toEqual({
      ...report,
      components: [{ ...component, detail: "ok" }],
    });
  });

  it("test_vetHealthReport_an_unknown_state_or_overall_is_unreadable", () => {
    expect(vetHealthReport({ components: [{ ...component, state: "rebooting" }] })).toBeNull();
    expect(vetHealthReport({ overall: "rebooting", components: [] })).toBeNull();
    const undeployed = [{ ...component, state: "not_deployed" }];
    expect(vetHealthReport({ components: undeployed })).toEqual({ components: undeployed });
  });

  it("test_vetHealthReport_a_named_component_with_no_readable_state_stays_without_one", () => {
    const components = [
      { ...component, state: null },
      { name: "disk", latency_ms: 1 },
      { ...component, name: "redis", state: 3, extra: "x" },
      { state: 42 },
      component,
    ];
    // Never dropped (A-d01): the record reads `not_received`; a nameless one has no tile.
    expect(vetHealthReport({ components })?.components).toEqual([
      { name: "oms", latency_ms: 3, latency_unit: "ms" },
      { name: "disk", latency_ms: 1 },
      { name: "redis", latency_ms: 3, latency_unit: "ms" },
      component,
    ]);
  });

  it("test_vetHealthReport_more_than_64_components_is_unreadable", () => {
    const many = (n: number) =>
      Array.from({ length: n }, (_, i) => ({ ...component, name: `c${i}` }));
    expect(vetHealthReport({ components: many(64) })?.components).toHaveLength(64);
    expect(vetHealthReport({ components: many(65) })).toBeNull();
  });
});

// The parity test [BQ-12]: #1135's `vetIncidentPage` pins, run on this copy until it is imported.
describe("vetIncidentPage, parity with the audit log's copy", () => {
  const meta = { next_cursor: null, has_more: false, count: 1 };
  const at = "2026-10-22T14:05:07Z";
  const incident = (over: Partial<Incident> = {}): Incident => ({
    ...{ id: "8c3e2f1a", component: "db", severity: "critical", status: "open" },
    ...{ title: "audit chain break at id <n>", occurrences: 1, signature: "5f0c2d9e4b7a1c3e" },
    ...{ first_seen_at: at, last_seen_at: at, acknowledged_at: null, runbook_ref: null },
    ...over,
  });
  const page = (over: Partial<Incident>) => vetIncidentPage({ items: [incident(over)], meta });

  it("test_vetIncidentPage_keeps_a_readable_page_whole", () => {
    expect(page({})).toEqual({ items: [incident()], meta });
  });

  it("test_vetIncidentPage_unknown_enum_missing_time_or_long_title_is_unreadable", () => {
    expect(page({ status: "closed" as "open" })).toBeNull();
    expect(page({ severity: "fatal" as "error" })).toBeNull();
    expect(page({ title: "t".repeat(201) })).toBeNull();
    const untimed = { ...incident(), first_seen_at: undefined };
    expect(vetIncidentPage({ items: [untimed], meta })).toBeNull();
    expect(vetIncidentPage({ items: [], meta: { ...meta, has_more: true } })).toBeNull();
  });

  it("test_vetIncidentPage_a_text_over_500_or_more_items_than_asked_is_unreadable", () => {
    const long = "a".repeat(501);
    for (const name of ["id", "component", "signature", "runbook_ref"] as const) {
      expect(page({ [name]: long })).toBeNull();
    }
    const items = Array.from({ length: 101 }, () => incident());
    expect(vetIncidentPage({ items, meta: { ...meta, count: 101 } })).toBeNull();
  });

  it("test_vetIncidentPage_an_acknowledger_or_a_cursor_over_500_is_unreadable", () => {
    expect(page({ acknowledged_by: "a".repeat(500) })).not.toBeNull();
    expect(page({ acknowledged_by: "a".repeat(501) })).toBeNull();
    const cursor = (next_cursor: string) =>
      vetIncidentPage({ items: [], meta: { ...meta, count: 0, has_more: true, next_cursor } });
    expect(cursor("c".repeat(500))).not.toBeNull();
    expect(cursor("c".repeat(501))).toBeNull();
  });
});

describe("vetProtection", () => {
  const kind = { machine_kind: "position_protection", degraded_machines: 0, environment: "demo" };
  const snapshots = { status: "ok" };

  it("test_vetProtection_reads_the_latch_counts_and_the_snapshots_status_only", () => {
    expect(vetProtection({ items: [{ machine_key: "x" }], kinds: [kind], snapshots })).toEqual({
      kinds: [{ machine_kind: "position_protection", degraded_machines: 0 }],
      snapshots,
    });
  });

  it("test_vetProtection_an_unknown_snapshots_status_is_unavailable_never_ok", () => {
    const unavailable = { status: "unavailable" };
    expect(vetProtection({ kinds: [], snapshots: { status: "fine" } })?.snapshots).toEqual(
      unavailable,
    );
    expect(vetProtection({ kinds: [], snapshots: {} })?.snapshots).toEqual(unavailable);
  });

  it("test_vetProtection_missing_kinds_or_a_bad_count_is_unreadable", () => {
    expect(vetProtection({ snapshots })).toBeNull();
    const negative = { ...kind, degraded_machines: -1 };
    expect(vetProtection({ kinds: [negative], snapshots })).toBeNull();
  });

  it("test_vetProtection_more_than_64_kinds_or_a_kind_over_500_is_unreadable", () => {
    expect(
      vetProtection({ kinds: Array.from({ length: 64 }, () => kind), snapshots }),
    ).not.toBeNull();
    expect(vetProtection({ kinds: Array.from({ length: 65 }, () => kind), snapshots })).toBeNull();
    const long = { ...kind, machine_kind: "k".repeat(501) };
    expect(vetProtection({ kinds: [long], snapshots })).toBeNull();
  });
});
