/** REST client (E40-S01): paths, params the OpenAPI document defines, outcome kinds, pagination. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { alertsApi } from "../../../src/features/alerts/alertsApi";

vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch: vi.fn() }));
import { apiFetch } from "../../../src/lib/http/csrfFetch";
const fetchMock = vi.mocked(apiFetch);
const json = (body: unknown, status = 200): Response =>
  new Response(status === 204 ? null : JSON.stringify(body), { status });

afterEach(() => fetchMock.mockReset());

describe("alertsApi", () => {
  it("follows cursors and sends only spec-defined query parameters", async () => {
    fetchMock
      .mockResolvedValueOnce(
        json({ items: [{ id: "a" }], meta: { has_more: true, next_cursor: "c 1" } }),
      )
      .mockResolvedValueOnce(
        json({ items: [{ id: "b" }], meta: { has_more: false, next_cursor: null } }),
      );
    const out = await alertsApi.list();
    expect(out).toEqual({ kind: "ok", value: [{ id: "a" }, { id: "b" }] });
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/alerts?limit=500");
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/alerts?limit=500&cursor=c%201");
  });

  it("flags a read that hit the page cap while more rows remain", async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(json({ items: [{ id: 1 }], meta: { has_more: true, next_cursor: "n" } })),
    );
    const out = await alertsApi.deliveries({ alertId: "x" });
    expect(out).toMatchObject({ kind: "ok", truncated: true });
    expect(fetchMock).toHaveBeenCalledTimes(10);
  });

  it("reads deliveries by alert and by failed status", async () => {
    fetchMock.mockResolvedValue(json({ items: [], meta: { has_more: false } }));
    await alertsApi.deliveries({ alertId: "x" });
    await alertsApi.deliveries({ status: "failed" });
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual([
      "/api/v1/alerts/deliveries?alert_id=x&limit=100",
      "/api/v1/alerts/deliveries?status=failed&limit=100",
    ]);
  });

  it("writes enabled, snooze and delete with the documented bodies", async () => {
    fetchMock
      .mockResolvedValueOnce(json({ id: "a" }))
      .mockResolvedValueOnce(json({ id: "a" }))
      .mockResolvedValueOnce(json(null, 204));
    await alertsApi.setEnabled("a/b", true);
    await alertsApi.setSnooze("a", null);
    const removed = await alertsApi.remove("a");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/alerts/a%2Fb/enabled");
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ method: "PUT", body: '{"enabled":true}' });
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({ body: '{"until":null}' });
    expect(fetchMock.mock.calls[2]?.[1]).toEqual({ method: "DELETE" });
    expect(removed).toEqual({ kind: "ok", value: null });
  });

  it("maps statuses and network failures to fixed kinds", async () => {
    for (const [status, kind] of [
      [403, "forbidden"],
      [404, "not_found"],
      [422, "invalid"],
      [503, "unavailable"],
    ] as const) {
      fetchMock.mockResolvedValueOnce(json({}, status));
      expect(await alertsApi.setEnabled("a", true)).toEqual({ kind });
    }
    fetchMock.mockRejectedValueOnce(new Error("offline"));
    expect(await alertsApi.remove("a")).toEqual({ kind: "unavailable" });
    fetchMock.mockResolvedValueOnce(json({ items: "nope" }));
    expect(await alertsApi.list()).toEqual({ kind: "unavailable" });
  });

  it("reads the vocabulary signals", async () => {
    fetchMock
      .mockResolvedValueOnce(json({ signals: [{ id: "s" }] }))
      .mockResolvedValueOnce(json({}, 403));
    expect(await alertsApi.vocabulary()).toEqual({ kind: "ok", value: [{ id: "s" }] });
    expect(await alertsApi.vocabulary()).toEqual({ kind: "forbidden" });
  });
});
