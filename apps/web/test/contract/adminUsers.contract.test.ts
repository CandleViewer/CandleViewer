/**
 * C-6.2 consumer contract (E42-S02, #1023): the users client's vocabularies and requests are the contract's. The
 * request and answer types are the generated `packages/protocol` ones; the client's role and status lists, its page
 * size and its search length are the spec's; every route and method it calls is declared in
 * `docs/plan/22-api-openapi.yaml` with the operation the client names.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, expectTypeOf, it } from "vitest";
import type { generated } from "@candleviewer/protocol";
import { PAGE_SIZE, Q_MAX, ROLE_NAMES, USER_STATUSES } from "../../src/features/admin/users/query";
import type { InviteInput, InviteBody } from "../../src/features/admin/users/usersApi";
import { USERS_ROUTES } from "../../src/features/admin/users/usersApi";
import type { CreatedInvite, Grant, VettedUser } from "../../src/features/admin/users/vet";

type Ops = generated.rest.operations;
type Schemas = generated.rest.components["schemas"];
type Json<T> = T extends { content: { "application/json": infer B } } ? B : never;

const SPEC = readFileSync(
  resolve(import.meta.dirname, "../../../../docs/plan/22-api-openapi.yaml"),
  "utf8",
);
const lines = SPEC.split("\n");

/** The lines of one operation in the spec: from its `operationId` to the next one. */
function operation(id: string): string {
  const at = lines.findIndex((line) => line.trim() === `operationId: ${id}`);
  if (at < 0) throw new Error(`operation ${id} not found`);
  const next = lines.findIndex((line, i) => i > at && line.trim().startsWith("operationId:"));
  return lines.slice(at, next < 0 ? undefined : next).join("\n");
}

/** The path and method an operation sits under. */
function routeOf(id: string): { readonly path: string; readonly method: string } {
  const at = lines.findIndex((line) => line.trim() === `operationId: ${id}`);
  let method = "";
  for (let i = at; i >= 0; i -= 1) {
    const line = lines[i] ?? "";
    const verb = /^ {4}(get|post|put|patch|delete):\s*$/.exec(line);
    if (verb !== null && method === "") method = (verb[1] ?? "").toUpperCase();
    const path = /^ {2}(\/[^:]+):\s*$/.exec(line);
    if (path !== null) return { path: path[1] ?? "", method };
  }
  throw new Error(`no path for ${id}`);
}

describe("users client consumer contract (C-6.2)", () => {
  it("test_contract_role_and_status_lists_are_the_spec_enums", () => {
    expectTypeOf<(typeof ROLE_NAMES)[number]>().toEqualTypeOf<Schemas["RoleName"]>();
    expectTypeOf<(typeof USER_STATUSES)[number]>().toEqualTypeOf<Schemas["UserStatus"]>();
    expect([...ROLE_NAMES].sort()).toEqual(["manager", "owner", "viewer"]);
    expect([...USER_STATUSES].sort()).toEqual(["active", "disabled", "invited", "locked"]);
  });

  it("test_contract_list_query_names_page_size_and_search_length", () => {
    expectTypeOf<keyof NonNullable<Ops["listUsers"]["parameters"]["query"]>>().toEqualTypeOf<
      "cursor" | "limit" | "q" | "role" | "status"
    >();
    expect(operation("listUsers")).toMatch(
      /- name: q\n\s+in: query\n[^\n]*\n\s+schema: \{ type: string, maxLength: 120 \}/,
    );
    expect(Q_MAX).toBe(120);
    expect(SPEC).toContain("schema: { type: integer, minimum: 1, maximum: 500, default: 100 }");
    expect(PAGE_SIZE).toBeLessThanOrEqual(500);
  });

  it("test_contract_invite_body_is_a_viewer_with_two_factor_and_no_account_access", () => {
    expectTypeOf<InviteBody>().toExtend<Schemas["CreateUserRequest"]>();
    expectTypeOf<InviteBody["roles"]>().toEqualTypeOf<["viewer"]>();
    expectTypeOf<InviteBody["mfa_required"]>().toEqualTypeOf<true>();
    expectTypeOf<"account_access" extends keyof InviteBody ? true : false>().toEqualTypeOf<false>();
    expectTypeOf<keyof InviteInput>().toEqualTypeOf<"username" | "email" | "displayName">();
    expect(operation("createUser")).toContain("roles");
  });

  it("test_contract_vetted_shapes_read_only_fields_the_schemas_name", () => {
    // A field the spec renames or drops fails here at compile time, not as a silently empty cell.
    expectTypeOf<Exclude<keyof VettedUser, keyof Schemas["User"]>>().toEqualTypeOf<never>();
    expectTypeOf<
      Exclude<keyof Grant, keyof Schemas["AccountAccessGrant"]>
    >().toEqualTypeOf<never>();
    expectTypeOf<
      Exclude<keyof CreatedInvite, keyof Schemas["UserWithInvite"]>
    >().toEqualTypeOf<never>();
  });

  it("test_contract_status_change_delete_and_reset_bodies", () => {
    expectTypeOf<NonNullable<Schemas["UpdateUserRequest"]["status"]>>().toEqualTypeOf<
      "active" | "disabled"
    >();
    expectTypeOf<keyof NonNullable<Ops["deleteUser"]["parameters"]["query"]>>().toEqualTypeOf<
      "acknowledge_unknown_positions" | "purge"
    >();
    expectTypeOf<
      keyof NonNullable<Ops["updateUser"]["parameters"]["query"]>
    >().toEqualTypeOf<"acknowledge_unknown_positions">();
    expectTypeOf<
      NonNullable<
        Json<NonNullable<Ops["resetUserMfa"]["requestBody"]>>["acknowledge_unknown_positions"]
      >
    >().toEqualTypeOf<boolean>();
    expectTypeOf<Json<Ops["setSubaccountTier"]["requestBody"]>["tier"]>().toEqualTypeOf<
      "regular" | "business_kyc"
    >();
  });

  it("test_contract_every_route_the_client_calls_is_declared_with_its_method", () => {
    for (const [op, route] of Object.entries(USERS_ROUTES)) {
      expect(routeOf(op), op).toEqual(route);
    }
    expect(Object.keys(USERS_ROUTES).sort()).toEqual(
      [
        "createUser",
        "deleteUser",
        "listPendingInvites",
        "listUserAccountAccess",
        "listUserSessions",
        "listUsers",
        "previewMfaReset",
        "reissueInvite",
        "resetUserMfa",
        "revokeInvite",
        "setSubaccountTier",
        "updateUser",
      ].sort(),
    );
  });
});
