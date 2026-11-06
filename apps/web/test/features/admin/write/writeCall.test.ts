/**
 * E42-S02 (#1023): the admin area's write call, shared by the users screens, E42-S04's export and E42-S05. A write
 * is held exactly as first sent (method, path with its query, `Idempotency-Key`, body) so a step-up re-send is the
 * same submission (C-2.10); its answer is read into a result the screen routes: the vetted body, the problem's code
 * only when it is one of `22`'s stable tokens, the first error's field and rule, and a `403 step_up_required`'s
 * challenge with the held request and a reader for the re-send's answer. A problem's free text never leaves.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  holdWrite,
  readWrite,
  sendWrite,
  type WriteResult,
} from "../../../../src/features/admin/write/writeCall";

const PATH =
  "/api/v1/users/0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d?acknowledge_unknown_positions=true";
const ATTEMPT = "5f1d2c3b-4a59-4e6d-8c7b-1a2b3c4d5e6f";
const json = (status: number, body: unknown, headers: Record<string, string> = {}): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
const vetName = (raw: unknown): { readonly name: string } | null =>
  typeof raw === "object" && raw !== null && typeof (raw as { name?: unknown }).name === "string"
    ? { name: (raw as { name: string }).name }
    : null;
const CHALLENGE = {
  type: "https://candleviewer.local/errors/step_up_required",
  title: "A dangerous action needs a live step-up elevation for its action class",
  status: 403,
  code: "step_up_required",
  action_class: "users",
  challenge_id: "0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d",
  challenge_expires_at: "2026-11-02T10:05:00Z",
  action_summary: "Disable user 'alex'",
  target: null,
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("holdWrite", () => {
  it("holds the method, the path with its query, the attempt and the JSON body", () => {
    const held = holdWrite("PATCH", PATH, ATTEMPT, { status: "disabled" });
    expect(held.method).toBe("PATCH");
    expect(held.url).toBe(PATH);
    expect(held.body).toBe('{"status":"disabled"}');
    const headers = new Headers(held.headers.map(([k, v]) => [k, v]));
    expect(headers.get("Idempotency-Key")).toBe(ATTEMPT);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("Accept")).toBe("application/json");
    expect(Object.isFrozen(held)).toBe(true);
  });

  it("sends no body and no Content-Type without one", () => {
    const held = holdWrite("DELETE", PATH, ATTEMPT);
    expect(held.body).toBeNull();
    expect(new Headers(held.headers.map(([k, v]) => [k, v])).has("Content-Type")).toBe(false);
  });

  it("sends no Idempotency-Key for a route that ignores it (attempt null)", () => {
    const held = holdWrite("PUT", "/api/v1/admin/capacity/subaccount-tier", null, {
      tier: "regular",
    });
    const headers = new Headers(held.headers.map(([k, v]) => [k, v]));
    expect(headers.has("Idempotency-Key")).toBe(false);
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("adds a route's own If-Match and no other header: never the kit's, the bearer or the CSRF token", () => {
    const held = holdWrite(
      "PATCH",
      PATH,
      ATTEMPT,
      { status: "disabled" },
      {
        "If-Match": '"v7"',
        "idempotency-key": "forged",
        Accept: "text/html",
        Authorization: "forged",
        "X-CSRF-Token": "forged",
        "X-Route-Note": "forged",
      },
    );
    const headers = new Headers(held.headers.map(([k, v]) => [k, v]));
    expect(headers.get("If-Match")).toBe('"v7"');
    expect(headers.get("Idempotency-Key")).toBe(ATTEMPT);
    expect(headers.get("Accept")).toBe("application/json");
    expect(headers.get("Content-Type")).toBe("application/json");
    for (const name of ["Authorization", "X-CSRF-Token", "X-Route-Note"]) {
      expect(headers.has(name), name).toBe(false);
    }
    expect(held.headers.map(([name]) => name.toLowerCase()).sort()).toEqual([
      "accept",
      "content-type",
      "idempotency-key",
      "if-match",
    ]);
  });
});

describe("sendWrite and readWrite", () => {
  it("sends the held request as held and reads a 2xx through the vet", async () => {
    const fetch = vi.fn(async () => json(200, { name: "alex", extra: { nested: true } }));
    vi.stubGlobal("fetch", fetch);
    const held = holdWrite("PATCH", PATH, ATTEMPT, { status: "disabled" });
    const res = await sendWrite(held, vetName);
    expect(res).toMatchObject<Partial<WriteResult<unknown>>>({
      ok: true,
      status: 200,
      data: { name: "alex" },
      code: null,
      stepUp: null,
    });
    const [input, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(input).toBe(PATH);
    expect(init.method).toBe("PATCH");
    expect(init.body).toBe('{"status":"disabled"}');
    expect(new Headers(init.headers).get("Idempotency-Key")).toBe(ATTEMPT);
  });

  it("a 2xx whose body the vet refuses is still done: ok, with no data (the caller reads back)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(200, { other: 1 })),
    );
    const res = await sendWrite(holdWrite("PATCH", PATH, ATTEMPT, {}), vetName);
    expect(res).toMatchObject({ ok: true, status: 200, data: null });
  });

  it("a 204 is done with no data and no vet", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 204 })),
    );
    const vet = vi.fn(vetName);
    const res = await sendWrite(holdWrite("DELETE", PATH, ATTEMPT), vet);
    expect(res).toMatchObject({ ok: true, status: 204, data: null });
    expect(vet).not.toHaveBeenCalled();
  });

  it("keeps a problem's code only when it is a stable token, with its first error's field and rule", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json(422, {
          code: "validation_failed",
          detail: "username already taken by alex@example.com",
          errors: [{ field: "username", rule: "pattern", message: "free text" }],
        }),
      ),
    );
    const res = await sendWrite(holdWrite("POST", "/api/v1/users", ATTEMPT, {}), vetName);
    expect(res).toMatchObject({
      ok: false,
      status: 422,
      code: "validation_failed",
      field: "username",
      rule: "pattern",
      data: null,
      stepUp: null,
    });
    expect(JSON.stringify(res)).not.toContain("alex@example.com");
    expect(JSON.stringify(res)).not.toContain("free text");
  });

  it("keeps a field or rule of 64 characters and drops a longer one", async () => {
    const at64 = "f".repeat(64);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json(422, { code: "validation_failed", errors: [{ field: at64, rule: "r".repeat(65) }] }),
      ),
    );
    const res = await sendWrite(holdWrite("POST", "/api/v1/users", ATTEMPT, {}), vetName);
    expect(res).toMatchObject({ field: at64, rule: null });
  });

  it("reads the answer's ETag and its Retry-After in whole seconds; a date form is none", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(200, { name: "alex" }, { ETag: '"v8"', "Retry-After": "3" })),
    );
    const res = await sendWrite(holdWrite("PATCH", PATH, ATTEMPT, {}), vetName);
    expect(res).toMatchObject({ etag: '"v8"', retryAfter: 3 });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json(429, { code: "rate_limited" }, { "Retry-After": "Mon, 02 Nov 2026 10:00:05 GMT" }),
      ),
    );
    const later = await sendWrite(holdWrite("PATCH", PATH, ATTEMPT, {}), vetName);
    expect(later).toMatchObject({ status: 429, etag: null, retryAfter: null });
  });

  it("reads an unknown or free-text code as no code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(409, { code: "Email or username in use" })),
    );
    const res = await sendWrite(holdWrite("POST", "/api/v1/users", ATTEMPT, {}), vetName);
    expect(res).toMatchObject({ ok: false, status: 409, code: null });
  });

  it("a 403 step_up_required carries the challenge, the held request and a reader for the re-send", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(403, CHALLENGE, { Date: "Mon, 02 Nov 2026 10:00:00 GMT" })),
    );
    const held = holdWrite("PATCH", PATH, ATTEMPT, { status: "disabled" });
    const res = await sendWrite(held, vetName);
    expect(res).toMatchObject({ ok: false, status: 403, code: "step_up_required" });
    expect(res.stepUp?.held).toBe(held);
    expect(res.stepUp?.challenge).toMatchObject({
      challengeId: CHALLENGE.challenge_id,
      actionClass: "users",
      actionSummary: "Disable user 'alex'",
    });
    const again = await res.stepUp?.read(json(200, { name: "alex" }));
    expect(again).toMatchObject({ ok: true, data: { name: "alex" }, stepUp: null });
  });

  it("a 403 that is no challenge is a refusal with its code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(403, { code: "forbidden" })),
    );
    const res = await sendWrite(holdWrite("DELETE", PATH, ATTEMPT), vetName);
    expect(res).toMatchObject({ ok: false, status: 403, code: "forbidden", stepUp: null });
  });

  it("a network error is no answer: status 0, nothing done", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    const res = await sendWrite(holdWrite("DELETE", PATH, ATTEMPT), vetName);
    expect(res).toMatchObject({
      ok: false,
      status: 0,
      code: null,
      data: null,
      stepUp: null,
      etag: null,
      retryAfter: null,
    });
  });

  it("an error body that is not JSON has no code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<html>bad gateway</html>", { status: 502 })),
    );
    const res = await readWrite(await fetch("/x"), holdWrite("DELETE", PATH, ATTEMPT), vetName);
    expect(res).toMatchObject({ ok: false, status: 502, code: null, field: null, rule: null });
  });
});
