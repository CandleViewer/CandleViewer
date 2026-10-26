/**
 * Module-scoped `/me` claims cache (E10-T01 / E10-T04 contract).
 *
 * E10-T04 owns the real bootstrap fetch + background refresh; this ticket
 * only needs a minimal, synchronously-readable cache so route guards never
 * issue their own network request per navigation (`12-sitemap.md` §4,
 * "Performance notes" in the ticket body). The shape here is intentionally
 * small and is expected to be replaced/extended by E10-T04 without route
 * code changing.
 */
import type { MeClaims } from "../../routes/rbac";

const UNAUTHENTICATED: MeClaims = {
  authenticated: false,
  role: null,
  permissions: [],
};

let cached: MeClaims = UNAUTHENTICATED;

/** Synchronous read used by route loaders. Never triggers a network request. */
export function getMeClaims(): MeClaims {
  return cached;
}

/** Set by the bootstrap fetch (E10-T04) or by tests. */
export function setMeClaims(claims: MeClaims): void {
  cached = claims;
}

export function resetMeClaims(): void {
  cached = UNAUTHENTICATED;
}
