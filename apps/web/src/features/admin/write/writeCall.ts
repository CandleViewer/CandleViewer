/**
 * The admin area's write call (E42-S02; the lane's shared write kit, reused by E42-S04's export and E42-S05). A write
 * is held exactly as first sent: method, path with its query, its attempt's `Idempotency-Key` and its JSON body,
 * through `apiFetch` (the CSRF double submit and the bearer), so the one re-send after a step-up is the same
 * submission (C-2.10; `22` "Holding the refused request"). Its answer is read into a result the screen routes: the
 * body through the caller's vet, the problem's `code` only when it is one of `22`'s stable tokens, the first error's
 * `field` and `rule`, and a `403 step_up_required`'s challenge with the held request and a reader for the re-send's
 * answer. A problem's `message` and `detail` never leave this module, and no elevation is kept: the server holds it.
 */
import { ERROR_CODES, type ErrorCode } from "@candleviewer/protocol";
import {
  holdRequest,
  readChallenge,
  sendHeld,
  type HeldRequest,
  type StepUpChallenge,
} from "../../stepUp/challenge";

export type WriteMethod = "POST" | "PUT" | "PATCH" | "DELETE";

/** A refusal with a step-up challenge: the challenge, the refused request held unchanged, and its answer's reader. */
export interface StepUpHold<T> {
  readonly challenge: StepUpChallenge;
  readonly held: HeldRequest;
  /** Reads the answer to the held request's re-send, through the same vet. */
  readonly read: (response: Response) => Promise<WriteResult<T>>;
}

export interface WriteResult<T> {
  /** The server did it (a `2xx`). */
  readonly ok: boolean;
  /** `0` when nothing answered: a request that may have reached the server, so its outcome is unknown. */
  readonly status: number;
  /** The problem's `code`, one of `22`'s stable tokens, else null. */
  readonly code: ErrorCode | null;
  /** The first `errors[]` entry's `field` and `rule` (a `422`'s inline error), else null. */
  readonly field: string | null;
  readonly rule: string | null;
  /** A `2xx` body the vet accepted; null for `204`, or for a body it refused (the write is done: read back). */
  readonly data: T | null;
  readonly stepUp: StepUpHold<T> | null;
  /** The answer's `ETag` (`22`: the representation's version, sent back as `If-Match`); null without one. */
  readonly etag?: string | null;
  /** The answer's `Retry-After` in whole seconds (`22` `RetryAfter`); null without one or in another form. */
  readonly retryAfter?: number | null;
}

const STABLE: ReadonlySet<string> = new Set(ERROR_CODES);
const isRecord = (value: unknown): value is Readonly<Record<string, unknown>> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): string | null =>
  typeof value === "string" && value.length <= 64 ? value : null;
const codeOf = (value: unknown): ErrorCode | null =>
  typeof value === "string" && STABLE.has(value) ? (value as ErrorCode) : null;
/** `22`'s `RetryAfter`: whole seconds; an HTTP date or anything else is none. */
const secondsOf = (value: string | null): number | null =>
  value !== null && /^\d{1,9}$/u.test(value.trim()) ? Number(value.trim()) : null;
/**
 * The headers a write's own route may add, by allowlist: `If-Match` (SCR-122's `PATCH`, `22` `updateUser`). Any
 * other name is dropped, so a route can never replace the kit's own three or the transport's credentials.
 */
const ROUTE_HEADERS: ReadonlySet<string> = new Set(["if-match"]);

/**
 * The request a write sends, held: the attempt's value travels with it into any re-send. `attempt` null sends no
 * `Idempotency-Key`, for a route `22` marks `x-idempotency: ignored`; `extra` adds the route's own headers, only
 * those `ROUTE_HEADERS` names (`If-Match` on SCR-122's `PATCH`).
 */
export function holdWrite(
  method: WriteMethod,
  path: string,
  attempt: string | null,
  body?: unknown,
  extra?: Readonly<Record<string, string>>,
): HeldRequest {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (attempt !== null) headers["Idempotency-Key"] = attempt;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  for (const [name, value] of Object.entries(extra ?? {})) {
    if (ROUTE_HEADERS.has(name.toLowerCase())) headers[name] = value;
  }
  return holdRequest(method, path, headers, body === undefined ? null : JSON.stringify(body));
}

/** Reads the answer to `held` (its first send, or the re-send after a step-up). */
export async function readWrite<T>(
  response: Response,
  held: HeldRequest,
  vet: (raw: unknown) => T | null,
): Promise<WriteResult<T>> {
  let json: unknown = null;
  if (response.status !== 204 && response.status !== 205) {
    try {
      json = await response.json();
    } catch {
      json = null; // no body, or one that is not JSON
    }
  }
  // The `Date` header gives the server clock the challenge's expiry is on (plain test doubles have none).
  const date = response.headers?.get("Date") ?? null;
  const etag = response.headers?.get("ETag") ?? null;
  const retryAfter = secondsOf(response.headers?.get("Retry-After") ?? null);
  const challenge = response.status === 403 ? readChallenge(json, date) : null;
  const problem = !response.ok && isRecord(json) ? json : {};
  const errors = problem["errors"];
  const first = Array.isArray(errors) && isRecord(errors[0]) ? errors[0] : {};
  return {
    ok: response.ok,
    status: response.status,
    code: codeOf(problem["code"]),
    field: text(first["field"]),
    rule: text(first["rule"]),
    data: response.ok && json !== null ? vet(json) : null,
    stepUp:
      challenge === null ? null : { challenge, held, read: (again) => readWrite(again, held, vet) },
    etag,
    retryAfter,
  };
}

/** No answer at all: the request may have reached the server, so its outcome is unknown (status 0). */
const unanswered = <T>(): WriteResult<T> => ({
  ok: false,
  status: 0,
  code: null,
  field: null,
  rule: null,
  data: null,
  stepUp: null,
  etag: null,
  retryAfter: null,
});

/** Sends a held write once and reads its answer; `signal` bounds the wait, it is not part of the request. */
export async function sendWrite<T>(
  held: HeldRequest,
  vet: (raw: unknown) => T | null,
  signal?: AbortSignal,
): Promise<WriteResult<T>> {
  let response: Response;
  try {
    response = await sendHeld(held, signal);
  } catch {
    return unanswered<T>();
  }
  return readWrite(response, held, vet);
}
