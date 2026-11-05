import { afterEach, describe, expect, it, vi } from "vitest";
import { savePreferences } from "../../src/features/a11y-preferences/prefsApi";

// #5852: `22` serves the partial update of `/settings` as PATCH only (no PUT handler), so a PUT
// save was a 405 that never persisted.

function reply(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: async () => body } as unknown as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("savePreferences", () => {
  it("sends the accessibility subtree as a PATCH of /api/v1/settings", async () => {
    const f = vi
      .fn()
      .mockResolvedValue(reply(200, { accessibility: { disable_canvas_animation: true } }));
    vi.stubGlobal("fetch", f);
    await savePreferences({ disable_canvas_animation: true });
    expect(f).toHaveBeenCalledTimes(1);
    const [url, init] = f.mock.calls[0] as [RequestInfo | URL, RequestInit];
    expect(String(url)).toBe("/api/v1/settings");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(String(init.body))).toEqual({
      accessibility: { disable_canvas_animation: true },
    });
  });

  it("surfaces a refused save as an error, never as the saved state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(405, {})));
    await expect(savePreferences({ disable_canvas_animation: true })).rejects.toThrow(
      "settings 405",
    );
  });
});
