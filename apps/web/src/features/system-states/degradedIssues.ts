/**
 * E10-S04 (#306) SCR-153: the degraded-mode issues, derived from the WS `system` stream, so a new
 * impairment class is a payload addition and a copy row, never a new banner (ticket Technical
 * notes). Pure: `reduceDegraded(facts, update)` depends on its arguments only. One row is the
 * client's own and never read from a frame: the GPU fallback (`setGpuFallback`, slice 9c).
 *
 * Routing (`docs/design/E17/E17-D02.md` §6, first match wins; one reason, one surface): row 6
 * blocking (maintenance: the `notice` or the `maintenance.mode` flag; the `postgres` component), row 8 the public exchange feed, row 10 the other
 * components. The overall `health` word routes nothing by itself. The transport states (the SCR-152
 * region) are never an issue here. SR-023's break-glass notice (`auth.break_glass_used`) has no §6
 * row: it leads the rows that gate nothing (PROPOSED), and no frame clears it, since a resolution
 * only stops the notice on later first authentications (`23` §15.9).
 *
 * A dismissal hides a row for its episode only and the row returns when a new frame re-asserts the
 * condition (§8): each issue carries `assertedSeq`, the number of frames that asserted it in the
 * current episode, and the banner shows a dismissed row again once that number grows.
 *
 * Row 9 (the upstream private reconnect) is a CMP-092 row "for up to 10 s": at 10 s it withdraws and
 * the region's R5 takes over, one surface at a time (§6). `handOverPrivateReconnect` withdraws it for
 * the rest of its episode; the shell store calls it `PRIVATE_HANDOVER_MS` after the episode starts.
 */
import type { SystemUpdate } from "../../lib/ws/protocol/frames";
import { DEGRADED_COPY, type DegradedCopy, type DegradedIssueId } from "./copy";

export interface DegradedIssue extends DegradedCopy {
  readonly id: DegradedIssueId;
  /** Per issue (CMP-092 A11y); a dismissal lasts until the condition is re-asserted. */
  readonly dismissible: true;
  readonly assertedSeq: number;
}

export interface DegradedFacts {
  /** The conditions that hold: present = asserted in the current episode, the value its frame count. */
  readonly asserted: Readonly<Partial<Record<DegradedIssueId, number>>>;
  /** Row 9 handed over to R5 in its current episode; reset when the episode ends. */
  readonly privateHandedOver: boolean;
}

export const INITIAL_DEGRADED_FACTS: DegradedFacts = Object.freeze({
  asserted: Object.freeze({}),
  privateHandedOver: false,
});

/** §6 row 9: the private-reconnect row shows "for up to 10 s". */
export const PRIVATE_HANDOVER_MS = 10_000;

/** The routing-table order (§6): the rows are listed, and announced, in this order. */
const ORDER: readonly DegradedIssueId[] = [
  "maintenance",
  "storeDown",
  "breakGlass",
  "exchangeFeedDown",
  "privateReconnect",
  "ruleEngineDown",
  "recorderDown",
  "gpuFallback",
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

/**
 * Row 9: `connecting` / `resyncing` asserts, `connected` ends the episode. `disconnected` is not a
 * row 9 value, so it neither asserts nor clears: a running episode keeps its 10 s hand-over to R5.
 */
function privateReconnecting(value: unknown): boolean | undefined {
  switch (value) {
    case "connecting":
    case "resyncing":
      return true;
    case "connected":
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
    if (u.reason === "auth.break_glass_used") out.set("breakGlass", true); // never on `critical`
  }
  if (u.kind === "health" || u.kind === "feature_flags") {
    // §15.9: the flag re-asserts maintenance on every snapshot or flag push; the notice is one-shot.
    const flags: unknown = u.feature_flags;
    const on = isRecord(flags) ? flags["maintenance.mode"] : undefined;
    if (typeof on === "boolean") out.set("maintenance", on);
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
    const word = (key: "public_ws" | "private_ws"): unknown =>
      (u.kind === "exchange_state" ? u[key] : undefined) ??
      (isRecord(exchange) ? exchange[key] : undefined);
    const down = publicFeedDown(word("public_ws"));
    if (down !== undefined) out.set("exchangeFeedDown", down);
    const verifying = privateReconnecting(word("private_ws"));
    if (verifying !== undefined) out.set("privateReconnect", verifying);
  }
  return out;
}

export function reduceDegraded(facts: DegradedFacts, update: SystemUpdate): DegradedFacts {
  return applyVerdicts(facts, verdicts(update));
}

/**
 * §8's GPU-fallback row (routing row 10, info): asserted when the user keeps software rendering on
 * SCR-159's GPU page (#306 BQ-9.3), so it holds for the session; a new crash's page withdraws it.
 */
export function setGpuFallback(facts: DegradedFacts, holds: boolean): DegradedFacts {
  return applyVerdicts(facts, new Map<DegradedIssueId, boolean>([["gpuFallback", holds]]));
}

function applyVerdicts(
  facts: DegradedFacts,
  said: ReadonlyMap<DegradedIssueId, boolean>,
): DegradedFacts {
  if (said.size === 0) return facts;
  const next: Partial<Record<DegradedIssueId, number>> = { ...facts.asserted };
  let changed = false;
  for (const [id, holds] of said) {
    if (holds) {
      next[id] = (facts.asserted[id] ?? 0) + 1;
      changed = true;
    } else if (id in next) {
      delete next[id];
      changed = true;
    }
  }
  if (!changed) return facts;
  const privateHandedOver = facts.privateHandedOver && next.privateReconnect !== undefined;
  return Object.freeze({ asserted: Object.freeze(next), privateHandedOver });
}

/** Row 9 → R5 at 10 s: the private-reconnect row withdraws for the rest of its episode. */
export function handOverPrivateReconnect(facts: DegradedFacts): DegradedFacts {
  if (facts.asserted.privateReconnect === undefined || facts.privateHandedOver) return facts;
  return Object.freeze({ asserted: facts.asserted, privateHandedOver: true });
}

/** The CMP-092 rows for the conditions that hold, in the routing-table order. */
export function degradedIssues(facts: DegradedFacts): readonly DegradedIssue[] {
  const issues: DegradedIssue[] = [];
  for (const id of ORDER) {
    const assertedSeq = facts.asserted[id];
    if (id === "privateReconnect" && facts.privateHandedOver) continue;
    if (assertedSeq !== undefined) {
      issues.push({ id, ...DEGRADED_COPY[id], dismissible: true, assertedSeq });
    }
  }
  return issues;
}

let lastFacts: DegradedFacts | null = null;
let lastIssues: readonly DegradedIssue[] = [];

/**
 * `degradedIssues`, memoized on the facts' identity: the store keeps `degraded` by reference until a
 * frame changes it, so an unrelated store change (latency, connection) returns the same rows array.
 */
export function selectDegradedIssues(facts: DegradedFacts): readonly DegradedIssue[] {
  if (facts !== lastFacts) {
    lastFacts = facts;
    lastIssues = degradedIssues(facts);
  }
  return lastIssues;
}
