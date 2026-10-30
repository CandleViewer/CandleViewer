import type { BrowserContext, Cookie, Page } from "@playwright/test";

// E09-Q02 (#293) PR 2 (#2490): the browser's own cookie jar on the real lane (BQ-3, SR-012, SR-041).
// Values are compared here and never returned in a form a failed assertion would print: specs
// assert on flags and on booleans, never `toEqual` a value (a failure message would show it).

export const REFRESH_COOKIE = "cv_refresh";
export const CSRF_COOKIE = "__Host-cv_csrf";
/** `cv_refresh`'s path (ADR-0020; `api/sessions.py` `REFRESH_COOKIE_PATH`). */
export const REFRESH_PATH = "/api/v1/auth";

/** A cookie without its value: what the flag assertions compare. */
export interface CookieFlags {
  readonly name: string;
  readonly domain: string;
  readonly path: string;
  readonly secure: boolean;
  readonly httpOnly: boolean;
  readonly sameSite: Cookie["sameSite"];
}

export const flagsOf = (c: Cookie): CookieFlags => ({
  name: c.name,
  domain: c.domain,
  path: c.path,
  secure: c.secure,
  httpOnly: c.httpOnly,
  sameSite: c.sameSite,
});

/** The jar's cookies by name, sorted: the names and flags of what the server set. */
export async function jarFlags(context: BrowserContext): Promise<CookieFlags[]> {
  const cookies = await context.cookies();
  return cookies.map(flagsOf).sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
}

/** The value of `name` in the jar, or `undefined`: for comparisons only, never for an assertion's operand. */
export async function valueOf(context: BrowserContext, name: string): Promise<string | undefined> {
  return (await context.cookies()).find((c) => c.name === name)?.value;
}

/** The value of `name` in the jar; a missing cookie fails without naming any value. */
export async function requiredValue(context: BrowserContext, name: string): Promise<string> {
  const value = await valueOf(context, name);
  if (value === undefined || value === "") throw new Error(`no ${name} in the jar`);
  return value;
}

/** True when both are set and equal: `expect(same(a, b)).toBe(false)` fails without printing either. */
export const same = (a: string | undefined, b: string | undefined): boolean =>
  a !== undefined && b !== undefined && a === b;

/** `value` with the one character in its middle swapped for another of the token alphabet. */
export function tamperOneByte(value: string): string {
  if (value.length === 0) throw new Error("no value to tamper with");
  const at = Math.floor(value.length / 2);
  const swapped = value[at] === "A" ? "B" : "A";
  return `${value.slice(0, at)}${swapped}${value.slice(at + 1)}`;
}

/**
 * Puts `value` in the jar as `cv_refresh`, as the server would set it (host-only, `Secure`,
 * `HttpOnly`, `Strict`, its path): a planted, tampered or spent token for the next request.
 */
export async function plantRefresh(
  context: BrowserContext,
  origin: string,
  value: string,
): Promise<void> {
  const { hostname } = new URL(origin);
  await context.addCookies([
    {
      name: REFRESH_COOKIE,
      value,
      domain: hostname,
      path: REFRESH_PATH,
      secure: true,
      httpOnly: true,
      sameSite: "Strict",
    },
  ]);
}

/** The names a response's `Set-Cookie` headers set, in order: never their values. */
export function setCookieNames(headers: readonly { name: string; value: string }[]): string[] {
  return headers
    .filter((h) => h.name.toLowerCase() === "set-cookie")
    .flatMap((h) => h.value.split("\n"))
    .map((line) => line.slice(0, line.indexOf("=")).trim());
}

/** True when every `Set-Cookie` header of `headers` for `name` expires it (`Max-Age=0`). */
export function expires(headers: readonly { name: string; value: string }[], name: string): boolean {
  const lines = headers
    .filter((h) => h.name.toLowerCase() === "set-cookie")
    .flatMap((h) => h.value.split("\n"))
    .filter((line) => line.slice(0, line.indexOf("=")).trim() === name);
  return lines.length > 0 && lines.every((line) => /;\s*max-age=0\s*(?:;|$)/iu.test(line));
}

/** An answer as the specs compare it: its status and its problem `code`, never a body. */
export interface Answer {
  readonly status: number;
  readonly code: string | null;
}

/** `GET /auth/session` from the page with the jar's cookies and no bearer: the cookie-identified read. */
export async function sessionByCookie(page: Page): Promise<Answer> {
  return page.evaluate(async () => {
    const res = await fetch("/api/v1/auth/session", { credentials: "same-origin" });
    const body = (await res.json().catch(() => ({}))) as { code?: unknown };
    return { status: res.status, code: typeof body.code === "string" ? body.code : null };
  });
}

/** A refresh's answer: also whether it carried a token bundle, and a refresh token in its body. */
export interface RefreshAnswer extends Answer {
  readonly bundle: boolean;
  readonly refreshInBody: boolean;
}

/**
 * `POST /auth/refresh` from the page with the jar's cookies and the SR-041 header from the
 * readable `__Host-cv_csrf`, as the SPA sends it (`lib/auth/accessToken.ts`). The new access token
 * stays in the page.
 */
export async function refreshByCookie(page: Page): Promise<RefreshAnswer> {
  return page.evaluate(async (csrfName) => {
    const pair = document.cookie
      .split(";")
      .map((part) => part.trim())
      .find((part) => part.startsWith(`${csrfName}=`));
    const csrf = pair?.slice(csrfName.length + 1) ?? "";
    const res = await fetch("/api/v1/auth/refresh", {
      method: "POST",
      credentials: "same-origin",
      headers: csrf === "" ? {} : { "X-CSRF-Token": csrf },
    });
    const body = (await res.json().catch(() => ({}))) as {
      code?: unknown;
      tokens?: Record<string, unknown>;
    };
    const tokens = body.tokens ?? {};
    return {
      status: res.status,
      code: typeof body.code === "string" ? body.code : null,
      bundle: typeof tokens["access_token"] === "string" && tokens["token_type"] === "Bearer",
      refreshInBody: typeof tokens["refresh_token"] === "string",
    };
  }, CSRF_COOKIE);
}
