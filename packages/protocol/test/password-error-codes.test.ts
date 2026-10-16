import { describe, expect, expectTypeOf, it } from "vitest";
import type { components, operations } from "../src/generated/rest/index.js";
import { ERROR_CODES, ERROR_META, WS_ERROR_CODES, type ErrorCode } from "../src/index.js";

/** #2330: the codes SCR-004 and SCR-112 key on for `PUT /auth/password` (22-api-openapi.yaml). */
const PASSWORD_CODES = [
  "current_password_invalid",
  "password_breached",
  "password_reused",
] as const satisfies readonly ErrorCode[];

type ChangePasswordResponses = operations["authChangePassword"]["responses"];
type Problem = components["schemas"]["Problem"];

describe("password-change error codes (#2330)", () => {
  it.each(PASSWORD_CODES)("%s is a REST-only, non-retryable registry code", (code) => {
    expect(ERROR_CODES).toContain(code);
    expect(ERROR_META[code]).toEqual({
      surfaces: ["rest"],
      scope: null,
      retryable: false,
      restAnalogue: null,
      closeCode: null,
    });
    expect(WS_ERROR_CODES).not.toContain(code);
  });

  // Type-level: enforced by `tsc` (this package typechecks test/), a no-op at runtime.
  it("types the 403 and 422 refusals as problem+json and keeps 401 for the session", () => {
    expectTypeOf<
      ChangePasswordResponses[403]["content"]["application/problem+json"]
    >().toEqualTypeOf<Problem>();
    expectTypeOf<
      ChangePasswordResponses[422]["content"]["application/problem+json"]
    >().toEqualTypeOf<Problem>();
    expectTypeOf<ChangePasswordResponses[401]>().toEqualTypeOf<
      components["responses"]["Unauthorized"]
    >();
  });
});
