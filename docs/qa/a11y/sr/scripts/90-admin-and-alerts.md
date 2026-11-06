# Admin user creation and alert create and trigger

```yaml
script_id: ADA
title: "Admin user creation and alert create and trigger"
screens: [SCR-121, SCR-122, SCR-091, SCR-092]
status: "SURFACE PENDING E42-S02, E42-S03 (SCR-121, SCR-122), E40-S01 and E40-S02 (SCR-091, SCR-092)"
env: demo
fixture: "Seeded F-USR-OWNER and a demo account F-ACC-DEMO-1; passwords and TOTP seeds from the staging seed, never from this repo; a fixture event that fires the alert."
preconditions:
  - "Fresh profile, default hotkey map, default theme, screen reader at default verbosity (05 §8.2 item 1)."
  - "Keyboard only for the whole pass; no mouse."
  - "Demo environment and synthetic accounts only. Never Live."
  - "Synthetic users only; no real email address is typed (use the seeded canary-free test domain)."
last_verified_sha: c327ed438c01c5bab9247890dd00f5dce3717f97 # a main sha; parents below are pinned as stated
parents:
  - "E42-S02 (SCR-121 users list, SCR-123 invite): SURFACE PENDING (unbuilt)"
  - "E42-S03 (SCR-122 user detail, role and account binding): SURFACE PENDING (unbuilt)"
  - "E40-S01 (SCR-091 alert editor): SURFACE PENDING (unbuilt)"
  - "E40-S02 (SCR-092 fired-alert toast): SURFACE PENDING (unbuilt)"
  - "#5501 merged (T04 scripts, templates and checklist under docs/qa/a11y/sr/)"
  - "#5419 91e9bde449dc29325efd23e3e1f2fd5a34867351 (open, if merges as is)"
dry_run: pending
```

> **Expected text is a contract, not an observation.** No shipped sentence builder exists for these surfaces yet, so
> every expected cell states what must be obtainable and says `Record ... verbatim`: the tester writes down what is
> heard and never scripts copy (05 §8.2 item 3; "information must be obtainable, not identical" across NVDA, JAWS and
> VoiceOver). Wording is PROPOSED by the owning ticket; a copy change edits the builder, not this script. Nothing here
> was heard on a screen reader. Mark a step P/F only from what you hear. A `SURFACE PENDING` step cannot be executed
> until the named ticket mounts its surface, and is never P.
> Oracle: the spec row each step verifies. `heuristic: true` marks a row derived by an agent from the plan, never
> heard; a human pass may correct it. Lag column: note any keypress-to-speech delay over about 200 ms as an E46 candidate.

## Steps

| Step   | Keys                                                                                                     | Expected announcement                                                                                                                                   | Source                                                | Oracle         | Heuristic       | Lag | P/F           |
| ------ | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- | -------------- | --------------- | --- | ------------- |
| ADA-01 | [SCR-075 · SC 1.4.1 4.1.2] Tab to the top bar                                                            | `Trading environment: Demo` (read first). **Stop and fail the script if it says Live**; nothing was done                                                | apps/web/src/features/app-shell/TopBarEnvBadge.tsx:47 | Source column  | heuristic: true |     | [ ] P / [ ] F |
| ADA-02 | [SCR-121 · SC 2.1.1 1.3.1 2.4.6] Open the Admin area, then SCR-121 Users                                 | Record the page heading and the grid name verbatim; the grid is one tab stop with arrow keys (SURFACE PENDING E42-S02)                                  | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| ADA-03 | [SCR-123 · SC 3.3.2 4.1.2] Start the add-user flow (SCR-123 invite; key per E42-S02) and fill each field | Every control has a name, role and value; record each verbatim. Required fields say so (SURFACE PENDING E42-S02)                                        | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| ADA-04 | [SCR-123 · SC 3.3.1 3.3.3] Submit with an invalid email                                                  | Record the error verbatim; it names the field; focus goes to it (SURFACE PENDING E42-S02)                                                               | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| ADA-05 | [SCR-123 · SC 4.1.3 3.2.1] Submit a valid manager invite                                                 | Success is announced once; record verbatim; focus is not lost (SURFACE PENDING E42-S02)                                                                 | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| ADA-06 | [SCR-122 · SC 4.1.2 1.3.1] Open the new user in SCR-122 and assign a permission scope and one account    | Every control has a name, role and value; record the scope and account choices verbatim; the manager's scope is shown as text (SURFACE PENDING E42-S03) | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| ADA-07 | [SCR-122 · SC 4.1.3 3.3.1] Save SCR-122                                                                  | Success or error is announced; record verbatim; no other user's full email or any account id is said (SURFACE PENDING E42-S03)                          | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| ADA-08 | [SCR-091 · SC 3.3.2 4.1.2] Open the SCR-091 alert editor and create a price alert                        | Every control has a name, role and value; record each verbatim; the sound option, if any, is named (SURFACE PENDING E40-S01)                            | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| ADA-09 | [SCR-092 · SC 4.1.3 3.2.1] Fire the alert (fixture event) while focus rests elsewhere                    | The SCR-092 toast is announced once with its severity as text; focus does not move; record it verbatim (SURFACE PENDING E40-S02)                        | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| ADA-10 | [SCR-092 · SC 2.1.1 2.4.3] Open the toast detail with the keyboard and dismiss it                        | Reachable by keyboard, closes with `Esc` or its button, focus returns where it was; record verbatim (SURFACE PENDING E40-S02)                           | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |
| ADA-11 | [SCR-091 SCR-092 · SC 1.4.2 1.4.1] Fire an alert with sound on                                           | Sound is never the only channel and stops within 3 s or has a control (E47-TC-214); record what is said; record it verbatim (SURFACE PENDING E40-S02)   | n/a                                                   | 05 §8.2 item 3 | heuristic: true |     | [ ] P / [ ] F |

## Notes

- Maps to `E47-TC-113` (admin) and `E47-TC-209` and `E47-TC-214` (alerts) in `qa/plans/e47-accessibility-test-plan.md`.
