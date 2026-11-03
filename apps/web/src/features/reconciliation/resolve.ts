/**
 * Resolve… (E29-S07 #1028; BQ-10 of the ruling of record 6575172489): the Owner's decision on a
 * stale lock, `resolveReconciliation` (`22`, `POST /admin/reconciliation/{accountId}/resolve`).
 * Owner `admin:write`, a fresh step-up `accounts` each time (a `403 step_up_required` answered by
 * `features/stepUp`, the held request re-sent unchanged), a reason of 3 to 280 characters, one
 * `Idempotency-Key` per decision and CSRF (`apiFetch`). Never the arm: it is not an order (`22`
 * `ArmToken`, `32` R5). The server decides and audits it (`oms.reconcile` `stage: resolved`);
 * nothing here is enforcement (C-12.4).
 */
import type { generated } from "@candleviewer/protocol";
import {
  holdRequest,
  readChallenge,
  sendHeld,
  type HeldRequest,
  type StepUpChallenge,
} from "../stepUp/challenge";

export type ReconciliationResolved = generated.rest.components["schemas"]["ReconciliationResolved"];

/** `22` `ReconciliationResolveRequest.reason`: 3 to 280 characters, trimmed. */
export const REASON_MIN = 3;
export const REASON_MAX = 280;

export type ResolveOutcome =
  | { readonly kind: "resolved"; readonly resolved: ReconciliationResolved }
  | { readonly kind: "step_up"; readonly challenge: StepUpChallenge; readonly held: HeldRequest }
  | {
      readonly kind:
        | "nothing_to_resolve"
        | "forbidden"
        | "not_found"
        | "invalid"
        | "not_available"
        | "unavailable";
    };

/** Whether `reason` may be sent (the server validates it again). */
export function reasonValid(reason: string): boolean {
  const n = reason.trim().length;
  return n >= REASON_MIN && n <= REASON_MAX;
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** The request, held so a step-up re-sends it unchanged (the same key: one decision, C-2.10). */
export function resolveRequest(accountId: string, reason: string): HeldRequest {
  return holdRequest(
    "POST",
    `/api/v1/admin/reconciliation/${encodeURIComponent(accountId)}/resolve`,
    { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
    JSON.stringify({ reason: reason.trim() }),
  );
}

/** Reads an answer to `held` (its first send or its re-send after a step-up). */
export async function readResolve(response: Response, held: HeldRequest): Promise<ResolveOutcome> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (response.ok) {
    return isRecord(body) && typeof body["resolved"] === "string"
      ? { kind: "resolved", resolved: body as ReconciliationResolved }
      : { kind: "unavailable" };
  }
  const code = isRecord(body) ? body["code"] : undefined;
  const errors = isRecord(body) && Array.isArray(body["errors"]) ? body["errors"] : [];
  // `409 conflict` names its rule in `errors[].rule` (`22` Problem)
  const nothing =
    code === "nothing_to_resolve" ||
    errors.some((e: unknown) => isRecord(e) && e["rule"] === "nothing_to_resolve");
  switch (response.status) {
    case 403: {
      const challenge = readChallenge(body, response.headers?.get("Date") ?? null);
      return challenge === null ? { kind: "forbidden" } : { kind: "step_up", challenge, held };
    }
    case 404:
      return { kind: "not_found" };
    case 409:
      return nothing ? { kind: "nothing_to_resolve" } : { kind: "unavailable" };
    case 422:
      return { kind: "invalid" };
    case 501:
      return { kind: "not_available" };
    default:
      return { kind: "unavailable" };
  }
}

/**
 * Sends `held` (a first send, or a retry of the same decision after `unavailable`, which keeps its
 * `Idempotency-Key`, so a retry is never a second decision, C-2.10).
 */
export async function sendResolve(held: HeldRequest): Promise<ResolveOutcome> {
  try {
    return await readResolve(await sendHeld(held), held);
  } catch {
    return { kind: "unavailable" };
  }
}

/** Sends a new decision (a fresh key). */
export function resolveReconciliation(accountId: string, reason: string): Promise<ResolveOutcome> {
  return sendResolve(resolveRequest(accountId, reason));
}
