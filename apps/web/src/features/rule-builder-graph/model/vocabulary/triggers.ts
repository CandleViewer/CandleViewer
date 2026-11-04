/**
 * The trigger options of the node library and the trigger inspector (E37-S02): every served trigger, in the order
 * served, with the parameter its `required_fields` ask for. A trigger the client has no clause for reads by its
 * id, and a required field it does not know is a text field, so a new trigger needs no client change (AC 1).
 * Pure: no React, no DOM global.
 */
import { clauseOf } from "./copy.js";
import type { RuleVocabulary } from "./types.js";

/** How a required field is entered: the IR field names `ir/models.py` requires per trigger type. */
export type TriggerParameterKind = "timeframe" | "duration" | "cron" | "metric" | "text";

export interface TriggerParameter {
  /** The trigger's IR field, as served in `required_fields`. */
  readonly field: string;
  readonly kind: TriggerParameterKind;
}

export interface TriggerOption {
  readonly id: string;
  /** E36-D01 §5.6's "When …" clause, a slot per required field; the id when none is written. */
  readonly clause: string;
  /** The served description, the option's second line. */
  readonly description: string;
  readonly parameters: readonly TriggerParameter[];
}

const KINDS: Readonly<Record<string, TriggerParameterKind>> = {
  timeframe: "timeframe",
  interval_ms: "duration",
  cron: "cron",
  metric: "metric",
};

/** The control a required field takes; an unknown field is free text. */
export const parameterOf = (field: string): TriggerParameter => ({
  field,
  kind: Object.hasOwn(KINDS, field) ? (KINDS[field] as TriggerParameterKind) : "text",
});

/** Every served trigger with an id, as an option. */
export function triggerOptions(vocabulary: RuleVocabulary): TriggerOption[] {
  return (vocabulary.triggers ?? []).flatMap(({ id, description, required_fields: fields }) =>
    id === undefined
      ? []
      : [
          {
            id,
            clause: clauseOf(id),
            description: description ?? "",
            parameters: (fields ?? []).map(parameterOf),
          },
        ],
  );
}
