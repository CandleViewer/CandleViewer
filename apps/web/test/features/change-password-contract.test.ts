/**
 * #2330 consumer test (C-6.2): the SCR-004 client against the `PUT /auth/password` refusals in
 * docs/plan/22-api-openapi.yaml. Their `detail` values are the 04-security-program.md section
 * 6.3.1 strings, pinned there by services/api/tests/contract/test_password_change_contract.py.
 * Each refusal must reach the form: never success, never an outage, never a CSRF retry.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ErrorCode } from "@candleviewer/protocol";
import { changePassword, type ChangePasswordOutcome } from "../../src/features/auth/authApi";
import { CSRF_COOKIE } from "../../src/lib/http/csrfFetch";

interface Refusal {
  readonly status: 403 | 422;
  readonly code: ErrorCode;
  readonly detail: string;
}

const CASES: readonly (readonly [Refusal, ChangePasswordOutcome])[] = [
  [
    {
      status: 422,
      code: "password_breached",
      detail: "This password appears in a known breach list.",
    },
    "breached",
  ],
  [
    {
      status: 422,
      code: "password_reused",
      detail: "You cannot reuse any of your last 5 passwords.",
    },
    "reused",
  ],
  [
    { status: 403, code: "current_password_invalid", detail: "The current password is incorrect." },
    "invalid",
  ],
];

let csrfToken = "tok.1";

function problem({ status, code, detail }: Refusal): Response {
  const body = {
    type: `https://candleviewer.local/errors/${code}`,
    title: code,
    status,
    detail,
    code,
  };
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/problem+json" },
  });
}

beforeEach(() => {
  csrfToken = "tok.1";
  vi.spyOn(document, "cookie", "get").mockImplementation(() => `${CSRF_COOKIE}=${csrfToken}`);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks(); // restores the real document.cookie accessor
});

describe("changePassword against the #2330 refusals", () => {
  it.each(CASES)("maps %o to %s without a CSRF retry", async (refusal, outcome) => {
    // Another tab rotates the CSRF token mid-flight; only `csrf_token_invalid` may be retried.
    const fetchMock = vi.fn(async () => {
      csrfToken = "tok.2";
      return problem(refusal);
    });
    vi.stubGlobal("fetch", fetchMock);
    await expect(changePassword("old passphrase", "a brand new passphrase")).resolves.toBe(outcome);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
