/**
 * The server-written vocabularies (`packages/fixtures/golden/rule-graph/vocabulary/`, written and byte-checked by
 * `services/api/tests/contract/test_rule_vocabulary_fixtures.py`), and the extended one AC 1 asks for.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type {
  RuleVocabulary,
  VocabularyAction,
  VocabularySignal,
} from "../../../../src/features/rule-builder-graph/model/vocabulary/types.js";

const GOLDEN = resolve(
  import.meta.dirname,
  "../../../../../../packages/fixtures/golden/rule-graph/vocabulary",
);

/** The four personas the provider test writes: the Owner, the seeded Manager, no `orders:write`, SOLUSDT. */
export type Persona = "owner" | "manager" | "no-orders-write" | "unrecorded-solusdt";

/** What `GET /rules/vocabulary` serves `persona`, as the server wrote it. */
export const served = (persona: Persona): RuleVocabulary =>
  JSON.parse(readFileSync(resolve(GOLDEN, `${persona}.json`), "utf8")) as RuleVocabulary;

const NEW_METRIC: VocabularySignal = {
  id: "zz_new_metric",
  display_name: "New metric",
  description: "A metric no client table names",
  type: "number",
  unit: "ratio",
  scope: "position",
  dependencies: ["positions"],
  estimated: true,
  available: true,
  requires_recording: false,
};

const NEW_ACTION: VocabularyAction = {
  id: "zz_new_action",
  display_name: "New action",
  notes: "An action no client table names",
  required_permissions: [],
  places_orders: false,
  available: true,
  simulate_only: false,
  requires_step_up: false,
  loosens_risk: false,
};

/**
 * AC 1's extended fixture: the Manager's vocabulary plus one metric, action, trigger and operator the client has
 * never seen, so a test shows each new entry reaching the library with no client change.
 */
export function extended(): RuleVocabulary {
  const full = served("manager");
  return {
    ...full,
    signals: [...full.signals, NEW_METRIC],
    actions: [...full.actions, NEW_ACTION],
    triggers: [
      ...(full.triggers ?? []),
      {
        id: "zz_new_trigger",
        description: "When a new thing happens",
        required_fields: ["zz_window"],
      },
    ],
    operators: [
      ...full.operators,
      { id: "zz_new_op", arity: 2, operand_types: ["ratio"], result_type: "boolean" },
    ],
  };
}
