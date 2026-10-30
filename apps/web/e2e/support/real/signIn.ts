import { expect, type Page } from "@playwright/test";
import { setCookieNames } from "./cookies";
import type { FixtureUser, RealStack } from "./stack";

// E09-Q02 (#293) PR 2 (#2490): sign-in on the real lane. The password goes through the real SCR-001.
// SCR-002's OTP form is not built (#2711), so MFA is completed by a `fetch` from the page (#293 BQ-2,
// #2490 Q1): the browser's own cookie jar takes the answer, as it would from the form. The code is
// made at the server's time (`serverClock.ts`). The access token stays inside the page: what it
// reads with it comes back as facts (statuses, counts, booleans), never as the token.

const API_PATH = (path: string) => (r: { url(): string }) => new URL(r.url()).pathname === path;
export const LOGIN = "/api/v1/auth/login";
export const MFA_VERIFY = "/api/v1/auth/mfa/verify";

/** The password step as the browser saw it. `mfaToken` is a single-use handle: never print it. */
export interface PasswordStep {
  readonly status: number;
  readonly mfaRequired: boolean;
  readonly methods: readonly string[];
  /** How many `Set-Cookie` headers the answer carried. */
  readonly setCookies: number;
  readonly mfaToken: string;
}

/** Fills SCR-001 on the current page with `user`'s username and the password, and submits it. */
export async function submitPassword(
  page: Page,
  user: FixtureUser,
  password: string,
): Promise<PasswordStep> {
  const answered = page.waitForResponse(API_PATH(LOGIN));
  const submit = async (): Promise<void> => {
    await page.getByLabel("Username or email").fill(user.username);
    await page.getByLabel("Password", { exact: true }).fill(password);
    await page.getByRole("button", { name: "Sign in" }).click();
  };
  // Awaited together: if the form cannot be submitted, the wait for its answer goes with that
  // failure. Alone it would stay pending and reject, unhandled, when the page closes.
  const [res] = await Promise.all([answered, submit()]);
  const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
  const methods = Array.isArray(body["methods"]) ? (body["methods"] as unknown[]) : [];
  return {
    status: res.status(),
    mfaRequired: body["status"] === "mfa_required",
    methods: methods.filter((m): m is string => typeof m === "string"),
    setCookies: setCookieNames(await res.headersArray()).length,
    mfaToken: typeof body["mfa_token"] === "string" ? body["mfa_token"] : "",
  };
}

/** What `POST /auth/mfa/verify` and two reads with the token it issued showed, as facts. */
export interface MfaOutcome {
  readonly status: number;
  readonly authenticated: boolean;
  readonly tokenType: string | null;
  /** A refresh token value in the JSON body (`refresh_token` is `null` for a cookie client, `22` TokenBundle). */
  readonly refreshInBody: boolean;
  /** The names the answer's `Set-Cookie` headers set. */
  readonly cookiesSet: readonly string[];
  /** `GET /auth/session` with the issued bearer. */
  readonly session: {
    readonly status: number;
    readonly username: string | null;
    readonly permissions: number;
    readonly echoesToken: boolean;
  };
  /** `GET /me` with the issued bearer. */
  readonly me: { readonly status: number; readonly echoesToken: boolean };
}

/** Completes MFA from the page with `code`, then reads `/auth/session` and `/me` with the token. */
export async function completeMfa(page: Page, mfaToken: string, code: string): Promise<MfaOutcome> {
  const answered = page.waitForResponse(API_PATH(MFA_VERIFY));
  const read = page.evaluate(
    async ({ verifyPath, token: handle, totp }) => {
      const verify = await fetch(verifyPath, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mfa_token: handle, method: "totp", code: totp }),
      });
      const body = (await verify.json().catch(() => null)) as {
        status?: unknown;
        tokens?: Record<string, unknown>;
      } | null;
      const tokens = body?.tokens ?? {};
      const bearer = tokens["access_token"];
      const none = { status: 0, username: null, permissions: -1, echoesToken: false };
      if (typeof bearer !== "string" || bearer === "") {
        return {
          status: verify.status,
          authenticated: false,
          tokenType: null,
          refreshInBody: typeof tokens["refresh_token"] === "string",
          session: none,
          me: { status: 0, echoesToken: false },
        };
      }
      const auth = { Authorization: `Bearer ${bearer}` };
      const session = await fetch("/api/v1/auth/session", { headers: auth });
      const sessionText = await session.text();
      const me = await fetch("/api/v1/me", { headers: auth });
      const meText = await me.text();
      let info: { user?: { username?: unknown }; permissions?: unknown } = {};
      try {
        info = JSON.parse(sessionText) as typeof info;
      } catch {
        info = {};
      }
      return {
        status: verify.status,
        authenticated: body?.status === "authenticated",
        tokenType: typeof tokens["token_type"] === "string" ? tokens["token_type"] : null,
        refreshInBody: typeof tokens["refresh_token"] === "string",
        session: {
          status: session.status,
          username: typeof info.user?.username === "string" ? info.user.username : null,
          permissions: Array.isArray(info.permissions) ? info.permissions.length : -1,
          echoesToken: sessionText.includes(bearer),
        },
        me: { status: me.status, echoesToken: meText.includes(bearer) },
      };
    },
    { verifyPath: MFA_VERIFY, token: mfaToken, totp: code },
  );
  // Awaited together, as in `submitPassword`: a throwing `evaluate` must not leave `answered` pending.
  const [res, facts] = await Promise.all([answered, read]);
  return { ...facts, cookiesSet: setCookieNames(await res.headersArray()) };
}

/** A completed sign-in: the password step and the MFA step, both as the browser saw them. */
export interface SignedIn {
  readonly password: PasswordStep;
  readonly mfa: MfaOutcome;
}

/**
 * Signs `user` in from SCR-001: the password through the form, then MFA from the page with a code
 * at the server's time. It asserts only that each step succeeded; the specs assert the rest.
 */
export async function signIn(page: Page, stack: RealStack, user: FixtureUser): Promise<SignedIn> {
  await page.goto("/login");
  const password = await submitPassword(page, user, stack.password());
  expect(password.mfaRequired, "the password step asks for the second factor").toBe(true);
  await expect(page.getByRole("heading", { name: "Two-factor code" })).toBeVisible();
  const mfa = await completeMfa(page, password.mfaToken, stack.clock.totpAt(user.seed()));
  expect(mfa.authenticated, "MFA by in-page fetch authenticated the session").toBe(true);
  return { password, mfa };
}
