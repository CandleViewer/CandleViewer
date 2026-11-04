/**
 * One `Idempotency-Key` value per user attempt (`22` Idempotency; C-2.10): a client-generated UUIDv4 the server
 * stores with the request's fingerprint for 24 h. The admin write kit's rule (E42-S02, shared by the users screens,
 * E42-S04's export and E42-S05): a step-up re-send is the held request, so it carries its attempt unchanged; an
 * explicit Retry or a renewal is a new attempt, since a stored refusal would replay under the old value.
 */
export function newAttempt(): string {
  return crypto.randomUUID();
}
