// E13-S01 (#423) S2: the feature's one seam to the chart engine (BQ-01 AMEND, ruling 6652282467).
// The shapes here are #423's own consumer-side shapes: this file imports nothing from
// `@candleviewer/chart-engine`. The only file that may is the adapter `engine/adapter.ts`, which
// stays local until E13-T01 #425 PR-1 merges, and maps these calls onto the engine's handles. Until
// then the only implementation is `stub/fakeEngine.ts`. No #425-owned file is touched (70 §3).
import type { Compute, Params } from "../model/types";

/**
 * The port's opaque instance key (BQ-03 AMEND). For a `compute: server` instance it is the served
 * `spec_hash` the subscription echoes (`23:780`); for a `client_worker` one it is T01's PROPOSED
 * client key (#425 BQ-8, "if it merges as is"). The port returns it; the client never computes a
 * `spec_hash`, and the store never derives a key from params.
 */
export type EngineKey = string & { readonly __brand: "IndicatorEngineKey" };

/** What an add hands the engine: the plugin or the served stream is resolved by `indicator`. */
export interface EngineAddSpec {
  readonly indicator: string;
  /** `server` is read from the `indicators.*` stream, never computed on the client (SR-E13-11). */
  readonly compute: Compute;
  /** `paneKey()` of the placement: `"price"` or `"sub:<id>"`. */
  readonly pane: string;
  readonly params: Params;
}

/**
 * A server refusal, never pre-empted or clamped by the client (`23:779`): more than 8 `instances`
 * on the `indicators` subscription, or two with one `key`, is `invalid_options`.
 */
export type ServerRefusal = "invalid_options" | "subscription_limit";

export type PortOutcome =
  | { readonly ok: true; readonly key: EngineKey }
  | { readonly ok: false; readonly refusal: ServerRefusal };

export interface IndicatorEnginePort {
  /** Adds an instance; returns its key, or the server's refusal (a `server` instance). */
  add(spec: EngineAddSpec): PortOutcome;
  /**
   * Re-tunes the instance at `key`. Both key forms are functions of the params, so the outcome
   * carries the key the instance has afterwards; a refusal leaves the instance at `key`.
   */
  setParams(key: EngineKey, params: Params): PortOutcome;
  remove(key: EngineKey): void;
  /**
   * The render order of one pane, bottom to top. PROPOSED (G-a2 on #425): no engine member
   * reorders indicators within a pane on `main`.
   */
  setOrder(pane: string, keys: readonly EngineKey[]): void;
}
