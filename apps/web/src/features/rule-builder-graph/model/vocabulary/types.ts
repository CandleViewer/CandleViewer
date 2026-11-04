/**
 * The served rule vocabulary's shapes (`22` `RuleVocabulary`, generated; never written by hand). Pure: no React,
 * no DOM global (the feature's purity lint lands with E37-S01's model, so this folder keeps the rule by hand).
 */
import type { generated } from "@candleviewer/protocol";

/** `GET /rules/vocabulary`'s body. */
export type RuleVocabulary = generated.rest.components["schemas"]["RuleVocabulary"];

/**
 * A served signal. Carried row: `scope` is 24 §19.118's (E37-S02 PR 1, the generated type has it); apps/web reads
 * the protocol through its built `dist`, which carries it once that PR is on `main`. Until then it is typed here,
 * optional as the contract has it: drop the intersection then.
 */
export type VocabularySignal = RuleVocabulary["signals"][number] & {
  readonly scope?: "symbol" | "position" | "account" | "global";
};

/** A served action. Carried row: `places_orders` is 24 §19.118's, typed here until the `dist` has it (above). */
export type VocabularyAction = RuleVocabulary["actions"][number] & {
  readonly places_orders?: boolean;
};

export type VocabularyOperator = RuleVocabulary["operators"][number];

export type VocabularyTrigger = NonNullable<RuleVocabulary["triggers"]>[number];
