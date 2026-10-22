// Public entry of @candleviewer/rule-graph (E37-T01). The IR types are generated from the published
// schema and re-exported, never hand-written.
export type { RuleIr } from "@candleviewer/protocol/rule-ir";
export { canonicalise, compareWithServer, hash } from "./canonical/canonicalise.js";
export { RULE_GRAPH_ERROR_CODES, RuleGraphError, isRuleGraphError } from "./errors.js";
export type { RuleGraphErrorCode } from "./errors.js";
