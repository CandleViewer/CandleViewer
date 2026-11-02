# Rule node editor (graph)

```yaml
script_id: RNE
title: "Rule node editor (graph)"
screens: [SCR-082]
status: "SURFACE PENDING E37-S01 #1067 and E37-S05 #1071 (SCR-082 and the node-list wiring)"
env: demo
fixture: "A saved rule graph with a trigger, a condition, an action and one logic gate; two nodes sharing one name."
preconditions:
  - "Fresh profile, default hotkey map, default theme, screen reader at default verbosity (05 §8.2 item 1)."
  - "Keyboard only for the whole pass; no mouse."
  - "Demo environment and synthetic accounts only. Never Live."
last_verified_sha: c327ed438c01c5bab9247890dd00f5dce3717f97 # a main sha; parents below are pinned as stated
parents:
  - "#5372 merged (main sha cd28f8836a1949fef7df97a590ae1f0a2335e4ca)"
  - "E37-S01 #1067: SURFACE PENDING (unbuilt)"
  - "E37-S05 #1071: SURFACE PENDING (unbuilt)"
  - "#5419 91e9bde449dc29325efd23e3e1f2fd5a34867351 (open, if merges as is)"
dry_run: pending
```

> **Expected text is a contract, not an observation.** It is derived from the shipped sentence builders cited per
> step (`file:line`), written as a pattern with fields. Wording is PROPOSED in those files; a copy change edits the
> builder, not this script. Nothing here was heard on a screen reader. Mark a step P/F only from what you hear.
> A `SURFACE PENDING` script cannot be executed until the named ticket mounts its surface.
> Oracle: the spec row or the `Source` formatter `file:line` each step verifies. `heuristic: true` marks a row
> derived by an agent from source, never heard; a human pass may correct it. Lag column: note any keypress-to-speech delay over about 200 ms as an E46 candidate.

> The node-list key (Alt+L in the plan) is wired by E37-S05, not by the shipped core. Record the key you used.

## Steps

| Step   | Keys                                        | Expected announcement                                                                           | Source                                                        | Oracle         | Heuristic       | Lag | P/F           |
| ------ | ------------------------------------------- | ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------- | -------------- | --------------- | --- | ------------- |
| RNE-01 | Open the node list                          | One row per node in traversal order: `Node {i} of {n}.` then `{Type} {name}, {params}. {ports}` | apps/web/src/features/rule-builder-graph/a11y/copy.ts:144     | Source column  | heuristic: true |     | [ ] P / [ ] F |
| RNE-02 | Move through nodes (arrows, Home, End)      | Post-order traversal; each node is read as in RNE-01                                            | apps/web/src/features/rule-builder-graph/a11y/traversal.ts:55 | Source column  | heuristic: true |     | [ ] P / [ ] F |
| RNE-03 | A port row                                  | `{Input or Output} port, {type}, {connected to {names} or not connected}`                       | apps/web/src/features/rule-builder-graph/a11y/copy.ts:91      | Source column  | heuristic: true |     | [ ] P / [ ] F |
| RNE-04 | Two nodes with one name                     | Each reads `{name} (node {i})`                                                                  | apps/web/src/features/rule-builder-graph/a11y/copy.ts:134     | Source column  | heuristic: true |     | [ ] P / [ ] F |
| RNE-05 | Start a connect from an output port         | `Connecting from output port, {type} — choose an input. {k} inputs available.`                  | apps/web/src/features/rule-builder-graph/a11y/copy.ts:71      | Source column  | heuristic: true |     | [ ] P / [ ] F |
| RNE-06 | Step through candidate targets              | `{target}, {port} — can connect, {i} of {k}`                                                    | apps/web/src/features/rule-builder-graph/a11y/copy.ts:103     | Source column  | heuristic: true |     | [ ] P / [ ] F |
| RNE-07 | Choose an occupied input                    | `This input already has a connection.`                                                          | apps/web/src/features/rule-builder-graph/a11y/copy.ts:40      | Source column  | heuristic: true |     | [ ] P / [ ] F |
| RNE-08 | Complete a valid connect                    | `connected {source} output to {target} input {n}`                                               | apps/web/src/features/rule-builder-graph/a11y/copy.ts:74      | Source column  | heuristic: true |     | [ ] P / [ ] F |
| RNE-09 | Delete the connection                       | `Disconnected {source} from {target}`                                                           | apps/web/src/features/rule-builder-graph/a11y/copy.ts:77      | Source column  | heuristic: true |     | [ ] P / [ ] F |
| RNE-10 | Nudge a node (arrow with the move modifier) | `Moved {name} {step} {dir}, now x {x}, y {y}.`                                                  | apps/web/src/features/rule-builder-graph/a11y/copy.ts:111     | Source column  | heuristic: true |     | [ ] P / [ ] F |
| RNE-11 | Arm, then disarm the rule                   | Record the state change verbatim                                                                | n/a                                                           | 05 §8.2 item 1 | heuristic: true |     | [ ] P / [ ] F |
