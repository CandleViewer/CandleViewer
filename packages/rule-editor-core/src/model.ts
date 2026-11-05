// The form editor's model of a rule (E36-T01): what the form shows and edits, derived from the
// server's canonical IR by `irToForm` and written back by `formToIr` (the IR adapter, PR-2 of
// #1063). The IR types are the generated ones (C-4.16); nothing here is a hand-written DTO. Every
// row keeps its IR `node_id` as its id and its RFC 6901 pointer, so diagnostics anchor to it and
// `formToIr` writes it back into a structural clone of `base`.
import type {
  Action,
  Comparison,
  RuleIr,
  RuleLimits,
  RuleScope,
  Trigger,
} from "@candleviewer/protocol/rule-ir";
import type { FormReason } from "@candleviewer/rule-graph";
import type { LimitRefusal } from "./limits.js";
import type { JsonPointer } from "./pointer.js";

/** The presentation block: outside the hash, never read by the evaluator, carried untouched
 * through a form save (US-RULE-001; `rules/ir/canonical.py` `PRESENTATION_KEYS`). */
export type Presentation = Readonly<Pick<RuleIr, "graph_layout" | "editor">>;

/** A boolean group the form shows: CMP-141's `mode: "and" | "or"`, as the IR's ops. */
export type GroupMode = "all_of" | "any_of";

/**
 * One condition row (CMP-140): a comparison, or a `sustained_for` wrapping one, as the form subset
 * allows (`24` §11.4). Its operands are the IR's own values: a constant is never reformatted.
 */
export interface ConditionRow {
  /** The IR `node_id` of the comparison, or of the `sustained_for` node wrapping it. */
  readonly id: string;
  readonly pointer: JsonPointer;
  readonly comparison: Comparison;
  /** The `sustained_for` window in milliseconds, or `null` for a bare comparison. */
  readonly sustainedForMs: number | null;
  /**
   * Metric identifiers the vocabulary lacks (AC 3, D05-G11), in `left`, `right`, `right2` order.
   * Non-empty means the row is disabled and names each; it is re-emitted unchanged, never dropped.
   */
  readonly unknownIdentifiers: readonly string[];
}

/** A place in a group's list: a row, a nested any-of group (by id), or an opaque region (by id). */
export type ConditionEntry =
  | { readonly kind: "row"; readonly row: ConditionRow }
  | { readonly kind: "group"; readonly groupId: string }
  | { readonly kind: "opaque"; readonly regionId: string };

/**
 * A condition group (CMP-141). The root comes first in `FormModel.conditionGroups`, then each
 * any-of group it holds (one level, D02 R3), each in IR order.
 */
export interface ConditionGroup {
  /** The IR `node_id` of the boolean node; for an implicit root, the id of its one row. */
  readonly id: string;
  /** `null` for the root. */
  readonly parentId: string | null;
  readonly pointer: JsonPointer;
  readonly mode: GroupMode;
  /**
   * True when the IR's `conditions` is a single comparison, not a boolean node: the form shows it
   * as an "all of" of one row, and `formToIr` writes a bare comparison back while it has one row.
   */
  readonly implicit: boolean;
  readonly entries: readonly ConditionEntry[];
}

/** One action row: the IR action, its `params` as served. */
export interface ActionRow {
  /** The IR `node_id`. */
  readonly id: string;
  readonly pointer: JsonPointer;
  readonly action: Action;
  /** The action type when the vocabulary lacks it (AC 3's path for actions), else `null`. */
  readonly unknownIdentifier: string | null;
}

/**
 * An IR sub-tree the form cannot represent (a graph-only construct): shown in place as the
 * read-only card (CMP-235), never parsed into the model, and written back by `formToIr` at its
 * pointer byte-identical (SR-E36-03).
 */
export interface OpaqueRegion {
  readonly id: string;
  readonly irPointer: JsonPointer;
  /** The sub-tree as loaded. Rendered only as text, never interpreted. */
  readonly rawNode: unknown;
  /** The card's sentence, in words (no identifier left unexpanded). */
  readonly plainLanguageSummary: string;
  /** Why the form cannot show it, in the server's words (`rules/ir/form.py`). */
  readonly reason: string;
}

/** Why the whole rule opens read-only: a §5.1 refusal (`ir_version`, or condition nodes past
 * the editable bound), carried with its reason so the banner can say it. */
export type ReadOnlyReason = LimitRefusal;

/** The form editor's rule: SCR-081's five sections, the presentation block and opaque regions. */
export interface FormModel {
  /** The IR as loaded: the base `formToIr` clones. Never mutated. */
  readonly base: RuleIr;
  readonly scope: RuleScope;
  readonly trigger: Trigger;
  /** The root group first, then the any-of groups it holds. */
  readonly conditionGroups: readonly ConditionGroup[];
  readonly actions: readonly ActionRow[];
  /** The rule's limits as served, or `null` when the IR has none. */
  readonly options: RuleLimits | null;
  readonly presentation: Presentation;
  readonly opaqueRegions: readonly OpaqueRegion[];
  /**
   * The whole-rule verdict of rule-graph's `isFormRepresentable` (one subset, never mirrored here),
   * `[]` when the form can show every node. Carried beside `opaqueRegions` (BQ-02 rider a): whether
   * it shows as the cards in place or as D02-G2's whole-rule banner is E36-S03's to decide.
   */
  readonly formReasons: readonly FormReason[];
  /** `null` when the form may edit the rule, else why it is read-only. */
  readonly readOnly: ReadOnlyReason | null;
}
