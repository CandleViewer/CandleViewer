/**
 * E10-S04 (#306) SCR-153: the degraded-mode issues, derived from the WS `system` stream alone, so a
 * new impairment class is a payload addition and a copy row, never a new banner (ticket Technical
 * notes). Pure: `reduceDegraded(facts, update)` depends on its arguments only.
 *
 * Routing (`docs/design/E17/E17-D02.md` §6, first match wins; one reason, one surface): row 6
 * blocking (maintenance, the `postgres` component), row 8 the public exchange feed, row 10 the other
 * components. The overall `health` word routes nothing by itself. The transport states (the SCR-152
 * region) are never an issue here.
 *
 * A dismissal hides a row for its episode only and the row returns when a new frame re-asserts the
 * condition (§8): each issue carries `assertedSeq`, the number of frames that asserted it in the
 * current episode, and the banner shows a dismissed row again once that number grows.
 */
import type { SystemUpdate } from "../../lib/ws/protocol/frames";
import { DEGRADED_COPY, type DegradedCopy, type DegradedIssueId } from "./copy";

export interface DegradedIssue extends DegradedCopy {
  readonly id: DegradedIssueId;
  /** Per issue (CMP-092 A11y); a dismissal lasts until the condition is re-asserted. */
  readonly dismissible: true;
  readonly assertedSeq: number;
}

/** The conditions that hold: present = asserted in the current episode, the value its frame count. */
export type DegradedFacts = Readonly<Partial<Record<DegradedIssueId, number>>>;

export const INITIAL_DEGRADED_FACTS: DegradedFacts = Object.freeze({});

/** The routing-table order (§6): the rows are listed, and announced, in this order. */
const ORDER: readonly DegradedIssueId[] = [
  "maintenance",
  "storeDown",
  "exchangeFeedDown",
  "ruleEngineDown",
  "recorderDown",
];

/** A `health.components[]` name → its issue. A `switch`: a key such as `__proto__` is not a component. */
function componentIssue(name: unknown): DegradedIssueId | undefined {
  switch (name) {
    case "postgres":
      return "storeDown";
    case "rule_engine":
      return "ruleEngineDown";
    case "recorder":
      return "recorderDown";
    default:
      return undefined;
  }
}

/** Matrix row 13: `connecting` / `disconnected` is down; `undefined` for anything else on the wire. */
function publicFeedDown(value: unknown): boolean | undefined {
  switch (value) {
    case "connecting":
    case "disconnected":
      return true;
    case "connected":
    case "resyncing":
      return false;
    default:
      return undefined;
  }
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** What one frame says: `true` asserts an issue, `false` clears it; an issue it does not name is kept. */
function verdicts(u: SystemUpdate): Map<DegradedIssueId, boolean> {
  const out = new Map<DegradedIssueId, boolean>();
  if (!isRecord(u)) return out; // the wire is untrusted: not a payload at all
  if (u.kind === "notice") {
    if (u.reason === "maintenance.enabled") out.set("maintenance", true);
    if (u.reason === "maintenance.disabled") out.set("maintenance", false);
  }
  if (u.kind === "health" && Array.isArray(u.components)) {
    for (const c of u.components as unknown[]) {
      if (!isRecord(c)) continue;
      const id = componentIssue(c["name"]);
      if (id !== undefined) out.set(id, c["state"] === "down");
    }
  }
  if (u.kind === "health" || u.kind === "exchange_state") {
    const exchange: unknown = u.exchange;
    const top: unknown = u.kind === "exchange_state" ? u.public_ws : undefined;
    const down = publicFeedDown(top ?? (isRecord(exchange) ? exchange["public_ws"] : undefined));
    if (down !== undefined) out.set("exchangeFeedDown", down);
  }
  return out;
}

export function reduceDegraded(facts: DegradedFacts, update: SystemUpdate): DegradedFacts {
  const said = verdicts(update);
  if (said.size === 0) return facts;
  const next: Partial<Record<DegradedIssueId, number>> = { ...facts };
  let changed = false;
  for (const [id, holds] of said) {
    if (holds) {
      next[id] = (facts[id] ?? 0) + 1;
      changed = true;
    } else if (id in next) {
      delete next[id];
      changed = true;
    }
  }
  return changed ? Object.freeze(next) : facts;
}

/** The CMP-092 rows for the conditions that hold, in the routing-table order. */
export function degradedIssues(facts: DegradedFacts): readonly DegradedIssue[] {
  const issues: DegradedIssue[] = [];
  for (const id of ORDER) {
    const assertedSeq = facts[id];
    if (assertedSeq !== undefined) {
      issues.push({ id, ...DEGRADED_COPY[id], dismissible: true, assertedSeq });
    }
  }
  return issues;
}
