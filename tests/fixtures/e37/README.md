# tests/fixtures/e37

Static data for the E37 node-graph editor's black-box test plan (`qa/plans/e37-node-editor-test-plan.md`,
E37-Q01): two rule documents derived from the 30-rule round-trip corpus
(`services/api/tests/fixtures/rule_corpus/`) and three small hand-made corrupted ones. Nothing real is in
any file: no account id, key, token or user id; ids follow the corpus's `00000000-0000-4000-8000-…` form.

| File                                  | Plan handle    | What it is and how it is seeded                                                                                                                                                                                                                                                                            | Cases                                          |
| ------------------------------------- | -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| `armed_demo_rule.json`                | RULE-ARMED-1   | RC-09, `scope.environments` `["demo"]`, `mode` `simulate`; `POST /rules` (a create lands disarmed), then arm on demo: no step-up is needed, but the arm needs a completed simulation run on the exact version, and the promotion gate (5 fires or 24 h) or, for the OWNER, a written `reason` in its place | E37-TC-A16, E37-TC-B12, E37-TC-D11, E37-TC-E16 |
| `layout_hand_placed.json`             | RULE-LAYOUT-1  | RC-11 with a `graph_layout`: eight hand-placed positions, off any grid, and two comments; `POST /rules`                                                                                                                                                                                                    | E37-TC-B14, E37-TC-B16, E37-TC-D12, E37-TC-F09 |
| `corrupt_ir_truncated.json`           | RULE-CORRUPT-1 | a one-condition, one-action rule cut mid-object and mid-string; fails to parse at its last line (seeded as a JSON string, it fails at the document root, `/`)                                                                                                                                              | E37-TC-C10                                     |
| `corrupt_ir_schema_violation.json`    | RULE-CORRUPT-2 | the same rule with the string `"soon"` at `limits.cooldown_ms` (the build names it `/limits/cooldown_ms`), where an integer is required                                                                                                                                                                    | E37-TC-C10, E37-TC-C14                         |
| `corrupt_ir_unsupported_version.json` | RULE-CORRUPT-3 | the same rule with `ir_version` 2; the engine supports version 1 only                                                                                                                                                                                                                                      | E37-TC-C10                                     |

The three `corrupt_ir_*` files are seeded at the database level (the plan's fault toggle `FT-CORRUPT`,
section 13.5), because the API refuses each of them. Expected on open: read-only, disarmed, the failing
JSON path named, an export offered, no run recorded. E37-TC-C14 seeds `corrupt_ir_schema_violation.json`
on a row whose mode is `armed` too (`FT-CORRUPT` writes the mode as well as the stored IR): on open the
server force-disarms it, so the mode reads `disabled` and one `rule.disarmed` row names the cause
`quarantined`. Prettier cannot parse `corrupt_ir_truncated.json`, so `.prettierignore` lists it.
