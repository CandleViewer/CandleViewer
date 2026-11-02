/**
 * Module-scoped `/me` claims cache (E10-T01 / E10-T04 contract).
 *
 * The bootstrap fetch (E10-T04) sets the claims and registers the `/me` reader. Route loaders
 * call `refreshMeClaims()` before they guard (#5405): every client-side navigation re-reads `/me`,
 * so a role or grant the server has changed applies on the next navigation, not only on reload.
 * `CLAIMS_MAX_AGE_MS` only folds a burst (the bootstrap read and the first loaders, or nested
 * loaders of one navigation) into one request; it is not a staleness window (coordinator ruling,
 * #5421). A read that finds the session gone (`MeSignedOutError`) sets the unauthenticated claims,
 * so the guard sends the user to sign-in with the destination as `next`. Any other failed read
 * keeps the old claims: a blip never locks the user out, and the server still refuses anything the
 * claims no longer allow. The rail subscribes through `useMeClaims()`. The server stays the
 * boundary (C-12.4): this cache only keeps the UI in step with it.
 */
import { useSyncExternalStore } from "react";
import type { MeClaims } from "../../routes/rbac";

/** The burst dedupe: a read younger than this is reused, so one navigation makes one request. */
export const CLAIMS_MAX_AGE_MS = 250;

const UNAUTHENTICATED: MeClaims = {
  authenticated: false,
  role: null,
  permissions: [],
};

/**
 * Reads the current claims from the server (`GET /me`); registered by the bootstrap. It rejects
 * with `MeSignedOutError` when the session is gone, and with anything else on any other failure.
 */
export type MeClaimsReader = () => Promise<MeClaims>;

/** The reader's answer for a session that is gone (a `401` no refresh cured): not a blip. */
export class MeSignedOutError extends Error {
  constructor() {
    super("the session is signed out");
    this.name = "MeSignedOutError";
  }
}

let cached: MeClaims = UNAUTHENTICATED;
let readAt = Number.NEGATIVE_INFINITY;
let reader: MeClaimsReader | null = null;
let inFlight: Promise<void> | null = null;
// Bumped by `resetMeClaims()`: a read started before a reset (sign-out, a test) must not bring
// back the claims it answers with.
let generation = 0;
const listeners = new Set<() => void>();

function sameClaims(a: MeClaims, b: MeClaims): boolean {
  return (
    a.authenticated === b.authenticated &&
    a.role === b.role &&
    // stringified: a `/me` answer is not validated here, so tolerate a missing list
    JSON.stringify(a.permissions) === JSON.stringify(b.permissions)
  );
}

/** Synchronous read used by route loaders. Never triggers a network request. */
export function getMeClaims(): MeClaims {
  return cached;
}

/**
 * Set by the bootstrap fetch (E10-T04), a navigation's re-read, or tests. Unchanged claims keep
 * the same object, so subscribers re-render only on a real change.
 */
export function setMeClaims(claims: MeClaims): void {
  readAt = Date.now();
  if (sameClaims(cached, claims)) return;
  cached = claims;
  for (const listener of listeners) listener();
}

/** Registers (or, with `null`, removes) the `/me` reader the navigation re-read uses. */
export function setMeClaimsReader(next: MeClaimsReader | null): void {
  reader = next;
}

/**
 * Re-reads `/me` when the claims are older than `CLAIMS_MAX_AGE_MS`; concurrent loaders share one
 * request. A read that finds the session gone sets the unauthenticated claims; any other failed
 * read keeps the cached ones (the server still refuses what they no longer allow).
 */
export function refreshMeClaims(): Promise<void> {
  if (inFlight) return inFlight;
  const read = reader;
  if (read === null || Date.now() - readAt < CLAIMS_MAX_AGE_MS) return Promise.resolve();
  const started = generation;
  const pending: Promise<void> = read()
    .then(
      (claims) => {
        if (started === generation) setMeClaims(claims);
      },
      (error: unknown) => {
        if (error instanceof MeSignedOutError && started === generation) {
          setMeClaims(UNAUTHENTICATED);
        }
      },
    )
    .finally(() => {
      if (inFlight === pending) inFlight = null;
    });
  inFlight = pending;
  return pending;
}

export function subscribeMeClaims(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The current claims for a component; it re-renders when they change. */
export function useMeClaims(): MeClaims {
  return useSyncExternalStore(subscribeMeClaims, getMeClaims);
}

/** Back to unauthenticated; a read still in flight is dropped when it answers. */
export function resetMeClaims(): void {
  generation += 1;
  cached = UNAUTHENTICATED;
  readAt = Number.NEGATIVE_INFINITY;
  reader = null;
  inFlight = null;
  for (const listener of listeners) listener();
}
