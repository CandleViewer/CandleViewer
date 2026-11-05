// Public entry of @candleviewer/rule-editor-core (E36-T01). The IR types are the generated ones
// from @candleviewer/protocol, re-exported, never hand-written (C-4.16).
export type { RuleIr } from "@candleviewer/protocol/rule-ir";
export type { FormReason } from "@candleviewer/rule-graph";
export {
  RULE_LIMITS,
  checkImportSelection,
  checkRuleShape,
  countValues,
  encodeRequestBody,
  jsonDepthExceeds,
  parseRuleJson,
  utf8ByteLength,
} from "./limits.js";
export type { DocumentKind, LimitReason, LimitRefusal, LimitResult, RuleShape } from "./limits.js";
export type * from "./model.js";
export {
  PointerError,
  cloneJson,
  encodePointer,
  getAt,
  hasAt,
  parsePointer,
  setAt,
} from "./pointer.js";
export type { JsonPointer, PointerErrorCode } from "./pointer.js";
