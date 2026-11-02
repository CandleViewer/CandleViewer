# Rule form editor

```yaml
script_id: RFE
title: "Rule form editor"
screens: [SCR-081]
status: "SURFACE PENDING E36-S02 #1058 (SCR-081 form)"
env: demo
fixture: "A demo account and a saved draft rule from the E35 fixtures."
preconditions:
  - "Fresh profile, default hotkey map, default theme, screen reader at default verbosity (05 §8.2 item 1)."
  - "Keyboard only for the whole pass; no mouse."
  - "Demo environment and synthetic accounts only. Never Live."
last_verified_sha: c327ed438c01c5bab9247890dd00f5dce3717f97 # a main sha; parents below are pinned as stated
parents:
  - "#5372 merged (main sha cd28f8836a1949fef7df97a590ae1f0a2335e4ca)"
  - "E36-S02 #1058: SURFACE PENDING (unbuilt)"
  - "#5419 91e9bde449dc29325efd23e3e1f2fd5a34867351 (open, if merges as is)"
dry_run: pending
```

> **Expected text is a contract, not an observation.** It is derived from the shipped sentence builders cited per
> step (`file:line`), written as a pattern with fields. Wording is PROPOSED in those files; a copy change edits the
> builder, not this script. Nothing here was heard on a screen reader. Mark a step P/F only from what you hear.
> A `SURFACE PENDING` script cannot be executed until the named ticket mounts its surface.
> Oracle: the spec row or the `Source` formatter `file:line` each step verifies. `heuristic: true` marks a row
> derived by an agent from source, never heard; a human pass may correct it. Lag column: note any keypress-to-speech delay over about 200 ms as an E46 candidate.

## Steps

| Step   | Keys                   | Expected announcement                                                                                           | Source                                                    | Oracle         | Heuristic       | Lag | P/F           |
| ------ | ---------------------- | --------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- | -------------- | --------------- | --- | ------------- |
| RFE-01 | Open the rule form     | Heading, landmarks and every control's name, role and value; record verbatim (05 §8.2 item 6 scope)             | n/a                                                       | 05 §8.2 item 6 | heuristic: true |     | [ ] P / [ ] F |
| RFE-02 | Tab through all fields | Record each field's name, required marker and value verbatim; focus order follows the visual order              | n/a                                                       | 05 §8.2 item 6 | heuristic: true |     | [ ] P / [ ] F |
| RFE-03 | Submit an invalid rule | `{n} problems. First: {where}: {message} {m} more problems in the problems list.` (one problem: no "more" tail) | apps/web/src/features/rule-builder-graph/a11y/copy.ts:122 | Source column  | heuristic: true |     | [ ] P / [ ] F |
| RFE-04 | Fix and validate again | `No problems found.`                                                                                            | apps/web/src/features/rule-builder-graph/a11y/copy.ts:121 | Source column  | heuristic: true |     | [ ] P / [ ] F |
| RFE-05 | Save                   | Record the confirmation verbatim; focus is not stolen                                                           | n/a                                                       | 05 §8.2 item 1 | heuristic: true |     | [ ] P / [ ] F |
| RFE-06 | Arm, then disarm       | Record the state change verbatim; an armed rule is not announced as Live trading                                | n/a                                                       | 05 §8.2 item 1 | heuristic: true |     | [ ] P / [ ] F |
