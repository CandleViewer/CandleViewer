/**
 * E42-S02 (#1023): the users screens' vetting, in the read layer's way (`adminReads.ts`): every served shape is
 * checked before anything shows it, a field a row does not read is dropped, and a value of another shape is never
 * guessed. A status the client does not know reads as unknown, never Active; an id that is not a UUID drops its row;
 * an invite's link is accepted only as a relative `/invite/…` path; a page without its `meta` is unreadable.
 */
import { describe, expect, it } from "vitest";
import {
  userIdOf,
  vetCreatedInvite,
  vetGrants,
  vetMfaPreview,
  vetMfaReset,
  vetPendingInvites,
  vetSessionCount,
  vetUser,
  vetUserPage,
} from "../../../../src/features/admin/users/vet";

const ID = "0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d";
const ID2 = "1d2c3b4a-5f6e-4d7c-8b9a-0f1e2d3c4b5a";
const USER = {
  id: ID,
  username: "alex",
  email: "alex@example.com",
  display_name: "Alex",
  roles: ["manager"],
  status: "active",
  mfa_enabled: true,
  mfa_required: true,
  last_login_at: "2026-11-01T09:00:00Z",
  created_at: "2026-10-01T09:00:00Z",
};

describe("userIdOf", () => {
  it("takes a UUID only", () => {
    expect(userIdOf(ID)).toBe(ID);
    for (const raw of ["", "alex", `${ID}/invite`, "../admin", 7, null, undefined, `${ID} `]) {
      expect(userIdOf(raw), String(raw)).toBeNull();
    }
  });
});

describe("vetUser", () => {
  it("keeps the fields a row reads, in their types", () => {
    expect(vetUser(USER)).toEqual({
      id: ID,
      username: "alex",
      email: "alex@example.com",
      display_name: "Alex",
      roles: ["manager"],
      status: "active",
      mfa_enabled: true,
      last_login_at: "2026-11-01T09:00:00Z",
    });
  });

  it("reads a status it does not know as unknown, never active", () => {
    expect(vetUser({ ...USER, status: "suspended" })?.status).toBe("unknown");
    expect(vetUser({ ...USER, status: 1 })?.status).toBe("unknown");
  });

  it("keeps the known roles alone, and an absent two-factor or sign-in as not known", () => {
    const rest: Record<string, unknown> = { ...USER };
    delete rest["mfa_enabled"];
    delete rest["last_login_at"];
    expect(vetUser({ ...rest, roles: ["owner", "admin", 3] })).toMatchObject({
      roles: ["owner"],
      mfa_enabled: null,
      last_login_at: null,
    });
  });

  it("drops a user without a UUID id, a username or an e-mail", () => {
    expect(vetUser({ ...USER, id: "u1" })).toBeNull();
    expect(vetUser({ ...USER, username: undefined })).toBeNull();
    expect(vetUser({ ...USER, email: 5 })).toBeNull();
    expect(vetUser(null)).toBeNull();
    expect(vetUser([USER])).toBeNull();
  });

  it("caps a name and an address at 320 characters: 321 drops the row or the display name", () => {
    expect(vetUser({ ...USER, username: "u".repeat(320) })?.username).toHaveLength(320);
    expect(vetUser({ ...USER, username: "u".repeat(321) })).toBeNull();
    expect(vetUser({ ...USER, email: "e".repeat(321) })).toBeNull();
    expect(vetUser({ ...USER, display_name: "d".repeat(320) })?.display_name).toHaveLength(320);
    expect(vetUser({ ...USER, display_name: "d".repeat(321) })?.display_name).toBeNull();
  });

  it("drops an unreadable sign-in time rather than guess one", () => {
    expect(vetUser({ ...USER, last_login_at: "yesterday" })?.last_login_at).toBeNull();
  });
});

describe("vetUserPage", () => {
  it("reads the items and the cursor; an item it cannot read is dropped", () => {
    const page = vetUserPage({
      items: [USER, { ...USER, id: "bad" }, { ...USER, id: ID2, username: "sam" }],
      meta: { count: 3, has_more: true, next_cursor: "c1" },
    });
    expect(page?.items.map((u) => u.username)).toEqual(["alex", "sam"]);
    expect(page).toMatchObject({ hasMore: true, nextCursor: "c1" });
  });

  it("reads no further page when the server says none", () => {
    expect(
      vetUserPage({ items: [], meta: { count: 0, has_more: false, next_cursor: null } }),
    ).toEqual({ items: [], hasMore: false, nextCursor: null });
  });

  it("is unreadable without its meta or its items", () => {
    expect(vetUserPage({ items: [USER] })).toBeNull();
    expect(vetUserPage({ meta: { has_more: false } })).toBeNull();
    expect(vetUserPage({ items: [USER], meta: { has_more: "no" } })).toBeNull();
    expect(vetUserPage("[]")).toBeNull();
  });

  it("never follows a page that has more but no cursor", () => {
    expect(
      vetUserPage({ items: [USER], meta: { count: 1, has_more: true, next_cursor: null } }),
    ).toMatchObject({ hasMore: false, nextCursor: null });
  });
});

describe("vetPendingInvites", () => {
  const INVITE = {
    user_id: ID,
    username: "carol",
    email: "carol@example.com",
    display_name: null,
    role: "viewer",
    expires_at: "2026-11-04T10:00:00+00:00",
    expired: false,
  };

  it("reads each pending invite (no link is ever in it)", () => {
    expect(vetPendingInvites({ items: [INVITE, { ...INVITE, user_id: "x" }] })).toEqual([
      {
        user_id: ID,
        username: "carol",
        email: "carol@example.com",
        display_name: null,
        role: "viewer",
        expires_at: "2026-11-04T10:00:00+00:00",
        expired: false,
      },
    ]);
  });

  it("drops an invite without an expiry it can read, or whose expired flag is not a boolean", () => {
    expect(vetPendingInvites({ items: [{ ...INVITE, expires_at: "soon" }] })).toEqual([]);
    expect(vetPendingInvites({ items: [{ ...INVITE, expired: "no" }] })).toEqual([]);
    expect(vetPendingInvites({})).toBeNull();
  });
});

describe("vetGrants, vetSessionCount, vetMfaPreview, vetMfaReset", () => {
  it("reads each grant's account, level and environment", () => {
    expect(
      vetGrants({
        items: [
          {
            exchange_account_id: ID,
            level: "trade",
            account_label: "sub_001",
            environment: "live",
            granted_by: ID2,
          },
          { exchange_account_id: ID2, level: "admin" },
        ],
      }),
    ).toEqual([
      { exchange_account_id: ID, level: "trade", account_label: "sub_001", environment: "live" },
    ]);
  });

  it("counts sessions and keeps nothing about them", () => {
    expect(vetSessionCount({ items: [{ ip: "10.0.0.1", user_agent: "x" }, {}] })).toBe(2);
    expect(vetSessionCount({ items: "2" })).toBeNull();
  });

  it("reads the reset preview, never a count it was not given", () => {
    expect(
      vetMfaPreview({
        message: "x",
        open_position_count: null,
        position_source: "not_deployed",
        positions: "unavailable",
        requires_acknowledge_unknown_positions: true,
        target_user_id: ID,
      }),
    ).toEqual({
      positions: "unavailable",
      openPositionCount: null,
      requiresAcknowledge: true,
    });
    expect(
      vetMfaPreview({ positions: "maybe", requires_acknowledge_unknown_positions: true }),
    ).toBeNull();
  });

  it("reads the reset's counts", () => {
    expect(vetMfaReset({ methods_revoked: 1, sessions_revoked: 2, target_user_id: ID })).toEqual({
      methodsRevoked: 1,
      sessionsRevoked: 2,
    });
    expect(vetMfaReset({ methods_revoked: "1" })).toBeNull();
  });
});

describe("vetCreatedInvite (a create's 201 and a re-issue's, one shape)", () => {
  const CREATED = {
    id: ID,
    username: "carol",
    email: "carol@example.com",
    display_name: null,
    roles: ["viewer"],
    status: "invited",
    invite_url: "/invite/e2e-link",
    invite_expires_at: "2026-11-05T10:00:00+00:00",
    created_at: "2026-11-02T10:00:00+00:00",
  };

  it("reads the user, the relative link and its expiry", () => {
    expect(vetCreatedInvite(CREATED)).toEqual({
      id: ID,
      username: "carol",
      invite_url: "/invite/e2e-link",
      invite_expires_at: "2026-11-05T10:00:00+00:00",
    });
  });

  it.each([
    "https://elsewhere.example/invite/abc",
    "//elsewhere.example/invite/abc",
    "@elsewhere.example/invite/abc",
    "/invite/../admin",
    "/invite/",
    "/invites/abc",
    "javascript:alert(1)",
    "/invite/a b",
  ])("refuses a link that is not a relative /invite/ path: %s", (invite_url) => {
    expect(vetCreatedInvite({ ...CREATED, invite_url })).toBeNull();
  });

  it("refuses an answer without its expiry or a UUID id", () => {
    expect(vetCreatedInvite({ ...CREATED, invite_expires_at: undefined })).toBeNull();
    expect(vetCreatedInvite({ ...CREATED, id: "u1" })).toBeNull();
  });
});
