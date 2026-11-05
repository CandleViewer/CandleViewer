// E13-S01 (#423) S1: whether an entry can be added, and by which path (BQ-2, BQ-15; D06 §8.1).
// An entry is never hidden: when it cannot be added its Add is T2 "disabled with a visible reason"
// (`32-design-specs.md` G-T2; the reason a PROPOSED key, BQ-08). RBAC and view-as legs are the UI's RbacGate
// (S3b, BQ-8), checked before these; the server stays the authority (C-12.4).
import type { CatalogueEntry } from "./catalogue";
import { CAP_INSTANCES, CAP_SUBPANES, subpaneCount, type Instance } from "./instances";
import type { PaneTarget } from "./types";

/**
 * - `server-stream`: a `compute: server` entry, read from the `indicators.*` WS topic. The client
 *   never computes it, whatever plugin it holds (SR-E13-11: no second client path).
 * - `worker`: a `client_worker` entry whose engine plugin is registered.
 */
export type ComputePath = "server-stream" | "worker";

/** The cap keys: the deck's sentences under PROPOSED keys (BQ-08 rider; `copy.ts` `PROPOSED_KEYS`). */
export type CapReason = "indicator.cap_instances" | "indicator.cap_subpanes";

/**
 * Why an entry cannot be added. `no_path` is a code-internal cause, not a reason key: the key and
 * words for it are unruled (BQ-02 rider (c), ruling 6652282467), so its reason slot renders nothing.
 */
export type UnavailableReason = CapReason | "no_path";

export type Availability =
  | { readonly kind: "available"; readonly path: ComputePath }
  | { readonly kind: "disabled"; readonly reason: UnavailableReason };

export interface AvailabilityContext {
  /** Whether the chart engine has a plugin for this indicator id (none until E13-T01 / S02..S07). */
  readonly hasPlugin: (indicator: string) => boolean;
  readonly instances: readonly Instance[];
}

/** The path an entry computes on, or `null` when no path exists on this client yet. */
export function computePath(
  entry: Pick<CatalogueEntry, "id" | "compute">,
  hasPlugin: (indicator: string) => boolean,
): ComputePath | null {
  if (entry.compute === "server") return "server-stream";
  return hasPlugin(entry.id) ? "worker" : null;
}

/** The pane targets an entry offers (D06 §3.3): `both` offers the two. */
export function targetsOf(entry: Pick<CatalogueEntry, "pane">): readonly PaneTarget[] {
  if (entry.pane === "price") return ["overlay"];
  if (entry.pane === "sub") return ["subpane"];
  return ["overlay", "subpane"];
}

/** The target an add takes without a choice: `pane_target`'s contract default for `both` (`22`). */
export const defaultTarget = (entry: Pick<CatalogueEntry, "pane">): PaneTarget =>
  entry.pane === "sub" ? "subpane" : "overlay";

/**
 * Whether `entry` can be added to `target` now. The order: no path (no plugin, or a schema the
 * renderer refused), then the 20-instance cap, then the 6-sub-pane cap for a sub-pane target.
 * The server's caps (8 server instances, 500 presets) are its refusals, never pre-empted here.
 */
export function availability(
  entry: CatalogueEntry,
  target: PaneTarget,
  context: AvailabilityContext,
): Availability {
  const path = computePath(entry, context.hasPlugin);
  if (path === null || !entry.schema.ok) {
    return { kind: "disabled", reason: "no_path" };
  }
  if (context.instances.length >= CAP_INSTANCES) {
    return { kind: "disabled", reason: "indicator.cap_instances" };
  }
  if (target === "subpane" && subpaneCount(context.instances) >= CAP_SUBPANES) {
    return { kind: "disabled", reason: "indicator.cap_subpanes" };
  }
  return { kind: "available", path };
}
