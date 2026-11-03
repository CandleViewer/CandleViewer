/**
 * E42-S04 (#1135): the audit log's read layer (E42-D04 §4, §7, §8; the plan's §3). Each of the six
 * operations goes through `apiFetch`, typed from `packages/protocol`, and settles as one of four
 * answers: `ok` (the body vetted, an unknown enum or a missing field unreadable), `refused` (the
 * status, the problem's code, `Retry-After`, the Ref, the field errors and, on the export and its
 * download, the step-up hold), `unknown` (a write that got no answer) or `failed` (a read that got
 * none, or an answer it could not read). List reads stop at 6 s (BQ-11, PROPOSED), above the
 * server's 4 s stop; the tamper check waits past its 60 s deadline (BQ-6). The orchestrator's
 * binding cases live here too: a Viewer's 403, the view-as refusals (the download's `403 forbidden`
 * under view-as is the target's, BQ-9) and `step_up_required` on both the export and its download.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  AUDIT_CADENCE,
  AUDIT_READ_TIMEOUT_MS,
  EXPORT_TIMEOUT_MS,
  INCIDENT_LIMIT,
  VERIFY_TIMEOUT_MS,
  downloadAuditExport,
  exportAuditLog,
  fileNameOf,
  forbiddenMeaning,
  getJob,
  jobPollDelay,
  listIncidents,
  queryAuditLog,
  queryString,
  readDownloadAnswer,
  readExportAnswer,
  retryAfterSeconds,
  verifyAuditChain,
  vetAuditPage,
  vetIncidentPage,
  vetJob,
  vetVerifyResult,
  type AuditAnswer,
  type AuditRefusal,
} from "../../../../src/features/admin/audit/auditReads";
import { holdRequest } from "../../../../src/features/stepUp/challenge";
import {
  BROKEN,
  JOB_ID,
  OWNER_ID,
  REF,
  T0,
  entry,
  exportResult,
  hangingFetch,
  incident,
  job,
  json,
  pageBody,
  problem,
  stepUpRequired,
  stubFetch,
  verifyBody,
} from "./fixtures";

/** The caller's `Idempotency-Key` (a UUIDv4), kept for [Check again] (X11). */
const ONCE = "4d9f0c2b-8e1a-4b7c-9d3e-2f1a0b9c8d7e";
const WINDOW = { from: "2026-10-21T14:00:00Z", to: "2026-10-22T14:00:00Z", compress: true };

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

describe("exportAuditLog: the shipped step-up gate holds the request (inviteApi's idiom)", () => {
  it("test_exportAuditLog_posts_the_window_under_the_given_idempotency_id", async () => {
    const calls = stubFetch(() => json(202, { job_id: JOB_ID, download_url: null }));
    expect(await exportAuditLog(WINDOW, ONCE)).toEqual({
      kind: "ok",
      body: { job_id: JOB_ID, download_url: null },
    });
    const [sent] = calls;
    expect(sent?.url).toBe("/api/v1/admin/audit/export");
    expect(sent?.method).toBe("POST");
    expect(sent?.headers.get("Idempotency-Key")).toBe(ONCE);
    expect(JSON.parse(sent?.body ?? "null")).toEqual(WINDOW);
  });

  it("test_exportAuditLog_step_up_required_holds_the_request_unchanged_for_the_gate", async () => {
    stubFetch(() => stepUpRequired());
    const answer = refusal(await exportAuditLog(WINDOW, ONCE));
    expect(answer.code).toBe("step_up_required");
    expect(answer.stepUp?.challenge).toMatchObject({
      actionClass: "audit",
      challengeId: "6f1d2c3b-4a5e-4f60-8a7b-9c0d1e2f3a4b",
    });
    const held = answer.stepUp?.held;
    expect(held?.method).toBe("POST");
    expect(held?.url).toBe("/api/v1/admin/audit/export");
    expect(new Headers(held?.headers.map(([k, v]) => [k, v])).get("Idempotency-Key")).toBe(ONCE);
    expect(JSON.parse(held?.body ?? "null")).toEqual(WINDOW);
  });

  it("test_readExportAnswer_reads_the_gates_resend_like_a_first_answer", async () => {
    stubFetch(() => stepUpRequired());
    const held = refusal(await exportAuditLog(WINDOW, ONCE)).stepUp?.held;
    if (held === undefined) throw new Error("no hold");
    expect(await readExportAnswer(json(202, { job_id: JOB_ID }), held)).toEqual({
      kind: "ok",
      body: { job_id: JOB_ID },
    });
    expect(refusal(await readExportAnswer(problem(409, "conflict"), held))).toMatchObject({
      status: 409,
      code: "conflict",
    });
  });

  it("test_exportAuditLog_no_answer_is_unknown_and_a_job_id_not_a_uuid_is_unreadable", async () => {
    vi.useFakeTimers();
    hangingFetch();
    const pending = exportAuditLog(WINDOW, ONCE);
    await vi.advanceTimersByTimeAsync(EXPORT_TIMEOUT_MS);
    expect(await pending).toEqual({ kind: "unknown" });
    vi.useRealTimers();
    stubFetch(() => json(202, { job_id: "../../x" }));
    expect(await exportAuditLog(WINDOW, ONCE)).toEqual({ kind: "failed", reason: "unreadable" });
  });

  it("test_exportAuditLog_and_verify_view_as_refusals_are_never_a_step_up", async () => {
    stubFetch(() => problem(403, "view_as_read_only"));
    const exported = refusal(await exportAuditLog(WINDOW, ONCE));
    expect(exported).toMatchObject({ status: 403, code: "view_as_read_only" });
    expect(exported.stepUp).toBeUndefined();
    expect(forbiddenMeaning(exported, {})).toBe("view_as");
    stubFetch(() => problem(403, "view_as_expired"));
    const verified = refusal(await verifyAuditChain());
    expect(forbiddenMeaning(verified, {})).toBe("view_as");
  });

  it("test_exportAuditLog_refusals_keep_their_code_and_retry_after", async () => {
    stubFetch(() => problem(429, "rate_limited", {}, { "Retry-After": "1200" }));
    expect(refusal(await exportAuditLog(WINDOW, ONCE))).toMatchObject({
      status: 429,
      code: "rate_limited",
      retryAfterS: 1200,
    });
    stubFetch(() =>
      problem(422, "validation_failed", {
        detail: "the window is longer than audit_export_max_range_days (31)",
        errors: [{ field: "to", rule: "max_export_range" }],
      }),
    );
    expect(refusal(await exportAuditLog(WINDOW, ONCE))).toMatchObject({
      detail: "the window is longer than audit_export_max_range_days (31)",
      errors: [{ field: "to", rule: "max_export_range" }],
    });
  });
});

describe("getJob", () => {
  it("test_getJob_asks_the_jobs_path_and_answers_a_running_job", async () => {
    const calls = stubFetch(() => json(200, job()));
    expect(await getJob(JOB_ID)).toEqual({ kind: "ok", body: job() });
    expect(calls[0]?.url).toBe(`/api/v1/admin/jobs/${JOB_ID}`);
    expect(calls[0]?.method).toBe("GET");
  });

  it("test_getJob_is_not_a_list_read_its_bound_is_the_exports", async () => {
    // BQ-11 as ruled: the 6 s bound is the list reads' alone
    expect(EXPORT_TIMEOUT_MS).toBeGreaterThan(AUDIT_READ_TIMEOUT_MS);
    vi.useFakeTimers();
    const signals = hangingFetch();
    const pending = getJob(JOB_ID);
    await vi.advanceTimersByTimeAsync(AUDIT_READ_TIMEOUT_MS);
    expect(signals[0]?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(EXPORT_TIMEOUT_MS - AUDIT_READ_TIMEOUT_MS);
    expect(await pending).toEqual({ kind: "failed", reason: "timeout" });
  });

  it("test_vetJob_succeeded_export_needs_a_whole_result_in_its_served_shape", () => {
    const done = job({ status: "succeeded", progress_pct: 100, result: exportResult() });
    expect(vetJob(done)).toEqual(done);
    for (const change of [
      { sha256: "abc" },
      { signature_alg: "rsa" },
      { key_id: "k1" },
      { row_count: -1 },
      { expires_at: undefined },
    ]) {
      expect(vetJob({ ...done, result: { ...exportResult(), ...change } })).toBeNull();
    }
  });

  it("test_vetJob_unknown_status_is_unreadable_and_an_unknown_kind_is_tolerated", () => {
    expect(vetJob(job({ status: "paused" as "running" }))).toBeNull();
    expect(vetJob({ ...job(), status: undefined })).toBeNull();
    expect(vetJob(job({ progress_pct: 101 }))).toBeNull();
    expect(vetJob(job({ kind: "future_kind" as "backup" }))?.kind).toBe("future_kind");
  });

  it("test_getJob_404_job_unknown_and_failed_jobs_keep_their_codes", async () => {
    stubFetch(() => problem(404, "not_found", { errors: [{ rule: "job_unknown" }] }));
    expect(refusal(await getJob(JOB_ID)).status).toBe(404);
    stubFetch(() => json(200, job({ status: "failed", error: "export_too_large" })));
    expect(await getJob(JOB_ID)).toMatchObject({ kind: "ok", body: { error: "export_too_large" } });
  });
});

describe("downloadAuditExport", () => {
  it("test_downloadAuditExport_answers_the_bytes_with_the_served_file_name", async () => {
    const calls = stubFetch(
      () =>
        new Response("{}\n", {
          status: 200,
          headers: {
            "Content-Type": "application/gzip",
            "Content-Disposition": `attachment; filename="${JOB_ID}.ndjson.gz"`,
          },
        }),
    );
    const answer = await downloadAuditExport(JOB_ID);
    if (answer.kind !== "ok") throw new Error(answer.kind);
    expect(answer.body.fileName).toBe(`${JOB_ID}.ndjson.gz`);
    expect(answer.body.contentType).toBe("application/gzip");
    expect(await answer.body.blob.text()).toBe("{}\n");
    expect(calls[0]?.url).toBe(`/api/v1/admin/audit/exports/${JOB_ID}`);
    expect(calls[0]?.method).toBe("GET");
  });

  it("test_downloadAuditExport_step_up_holds_the_get_and_reads_the_resend", async () => {
    stubFetch(() => stepUpRequired());
    const answer = refusal(await downloadAuditExport(JOB_ID));
    const held = answer.stepUp?.held;
    if (held === undefined) throw new Error("no hold");
    expect(held).toMatchObject({ method: "GET", body: null });
    const resent = new Response("x", { status: 200, headers: { "Content-Type": "text/plain" } });
    const again = await readDownloadAnswer(resent, held, JOB_ID);
    expect(again).toMatchObject({ kind: "ok", body: { fileName: `${JOB_ID}.ndjson` } });
  });

  it.each([
    [404, "not_found"],
    [410, "gone"],
    [429, "rate_limited"],
    [503, "store_unavailable"],
  ])("test_downloadAuditExport_%i_is_refused_with_its_code", async (status, code) => {
    stubFetch(() => problem(status, code));
    expect(refusal(await downloadAuditExport(JOB_ID))).toMatchObject({ status, code });
  });

  it("test_downloadAuditExport_bound_covers_the_answer_not_the_transfer", async () => {
    vi.useFakeTimers();
    let push: ((chunk: string) => void) | undefined;
    let end: (() => void) | undefined;
    stubFetch((sent) => {
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          push = (chunk) => controller.enqueue(new TextEncoder().encode(chunk));
          end = () => controller.close();
          // as a browser does: aborting the request errors its body mid-transfer
          sent.signal?.addEventListener("abort", () =>
            controller.error(new DOMException("aborted", "AbortError")),
          );
        },
      });
      return new Response(stream, {
        status: 200,
        headers: { "Content-Type": "application/x-ndjson" },
      });
    });
    const pending = downloadAuditExport(JOB_ID);
    await vi.advanceTimersByTimeAsync(EXPORT_TIMEOUT_MS * 3);
    push?.("{}\n");
    end?.();
    const answer = await pending;
    expect(answer.kind).toBe("ok");
  });

  it("test_readDownloadAnswer_a_body_that_breaks_off_is_failed_never_a_rejection", async () => {
    // C-1135P2-01: the gate's re-send reads its own answer, so every answer settles there too
    const broken = new Response(
      new ReadableStream<Uint8Array>({
        pull(controller) {
          controller.error(new TypeError("network error"));
        },
      }),
      { status: 200, headers: { "Content-Type": "application/gzip" } },
    );
    const held = holdRequest("GET", `/api/v1/admin/audit/exports/${JOB_ID}`, {}, null);
    await expect(readDownloadAnswer(broken, held, JOB_ID)).resolves.toEqual({
      kind: "failed",
      reason: "network",
    });
  });

  it("test_fileNameOf_keeps_a_plain_served_ndjson_name_else_the_job_id", () => {
    const gz = "application/gzip";
    expect(fileNameOf('attachment; filename="a.ndjson"', JOB_ID, gz)).toBe("a.ndjson");
    expect(fileNameOf("attachment; filename=b.ndjson.gz", JOB_ID, gz)).toBe("b.ndjson.gz");
    expect(fileNameOf("attachment; filename*=UTF-8''c%20d.ndjson", JOB_ID, gz)).toBe("c_d.ndjson");
    expect(fileNameOf('attachment; filename="../../etc/b.ndjson"', JOB_ID, gz)).toBe("b.ndjson");
    // S-1135P2-03: a name that is not NDJSON, gzipped or not, is the job's own
    expect(fileNameOf('attachment; filename="../../etc/passwd"', JOB_ID, gz)).toBe(
      `${JOB_ID}.ndjson.gz`,
    );
    expect(fileNameOf('attachment; filename="report.exe"', JOB_ID, gz)).toBe(`${JOB_ID}.ndjson.gz`);
    expect(fileNameOf('attachment; filename=".."', JOB_ID, gz)).toBe(`${JOB_ID}.ndjson.gz`);
    expect(fileNameOf(null, JOB_ID, "application/x-ndjson")).toBe(`${JOB_ID}.ndjson`);
    expect(fileNameOf(`attachment; filename="${"x".repeat(300)}"`, JOB_ID, gz)).toBe(
      `${JOB_ID}.ndjson.gz`,
    );
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
