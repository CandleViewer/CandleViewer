// E15-S03 (#476) PR-1: the `/workspaces*` reads and the `/terminal` resolution. Refusals are
// read by status, code and rule only; a 412 is reported (LY-T06); a 429 carries its wait
// (SR-E15-04); a non-UUID id never reaches a URL; the last-used record is ids only, per user.
import { afterEach, describe, expect, it, vi } from "vitest";

const apiFetch = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>();
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

const api = await import("../../../src/features/workspace/api/workspacesApi");
const { readLastUsed, resolveTerminal, writeLastUsed } =
  await import("../../../src/features/workspace/current/resolveTarget");

const [WS, WS2] = ["0190a000-0000-7000-8000-000000000001", "0190a000-0000-7000-8000-000000000002"];
const LAYOUT = "0190a000-0000-7000-8000-00000000000a";
const USER = "0190a000-0000-7000-8000-0000000000aa";
const res = (status: number, body: unknown = {}, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers });

afterEach(() => {
  apiFetch.mockReset();
  localStorage.clear();
});

describe("workspacesApi", () => {
  it("test_failure_of_maps_each_status_and_keeps_no_free_text", async () => {
    const free = { detail: "free text", errors: [{ rule: "name_taken", message: "free text" }] };
    const cases: [Response, object][] = [
      [res(404), { kind: "not_found" }],
      [res(412), { kind: "precondition_failed" }],
      [res(429, {}, { "Retry-After": "7" }), { kind: "rate_limited", retryAfterS: 7 }],
      [res(503), { kind: "unavailable" }],
      [res(409, { code: "conflict", ...free }), { kind: "conflict", rule: "name_taken" }],
      [res(403, { code: "view_as_read_only" }), { kind: "forbidden", code: "view_as_read_only" }],
      [
        res(422, { code: "unknown_symbol", errors: [{ rule: "unknown_symbol" }] }),
        { kind: "invalid", code: "unknown_symbol", rule: "unknown_symbol" },
      ],
      [new Response(null, { status: 500 }), { kind: "http", status: 500 }],
    ];
    for (const [response, failure] of cases) expect(await api.failureOf(response)).toEqual(failure);
  });

  it("test_reads_are_one_request_and_a_non_uuid_id_makes_no_call", async () => {
    apiFetch.mockResolvedValueOnce(res(200, { id: WS, layouts: [] }, { ETag: "t1" }));
    expect(await api.getWorkspace(WS)).toMatchObject({ ok: true, etag: "t1", value: { id: WS } });
    expect(String(apiFetch.mock.calls[0]?.[0])).toBe(`/api/v1/workspaces/${WS}`);
    expect(await api.getWorkspace("../admin")).toMatchObject({ failure: { kind: "not_found" } });
    apiFetch.mockResolvedValueOnce(res(200, { items: [{ id: WS }] }));
    expect(await api.listWorkspaces()).toMatchObject({ ok: true, value: [{ id: WS }] });
    apiFetch.mockResolvedValueOnce(res(503));
    expect(await api.listWorkspaces()).toMatchObject({ ok: false });
    expect(apiFetch).toHaveBeenCalledTimes(3);
    apiFetch.mockRejectedValueOnce(new TypeError("offline"));
    expect(await api.listWorkspaces()).toEqual({ ok: false, failure: { kind: "network" } });
    apiFetch.mockResolvedValueOnce(new Response("<html>"));
    expect(await api.getWorkspace(WS)).toEqual({ ok: false, failure: { kind: "network" } });
  });

  it("test_a_200_of_the_wrong_shape_is_the_network_failure", async () => {
    const net = { ok: false, failure: { kind: "network" } };
    for (const body of [{}, { id: WS }, { id: 7, layouts: [] }, [], null]) {
      apiFetch.mockResolvedValueOnce(res(200, body));
      expect(await api.getWorkspace(WS)).toEqual(net);
    }
    for (const body of [{}, { items: "x" }, { items: [{}] }, null]) {
      apiFetch.mockResolvedValueOnce(res(200, body));
      expect(await api.listWorkspaces()).toEqual(net);
    }
  });

  it("test_a_read_with_no_answer_is_given_up_after_the_deadline_or_the_callers_abort", async () => {
    vi.useFakeTimers();
    // A hung server: the request ends only when its signal aborts.
    apiFetch.mockImplementation(
      (_path, init) =>
        new Promise((_, fail) => init?.signal?.addEventListener("abort", () => fail(new Error()))),
    );
    const hung = api.getWorkspace(WS);
    await vi.advanceTimersByTimeAsync(api.READ_TIMEOUT_MS - 1);
    expect(vi.getTimerCount()).toBe(1); // still waiting
    await vi.advanceTimersByTimeAsync(1);
    expect(await hung).toEqual({ ok: false, failure: { kind: "network" } });
    const leave = new AbortController();
    const listed = api.listWorkspaces(leave.signal);
    leave.abort();
    expect(await listed).toEqual({ ok: false, failure: { kind: "network" } });
    expect(vi.getTimerCount()).toBe(0); // the deadline is cleared with the read
    vi.useRealTimers();
  });
});

describe("resolveTerminal", () => {
  const ok = (value: unknown) => Promise.resolve({ ok: true, etag: null, value });
  const deps = (list: object[], layoutsOf: Record<string, string[]> = {}) =>
    ({
      list: () => ok(list),
      get: vi.fn((id: string) => ok({ layouts: (layoutsOf[id] ?? []).map((l) => ({ id: l })) })),
    }) as unknown as NonNullable<Parameters<typeof resolveTerminal>[2]>;
  const two = [{ id: WS }, { id: WS2, is_default: true }];
  const open = (w: string, l: string | null) => ({ kind: "open", workspaceId: w, layoutId: l });

  it("test_last_opens_last_used_then_default_then_first", async () => {
    expect(await resolveTerminal("last", null, deps(two))).toEqual(open(WS2, null));
    const last = { workspaceId: WS, layoutId: LAYOUT };
    expect(await resolveTerminal("last", last, deps(two))).toEqual(open(WS, LAYOUT));
    const plain = deps([{ id: WS }, { id: WS2 }]);
    expect(await resolveTerminal("new", null, plain)).toEqual(open(WS, null));
  });

  it("test_a_layout_uuid_opens_its_workspace_and_an_unknown_one_is_not_found", async () => {
    const d = deps(two, { [WS2]: [LAYOUT] });
    expect(await resolveTerminal(LAYOUT, null, d)).toEqual(open(WS2, LAYOUT));
    const other = "0190a000-0000-7000-8000-0000000000ff";
    const notFound = { kind: "failed", failure: { kind: "not_found" } };
    expect(await resolveTerminal(other, null, d)).toEqual(notFound);
    // The remembered workspace first, and one GET per id: never fetched twice.
    vi.mocked(d.get).mockClear();
    const last = { workspaceId: WS2, layoutId: null };
    expect(await resolveTerminal(other, last, d)).toEqual(notFound);
    expect(vi.mocked(d.get).mock.calls.map(([id]) => id)).toEqual([WS2, WS]);
  });

  it("test_a_429_while_probing_ends_the_probe_with_its_wait", async () => {
    const failure = { kind: "rate_limited", retryAfterS: 7 };
    const d = deps(two, { [WS2]: [LAYOUT] });
    vi.mocked(d.get).mockResolvedValueOnce({ ok: false, failure } as never);
    expect(await resolveTerminal(LAYOUT, null, d)).toEqual({ kind: "failed", failure });
    expect(d.get).toHaveBeenCalledTimes(1); // never queued, never the next workspace
  });

  it("test_no_workspace_is_empty_and_a_failed_list_is_failed", async () => {
    expect(await resolveTerminal("last", null, deps([]))).toEqual({ kind: "empty" });
    const failure = { kind: "unavailable" };
    const failed = { list: () => Promise.resolve({ ok: false, failure }), get: vi.fn() };
    expect(await resolveTerminal("last", null, failed as never)).toEqual({
      kind: "failed",
      failure,
    });
  });

  it("test_last_used_is_ids_only_per_user_and_a_tampered_record_reads_as_none", () => {
    const key = `cv.workspace.last.${USER}`;
    writeLastUsed(USER, { workspaceId: WS, layoutId: LAYOUT });
    expect(readLastUsed(USER)).toEqual({ workspaceId: WS, layoutId: LAYOUT });
    expect(readLastUsed("another-user")).toBeNull();
    expect(localStorage.getItem(key)).toBe(JSON.stringify({ workspaceId: WS, layoutId: LAYOUT }));
    for (const raw of [JSON.stringify({ workspaceId: "<b>" }), "{not json"]) {
      localStorage.setItem(key, raw);
      expect(readLastUsed(USER)).toBeNull();
    }
    localStorage.setItem(key, JSON.stringify({ workspaceId: WS, layoutId: 5 }));
    expect(readLastUsed(USER)).toEqual({ workspaceId: WS, layoutId: null });
    const full = {
      getItem: () => null,
      setItem: () => {
        throw new Error("quota");
      },
    };
    expect(() => writeLastUsed(USER, { workspaceId: WS, layoutId: null }, full)).not.toThrow();
  });
});
