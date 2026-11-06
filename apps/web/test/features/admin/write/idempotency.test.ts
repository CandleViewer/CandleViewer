/**
 * E42-S02 (#1023): one `Idempotency-Key` value per user attempt (`22` Idempotency, 388-393): a step-up re-send
 * reuses the held request's, while an explicit Retry or a renewal is a new attempt, since a stored refusal would
 * replay under the old one.
 */
import { describe, expect, it } from "vitest";
import { newAttempt } from "../../../../src/features/admin/write/idempotency";

const UUID4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe("newAttempt", () => {
  it("is a client-generated UUIDv4", () => {
    expect(newAttempt()).toMatch(UUID4);
  });

  it("is a new value for every attempt", () => {
    const seen = new Set(Array.from({ length: 50 }, () => newAttempt()));
    expect(seen.size).toBe(50);
  });
});
