/**
 * Step-up challenges (#2304, #2725): read the `403 step_up_required` challenge and hold the refused
 * request so it can be re-sent unchanged after a successful `POST /auth/step-up`
 * (`docs/plan/22-api-openapi.yaml`, "Holding the refused request"; E09-D06 §2 item 7).
 */
import type { generated } from "@candleviewer/protocol";
import { apiFetch } from "../../lib/http/csrfFetch";

type Rest = generated.rest.components;
/** The `403` problem body that carries the challenge. */
export type StepUpProblem = Rest["schemas"]["Problem"];
type StepUpOperation = generated.rest.operations["authStepUp"];
export type StepUpRequestBody = StepUpOperation["requestBody"]["content"]["application/json"];
export type StepUpGranted = StepUpOperation["responses"][200]["content"]["application/json"];

export const STEP_UP_PATH = "/api/v1/auth/step-up";
export const STEP_UP_REQUIRED = "step_up_required";
/** The `400 validation_failed` rules of a challenge that can no longer be answered. */
export const STALE_CHALLENGE_RULES: ReadonlySet<string> = new Set([
  "challenge_expired",
  "challenge_required",
]);

/** The challenge a `403 step_up_required` issued for the one request it refused. */
export interface StepUpChallenge {
  readonly challengeId: string;
  readonly expiresAt: string;
  readonly actionClass: string;
  /** Server-composed; shown verbatim, never composed by the client. Null when the route sent none. */
  readonly actionSummary: string | null;
  readonly target: string | null;
  /**
   * Server clock minus client clock when the `403` arrived, from its `Date` header (0 without one),
   * so `challenge_expires_at` (server clock) is never judged by the client's clock alone.
   */
  readonly clockOffsetMs: number;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

/** Server minus client clock from a response `Date` header; 0 when it is absent or unreadable. */
export function clockOffsetMs(
  serverDate: string | null | undefined,
  now: number = Date.now(),
): number {
  const server = serverDate ? Date.parse(serverDate) : Number.NaN;
  return Number.isNaN(server) ? 0 : server - now;
}

/** Milliseconds until the challenge expires, on the server's clock. */
export function msUntilExpiry(challenge: StepUpChallenge, now: number = Date.now()): number {
  return Date.parse(challenge.expiresAt) - (now + challenge.clockOffsetMs);
}

/**
 * The challenge of a `403 step_up_required` body, or null when the body is not one. `serverDate`
 * is the response's `Date` header.
 */
export function readChallenge(
  body: unknown,
  serverDate: string | null = null,
  now: number = Date.now(),
): StepUpChallenge | null {
  if (!isRecord(body) || body["code"] !== STEP_UP_REQUIRED) return null;
  const problem = body as Partial<StepUpProblem>;
  const { challenge_id: id, challenge_expires_at: expires, action_class: cls } = problem;
  if (typeof id !== "string" || typeof expires !== "string" || typeof cls !== "string") {
    return null;
  }
  return {
    challengeId: id,
    expiresAt: expires,
    actionClass: cls,
    actionSummary: typeof problem.action_summary === "string" ? problem.action_summary : null,
    target: typeof problem.target === "string" ? problem.target : null,
    clockOffsetMs: clockOffsetMs(serverDate, now),
  };
}

/** True for a `400` whose rule says the challenge cannot be answered any more. */
export function isStaleChallenge(status: number, body: unknown): boolean {
  if (status !== 400 || !isRecord(body) || !Array.isArray(body["errors"])) return false;
  return body["errors"].some(
    (error: unknown) =>
      isRecord(error) &&
      typeof error["rule"] === "string" &&
      STALE_CHALLENGE_RULES.has(error["rule"]),
  );
}

/** A request kept exactly as first sent: method, URL, headers (`Idempotency-Key` included), body. */
export interface HeldRequest {
  readonly method: string;
  readonly url: string;
  readonly headers: readonly (readonly [string, string])[];
  readonly body: string | null;
}

/** Freezes a request so the copy sent later is byte-for-byte the one first sent. */
export function holdRequest(
  method: string,
  url: string,
  headers: Readonly<Record<string, string>>,
  body: string | null,
): HeldRequest {
  return Object.freeze({
    method,
    url,
    headers: Object.freeze(Object.entries(headers).map(([k, v]) => Object.freeze([k, v] as const))),
    body,
  });
}

/**
 * Sends a held request (first send or the one re-send); a fresh `RequestInit` every time. The
 * optional `signal` bounds the wait; it is not part of the request.
 */
export function sendHeld(held: HeldRequest, signal?: AbortSignal): Promise<Response> {
  const init: RequestInit = { method: held.method, headers: held.headers.map(([k, v]) => [k, v]) };
  if (held.body !== null) init.body = held.body;
  if (signal !== undefined) init.signal = signal;
  return apiFetch(held.url, init);
}
