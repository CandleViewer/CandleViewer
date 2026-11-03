# tests/fixtures/e37

Static data for the E37 node-graph editor's black-box test plan (`qa/plans/e37-node-editor-test-plan.md`,
E37-Q01): two rule documents derived from the 30-rule round-trip corpus
(`services/api/tests/fixtures/rule_corpus/`) and three small hand-made corrupted ones. Nothing real is in
any file: no account id, key, token or user id; ids follow the corpus's `00000000-0000-4000-8000-…` form.

| File                                  | Plan handle    | What it is and how it is seeded                                                                                                     | Cases                                          |
| ------------------------------------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| `armed_demo_rule.json`                | RULE-ARMED-1   | RC-09, `scope.environments` `["demo"]`, `mode` `simulate`; `POST /rules`, then arm on demo with a step-up (a create lands disarmed) | E37-TC-A16, E37-TC-B12, E37-TC-D11, E37-TC-E16 |
| `layout_hand_placed.json`             | RULE-LAYOUT-1  | RC-11 with a `graph_layout`: eight hand-placed positions, off any grid, and two comments; `POST /rules`                             | E37-TC-B14, E37-TC-B16, E37-TC-D12, E37-TC-F09 |
| `corrupt_ir_truncated.json`           | RULE-CORRUPT-1 | a one-condition, one-action rule cut mid-object and mid-string; fails to parse at its last line                                     | E37-TC-C10                                     |
| `corrupt_ir_schema_violation.json`    | RULE-CORRUPT-2 | the same rule with the string `"soon"` at `limits.cooldown_ms`, where an integer is required                                        | E37-TC-C10                                     |
| `corrupt_ir_unsupported_version.json` | RULE-CORRUPT-3 | the same rule with `ir_version` 2; the engine supports version 1 only                                                               | E37-TC-C10                                     |

The three `corrupt_ir_*` files are seeded at the database level (the plan's fault toggle `FT-CORRUPT`,
section 13.5), because the API refuses each of them. Expected on open: read-only, disarmed, the failing
JSON path named, an export offered, no run recorded. `corrupt_ir_truncated.json` does not parse, so
prettier cannot format it and `.prettierignore` lists it; the other JSON files are formatted by prettier.
