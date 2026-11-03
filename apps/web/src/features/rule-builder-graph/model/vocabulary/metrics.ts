/**
 * The metric options the node library and CMP-157 offer (E37-S02): every served signal, in the order served,
 * with its category, unit and availability as the server states them. No metric, category or estimated list
 * lives in the client (AC 1): a new signal is an option with no client change. Pure: no React, no DOM global.
 */
import { verbOf } from "./copy.js";
import type { RuleVocabulary, VocabularyOperator, VocabularySignal } from "./types.js";

/** E36-D01 R2's seven picker categories (`docs/design/research/e36-rules-in-words.md` §5.2). */
export type MetricCategory =
  "price" | "orderflow" | "book" | "derivatives" | "position" | "account" | "replay";

/** One served signal as an option: the fields CMP-157 renders and the inspector stores. */
export interface MetricOption {
  readonly id: string;
  /** The served `display_name`; the id only where the server serves none (P1). */
  readonly label: string;
  readonly unit: string | undefined;
  readonly description: string;
  readonly category: MetricCategory;
  /** The served `estimated` flag: "(estimated)" follows the name wherever it shows (E36-D01 R5). */
  readonly estimated: boolean;
  /** `false`: shown and explained, never chosen (AC 3). */
  readonly available: boolean;
  /** The served reason, naming the symbol that is not recorded. */
  readonly unavailableReason: string | undefined;
  /** The served `missing_dependency.inputs`: what the symbol lacks. */
  readonly missingInputs: readonly string[];
  /** The served `recorder_action`: Start recording sends it as served. */
  readonly recorderAction: VocabularySignal["recorder_action"];
}

/** An operator a metric can take: the server's operators whose operand units include the metric's unit. */
export interface OperatorOption {
  readonly id: string;
  /** Operands, the metric included: 1 is a predicate, 2 takes a value, 3 a range. */
  readonly arity: number;
  /** E36-D05 `rules.editor.verb.<id>`, or the id. */
  readonly verb: string;
}

/** The inputs that make a symbol's signal a derivatives one (R2: open interest, funding, liquidations). */
const DERIVATIVES = new Set(["oi", "funding", "liquidations"]);

/**
 * R2's derivation, from the signal's served `scope` and `dependencies` alone: position, account and global
 * (`replay`) by scope; a symbol's signal by its inputs: trades, then the book, then derivatives, else price.
 * A signal served without a scope is the registry's default, `symbol`.
 */
export function categoryOf(signal: VocabularySignal): MetricCategory {
  if (signal.scope === "position") return "position";
  if (signal.scope === "account") return "account";
  if (signal.scope === "global") return "replay";
  const inputs = signal.dependencies ?? [];
  if (inputs.includes("trades")) return "orderflow";
  if (inputs.includes("book")) return "book";
  return inputs.some((input) => DERIVATIVES.has(input)) ? "derivatives" : "price";
}

const missingInputs = (signal: VocabularySignal): string[] => {
  const inputs = signal.missing_dependency?.["inputs"];
  return Array.isArray(inputs) ? inputs.filter((i): i is string => typeof i === "string") : [];
};

/** Every served signal as an option, unavailable ones included, in the order served. */
export function metricOptions(vocabulary: RuleVocabulary): MetricOption[] {
  return vocabulary.signals.map((signal: VocabularySignal) => ({
    id: signal.id,
    label: signal.display_name ?? signal.id,
    unit: signal.unit ?? undefined,
    description: signal.description ?? "",
    category: categoryOf(signal),
    estimated: signal.estimated,
    available: signal.available,
    unavailableReason: signal.unavailable_reason,
    missingInputs: missingInputs(signal),
    recorderAction: signal.recorder_action,
  }));
}

/** The operators `metric` can take, by its unit (the served `operand_types`), each with its arity and verb. */
export function operatorsFor(
  metric: Pick<MetricOption, "unit">,
  operators: readonly VocabularyOperator[],
): OperatorOption[] {
  const { unit } = metric;
  if (unit === undefined) return [];
  return operators.flatMap(({ id, arity, operand_types: units }) =>
    id === undefined || !(units ?? []).includes(unit)
      ? []
      : [{ id, arity: arity ?? 2, verb: verbOf(id) }],
  );
}
