// Public entry of @candleviewer/rule-graph (E37-T01). The IR types are generated from the published
// schema and re-exported, never hand-written.
export type { RuleIr } from "@candleviewer/protocol/rule-ir";
export { nodesNeedingLayout, readLayout, toGraph } from "./adapter/toGraph.js";
export { toIr } from "./adapter/toIr.js";
export { findCycles } from "./analysis/cycles.js";
export { findDanglingPorts, type DanglingPort } from "./analysis/dangling.js";
export { isFormRepresentable, type FormReason } from "./analysis/formSubset.js";
export { findOrphans } from "./analysis/orphans.js";
export { canonicalise, compareWithServer, hash } from "./canonical/canonicalise.js";
export { RULE_GRAPH_ERROR_CODES, RuleGraphError, isRuleGraphError } from "./errors.js";
export type { RuleGraphErrorCode } from "./errors.js";
export type * from "./model.js";
export { NODE_PORTS, PORT_COMPAT, PORT_TYPES, canConnect, portTypeOfMetric } from "./ports.js";
export { portsOf, type Connect, type MetricUnit, type MetricValueType } from "./ports.js";
export type { NodeKind, NodePorts, PortType } from "./ports.js";
