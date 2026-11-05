/** E29-S07 (#1028) the summary's reads against a stubbed `apiFetch` (no network). */
import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import {
  MAX_ORDER_READS,
  isDigest,
  reconciliationReads,
} from "../../../src/features/reconciliation/digest";
import { A, digest } from "./support/digests";

const reply = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });
const WINDOW = { fromMs: Date.UTC(2026, 10, 3, 14, 1, 30), toMs: Date.UTC(2026, 10, 3, 14, 2, 11) };
const trade = (orderId: string, type = "Trade") => ({
  exchange_account_id: A,
  order_id: orderId,
  exec_type: type,
  is_paper: false,
});

beforeEach(() => apiFetch.mockReset());

describe("getDigest", () => {
  it("reads the account's latest pass; a member it does not know is tolerated (C-6.3)", async () => {
    apiFetch.mockResolvedValueOnce(reply(200, { ...digest(), later_member: 1 }));
    const got = await reconciliationReads.getDigest(A);
    expect(apiFetch).toHaveBeenCalledWith(
      `/api/v1/exchange-accounts/${A}/reconciliation/latest`,
      undefined,
    );
    expect(got.kind).toBe("ok");
  });

  it.each([
    [404, "none"],
    [403, "forbidden"],
    [503, "unavailable"],
  ] as const)("%i is %s, never a server detail", async (status, kind) => {
    apiFetch.mockResolvedValueOnce(reply(status, { detail: "x" }));
    expect(await reconciliationReads.getDigest(A)).toEqual({ kind });
  });

  it("a body that is not a digest, or a network failure, is unavailable", async () => {
    apiFetch.mockResolvedValueOnce(reply(200, { exchange_account_id: A }));
    expect(await reconciliationReads.getDigest(A)).toEqual({ kind: "unavailable" });
    apiFetch.mockRejectedValueOnce(new TypeError("offline"));
    expect(await reconciliationReads.getDigest(A)).toEqual({ kind: "unavailable" });
    expect(isDigest([])).toBe(false);
  });
});

describe("offlineFills", () => {
  it("Trade fills in the window, grouped by order, each order's state read once", async () => {
    apiFetch.mockResolvedValueOnce(
      reply(200, {
        items: [
          trade("o-1"),
          trade("o-1"),
          trade("o-2"),
          trade("o-3", "AdlTrade"),
          trade("o-4", "Funding"),
        ],
        meta: { has_more: false },
      }),
    );
    apiFetch.mockResolvedValueOnce(reply(200, { state: "filled" }));
    apiFetch.mockResolvedValueOnce(reply(200, { state: "partially_filled" }));
    const got = await reconciliationReads.offlineFills([A], WINDOW);
    expect(got).toEqual([
      { accountId: A, orderId: "o-1", filled: true },
      { accountId: A, orderId: "o-2", filled: false },
    ]);
    expect(apiFetch.mock.calls[0]?.[0]).toBe(
      `/api/v1/executions?exchange_account_ids=${A}&from=2026-11-03T14%3A01%3A30.000Z&to=2026-11-03T14%3A02%3A11.000Z&limit=500`,
    );
    expect(apiFetch).toHaveBeenCalledTimes(3);
  });

  it("is null (no fills clause, never a guess) when the window cannot be read whole", async () => {
    apiFetch.mockResolvedValueOnce(reply(200, { items: [], meta: { has_more: true } }));
    expect(await reconciliationReads.offlineFills([A], WINDOW)).toBeNull();
    const many = Array.from({ length: MAX_ORDER_READS + 1 }, (_, i) => trade(`o-${i}`));
    apiFetch.mockResolvedValueOnce(reply(200, { items: many }));
    expect(await reconciliationReads.offlineFills([A], WINDOW)).toBeNull();
    apiFetch.mockResolvedValueOnce(reply(200, { items: [trade("o-1")] }));
    apiFetch.mockResolvedValueOnce(reply(404));
    expect(await reconciliationReads.offlineFills([A], WINDOW)).toBeNull();
    apiFetch.mockResolvedValueOnce(reply(503));
    expect(await reconciliationReads.offlineFills([A], WINDOW)).toBeNull();
  });

  it("reads nothing for no account, or more than one request may name", async () => {
    expect(await reconciliationReads.offlineFills([], WINDOW)).toBeNull();
    expect(
      await reconciliationReads.offlineFills(
        Array.from({ length: 26 }, () => A),
        WINDOW,
      ),
    ).toBeNull();
    expect(apiFetch).not.toHaveBeenCalled();
  });
});
