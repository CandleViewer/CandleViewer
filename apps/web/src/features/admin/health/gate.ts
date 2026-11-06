/**
 * D9's gate (E42-D05 D9; ruling Q11): whether a faulted tile, and the outage banner, may add
 * `health.safe`. It fails closed, as of D5's last reads: `oms`'s words fresh and not `degraded`,
 * `warning` or `down`; both incident pages (`open`, `acknowledged`) answered, with no `oms` incident
 * and nothing more to read; the statecharts read answered, `snapshots` `ok`, a `position_protection`
 * row and none latched in any environment. A pending, failed or stale leg withholds it, never rewords it;
 * `oms`'s own tile never says it. Today `snapshots` is `unavailable`: withheld everywhere [BQ-9].
 * `listStatecharts` has a row per kind with a live machine, so no live `position_protection` machine
 * (a flat book) means no row, and the sentence stays withheld even with `snapshots` `ok`: stricter
 * than D9's text, which withholds only on a latched kind or a slice not `ok`. BQ-24, ruled: keep it
 * fail closed; the safe line is never shown on missing data. A flat book as a third state is
 * PROPOSED, routed as a C-row to E42's design owner (D9's text), never inferred by the client.
 *
 * Rulings (orchestrator, 11:36Z): (1) the newest source wins both ways: a report newer than the
 * newest frame that no longer lists a name the frames still carry gives that name `not_received`,
 * which withholds here as any word not received does. (2) A state STRING the contract does not name
 * keeps the whole report unreadable (a contract disagreement); a missing or non-string state stays
 * per-tile `not_received`, as built (`vetHealthReport`).
 */
import type { ComponentState, IncidentPageBody, ProtectionBody } from "../ops/opsReads";

export interface GateLegs {
  /** `oms`'s words: its state and whether its source still answers; undefined when not received. */
  readonly oms: { readonly state: ComponentState; readonly fresh: boolean } | undefined;
  /** Each incident read's last answer; undefined while pending or after a failed read. */
  readonly open: IncidentPageBody | undefined;
  readonly acknowledged: IncidentPageBody | undefined;
  /** The statecharts read's last answer; undefined while pending or after a failed read. */
  readonly protection: ProtectionBody | undefined;
}

const OMS = "oms";
const PROTECTION = "position_protection";
const OMS_FAULTS: ReadonlySet<ComponentState> = new Set(["degraded", "warning", "down"]);

/** A page that answered, lists no `oms` incident and has nothing more to read. */
const clear = (page: IncidentPageBody | undefined): boolean =>
  page !== undefined &&
  !page.meta.has_more &&
  !page.items.some((incident) => incident.component === OMS);

export function stillSafe(component: string, legs: GateLegs): boolean {
  const { oms, protection } = legs;
  if (component === OMS || oms === undefined || !oms.fresh || OMS_FAULTS.has(oms.state)) {
    return false;
  }
  if (!clear(legs.open) || !clear(legs.acknowledged)) return false;
  if (protection === undefined || protection.snapshots.status !== "ok") return false;
  // No `position_protection` row cannot show that none is latched.
  const rows = protection.kinds.filter((kind) => kind.machine_kind === PROTECTION);
  return rows.length > 0 && rows.every((kind) => kind.degraded_machines === 0);
}
