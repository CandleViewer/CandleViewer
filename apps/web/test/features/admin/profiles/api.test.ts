/**
 * E28-S01 (#971): the profile screens' REST layer against `22`'s seven operations as this slice uses
 * them: reads settle as fixed kinds, writes carry `Idempotency-Key` (and `If-Match` where `22` requires
 * it), a `403 step_up_required` is held for the gate, and a refusal keeps only the served strings.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createProfile,
  deleteProfile,
  getProfile,
  listAccounts,
  listProfiles,
  pathId,
  profileETag,
  readWrite,
  updateProfile,
  vetRefusal,
} from "../../../../src/features/admin/profiles/api";
import { sendHeld } from "../../../../src/features/stepUp/challenge";
import { ACCOUNT_IDS, account, input, json, stepUpBody, stored } from "./fixtures";

interface Call {
  readonly url: string;
  readonly init: RequestInit;
}

function serve(...answers: Response[]): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: RequestInfo | URL, init: RequestInit = {}) => {
      calls.push({ url: String(url), init });
      const next = answers.shift();
      if (next === undefined) throw new TypeError("network");
      return next;
    }),
  );
  return calls;
}

const header = (call: Call | undefined, name: string): string | null =>
  new Headers(call?.init.headers).get(name);

const PID = "e28f0000-0000-4000-8000-0000000000b1";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("listAccounts", () => {
  it("test_list_accounts_pages_follows_the_cursor_until_has_more_is_false", async () => {
    const calls = serve(
      json(200, {
        items: [account(ACCOUNT_IDS.main, "Main")],
        meta: { has_more: true, next_cursor: "c 1" },
      }),
      json(200, {
        items: [account(ACCOUNT_IDS.sub1, "sub_001"), { junk: 1 }],
        meta: { has_more: false },
      }),
    );
    const outcome = await listAccounts();
    expect(outcome.kind === "ok" && outcome.value.map((a) => a.label)).toEqual(["Main", "sub_001"]);
    expect(calls.map((c) => c.url)).toEqual([
      "/api/v1/exchange-accounts?limit=500",
      "/api/v1/exchange-accounts?limit=500&cursor=c%201",
    ]);
  });

  it("test_list_accounts_refused_or_unreadable_is_a_fixed_kind", async () => {
    serve(json(403, { code: "forbidden" }));
    expect(await listAccounts()).toEqual({ kind: "denied" });
    serve(json(200, { nope: true }));
    expect(await listAccounts()).toEqual({ kind: "failed" });
    serve();
    expect(await listAccounts()).toEqual({ kind: "failed" });
  });
});

describe("listProfiles", () => {
  it("test_list_profiles_reads_the_accounts_path_and_drops_malformed_items", async () => {
    const good = stored(ACCOUNT_IDS.sub1, "sub_001");
    const calls = serve(json(200, { items: [good, { id: 3 }] }));
    const outcome = await listProfiles(ACCOUNT_IDS.sub1);
    expect(outcome).toEqual({ kind: "ok", value: [good] });
    expect(calls[0]?.url).toBe(`/api/v1/exchange-accounts/${ACCOUNT_IDS.sub1}/profiles`);
  });

  it("test_list_profiles_404_is_not_found_and_5xx_failed", async () => {
    serve(json(404, { code: "not_found" }), json(503, { code: "service_unavailable" }));
    expect(await listProfiles(ACCOUNT_IDS.sub1)).toEqual({ kind: "not_found" });
    expect(await listProfiles(ACCOUNT_IDS.sub1)).toEqual({ kind: "failed" });
  });
});

describe("getProfile", () => {
  it("test_get_profile_keeps_the_served_etag", async () => {
    const p = stored(ACCOUNT_IDS.sub1, "sub_001");
    serve(json(200, p, { ETag: 'W/"served:7"' }));
    const outcome = await getProfile(ACCOUNT_IDS.sub1, p.id);
    expect(outcome).toEqual({ kind: "ok", value: { profile: p, etag: 'W/"served:7"' } });
  });

  it("test_get_profile_without_a_tag_falls_back_to_the_published_form", async () => {
    const p = stored(ACCOUNT_IDS.sub1, "sub_001");
    serve(json(200, p));
    const outcome = await getProfile(ACCOUNT_IDS.sub1, p.id);
    expect(outcome.kind === "ok" && outcome.value.etag).toBe(`W/"${p.id}:2"`);
    expect(profileETag(p)).toBe(`W/"${p.id}:2"`);
  });
});

describe("writes", () => {
  it("test_create_posts_the_policy_with_an_idempotency_key_and_no_if_match", async () => {
    const created = stored(ACCOUNT_IDS.sub1, "copy");
    const calls = serve(json(201, created, { ETag: 'W/"x:1"' }));
    const body = input("copy");
    const outcome = await createProfile(ACCOUNT_IDS.sub1, body);
    expect(outcome).toEqual({ kind: "ok", profile: created, etag: 'W/"x:1"' });
    expect(calls[0]?.init.method).toBe("POST");
    expect(JSON.parse(String(calls[0]?.init.body))).toEqual(body);
    expect(header(calls[0], "Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/);
    expect(header(calls[0], "If-Match")).toBeNull();
  });

  it("test_update_sends_if_match_and_the_whole_profile", async () => {
    const calls = serve(json(200, stored(ACCOUNT_IDS.sub1, "sub_001")));
    await updateProfile(ACCOUNT_IDS.sub1, PID, input("sub_001"), 'W/"p1:2"');
    expect(calls[0]?.init.method).toBe("PUT");
    expect(calls[0]?.url).toBe(`/api/v1/exchange-accounts/${ACCOUNT_IDS.sub1}/profiles/${PID}`);
    expect(header(calls[0], "If-Match")).toBe('W/"p1:2"');
  });

  it("test_delete_sends_the_profiles_tag_and_reads_204_as_ok", async () => {
    const p = stored(ACCOUNT_IDS.sub1, "sub_001 0.5R");
    const calls = serve(json(204, null));
    expect(await deleteProfile(p)).toEqual({ kind: "ok", profile: null, etag: null });
    expect(calls[0]?.init.method).toBe("DELETE");
    expect(header(calls[0], "If-Match")).toBe(profileETag(p));
    expect(calls[0]?.init.body).toBeUndefined();
  });

  it("test_a_step_up_refusal_is_held_unchanged_for_the_gate", async () => {
    const p = stored(ACCOUNT_IDS.sub1, "sub_001");
    const calls = serve(json(403, stepUpBody()), json(204, null));
    const outcome = await deleteProfile(p);
    if (outcome.kind !== "step_up") throw new Error(`expected a hold, got ${outcome.kind}`);
    expect(outcome.hold.challenge.actionClass).toBe("risk_caps");
    // the re-send is the same request: same key, same tag
    await sendHeld(outcome.hold.held);
    expect(header(calls[1], "Idempotency-Key")).toBe(header(calls[0], "Idempotency-Key"));
    expect(header(calls[1], "If-Match")).toBe(header(calls[0], "If-Match"));
  });

  it("test_a_plain_403_is_a_refusal_not_a_hold", async () => {
    serve(json(403, { code: "forbidden", status: 403 }));
    const outcome = await deleteProfile(stored(ACCOUNT_IDS.sub1, "x"));
    expect(outcome).toEqual({
      kind: "refused",
      refusal: { status: 403, code: "forbidden", detail: null, errors: [] },
    });
  });

  it("test_no_answer_is_unknown_never_a_refusal", async () => {
    serve();
    expect(await createProfile(ACCOUNT_IDS.sub1, input("x"))).toEqual({ kind: "unknown" });
  });

  it("test_read_write_of_an_unreadable_error_body_keeps_the_status", async () => {
    const held = { method: "DELETE", url: "/x", headers: [], body: null } as const;
    const res = new Response("<html>", { status: 502 });
    expect(await readWrite(res, held)).toEqual({
      kind: "refused",
      refusal: { status: 502, code: "unknown", detail: null, errors: [] },
    });
  });
});

describe("vetRefusal", () => {
  it("test_vet_refusal_keeps_served_strings_and_drops_everything_else", () => {
    const refusal = vetRefusal(422, {
      code: "validation_failed",
      detail: "Nothing was saved.",
      errors: [
        {
          field: "leverage",
          rule: "max_leverage",
          message: "SOLUSDT allows at most 20x — your 25x would be rejected.",
          symbol: "SOLUSDT",
          limit: "20",
          extra: { nested: true },
        },
        "junk",
        { field: 7, message: "x".repeat(501) },
      ],
    });
    expect(refusal).toEqual({
      status: 422,
      code: "validation_failed",
      detail: "Nothing was saved.",
      errors: [
        {
          field: "leverage",
          rule: "max_leverage",
          message: "SOLUSDT allows at most 20x — your 25x would be rejected.",
          symbol: "SOLUSDT",
          limit: "20",
        },
        {},
      ],
    });
  });
});

const BAD_IDS = [".", "..", "", "a/b", "%2e%2e", "%2E", "not-a-uuid", `${ACCOUNT_IDS.main}/x`];

describe("ids in request paths", () => {
  it("test_path_id_accepts_only_the_contract_uuid_shape", () => {
    expect(pathId(ACCOUNT_IDS.main)).toBe(ACCOUNT_IDS.main);
    expect(pathId(ACCOUNT_IDS.main.toUpperCase())).toBe(ACCOUNT_IDS.main);
    for (const id of BAD_IDS) expect(pathId(id)).toBeNull();
  });

  it("test_reads_with_a_malformed_id_send_nothing_and_are_not_found", async () => {
    const calls = serve(json(200, { items: [] }));
    const good = stored(ACCOUNT_IDS.sub1, "sub_001");
    for (const id of BAD_IDS) {
      expect(await listProfiles(id)).toEqual({ kind: "not_found" });
      expect(await getProfile(id, good.id)).toEqual({ kind: "not_found" });
      expect(await getProfile(ACCOUNT_IDS.sub1, id)).toEqual({ kind: "not_found" });
    }
    expect(calls).toEqual([]);
  });

  it("test_writes_with_a_malformed_id_send_nothing_and_are_refused_as_not_found", async () => {
    const calls = serve(json(200, {}));
    const good = stored(ACCOUNT_IDS.sub1, "sub_001");
    const refused = { kind: "refused", refusal: { status: 404, code: "not_found" } };
    for (const id of BAD_IDS) {
      expect(await createProfile(id, input("sub_001"))).toMatchObject(refused);
      expect(await updateProfile(id, good.id, input("sub_001"), 'W/"x:1"')).toMatchObject(refused);
      expect(await updateProfile(ACCOUNT_IDS.sub1, id, input("sub_001"), 'W/"x:1"')).toMatchObject(
        refused,
      );
      expect(await deleteProfile({ ...good, id })).toMatchObject(refused);
    }
    expect(calls).toEqual([]);
  });

  it("test_a_valid_uuid_still_builds_the_expected_path", async () => {
    const good = stored(ACCOUNT_IDS.sub1, "sub_001");
    const calls = serve(json(200, good));
    await getProfile(ACCOUNT_IDS.sub1, good.id);
    expect(calls[0]?.url).toBe(`/api/v1/exchange-accounts/${ACCOUNT_IDS.sub1}/profiles/${good.id}`);
  });

  it("test_a_served_profile_or_account_with_a_malformed_id_is_refused_at_the_vet_step", async () => {
    const good = stored(ACCOUNT_IDS.sub1, "sub_001");
    const odd = { ...good, id: ".." };
    const oddAccount = { ...good, exchange_account_id: "a/b" };
    serve(json(200, { items: [good, odd, oddAccount] }), json(200, odd));
    expect(await listProfiles(ACCOUNT_IDS.sub1)).toEqual({ kind: "ok", value: [good] });
    expect(await getProfile(ACCOUNT_IDS.sub1, good.id)).toEqual({ kind: "failed" });
    serve(json(200, { items: [account("..", "X"), account(ACCOUNT_IDS.main, "Main")] }));
    const accounts = await listAccounts();
    expect(accounts.kind === "ok" && accounts.value.map((a) => a.label)).toEqual(["Main"]);
  });
});
