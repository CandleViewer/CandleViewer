/**
 * E42-S04 (#1135): the audit log's read layer (E42-D04 §4, §7; the plan's §3). The list read, the
 * tamper check and the incident read go through `apiFetch`, typed from `packages/protocol`, and
 * settle as one of four answers: `ok` (the body vetted, an unknown enum or a missing field
 * unreadable), `refused` (the status, the problem's code, `Retry-After`, the Ref and the field
 * errors), `unknown` (a write that got no answer) or `failed` (a read that got none, or an answer
 * it could not read). List reads stop at 6 s (BQ-11, PROPOSED), above the server's 4 s stop; the
 * tamper check waits past its 60 s deadline (BQ-6). The orchestrator's binding cases live here too:
 * a Viewer's 403 and the view-as refusals (BQ-9).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  AUDIT_CADENCE,
  AUDIT_READ_TIMEOUT_MS,
  INCIDENT_LIMIT,
  VERIFY_TIMEOUT_MS,
  forbiddenMeaning,
  jobPollDelay,
  listIncidents,
  queryAuditLog,
  queryString,
  retryAfterSeconds,
  verifyAuditChain,
  vetAuditPage,
  vetIncidentPage,
  vetVerifyResult,
  type AuditAnswer,
  type AuditRefusal,
} from "../../../../src/features/admin/audit/auditReads";
import {
  BROKEN,
  OWNER_ID,
  REF,
  T0,
  entry,
  hangingFetch,
  incident,
  json,
  pageBody,
  problem,
  stubFetch,
  verifyBody,
} from "./fixtures";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const refusal = <T>(answer: AuditAnswer<T>): AuditRefusal => {
  if (answer.kind !== "refused") throw new Error(`expected a refusal, got ${answer.kind}`);
  return answer;
};

describe("queryAuditLog", () => {
  it("test_queryAuditLog_ok_asks_get_with_the_query_and_answers_the_vetted_page", async () => {
    const page = pageBody([entry()], { next: "c1" });
    const calls = stubFetch(() => json(200, page));
    const answer = await queryAuditLog({
      limit: 200,
      cursor: "c0",
      action: ["orders.submit", "admin.audit_read"],
      severity: "critical",
      q: "BTC usdt",
    });
    expect(answer).toEqual({ kind: "ok", body: page });
    const [sent] = calls;
    const url = new URL(sent?.url ?? "", "http://x");
    expect(url.pathname).toBe("/api/v1/admin/audit");
    expect(url.searchParams.getAll("action")).toEqual(["orders.submit", "admin.audit_read"]);
    expect(url.searchParams.get("cursor")).toBe("c0");
    expect(url.searchParams.get("limit")).toBe("200");
    expect(url.searchParams.get("q")).toBe("BTC usdt");
    expect(sent?.method).toBe("GET");
    expect(sent?.headers.get("Accept")).toBe("application/json");
  });

  it("test_queryAuditLog_no_answer_in_6s_is_failed_timeout_and_leaves_no_timer", async () => {
    expect(AUDIT_READ_TIMEOUT_MS).toBe(6_000);
    vi.useFakeTimers();
    const signals = hangingFetch();
    const pending = queryAuditLog({ limit: 200 });
    await vi.advanceTimersByTimeAsync(AUDIT_READ_TIMEOUT_MS - 1);
    expect(signals[0]?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(await pending).toEqual({ kind: "failed", reason: "timeout" });
    expect(signals[0]?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("test_queryAuditLog_caller_abort_stops_the_request_as_failed_network", async () => {
    vi.useFakeTimers();
    const signals = hangingFetch();
    const caller = new AbortController();
    const pending = queryAuditLog({ limit: 200 }, { signal: caller.signal });
    caller.abort();
    expect(await pending).toEqual({ kind: "failed", reason: "network" });
    expect(signals[0]?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("test_queryAuditLog_lost_connection_or_unreadable_body_is_failed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))),
    );
    expect(await queryAuditLog({})).toEqual({ kind: "failed", reason: "network" });
    stubFetch(() => new Response("<!doctype html>", { status: 200 }));
    expect(await queryAuditLog({})).toEqual({ kind: "failed", reason: "unreadable" });
    stubFetch(() => json(200, { items: [] }));
    expect(await queryAuditLog({})).toEqual({ kind: "failed", reason: "unreadable" });
  });

  it("test_queryAuditLog_503_is_refused_with_its_code_retry_after_and_ref", async () => {
    stubFetch(() =>
      problem(503, "store_unavailable", { retry_after_seconds: 9 }, { "Retry-After": "5" }),
    );
    expect(await queryAuditLog({})).toEqual({
      kind: "refused",
      status: 503,
      code: "store_unavailable",
      retryAfterS: 5,
      refId: REF,
    });
  });

  it("test_queryAuditLog_422_keeps_each_field_and_rule_never_a_message_at_most_ten", async () => {
    const errors = Array.from({ length: 12 }, (_, i) => ({
      field: i === 0 ? "to" : `f${i}`,
      rule: "value_error",
      message: "echo",
    }));
    stubFetch(() => problem(422, "validation_failed", { errors, detail: "2 field(s) failed" }));
    const answer = refusal(await queryAuditLog({ from: "b", to: "a" }));
    expect(answer.errors).toHaveLength(10);
    expect(answer.errors?.[0]).toEqual({ field: "to", rule: "value_error" });
    expect(answer.detail).toBe("2 field(s) failed");
  });

  it("test_queryAuditLog_400_invalid_cursor_is_refused_with_that_code", async () => {
    stubFetch(() => problem(400, "invalid_cursor"));
    expect(refusal(await queryAuditLog({ cursor: "zz" })).code).toBe("invalid_cursor");
  });

  it("test_queryAuditLog_refusal_without_a_problem_body_has_no_code_and_no_ref", async () => {
    stubFetch(() => new Response("bad gateway", { status: 502 }));
    expect(await queryAuditLog({})).toEqual({ kind: "refused", status: 502, code: null });
    stubFetch(() => json(403, { code: "<b>x</b>", instance: "<img src=x onerror=1>" }));
    expect(await queryAuditLog({})).toEqual({ kind: "refused", status: 403, code: null });
  });
});

describe("vetAuditPage: an unknown enum value or a missing field is a failed read", () => {
  it("test_vetAuditPage_served_page_passes_and_unknown_fields_are_dropped", () => {
    const raw = pageBody([{ ...entry(), extra: "x" } as ReturnType<typeof entry>], { next: "c" });
    const body = vetAuditPage(raw);
    expect(body?.items[0]).toEqual(entry());
    expect(body?.meta).toEqual({ next_cursor: "c", has_more: true, count: 1 });
    expect(body?.chain_verified).toBe(true);
  });

  it("test_vetAuditPage_manager_projection_with_nulls_and_empty_detail_passes", () => {
    const projected = entry({
      actor_user_id: OWNER_ID,
      subject_label: null,
      environment: null,
      ip: null,
      session_id: null,
      user_agent: null,
      reason: null,
      entry_hash: null,
      prev_hash: null,
      detail: {},
    });
    expect(vetAuditPage(pageBody([projected]))?.items).toEqual([projected]);
  });

  it.each([
    ["an unknown severity", { severity: "fatal" }],
    ["an unknown outcome", { outcome: "ok" }],
    ["an unknown environment", { environment: "staging" }],
    ["a missing id", { id: undefined }],
    ["a fractional id", { id: 1.5 }],
    ["an unreadable time", { ts: "yesterday" }],
    ["a detail that is a list", { detail: [] }],
    ["an after that is a string", { detail: { after: "x" } }],
    ["an elided name it does not know", { detail: { before: null, elided: ["middle"] } }],
    ["a hash that is a number", { entry_hash: 7 }],
  ])("test_vetAuditPage_entry_with_%s_fails_the_whole_page", (_name, change) => {
    const bad = { ...entry(), ...change };
    expect(vetAuditPage(pageBody([entry({ id: 1 }), bad as ReturnType<typeof entry>]))).toBeNull();
  });

  it("test_vetAuditPage_more_without_a_cursor_or_no_chain_verified_is_unreadable", () => {
    const page = pageBody([entry()]);
    expect(
      vetAuditPage({ ...page, meta: { has_more: true, count: 1, next_cursor: null } }),
    ).toBeNull();
    expect(vetAuditPage({ items: page.items, meta: page.meta })).toBeNull();
    expect(vetAuditPage({ ...page, meta: undefined })).toBeNull();
    expect(vetAuditPage(null)).toBeNull();
  });
});

describe("Retry-After and the 403 codes", () => {
  it("test_retryAfterSeconds_reads_the_header_seconds_or_date_else_the_problem", () => {
    expect(retryAfterSeconds("12", { retry_after_seconds: 3 }, T0)).toBe(12);
    expect(retryAfterSeconds(new Date(T0 + 30_500).toUTCString(), null, T0)).toBe(30);
    expect(retryAfterSeconds(null, { retry_after_seconds: 3 }, T0)).toBe(3);
    expect(retryAfterSeconds("soon", { retry_after_seconds: -1 }, T0)).toBeUndefined();
    expect(retryAfterSeconds(new Date(T0 - 5_000).toUTCString(), null, T0)).toBe(0);
    expect(retryAfterSeconds("999999", null, T0)).toBe(86_400);
  });

  const r403 = (code: string): AuditRefusal => ({ kind: "refused", status: 403, code });

  it("test_forbiddenMeaning_forbidden_is_the_area_withdrawn", () => {
    // an Owner's, or a Manager's: this client never sends a Manager's `q` or `ip` (BQ-3)
    expect(forbiddenMeaning(r403("forbidden"), {})).toBe("withdrawn");
  });

  it("test_forbiddenMeaning_viewer_403_is_the_area_withdrawn", async () => {
    // a Viewer holds no `audit:read` (#2083): the served refusal names the permission
    stubFetch(() => problem(403, "forbidden", { required_permissions: ["audit:read"] }));
    const answer = refusal(await queryAuditLog({ limit: 200 }));
    expect(answer).toMatchObject({ status: 403, code: "forbidden", refId: REF });
    expect(forbiddenMeaning(answer, {})).toBe("withdrawn");
  });

  it("test_forbiddenMeaning_names_step_up_read_only_and_the_view_as_refusals", () => {
    expect(forbiddenMeaning(r403("step_up_required"), {})).toBe("step_up");
    expect(forbiddenMeaning(r403("session_read_only"), {})).toBe("read_only");
    expect(forbiddenMeaning(r403("view_as_read_only"), {})).toBe("view_as");
    expect(forbiddenMeaning(r403("view_as_expired"), {})).toBe("view_as");
    expect(forbiddenMeaning(r403("csrf_token_invalid"), {})).toBe("other");
    expect(forbiddenMeaning({ kind: "refused", status: 503, code: "forbidden" }, {})).toBeNull();
  });

  it("test_forbiddenMeaning_forbidden_while_viewing_as_is_the_targets_refusal", () => {
    // BQ-9: a read while viewing as answers as the target (`22` View-as, Scope), so the
    // download's `403 forbidden` is the view-as refusal, never the area withdrawn
    expect(forbiddenMeaning(r403("forbidden"), { viewAs: true })).toBe("view_as");
    expect(forbiddenMeaning(r403("forbidden"), { viewAs: false })).toBe("withdrawn");
  });
});

describe("the cadences, set together (the ruling's polling cost)", () => {
  it("test_cadence_block_holds_the_30s_60s_and_2_to_5s_cadences", () => {
    expect(AUDIT_CADENCE).toEqual({
      headRereadMs: 30_000,
      incidentReadMs: 60_000,
      jobPoll: { firstMs: 2_000, stepMs: 1_000, maxMs: 5_000, backoffAfter: 10, backoffMs: 30_000 },
    });
    expect([0, 1, 2, 3, 4, 40].map((n) => jobPollDelay(n))).toEqual([
      2_000, 3_000, 4_000, 5_000, 5_000, 5_000,
    ]);
  });

  it("test_jobPollDelay_backs_off_to_30s_after_ten_failed_polls_in_a_row", () => {
    // C-1135P2-16: an unreadable job is not polled at 5 s for as long as the page is open
    expect(jobPollDelay(12, 9)).toBe(5_000);
    expect(jobPollDelay(12, 10)).toBe(30_000);
    expect(jobPollDelay(0, 40)).toBe(30_000);
  });
});

describe("queryString", () => {
  it("test_queryString_contract_names_in_contract_order_action_repeated_nothing_empty", () => {
    expect(
      queryString({
        q: "a b",
        to: "2026-10-22T14:00:00Z",
        action: ["x.y", "a.b"],
        limit: 200,
        cursor: "c",
        actor_user_id: OWNER_ID,
        subject_id: "",
      }),
    ).toBe(
      `cursor=c&limit=200&actor_user_id=${OWNER_ID}&action=x.y&action=a.b` +
        "&to=2026-10-22T14%3A00%3A00Z&q=a+b",
    );
    expect(queryString({})).toBe("");
  });
});

describe("verifyAuditChain", () => {
  it("test_verifyAuditChain_posts_no_bounds_with_the_csrf_header", async () => {
    vi.spyOn(document, "cookie", "get").mockReturnValue("__Host-cv_csrf=csrf.mac");
    const calls = stubFetch(() => json(200, verifyBody()));
    expect(await verifyAuditChain()).toEqual({ kind: "ok", body: verifyBody() });
    const [sent] = calls;
    expect(sent?.url).toBe("/api/v1/admin/audit/verify");
    expect(sent?.method).toBe("POST");
    expect(JSON.parse(sent?.body ?? "null")).toEqual({});
    expect(sent?.headers.get("X-CSRF-Token")).toBe("csrf.mac");
  });

  it("test_verifyAuditChain_no_answer_is_unknown_never_failed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))),
    );
    expect(await verifyAuditChain()).toEqual({ kind: "unknown" });
  });

  it("test_verifyAuditChain_waits_past_the_server_run_deadline_then_is_unknown", async () => {
    expect(VERIFY_TIMEOUT_MS).toBeGreaterThan(60_000);
    vi.useFakeTimers();
    const signals = hangingFetch();
    const pending = verifyAuditChain();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(signals[0]?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(VERIFY_TIMEOUT_MS - 60_000);
    expect(await pending).toEqual({ kind: "unknown" });
    expect(vi.getTimerCount()).toBe(0);
  });

  it("test_vetVerifyResult_needs_every_required_member_in_its_served_shape", () => {
    expect(vetVerifyResult(BROKEN)).toEqual(BROKEN);
    expect(vetVerifyResult({ ...BROKEN, anchor_hash: "zz" })).toBeNull();
    expect(vetVerifyResult({ ...BROKEN, last_hash: undefined })).toBeNull();
    expect(vetVerifyResult({ ...BROKEN, entries_checked: -1 })).toBeNull();
    expect(vetVerifyResult({ ...BROKEN, first_bad_id: "41207" })).toBeNull();
    expect(vetVerifyResult({ ...BROKEN, checked_at: "later" })).toBeNull();
  });
});

describe("listIncidents", () => {
  it("test_listIncidents_reads_one_page_of_every_status_and_vets_it", async () => {
    // PROPOSED (D04 §7): one read of the newest 100 by `last_seen_at`, never one per status, as
    // each read writes an `admin.area_entered` row
    expect(INCIDENT_LIMIT).toBe(100);
    const body = { items: [incident()], meta: { next_cursor: null, has_more: false, count: 1 } };
    const calls = stubFetch(() => json(200, body));
    expect(await listIncidents()).toEqual({ kind: "ok", body });
    const url = new URL(calls[0]?.url ?? "", "http://x");
    expect(url.pathname).toBe("/api/v1/admin/incidents");
    expect(url.searchParams.get("limit")).toBe(String(INCIDENT_LIMIT));
    expect(url.searchParams.has("status")).toBe(false);
  });

  it("test_vetIncidentPage_unknown_status_or_missing_time_is_unreadable", () => {
    const meta = { next_cursor: null, has_more: false, count: 1 };
    expect(vetIncidentPage({ items: [incident({ status: "closed" as "open" })], meta })).toBeNull();
    expect(
      vetIncidentPage({ items: [{ ...incident(), first_seen_at: undefined }], meta }),
    ).toBeNull();
    expect(vetIncidentPage({ items: [incident({ title: "t".repeat(201) })], meta })).toBeNull();
    expect(vetIncidentPage({ items: [incident()], meta })?.items).toEqual([incident()]);
  });

  it("test_listIncidents_501_is_refused_not_built", async () => {
    stubFetch(() => problem(501, "not_implemented"));
    expect(refusal(await listIncidents())).toMatchObject({ status: 501, code: "not_implemented" });
  });
});
