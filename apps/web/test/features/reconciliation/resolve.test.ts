/** E29-S07 (#1028) Resolve… → `resolveReconciliation` (BQ-10 of 6575172489), against a stubbed `apiFetch`. */
import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import {
  REASON_MAX,
  readResolve,
  reasonValid,
  resolveReconciliation,
  resolveRequest,
} from "../../../src/features/reconciliation/resolve";

const A = "a1000000-0000-4000-8000-00000000000a";
const reply = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });
const RESOLVED = {
  exchange_account_id: A,
  resolved: "stale_lockout",
  resolved_at: "2026-11-03T14:05:00Z",
};

beforeEach(() => apiFetch.mockReset());

describe("resolveReconciliation", () => {
  it("POSTs the trimmed reason with a fresh Idempotency-Key, and never the arm", async () => {
    apiFetch.mockResolvedValueOnce(reply(200, RESOLVED));
    expect(await resolveReconciliation(A, "  checked on Bybit  ")).toEqual({
      kind: "resolved",
      resolved: RESOLVED,
    });
    const [url, init] = apiFetch.mock.calls[0] ?? [];
    expect(url).toBe(`/api/v1/admin/reconciliation/${A}/resolve`);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(JSON.stringify({ reason: "checked on Bybit" }));
    const headers = new Map(init?.headers as [string, string][]);
    expect(headers.get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/);
    expect([...headers.keys()].some((h) => /arm/i.test(h))).toBe(false);
  });

  it("each decision has its own key; a held request keeps its key for the re-send", () => {
    const one = resolveRequest(A, "abc");
    const two = resolveRequest(A, "abc");
    const key = (h: typeof one) => new Map(h.headers).get("Idempotency-Key");
    expect(key(one)).not.toBe(key(two));
  });

  it("a 403 step_up_required is a challenge with the request held unchanged", async () => {
    const held = resolveRequest(A, "abc");
    const out = await readResolve(
      reply(403, {
        code: "step_up_required",
        challenge_id: "c-1",
        challenge_expires_at: "2026-11-03T14:10:00Z",
        action_class: "accounts",
        status: 403,
        title: "t",
        type: "about:blank",
      }),
      held,
    );
    expect(out).toMatchObject({ kind: "step_up", held, challenge: { actionClass: "accounts" } });
  });

  it.each([
    [409, { code: "conflict", errors: [{ rule: "nothing_to_resolve" }] }, "nothing_to_resolve"],
    [409, { code: "idempotency_in_flight" }, "unavailable"],
    [403, { code: "forbidden" }, "forbidden"],
    [404, { code: "not_found" }, "not_found"],
    [422, { code: "validation_failed" }, "invalid"],
    [501, { code: "not_implemented" }, "not_available"],
    [503, {}, "unavailable"],
    [200, { other: 1 }, "unavailable"],
  ] as const)("%i %o is %s", async (status, body, kind) => {
    expect(await readResolve(reply(status, body), resolveRequest(A, "abc"))).toEqual({ kind });
  });

  it("a network failure is unavailable", async () => {
    apiFetch.mockRejectedValueOnce(new TypeError("offline"));
    expect(await resolveReconciliation(A, "abc")).toEqual({ kind: "unavailable" });
  });

  it("the reason is 3 to 280 characters once trimmed", () => {
    expect(reasonValid("  ab ")).toBe(false);
    expect(reasonValid("abc")).toBe(true);
    expect(reasonValid("x".repeat(REASON_MAX))).toBe(true);
    expect(reasonValid("x".repeat(REASON_MAX + 1))).toBe(false);
  });
});
