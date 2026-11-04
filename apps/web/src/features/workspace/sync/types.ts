/**
 * The SyncBus's vocabulary (E15-T03): the axes, the allow-listed payloads and the member adapter.
 * The payload carries exactly `symbol`, `interval`, `timeRange`, `crosshair` or `priceLevel`, and
 * never an account, an environment or a price for the crosshair (the ticket's Security note, A-4).
 */
import type { generated } from "@candleviewer/protocol";

type Schemas = generated.rest.components["schemas"];

/** `22` `PaneConfig.sync_group` without its `null`: the three group letters. */
export type SyncGroupId = NonNullable<Schemas["PaneConfig"]["sync_group"]>;
export const SYNC_GROUPS: readonly SyncGroupId[] = ["A", "B", "C"];
export type IntervalCode = Schemas["PaneIntervalCode"];

/**
 * SCR-023's switches this bus carries, in their reading order. `scale` is E15-S05's and `account` is
 * reserved for R3: neither is an axis here.
 */
export const SYNC_AXES = ["symbol", "interval", "crosshair", "timeRange", "drawings"] as const;
export type SyncAxis = (typeof SYNC_AXES)[number];
export type SyncAxes = Readonly<Record<SyncAxis, boolean>>;

/** A time window in the engine's public `TimeRange` unit (inclusive start, exclusive end). */
export interface TimeWindow {
  readonly from: number;
  readonly to: number;
}

/** Each axis's one field. `drawings` carries a price level only (A-5): drawing content is E14's. */
export interface SyncPayloadMap {
  readonly symbol: { readonly symbol: string };
  readonly interval: { readonly interval: IntervalCode };
  /** A bar time (never a price, E11-D01 D3); `null` when the pointer left the pane. */
  readonly crosshair: { readonly crosshair: number | null };
  readonly timeRange: { readonly timeRange: TimeWindow };
  readonly drawings: { readonly priceLevel: number };
}

export type SyncPayload<A extends SyncAxis = SyncAxis> = {
  readonly [K in A]: { readonly axis: K } & SyncPayloadMap[K];
}[A];

/** The one field each axis's payload may carry besides `axis`. */
export const PAYLOAD_FIELD: { readonly [K in SyncAxis]: keyof SyncPayloadMap[K] } = {
  symbol: "symbol",
  interval: "interval",
  crosshair: "crosshair",
  timeRange: "timeRange",
  drawings: "priceLevel",
};

/**
 * `applied`: the member took the value. `held`: it kept its own (an armed, order-capable chart,
 * CMP-221, holds a symbol while armed; BQ-05). A held value is dropped, never replayed later.
 */
export type ApplyResult = "applied" | "held";

/** What a member reports about itself, read at flush time and for the conflict states. */
export interface MemberState {
  readonly symbol: string | null;
  readonly interval: IntervalCode | null;
}

/**
 * The adapter a pane joins with. The bus keeps only a weak reference to it, calls nothing but
 * `apply` and `current`, and has no way to arm or disarm a member: no sync write ever re-arms.
 */
export interface SyncMember {
  readonly paneId: string;
  /** The `22` `PaneKind` (open-ended): every axis reaches `chart` members only (BQ-05). */
  readonly kind: string;
  current(): MemberState;
  apply(payload: SyncPayload): ApplyResult;
}

/** The kinds each axis reaches. A kind with no entry receives nothing, so it fails closed. */
export const RECEIVING_KINDS: { readonly [K in SyncAxis]: ReadonlySet<string> } = {
  symbol: new Set(["chart"]),
  interval: new Set(["chart"]),
  crosshair: new Set(["chart"]),
  timeRange: new Set(["chart"]),
  drawings: new Set(["chart"]),
};
