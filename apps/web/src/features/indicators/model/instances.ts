// E13-S01 (#423) S1: the chart's indicator instances as client state (BQ-3; D06 §3.2 "SCR-036 tree
// ← client state"). An instance is named by an opaque id the client mints, never by its params, so
// a re-tune keeps its identity. The engine port's opaque `key` (BQ-03: the served `spec_hash` for a
// `server` instance) belongs to the binding and is held by the store (S2), never derived here.
// Pure functions over readonly lists: the store is S2's.
import type { CatalogueEntry } from "./catalogue";
import type { Compute, Params, PaneTarget } from "./types";

export type InstanceId = string & { readonly __brand: "IndicatorInstanceId" };
export const asInstanceId = (value: string): InstanceId => value as InstanceId;

/** The price pane, or one sub-pane (its id minted with the instance that opened it). */
export type Placement =
  { readonly kind: "price" } | { readonly kind: "sub"; readonly pane: string };

export interface Instance {
  readonly id: InstanceId;
  readonly indicator: string;
  readonly compute: Compute;
  readonly params: Params;
  readonly placement: Placement;
  /** Palette slot 1..8 and ladder tier 0..5: the pair is unique per pane (D03 §3.4). */
  readonly slot: number;
  readonly tier: number;
  /** Session state only: nothing persists lock or visibility (D03 G-11). */
  readonly visible: boolean;
  readonly locked: boolean;
}

/** ≤ 20 instances (hidden ones count) and ≤ 6 sub-panes per chart: client gates (D06 §8.1). */
export const CAP_INSTANCES = 20;
export const CAP_SUBPANES = 6;
export const SLOTS = 8;
export const TIERS = 6;

export const paneKey = (placement: Placement): string =>
  placement.kind === "price" ? "price" : `sub:${placement.pane}`;

export const subpaneCount = (instances: readonly Instance[]): number =>
  new Set(instances.filter((i) => i.placement.kind === "sub").map((i) => paneKey(i.placement)))
    .size;

/**
 * D03 §3.4's assignment for an add to a pane: the lowest tier no sibling (same indicator) uses,
 * then the lowest hue not on the pane, else the lowest free (slot, tier) pair searching tiers
 * from that tier on. A preset's colour token would win first, but `IndicatorPresetStyle` is empty
 * until E13-D04 (D06 §3.2), so that branch has no input yet.
 */
export function assignSlot(
  onPane: readonly Pick<Instance, "indicator" | "slot" | "tier">[],
  indicator: string,
): { readonly slot: number; readonly tier: number } {
  const pairs = new Set(onPane.map((i) => i.slot * TIERS + i.tier));
  const siblingTiers = new Set(onPane.filter((i) => i.indicator === indicator).map((i) => i.tier));
  let tier = 0;
  while (tier < TIERS && siblingTiers.has(tier)) tier += 1;
  if (tier === TIERS) tier = 0;
  const hues = new Set(onPane.map((i) => i.slot));
  for (let slot = 1; slot <= SLOTS; slot += 1) {
    if (!hues.has(slot)) return { slot, tier };
  }
  for (let step = 0; step < TIERS; step += 1) {
    const t = (tier + step) % TIERS;
    for (let slot = 1; slot <= SLOTS; slot += 1) {
      if (!pairs.has(slot * TIERS + t)) return { slot, tier: t };
    }
  }
  // 48 pairs exceed the 20-instance cap, so a pane is never full; kept total for the type.
  return { slot: 1, tier };
}

export interface AddRequest {
  readonly entry: CatalogueEntry;
  readonly params: Params;
  readonly target: PaneTarget;
}

/** Ids for the instance and, for a sub-pane target, the new sub-pane. */
export type Mint = () => string;

/** The instance an add creates; the caller checked availability first (`availability.ts`). */
export function createInstance(
  instances: readonly Instance[],
  request: AddRequest,
  mint: Mint,
): Instance {
  const placement: Placement =
    request.target === "subpane" ? { kind: "sub", pane: mint() } : { kind: "price" };
  const key = paneKey(placement);
  const onPane = instances.filter((i) => paneKey(i.placement) === key);
  return Object.freeze({
    id: asInstanceId(mint()),
    indicator: request.entry.id,
    compute: request.entry.compute,
    params: request.params,
    placement,
    ...assignSlot(onPane, request.entry.id),
    visible: true,
    locked: false,
  });
}

/**
 * Re-adds a removed instance (undo; BQ-04 rider, ruling 6652282467): the same params and the next
 * free (slot, tier) pair on its pane, as an add takes it, never its old pair or position.
 */
export function readdInstance(instances: readonly Instance[], removed: Instance): Instance {
  const key = paneKey(removed.placement);
  const onPane = instances.filter((i) => paneKey(i.placement) === key);
  return Object.freeze({ ...removed, ...assignSlot(onPane, removed.indicator) });
}

/** How many instances of `indicator` the chart holds (D02 D4 "On chart ×N"). */
export const onChartCount = (instances: readonly Instance[], indicator: string): number =>
  instances.filter((i) => i.indicator === indicator).length;
