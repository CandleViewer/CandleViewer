/**
 * E16-S01 2/9: the recorder screen's REST client against a stubbed `apiFetch` (no network, C-13.5),
 * answered with the `22` examples (fixtures.ts): the calls, one Idempotency-Key per write, the step-up
 * hold (E16-D06 §20.3 (iii)) and §16.4's routing of every declared code. E16-S03 / E16-S04 add the
 * retention set and its sweep's `job_id`, the archive import, the health read and the job result
 * read by the action that issued the id (BQ-2, BQ-4, BQ-11).
 */
import { afterEach, describe, expect, expectTypeOf, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { sendHeld } from "../../../src/features/stepUp/challenge";
import {
  LIST_PAGE_SIZE,
  MAX_LIST_PAGES,
  READ_TIMEOUT_MS,
  readResult,
  recorderApi,
  type CompactionRunResult,
  type JobAction,
  type RetentionPoliciesBody,
  type RetentionSweepResult,
} from "../../../src/features/recorder/recorderApi";
import {
  addManual,
  compactionResult,
  healthDegraded,
  importJanuary,
  importResult,
  listTwo,
  problem,
  purgeAnchoredBound,
  purgeJobRunning,
  retentionAppliedNow,
  retentionDefaults,
  retentionScheduled,
  statusHealthy,
  stepUpRequired,
  storageUsage,
  sweepResult,
} from "./fixtures";

const ID = "e1000000-0000-4000-8000-000000000001";
const JOB = "19000000-0000-4000-8000-000000000001";
const PURGE = {
  symbol: "ETHUSDT",
  confirm_symbol: "ETHUSDT",
  reason: "space",
  before: "2026-09-14T10:00:00Z",
};
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const EMPTY_PAGE = { items: [], meta: { count: 0, has_more: false } };
const OK = { ok: true, status: 200, code: null, stepUp: null, route: null };
/** A set to PUT: the client sends what it is given (the model builds the whole set, BQ-10). */
const POLICY_SET = {
  items: [
    { stream: "trades", retain_days: 7, action: "drop", symbol: null, applies_to_pinned: false },
  ],
} satisfies RetentionPoliciesBody;
/** A succeeded job as `getJob` answers it: `kind` and `result` as the route serves them. */
const done = (kind: string, result: object) => ({
  id: JOB,
  kind,
  status: "succeeded",
  progress_pct: 100,
  result,
  error: null,
});

const reply = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });
/** What call `n` sent, as the server sees it. */
function sent(n = 0) {
  const [url, init] = apiFetch.mock.calls[n] ?? [];
  const idemp = new Headers(init?.headers).get("Idempotency-Key");
  return { url, method: init?.method, body: init?.body, idemp };
}

afterEach(() => vi.clearAllMocks());

// prettier-ignore
const READS = [
  ["list", () => recorderApi.list({ state: "recording", pinned: true }), "/recording/symbols?state=recording&pinned=true", listTwo],
  ["status", () => recorderApi.status(), "/recording/status", statusHealthy],
  ["storage", () => recorderApi.storage(), "/recording/storage", storageUsage],
  ["sessions", () => recorderApi.sessions({ symbol: "BTCUSDT", limit: 1 }), "/recording/sessions?symbol=BTCUSDT&limit=1", EMPTY_PAGE],
  ["coverage", () => recorderApi.coverage({ symbol: "BTCUSDT", stream: ["trades", "klines"] }), "/market/data-coverage?symbol=BTCUSDT&stream=trades&stream=klines", { symbol: "BTCUSDT" }],
  ["job", () => recorderApi.job(JOB, "compact"), `/admin/jobs/${JOB}`, { id: JOB, status: "running", progress_pct: 42 }],
  ["retention", () => recorderApi.retention(), "/recording/retention-policies", retentionDefaults],
  ["health", () => recorderApi.health(), "/admin/health", healthDegraded],
  ["job, a sweep", () => recorderApi.job(JOB, "retention"), `/admin/jobs/${JOB}`, done("retention_sweep", sweepResult)],
  ["job, an import", () => recorderApi.job(JOB, "import"), `/admin/jobs/${JOB}`, done("archive_import", importResult)],
] as const;

// prettier-ignore
const WRITES = [
  ["add", () => recorderApi.add(addManual), "POST", "/recording/symbols", addManual],
  ["update", () => recorderApi.update(ID, { depth: 50 }), "PATCH", `/recording/symbols/${ID}`, { depth: 50 }],
  ["remove", () => recorderApi.remove(ID), "DELETE", `/recording/symbols/${ID}`, undefined],
  ["remove, forced", () => recorderApi.remove(ID, { force: true }), "DELETE", `/recording/symbols/${ID}?force=true`, undefined],
  ["pin", () => recorderApi.pin(ID, { pinned: true }), "PUT", `/recording/symbols/${ID}/pin`, { pinned: true }],
  ["compact", () => recorderApi.compact(), "POST", "/admin/recorder/compact", undefined],
  ["purge", () => recorderApi.purge(PURGE), "POST", "/admin/recorder/purge", PURGE],
  ["set retention", () => recorderApi.setRetention(POLICY_SET), "PUT", "/recording/retention-policies", POLICY_SET],
  ["set retention, apply now", () => recorderApi.setRetention(POLICY_SET, { apply_now: true }), "PUT", "/recording/retention-policies?apply_now=true", POLICY_SET],
  ["import", () => recorderApi.importArchive(importJanuary), "POST", "/admin/recorder/import", importJanuary],
] as const;

describe("recorderApi calls", () => {
  it.each(READS)(
    "%s: a GET with no Idempotency-Key; the body as served",
    async (_, run, path, body) => {
      apiFetch.mockResolvedValueOnce(reply(200, body));
      expect(await run()).toEqual({ ...OK, data: body });
      expect(sent()).toEqual({
        url: `/api/v1${path}`,
        method: "GET",
        body: undefined,
        idemp: null,
      });
    },
  );

  it.each(WRITES)("%s: one fresh Idempotency-Key per call", async (_, run, method, path, body) => {
    apiFetch.mockImplementation(() => Promise.resolve(reply(202, { job_id: JOB })));
    await run();
    await run();
    const [first, second] = [sent(0), sent(1)];
    expect(first).toMatchObject({ url: `/api/v1${path}`, method });
    expect(first.body).toBe(body === undefined ? undefined : JSON.stringify(body));
    expect(first.idemp).toMatch(UUID);
    expect(second.idemp).toMatch(UUID);
    expect(second.idemp).not.toBe(first.idemp);
  });

  it("a stop sends `force` alone, never `purge_data` (§20.3 (ii): purge is the one delete path)", async () => {
    apiFetch.mockResolvedValueOnce(reply(204));
    // @ts-expect-error the stop's query is `force` alone; `purge_data` is not a field of it
    const result = await recorderApi.remove(ID, { purge_data: true });
    expect(sent().url).toBe(`/api/v1/recording/symbols/${ID}`);
    expect(result).toMatchObject({ ok: true, status: 204, data: null, route: null });
  });
});

describe("the step-up hold (E16-D06 §20.3 (iii))", () => {
  it("a 403 step_up_required holds the request; its one re-send is the same submission", async () => {
    apiFetch.mockResolvedValueOnce(reply(403, stepUpRequired));
    const refused = await recorderApi.pin(ID, { pinned: true });
    expect(refused).toMatchObject({ ok: false, status: 403, code: "step_up_required", data: null });
    expect(refused.stepUp?.challenge).toMatchObject({
      challengeId: stepUpRequired.challenge_id,
      actionClass: "recorder",
      actionSummary: "Keep BTCUSDT data forever",
    });
    expect(refused.route).toEqual({ kind: "step_up", hold: refused.stepUp });
    if (refused.stepUp === null) throw new Error("no hold");
    const { held } = refused.stepUp;
    apiFetch.mockResolvedValueOnce(reply(200, listTwo.items[0]));
    const answer = await readResult("pinRecordedSymbol", await sendHeld(held), held);
    expect(sent(1)).toEqual(sent(0));
    expect(answer).toMatchObject({ ok: true, data: listTwo.items[0], route: null });
  });

  it("a retention set's 403 holds the PUT with apply_now; its one re-send answers the sweep's id", async () => {
    apiFetch.mockResolvedValueOnce(reply(403, stepUpRequired));
    const refused = await recorderApi.setRetention(POLICY_SET, { apply_now: true });
    expect(refused).toMatchObject({ ok: false, status: 403, code: "step_up_required", data: null });
    expect(refused.route).toEqual({ kind: "step_up", hold: refused.stepUp });
    if (refused.stepUp === null) throw new Error("no hold");
    const { held } = refused.stepUp;
    apiFetch.mockResolvedValueOnce(reply(200, retentionAppliedNow));
    const answer = await readResult("setRetentionPolicies", await sendHeld(held), held);
    expect(sent(1)).toEqual(sent(0)); // the same URL, body and Idempotency-Key: one submission
    expect(sent(1).url).toBe("/api/v1/recording/retention-policies?apply_now=true");
    expect(answer).toMatchObject({ ok: true, data: retentionAppliedNow, route: null });
  });

  it("a 403 that is not a challenge is a refusal, never a held request", async () => {
    apiFetch.mockResolvedValueOnce(reply(403, problem(403, "session_read_only")));
    const result = await recorderApi.update(ID, { retention_days: 90 });
    expect(result.stepUp).toBeNull();
    expect(result.route).toEqual(t4("session_read_only", 403));
  });
});

function deck(key: string, code: string, serverTime: string | null = null) {
  return { kind: "deck", key, code, serverTime };
}
function t4(code: string | null, status: number, field: string | null = null) {
  return { kind: "t4", code, field, status };
}
const before = (message: string) =>
  problem(422, "validation_failed", {
    errors: [{ field: "before", rule: "before_in_future", message }],
  });
const LOST = { errors: [{ field: "jobId", rule: "job_unknown", message: "the job is unknown" }] };
const FIELD = { errors: [{ field: "symbol", rule: "unlisted", message: "server words" }] };
const NOW = "before is later than the server's clock, which reads 2026-09-14T10:31:03.250Z";
const SERVER_TEXT = [
  "server detail",
  "server's clock",
  "anchored before",
  "is unknown",
  "server words",
];
const purge = () => recorderApi.purge(PURGE);
const compact = () => recorderApi.compact({ older_than_days: 7 });
const poll = (job: JobAction) => () => recorderApi.job(JOB, job);
const add = () => recorderApi.add(addManual);
const setRetention = () => recorderApi.setRetention(POLICY_SET);
const applyNow = () => recorderApi.setRetention(POLICY_SET, { apply_now: true });
const importArchive = () => recorderApi.importArchive(importJanuary);

// prettier-ignore
const ROUTES = [
  ["purge, `before` in the future", purge, before(NOW), deck("storage.purge.refused.before", "validation_failed", "2026-09-14T10:31:03.250Z")],
  ["purge, `before` with no readable time", purge, before("later than the server's clock"), t4("validation_failed", 422, "before")],
  ["purge, pinned", purge, problem(422, "retention_pinned_refused"), deck("storage.purge.refused.pinned", "retention_pinned_refused")],
  ["purge, one running", purge, purgeJobRunning, deck("storage.job.refused.running", "job_running")],
  ["purge, no audit record", purge, problem(503, "audit_unavailable"), deck("storage.purge.refused.audit", "audit_unavailable")],
  ["purge, an anchored bound", purge, purgeAnchoredBound, t4("idempotency_key_reuse", 409, "before")],
  ["purge, the typed symbol differs", purge, problem(422, "purge_confirmation_mismatch"), t4("purge_confirmation_mismatch", 422)],
  ["compact, one running", compact, problem(409, "job_running"), deck("storage.job.refused.running", "job_running")],
  ["compact, the key reused", compact, problem(422, "idempotency_key_reused"), t4("idempotency_key_reused", 422)],
  ["compact poll, the job lost", poll("compact"), problem(404, "not_found", LOST), deck("storage.compact.unknown", "not_found")],
  ["purge poll, the job lost", poll("purge"), problem(404, "not_found", LOST), deck("storage.purge.unknown", "not_found")],
  ["poll, no audit record", poll("purge"), problem(503, "audit_unavailable"), t4("audit_unavailable", 503)],
  ["add, a field refused", add, problem(422, "validation_failed", FIELD), t4("validation_failed", 422, "symbol")],
  ["add, the symbol limit", add, problem(422, "recorder_symbol_limit"), t4("recorder_symbol_limit", 422)],
  ["stop, a trigger holds it", () => recorderApi.remove(ID), problem(409, "conflict"), t4("conflict", 409)],
  ["list, a stale cursor", () => recorderApi.list({ cursor: "c1" }), problem(400, "invalid_cursor"), t4("invalid_cursor", 400)],
  ["set retention, the derived rule", setRetention, problem(422, "retention_invalid_policy"), deck("retention.refused.invalid", "retention_invalid_policy")],
  ["set retention, a field refused", setRetention, problem(422, "validation_failed", FIELD), deck("retention.refused.unknown", "validation_failed")],
  ["set retention, a run already running", applyNow, problem(409, "job_running"), deck("retention.refused.job_running", "job_running")],
  ["set retention, runs off on the server", applyNow, problem(409, "conflict"), deck("retention.refused.scheduler_off", "conflict")],
  ["set retention, no audit record", setRetention, problem(503, "audit_unavailable"), deck("retention.refused.audit", "audit_unavailable")],
  ["set retention, not the owner", setRetention, problem(403, "forbidden"), t4("forbidden", 403)],
  ["set retention, the write budget spent", setRetention, problem(429, "rate_limited"), t4("rate_limited", 429)],
  ["retention read, no store yet", () => recorderApi.retention(), problem(503, "store_unavailable"), t4("store_unavailable", 503)],
  ["import, one running", importArchive, problem(409, "job_running"), deck("storage.job.refused.running", "job_running")],
  ["import, the range refused", importArchive, problem(422, "import_range_invalid"), t4("import_range_invalid", 422)],
  ["import, the key reused", importArchive, problem(422, "idempotency_key_reused"), t4("idempotency_key_reused", 422)],
  ["import, no audit record", importArchive, problem(503, "audit_unavailable"), t4("audit_unavailable", 503)],
  ["import poll, the job lost", poll("import"), problem(404, "not_found", LOST), deck("storage.import.unknown", "not_found")],
  ["sweep poll, the job lost (no deck line)", poll("retention"), problem(404, "not_found", LOST), t4("not_found", 404, "jobId")],
  ["health read, not wired", () => recorderApi.health(), problem(501, "not_implemented"), t4("not_implemented", 501)],
] as const;

describe("E16-D06 §16.4: a refusal is a deck sentence or the generic T4, never server text", () => {
  it.each(ROUTES)("%s", async (_, run, body, route) => {
    apiFetch.mockResolvedValueOnce(reply(body.status, body));
    const result = await run();
    expect(result).toMatchObject({ ok: false, status: body.status, code: body.code, data: null });
    expect(result.route).toEqual(route);
    const text = JSON.stringify(result);
    for (const words of SERVER_TEXT) expect(text).not.toContain(words); // `message`, `detail` stay out
  });

  it.each([
    ["no answer at all", () => apiFetch.mockRejectedValueOnce(new TypeError("offline")), 0],
    ["a 503 with no problem body", () => apiFetch.mockResolvedValueOnce(reply(503)), 503],
  ])("%s is the generic T4 with no code", async (_, answer, status) => {
    answer();
    const result = await recorderApi.sessions();
    expect(result).toEqual({
      ok: false,
      status,
      code: null,
      data: null,
      stepUp: null,
      route: t4(null, status),
    });
  });
});

describe("an answer the client cannot read (A-5309-02)", () => {
  it("a 2xx whose body is not JSON is a failure: the generic T4, no code, no data", async () => {
    apiFetch.mockResolvedValueOnce(new Response("<html>a proxy page</html>", { status: 200 }));
    expect(await recorderApi.status()).toEqual({
      ok: false,
      status: 200,
      code: null,
      data: null,
      stepUp: null,
      route: t4(null, 200),
    });
  });

  it.each([204, 205])("a %i with no body is a success", async (status) => {
    apiFetch.mockResolvedValueOnce(reply(status));
    expect(await recorderApi.remove(ID)).toEqual({ ...OK, status, data: null });
  });
});

describe("the code token: a stable one or none (A-5309-05)", () => {
  it("a `code` that is not one of `22`'s tokens is no code, in the result and the route", async () => {
    apiFetch.mockResolvedValueOnce(reply(500, problem(500, "Something went wrong: secret detail")));
    const result = await add();
    expect(result).toMatchObject({ ok: false, status: 500, code: null, route: t4(null, 500) });
    expect(JSON.stringify(result)).not.toContain("secret detail");
  });
});

describe("a read is bounded (A-5309-06)", () => {
  it("a GET gives up after READ_TIMEOUT_MS as an unanswered call; a write carries no bound", async () => {
    const controller = new AbortController();
    const timeout = vi.spyOn(AbortSignal, "timeout").mockReturnValue(controller.signal);
    try {
      apiFetch.mockImplementationOnce(
        (_url, init) =>
          new Promise<Response>((_, reject) => {
            init?.signal?.addEventListener("abort", () => reject(new Error("timed out")));
          }),
      );
      const pending = recorderApi.status();
      expect(timeout).toHaveBeenCalledWith(READ_TIMEOUT_MS);
      controller.abort();
      expect(await pending).toEqual({
        ok: false,
        status: 0,
        code: null,
        data: null,
        stepUp: null,
        route: t4(null, 0),
      });
      apiFetch.mockResolvedValueOnce(reply(201, listTwo.items[0]));
      await add();
      expect(apiFetch.mock.calls.at(-1)?.[1]?.signal).toBeUndefined();
      expect(timeout).toHaveBeenCalledTimes(1);
    } finally {
      timeout.mockRestore();
    }
  });
});

describe("the whole list, page by page (A-5309-02, C-5309-10 (a))", () => {
  const page = (items: unknown[], next: string | null) => ({
    items,
    meta: { next_cursor: next, has_more: next !== null, count: items.length },
  });

  it("reads `22`'s largest page and follows next_cursor until has_more is false", async () => {
    apiFetch
      .mockResolvedValueOnce(reply(200, page([listTwo.items[0]], "c2")))
      .mockResolvedValueOnce(reply(200, page([listTwo.items[1]], null)));
    const result = await recorderApi.listAll();
    expect(result).toMatchObject({ ok: true, status: 200, data: { items: listTwo.items } });
    expect(sent(0).url).toBe(`/api/v1/recording/symbols?limit=${LIST_PAGE_SIZE}`);
    expect(sent(1).url).toBe(`/api/v1/recording/symbols?limit=${LIST_PAGE_SIZE}&cursor=c2`);
  });

  it("a refused page is the result; an unreadable one, or one past the bound, is a failure", async () => {
    apiFetch.mockResolvedValueOnce(reply(200, page([], "c2")));
    apiFetch.mockResolvedValueOnce(reply(400, problem(400, "invalid_cursor")));
    expect(await recorderApi.listAll()).toMatchObject({
      ok: false,
      route: t4("invalid_cursor", 400),
    });
    apiFetch.mockResolvedValueOnce(reply(200, null));
    expect(await recorderApi.listAll()).toMatchObject({
      ok: false,
      data: null,
      route: t4(null, 200),
    });
    apiFetch.mockReset();
    apiFetch.mockImplementation(() => Promise.resolve(reply(200, page([], "again"))));
    expect(await recorderApi.listAll()).toMatchObject({
      ok: false,
      data: null,
      route: t4(null, 200),
    });
    expect(apiFetch).toHaveBeenCalledTimes(MAX_LIST_PAGES);
  });
});

describe("the retention set's sweep and each job's result (E16-S03 AC 6; BQ-2, BQ-4, BQ-11)", () => {
  it.each([
    ["no apply_now: saved for the nightly run, job_id null", {}, retentionScheduled],
    ["apply_now: the sweep it started, to poll", { apply_now: true }, retentionAppliedNow],
  ] as const)("%s", async (_, query, answer) => {
    apiFetch.mockResolvedValueOnce(reply(200, answer));
    const result = await recorderApi.setRetention(POLICY_SET, query);
    expect(result).toEqual({ ...OK, data: answer });
    expect(result.data?.job_id).toBe(answer.job_id);
  });

  it("a poll reads the result by the action that issued the id, never by its kind", async () => {
    // A compaction and an apply_now sweep both report `kind: retention_sweep` (22 `Job.result`).
    apiFetch.mockResolvedValueOnce(reply(200, done("retention_sweep", compactionResult)));
    const compaction = await recorderApi.job(JOB, "compact");
    apiFetch.mockResolvedValueOnce(reply(200, done("retention_sweep", sweepResult)));
    const sweep = await recorderApi.job(JOB, "retention");
    expect([compaction.data?.result, sweep.data?.result]).toEqual([compactionResult, sweepResult]);
    expectTypeOf(compaction.data?.result).toEqualTypeOf<CompactionRunResult | null | undefined>();
    expectTypeOf(sweep.data?.result).toEqualTypeOf<RetentionSweepResult | null | undefined>();
  });
});
