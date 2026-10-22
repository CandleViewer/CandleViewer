/**
 * The stable error codes of this package (E37-T01, Observability). The editor UI and telemetry
 * classify failures on these strings, so a code is never renamed or reused. Counters for them are
 * emitted by the consuming app, not by this package.
 *
 * - `CYCLE_DETECTED`: the graph holds a cycle, so no IR can be emitted for it.
 * - `DANGLING_PORT`: a required input port has no connection.
 * - `ORPHAN_NODE`: a node reaches no action.
 * - `NOT_FORM_REPRESENTABLE`: the rule uses a graph-only construct, so the form cannot show it.
 * - `SCHEMA_VIOLATION`: the document does not fit the published rule IR schema, or cannot be
 *   represented without loss.
 */
export const RULE_GRAPH_ERROR_CODES = Object.freeze([
  "CYCLE_DETECTED",
  "DANGLING_PORT",
  "ORPHAN_NODE",
  "NOT_FORM_REPRESENTABLE",
  "SCHEMA_VIOLATION",
] as const);

/** One of the stable {@link RULE_GRAPH_ERROR_CODES}. */
export type RuleGraphErrorCode = (typeof RULE_GRAPH_ERROR_CODES)[number];

/**
 * A refusal by this package: a named code a caller can classify on, a message for people, and the
 * ids of the graph or IR nodes involved (for a cycle, the path in order).
 */
export class RuleGraphError extends Error {
  readonly code: RuleGraphErrorCode;
  /** A frozen copy of the ids passed in: a later change to the caller's array cannot alter it. */
  readonly nodeIds: readonly string[];

  constructor(code: RuleGraphErrorCode, message: string, nodeIds: readonly string[] = []) {
    super(message);
    this.name = "RuleGraphError";
    this.code = code;
    this.nodeIds = Object.freeze([...nodeIds]);
  }
}

/** Whether `value` is a {@link RuleGraphError}: an `instanceof` check, so a lookalike is not. */
export function isRuleGraphError(value: unknown): value is RuleGraphError {
  return value instanceof RuleGraphError;
}
