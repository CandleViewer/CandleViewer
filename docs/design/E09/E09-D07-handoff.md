# E09-D07 — Hand-off (`16` §11.4): the ten checklists of the auth component band

Components: CMP-097, CMP-098 and CMP-200 … CMP-207. The pack is [E09-D07.md](E09-D07.md) (every "A-n" below is its §C row, applied to `15` by PR 2) and the composition map [E09-D07-composition.json](E09-D07-composition.json). A `CMP-*` ticket ships this file (`16` §13.3 item 8; README:81–82). The tables cite `15` by entry and never restate a props table; the keyboard tables add no global binding (`05` §3.2) and leave `Esc` and `Ctrl+K` untouched (`05` §3.3).

Rule: every line is `[x]` with its evidence, or `[ ]` with its reason (a PR still to land, or `N/A — <reason>`). No blank line at Done (`16` §11.4, §13.3).

## The A-row ledger by component (BQ-8)

The pack's §2 holds the ledger: 36<!--=COUNT:ledger--> rows, 21<!--=COUNT:ledger.applied--> applied, 2<!--=COUNT:ledger.amended--> applied-as-amended, 1<!--=COUNT:ledger.closed--> closed by #4086, 0<!--=COUNT:ledger.held--> held and 12<!--=COUNT:ledger.routed--> routed. Per component, the rows its A-rows carry (the tool derives this table from §2 and §C):

| Component                   | Ledger rows                                                                  | A-rows                 |
| --------------------------- | ---------------------------------------------------------------------------- | ---------------------- |
| CMP-200                     | L-26, L-27                                                                   | A-13, A-14             |
| CMP-201                     | L-1, L-7, L-10, L-25                                                         | A-17, A-18, A-19       |
| CMP-202                     | L-2, L-6, L-8                                                                | A-22, A-23, A-24       |
| CMP-203                     | L-3, L-4, L-5, L-9                                                           | A-26, A-28, A-29, A-30 |
| CMP-204                     | L-18, L-21, L-22, L-23, L-24                                                 | A-32, A-34, A-38       |
| CMP-205                     | L-17, L-20                                                                   | A-40, A-41, A-43       |
| CMP-207                     | L-15                                                                         | A-48                   |
| CMP-098                     | L-11, L-19                                                                   | A-6, A-8               |
| routed or closed (no A-row) | L-12, L-13, L-14, L-16, L-28, L-29, L-30, L-31, L-32, L-33, L-34, L-35, L-36 | —                      |

## Handoff checklist — CMP-200 AuthCard (E09-D07, #190)

- [x] **Final Penpot link** — page `E09-D07 auth band` (`e4de416d-a820-8072-8008-e06d290d694c`) of the per-set file `E09-D07 boards` (the PR 3 ruling), page name + page id only: the specimen frames `CMP-200 · AuthCard / State=…` on board 01, [E09-D07-01-auth-card-and-build-footer.png](img/E09-D07-01-auth-card-and-build-footer.png), and its row on the band boards 08, 09 and 10 (dark, light, high contrast); specimen boards, no library component (BQ-2)
- [x] **Variants × States matrix** — table 1; the stories of the pack's §7 (`15`:2597 (unchanged))
- [x] **Keyboard table** — table 2
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — table 5
- [x] **Motion pair** — N/A — none animated (E09-D08 S3 for secrets and factors)
- [x] **Density notes** — the density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — equal to the entry's Tokens field after PR 2 (A-14); the Penpot sets equal the token JSON under `packages/ui` at `a0132de011`
- [x] **Data contract confirmed** — N/A — pure chrome; the host binds the operation
- [x] **Contrast and CVD** — computed by the tool (the pack's §6: P-1, P-2, P-3; CR-2); no new colour pair is introduced, so `tools/contrast/pairs.mjs` gains none
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PR 3, on the boards
- [ ] **Sign-off** — the orchestrator's design approval (BQ-34) on PR 1, PR 2 and PR 3

### Table 1 — Variants × States

| Variant    | State               | Penpot variant                        | Story name |
| ---------- | ------------------- | ------------------------------------- | ---------- |
| Default    | idle                | CMP-200 · AuthCard / State=Default    | Default    |
| WithError  | form-level failure  | CMP-200 · AuthCard / State=WithError  | WithError  |
| Busy       | submitting          | CMP-200 · AuthCard / State=Busy       | Busy       |
| WithFooter | with the build line | CMP-200 · AuthCard / State=WithFooter | WithFooter |

### Table 2 — Keyboard

| Key             | Action                               | Focus after                                          | Global conflict?                      | Notes                     |
| --------------- | ------------------------------------ | ---------------------------------------------------- | ------------------------------------- | ------------------------- |
| Tab / Shift+Tab | moves through the form in order      | the next control                                     | none (05 §3.2: no view-local binding) | one tab sequence, no trap |
| Enter           | submits the form (the host's submit) | stays on the submit; to the field on a field failure | none                                  | E09-D05 C-19              |

### Table 3 — Accessible name / role

| Element      | Role    | Accessible name (source)                   | States / properties                                                  |
| ------------ | ------- | ------------------------------------------ | -------------------------------------------------------------------- |
| `<main>`     | main    | —                                          | —                                                                    |
| `<h1>`       | heading | `title` (visible text)                     | level 1                                                              |
| error region | alert   | its words (the host's form-level sentence) | focused on appearance; form-level failures only                      |
| form         | form    | the card title                             | `aria-busy="true"` while busy; the submit `aria-disabled`, focusable |

### Table 4 — Motion pair

| Property | motion-safe   | motion-reduce | Duration / easing tokens |
| -------- | ------------- | ------------- | ------------------------ |
| —        | none animated | —             | —                        |

### Table 5 — Live data

| Field        | Politeness                 | Cadence          | Coalescing              | Notes                                   |
| ------------ | -------------------------- | ---------------- | ----------------------- | --------------------------------------- |
| error region | assertive (`role="alert"`) | once per failure | the latest failure only | form-level failures only (E09-D05 §9.1) |

### Density

| Mode        | Row / control height                                                | Padding tokens           | Smallest target                                                      |
| ----------- | ------------------------------------------------------------------- | ------------------------ | -------------------------------------------------------------------- |
| compact     | `size.control.height` (24<!--=TOKEN:size.control.compact--> px)     | the entry's Tokens field | 24<!--=TOKEN:size.target.min--> × 24<!--=TOKEN:size.target.min--> px |
| comfortable | `size.control.height` (32<!--=TOKEN:size.control.comfortable--> px) | the entry's Tokens field | 24<!--=TOKEN:size.target.min--> × 24<!--=TOKEN:size.target.min--> px |

### Essential exceptions

| Exception | Compensating control | Reviewer | Date |
| --------- | -------------------- | -------- | ---- |
| none      | —                    | —        | —    |

## Handoff checklist — CMP-201 PasswordField (E09-D07, #190)

- [x] **Final Penpot link** — page `E09-D07 auth band` (`e4de416d-a820-8072-8008-e06d290d694c`) of the per-set file `E09-D07 boards` (the PR 3 ruling), page name + page id only: the specimen frames `CMP-201 · PasswordField / State=…` on board 02, [E09-D07-02-password-field.png](img/E09-D07-02-password-field.png), and its row on the band boards 08, 09 and 10 (dark, light, high contrast); specimen boards, no library component (BQ-2)
- [x] **Variants × States matrix** — table 1; the stories of the pack's §7 (A-19)
- [x] **Keyboard table** — table 2
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — table 5
- [x] **Motion pair** — N/A — none animated (E09-D08 S3 for secrets and factors)
- [x] **Density notes** — the density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — equal to the entry's Tokens field after PR 2 (inherits CMP-007 (`15`:2610, unchanged)); the Penpot sets equal the token JSON under `packages/ui` at `a0132de011`
- [x] **Data contract confirmed** — N/A — pure chrome; the host binds the operation
- [x] **Contrast and CVD** — computed by the tool (the pack's §6: P-4, P-5); no new colour pair is introduced, so `tools/contrast/pairs.mjs` gains none
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PR 3, on the boards
- [ ] **Sign-off** — the orchestrator's design approval (BQ-34) on PR 1, PR 2 and PR 3

### Table 1 — Variants × States

| Variant         | State        | Penpot variant                              | Story name               |
| --------------- | ------------ | ------------------------------------------- | ------------------------ |
| CurrentPassword | default      | CMP-201 · PasswordField / State=Default     | Default, CurrentPassword |
| NewPassword     | default      | CMP-201 · PasswordField / State=NewPassword | NewPassword              |
| any             | revealed     | CMP-201 · PasswordField / State=Revealed    | Revealed, PerFieldReveal |
| any             | caps lock on | CMP-201 · PasswordField / State=CapsLockOn  | CapsLockOn               |
| any             | invalid      | CMP-201 · PasswordField / State=WithError   | WithError                |

### Table 2 — Keyboard

| Key                    | Action                     | Focus after         | Global conflict? | Notes                                                |
| ---------------------- | -------------------------- | ------------------- | ---------------- | ---------------------------------------------------- |
| Tab                    | the field, then its reveal | the reveal button   | none             | one reveal per field                                 |
| Enter / Space (reveal) | toggles the field's reveal | stays on the reveal | none             | `aria-pressed` flips; the name stays "Show password" |
| Ctrl+V / paste         | pastes; never suppressed   | stays in the field  | none             | a security control                                   |

### Table 3 — Accessible name / role

| Element                   | Role            | Accessible name (source)            | States / properties                                  |
| ------------------------- | --------------- | ----------------------------------- | ---------------------------------------------------- |
| `<input type="password">` | textbox         | the field's visible label (CMP-040) | `autocomplete` per host; `aria-invalid` with `error` |
| reveal                    | button          | "Show password" (constant)          | `aria-pressed`                                       |
| caps-lock warning         | status (polite) | "Caps Lock is on." (A20)            | on the focused field only                            |

### Table 4 — Motion pair

| Property | motion-safe   | motion-reduce | Duration / easing tokens |
| -------- | ------------- | ------------- | ------------------------ |
| —        | none animated | —             | —                        |

### Table 5 — Live data

| Field             | Politeness | Cadence   | Coalescing            | Notes              |
| ----------------- | ---------- | --------- | --------------------- | ------------------ |
| caps-lock warning | polite     | on change | the latest state only | focused field only |

### Density

| Mode        | Row / control height                                                | Padding tokens           | Smallest target                                                      |
| ----------- | ------------------------------------------------------------------- | ------------------------ | -------------------------------------------------------------------- |
| compact     | `size.control.height` (24<!--=TOKEN:size.control.compact--> px)     | the entry's Tokens field | 24<!--=TOKEN:size.target.min--> × 24<!--=TOKEN:size.target.min--> px |
| comfortable | `size.control.height` (32<!--=TOKEN:size.control.comfortable--> px) | the entry's Tokens field | 24<!--=TOKEN:size.target.min--> × 24<!--=TOKEN:size.target.min--> px |

### Essential exceptions

| Exception | Compensating control | Reviewer | Date |
| --------- | -------------------- | -------- | ---- |
| none      | —                    | —        | —    |

## Handoff checklist — CMP-202 PasswordStrengthMeter (E09-D07, #190)

- [x] **Final Penpot link** — page `E09-D07 auth band` (`e4de416d-a820-8072-8008-e06d290d694c`) of the per-set file `E09-D07 boards` (the PR 3 ruling), page name + page id only: the specimen frames `CMP-202 · PasswordStrengthMeter / State=…` on board 03, [E09-D07-03-strength-meter-and-checklist.png](img/E09-D07-03-strength-meter-and-checklist.png), and its row on the band boards 08, 09 and 10 (dark, light, high contrast); specimen boards, no library component (BQ-2)
- [x] **Variants × States matrix** — table 1; the stories of the pack's §7 (A-24)
- [x] **Keyboard table** — N/A — not focusable (table 2 lists no key)
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — table 5
- [x] **Motion pair** — N/A — none animated (E09-D08 S3 for secrets and factors)
- [x] **Density notes** — the density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — equal to the entry's Tokens field after PR 2 (A-23); the Penpot sets equal the token JSON under `packages/ui` at `a0132de011`
- [x] **Data contract confirmed** — N/A — the score is the frontend's
- [x] **Contrast and CVD** — computed by the tool (the pack's §6: P-6, P-7); no new colour pair is introduced, so `tools/contrast/pairs.mjs` gains none
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PR 3, on the boards
- [ ] **Sign-off** — the orchestrator's design approval (BQ-34) on PR 1, PR 2 and PR 3

### Table 1 — Variants × States

| Variant        | State         | Penpot variant                                       | Story name   |
| -------------- | ------------- | ---------------------------------------------------- | ------------ |
| score 0–1      | Weak          | CMP-202 · PasswordStrengthMeter / State=Weak         | Weak         |
| score 2        | Fair          | CMP-202 · PasswordStrengthMeter / State=Fair         | Fair         |
| score 3–4      | Strong        | CMP-202 · PasswordStrengthMeter / State=Strong       | Strong       |
| any            | with feedback | CMP-202 · PasswordStrengthMeter / State=WithFeedback | WithFeedback |
| length not met | capped        | CMP-202 · PasswordStrengthMeter / State=CappedWeak   | CappedWeak   |

### Table 2 — Keyboard

| Key | Action        | Focus after | Global conflict? | Notes                         |
| --- | ------------- | ----------- | ---------------- | ----------------------------- |
| —   | not focusable | —           | —                | the component has no Tab stop |

### Table 3 — Accessible name / role

| Element       | Role                    | Accessible name (source)          | States / properties                          |
| ------------- | ----------------------- | --------------------------------- | -------------------------------------------- |
| strength word | text in the status node | `Strength: {word}` (E09-D05 §4.3) | advisory; never gates the submit             |
| bar           | presentation            | —                                 | the word carries the strength (`15` CMP-202) |

### Table 4 — Motion pair

| Property | motion-safe   | motion-reduce | Duration / easing tokens |
| -------- | ------------- | ------------- | ------------------------ |
| —        | none animated | —             | —                        |

### Table 5 — Live data

| Field         | Politeness                      | Cadence          | Coalescing      | Notes                                   |
| ------------- | ------------------------------- | ---------------- | --------------- | --------------------------------------- |
| strength word | polite (the shared status node) | debounced 500 ms | the latest word | after the checklist item (E09-D05 §4.3) |

### Density

| Mode        | Row / control height                                                | Padding tokens           | Smallest target                                                      |
| ----------- | ------------------------------------------------------------------- | ------------------------ | -------------------------------------------------------------------- |
| compact     | `size.control.height` (24<!--=TOKEN:size.control.compact--> px)     | the entry's Tokens field | 24<!--=TOKEN:size.target.min--> × 24<!--=TOKEN:size.target.min--> px |
| comfortable | `size.control.height` (32<!--=TOKEN:size.control.comfortable--> px) | the entry's Tokens field | 24<!--=TOKEN:size.target.min--> × 24<!--=TOKEN:size.target.min--> px |

### Essential exceptions

| Exception | Compensating control | Reviewer | Date |
| --------- | -------------------- | -------- | ---- |
| none      | —                    | —        | —    |

## Handoff checklist — CMP-203 RequirementChecklist (E09-D07, #190)

- [x] **Final Penpot link** — page `E09-D07 auth band` (`e4de416d-a820-8072-8008-e06d290d694c`) of the per-set file `E09-D07 boards` (the PR 3 ruling), page name + page id only: the specimen frames `CMP-203 · RequirementChecklist / State=…` on board 03, [E09-D07-03-strength-meter-and-checklist.png](img/E09-D07-03-strength-meter-and-checklist.png), and its row on the band boards 08, 09 and 10 (dark, light, high contrast); specimen boards, no library component (BQ-2)
- [x] **Variants × States matrix** — table 1; the stories of the pack's §7 (A-30)
- [x] **Keyboard table** — N/A — not focusable (table 2 lists no key)
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — table 5
- [x] **Motion pair** — N/A — none animated (E09-D08 S3 for secrets and factors)
- [x] **Density notes** — the density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — equal to the entry's Tokens field after PR 2 (A-29); the Penpot sets equal the token JSON under `packages/ui` at `a0132de011`
- [x] **Data contract confirmed** — N/A — client and server rules as E09-D05 §4.1 lists them
- [x] **Contrast and CVD** — computed by the tool (the pack's §6: P-7, P-8; CR-1); no new colour pair is introduced, so `tools/contrast/pairs.mjs` gains none
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PR 3, on the boards
- [ ] **Sign-off** — the orchestrator's design approval (BQ-34) on PR 1, PR 2 and PR 3

### Table 1 — Variants × States

| Variant      | State                     | Penpot variant                                              | Story name           |
| ------------ | ------------------------- | ----------------------------------------------------------- | -------------------- |
| items        | none met                  | CMP-203 · RequirementChecklist / State=NoneMet              | NoneMet              |
| items        | some met                  | CMP-203 · RequirementChecklist / State=PartiallyMet         | PartiallyMet         |
| items        | all met                   | CMP-203 · RequirementChecklist / State=AllMet               | AllMet               |
| server items | checked when you submit   | CMP-203 · RequirementChecklist / State=CheckedWhenYouSubmit | CheckedWhenYouSubmit |
| server items | not met after a rejection | CMP-203 · RequirementChecklist / State=ServerNotMet         | ServerNotMet         |

### Table 2 — Keyboard

| Key | Action        | Focus after | Global conflict? | Notes                         |
| --- | ------------- | ----------- | ---------------- | ----------------------------- |
| —   | not focusable | —           | —                | the component has no Tab stop |

### Table 3 — Accessible name / role

| Element     | Role            | Accessible name (source)                                           | States / properties               |
| ----------- | --------------- | ------------------------------------------------------------------ | --------------------------------- |
| `<ul>`      | list            | —                                                                  | not a live region                 |
| item        | listitem        | its words and state: "met" / "not met" / "checked when you submit" | glyph and weight beside the words |
| status node | status (polite) | the changed item, `{item}: {state}`                                | pre-rendered at mount             |

### Table 4 — Motion pair

| Property | motion-safe   | motion-reduce | Duration / easing tokens |
| -------- | ------------- | ------------- | ------------------------ |
| —        | none animated | —             | —                        |

### Table 5 — Live data

| Field       | Politeness | Cadence          | Coalescing                 | Notes                |
| ----------- | ---------- | ---------------- | -------------------------- | -------------------- |
| status node | polite     | debounced 500 ms | only the item that changed | never the whole list |

### Density

| Mode        | Row / control height                                                | Padding tokens           | Smallest target                                                      |
| ----------- | ------------------------------------------------------------------- | ------------------------ | -------------------------------------------------------------------- |
| compact     | `size.control.height` (24<!--=TOKEN:size.control.compact--> px)     | the entry's Tokens field | 24<!--=TOKEN:size.target.min--> × 24<!--=TOKEN:size.target.min--> px |
| comfortable | `size.control.height` (32<!--=TOKEN:size.control.comfortable--> px) | the entry's Tokens field | 24<!--=TOKEN:size.target.min--> × 24<!--=TOKEN:size.target.min--> px |

### Essential exceptions

| Exception | Compensating control | Reviewer | Date |
| --------- | -------------------- | -------- | ---- |
| none      | —                    | —        | —    |

## Handoff checklist — CMP-204 OtpInput (E09-D07, #190)

- [x] **Final Penpot link** — page `E09-D07 auth band` (`e4de416d-a820-8072-8008-e06d290d694c`) of the per-set file `E09-D07 boards` (the PR 3 ruling), page name + page id only: the specimen frames `CMP-204 · OtpInput / State=…` on board 04, [E09-D07-04-otp-input.png](img/E09-D07-04-otp-input.png), and its row on the band boards 08, 09 and 10 (dark, light, high contrast); specimen boards, no library component (BQ-2)
- [x] **Variants × States matrix** — table 1; the stories of the pack's §7 (A-36)
- [x] **Keyboard table** — table 2
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — N/A — static chrome, no streaming value
- [x] **Motion pair** — N/A — none animated (E09-D08 S3 for secrets and factors)
- [x] **Density notes** — the density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — equal to the entry's Tokens field after PR 2 (A-35); the Penpot sets equal the token JSON under `packages/ui` at `a0132de011`
- [x] **Data contract confirmed** — N/A — the host binds the operation
- [x] **Contrast and CVD** — computed by the tool (the pack's §6: P-4, P-5); no new colour pair is introduced, so `tools/contrast/pairs.mjs` gains none
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PR 3, on the boards
- [ ] **Sign-off** — the orchestrator's design approval (BQ-34) on PR 1, PR 2 and PR 3

### Table 1 — Variants × States

| Variant     | State                 | Penpot variant                             | Story name      |
| ----------- | --------------------- | ------------------------------------------ | --------------- |
| one control | empty                 | CMP-204 · OtpInput / State=Empty           | Empty           |
| one control | partly filled         | CMP-204 · OtpInput / State=PartiallyFilled | PartiallyFilled |
| one control | complete              | CMP-204 · OtpInput / State=Complete        | Complete        |
| one control | error                 | CMP-204 · OtpInput / State=Error           | Error           |
| one control | verifying (read-only) | CMP-204 · OtpInput / State=Disabled        | Disabled        |
| one control | pasted                | CMP-204 · OtpInput / State=Pasted          | Pasted          |

### Table 2 — Keyboard

| Key               | Action                               | Focus after        | Global conflict? | Notes                     |
| ----------------- | ------------------------------------ | ------------------ | ---------------- | ------------------------- |
| Tab               | enters the one input                 | the input          | none             | one Tab stop, never six   |
| digits            | fill the next cell                   | stays in the input | none             | no per-digit focus move   |
| Ctrl+V / paste    | fills the whole code; one submit     | stays in the input | none             | a security control        |
| ← / → / Backspace | move and delete within the one input | stays in the input | none             | no announcement per digit |

### Table 3 — Accessible name / role

| Element   | Role         | Accessible name (source)                                          | States / properties                                                                                                                     |
| --------- | ------------ | ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `<input>` | textbox      | `aria-labelledby` = the consumer's visible heading (`labelledBy`) | `inputmode="numeric"`, `autocomplete="one-time-code"`; `aria-describedby` = `describedBy`; `readOnly` + `aria-disabled` while verifying |
| cells     | presentation | —                                                                 | drawn, never focusable                                                                                                                  |

### Table 4 — Motion pair

| Property | motion-safe   | motion-reduce | Duration / easing tokens |
| -------- | ------------- | ------------- | ------------------------ |
| —        | none animated | —             | —                        |

### Table 5 — Live data

| Field | Politeness | Cadence | Coalescing | Notes  |
| ----- | ---------- | ------- | ---------- | ------ |
| —     | none       | —       | —          | static |

### Density

| Mode        | Row / control height                                                | Padding tokens           | Smallest target                                                      |
| ----------- | ------------------------------------------------------------------- | ------------------------ | -------------------------------------------------------------------- |
| compact     | `size.control.height` (24<!--=TOKEN:size.control.compact--> px)     | the entry's Tokens field | 24<!--=TOKEN:size.target.min--> × 24<!--=TOKEN:size.target.min--> px |
| comfortable | `size.control.height` (32<!--=TOKEN:size.control.comfortable--> px) | the entry's Tokens field | 24<!--=TOKEN:size.target.min--> × 24<!--=TOKEN:size.target.min--> px |

### Essential exceptions

| Exception | Compensating control | Reviewer | Date |
| --------- | -------------------- | -------- | ---- |
| none      | —                    | —        | —    |

## Handoff checklist — CMP-205 QrCode (E09-D07, #190)

- [x] **Final Penpot link** — page `E09-D07 auth band` (`e4de416d-a820-8072-8008-e06d290d694c`) of the per-set file `E09-D07 boards` (the PR 3 ruling), page name + page id only: the specimen frames `CMP-205 · QrCode / State=…` on board 05, [E09-D07-05-qr-code-and-recovery-codes.png](img/E09-D07-05-qr-code-and-recovery-codes.png), and its row on the band boards 08, 09 and 10 (dark, light, high contrast); specimen boards, no library component (BQ-2)
- [x] **Variants × States matrix** — table 1; the stories of the pack's §7 (`15`:2661 (unchanged))
- [x] **Keyboard table** — N/A — not focusable (table 2 lists no key)
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — N/A — static chrome, no streaming value
- [x] **Motion pair** — N/A — none animated (E09-D08 S3 for secrets and factors)
- [x] **Density notes** — the density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — equal to the entry's Tokens field after PR 2 (A-41); the Penpot sets equal the token JSON under `packages/ui` at `a0132de011`
- [x] **Data contract confirmed** — `otpauth_uri` (`MfaEnrollResponse`) or `secret_base32` on the invite path (`22-api-openapi.yaml`)
- [x] **Contrast and CVD** — computed by the tool (the pack's §6: — (the bitmap is untinted: the one sanctioned non-token fill)); no new colour pair is introduced, so `tools/contrast/pairs.mjs` gains none
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PR 3, on the boards
- [ ] **Sign-off** — the orchestrator's design approval (BQ-34) on PR 1, PR 2 and PR 3

### Table 1 — Variants × States

| Variant     | State   | Penpot variant                     | Story name |
| ----------- | ------- | ---------------------------------- | ---------- |
| size 200    | default | CMP-205 · QrCode / State=Default   | Default    |
| larger size | default | CMP-205 · QrCode / State=LargeSize | LargeSize  |

### Table 2 — Keyboard

| Key | Action        | Focus after | Global conflict? | Notes                         |
| --- | ------------- | ----------- | ---------------- | ----------------------------- |
| —   | not focusable | —           | —                | the component has no Tab stop |

### Table 3 — Accessible name / role

| Element              | Role                          | Accessible name (source)                                                  | States / properties                                         |
| -------------------- | ----------------------------- | ------------------------------------------------------------------------- | ----------------------------------------------------------- |
| QR image             | img                           | "QR code for your authenticator app. The setup key is shown below." (A21) | no secret, issuer, account or URI in a name, title or `alt` |
| manual secret (host) | CMP-020 text + CMP-033 button | the button's own label                                                    | the copy announcement never contains the value              |

### Table 4 — Motion pair

| Property | motion-safe   | motion-reduce | Duration / easing tokens |
| -------- | ------------- | ------------- | ------------------------ |
| —        | none animated | —             | —                        |

### Table 5 — Live data

| Field | Politeness | Cadence | Coalescing | Notes  |
| ----- | ---------- | ------- | ---------- | ------ |
| —     | none       | —       | —          | static |

### Density

| Mode        | Row / control height                                                | Padding tokens           | Smallest target                                                      |
| ----------- | ------------------------------------------------------------------- | ------------------------ | -------------------------------------------------------------------- |
| compact     | `size.control.height` (24<!--=TOKEN:size.control.compact--> px)     | the entry's Tokens field | 24<!--=TOKEN:size.target.min--> × 24<!--=TOKEN:size.target.min--> px |
| comfortable | `size.control.height` (32<!--=TOKEN:size.control.comfortable--> px) | the entry's Tokens field | 24<!--=TOKEN:size.target.min--> × 24<!--=TOKEN:size.target.min--> px |

### Essential exceptions

| Exception | Compensating control | Reviewer | Date |
| --------- | -------------------- | -------- | ---- |
| none      | —                    | —        | —    |

## Handoff checklist — CMP-206 RecoveryCodeList (E09-D07, #190)

- [x] **Final Penpot link** — page `E09-D07 auth band` (`e4de416d-a820-8072-8008-e06d290d694c`) of the per-set file `E09-D07 boards` (the PR 3 ruling), page name + page id only: the specimen frames `CMP-206 · RecoveryCodeList / State=…` on board 05, [E09-D07-05-qr-code-and-recovery-codes.png](img/E09-D07-05-qr-code-and-recovery-codes.png), and its row on the band boards 08, 09 and 10 (dark, light, high contrast); specimen boards, no library component (BQ-2)
- [x] **Variants × States matrix** — table 1; the stories of the pack's §7 (A-45)
- [x] **Keyboard table** — table 2
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — N/A — static chrome, no streaming value
- [x] **Motion pair** — N/A — none animated (E09-D08 S3 for secrets and factors)
- [x] **Density notes** — the density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — equal to the entry's Tokens field after PR 2 (A-44); the Penpot sets equal the token JSON under `packages/ui` at `a0132de011`
- [x] **Data contract confirmed** — the 10 codes of `MfaEnrollConfirmResponse`, shown exactly once (`22-api-openapi.yaml`)
- [x] **Contrast and CVD** — computed by the tool (the pack's §6: P-9); no new colour pair is introduced, so `tools/contrast/pairs.mjs` gains none
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PR 3, on the boards
- [ ] **Sign-off** — the orchestrator's design approval (BQ-34) on PR 1, PR 2 and PR 3

### Table 1 — Variants × States

| Variant | State                | Penpot variant                                  | Story name         |
| ------- | -------------------- | ----------------------------------------------- | ------------------ |
| codes   | shown once           | CMP-206 · RecoveryCodeList / State=Default      | Default            |
| codes   | acknowledged         | CMP-206 · RecoveryCodeList / State=Acknowledged | Acknowledged       |
| codes   | consumed / remaining | CMP-206 · RecoveryCodeList / State=held         | held (E09-D12 G-3) |

### Table 2 — Keyboard

| Key   | Action                                                         | Focus after           | Global conflict? | Notes                   |
| ----- | -------------------------------------------------------------- | --------------------- | ---------------- | ----------------------- |
| Tab   | each action button, then the acknowledgement, in reading order | the next control      | none             | real buttons            |
| Space | toggles the acknowledgement                                    | stays on the checkbox | none             | Continue is gated on it |

### Table 3 — Accessible name / role

| Element                          | Role               | Accessible name (source) | States / properties       |
| -------------------------------- | ------------------ | ------------------------ | ------------------------- |
| codes                            | list (ordered)     | —                        | monospace; read in order  |
| Copy all / Download .txt / Print | button             | the visible label        | —                         |
| acknowledgement                  | checkbox (CMP-005) | its visible label        | states why it is required |

### Table 4 — Motion pair

| Property | motion-safe   | motion-reduce | Duration / easing tokens |
| -------- | ------------- | ------------- | ------------------------ |
| —        | none animated | —             | —                        |

### Table 5 — Live data

| Field | Politeness | Cadence | Coalescing | Notes  |
| ----- | ---------- | ------- | ---------- | ------ |
| —     | none       | —       | —          | static |

### Density

| Mode        | Row / control height                                                | Padding tokens           | Smallest target                                                      |
| ----------- | ------------------------------------------------------------------- | ------------------------ | -------------------------------------------------------------------- |
| compact     | `size.control.height` (24<!--=TOKEN:size.control.compact--> px)     | the entry's Tokens field | 24<!--=TOKEN:size.target.min--> × 24<!--=TOKEN:size.target.min--> px |
| comfortable | `size.control.height` (32<!--=TOKEN:size.control.comfortable--> px) | the entry's Tokens field | 24<!--=TOKEN:size.target.min--> × 24<!--=TOKEN:size.target.min--> px |

### Essential exceptions

| Exception | Compensating control | Reviewer | Date |
| --------- | -------------------- | -------- | ---- |
| none      | —                    | —        | —    |

## Handoff checklist — CMP-207 BuildFooter (E09-D07, #190)

- [x] **Final Penpot link** — page `E09-D07 auth band` (`e4de416d-a820-8072-8008-e06d290d694c`) of the per-set file `E09-D07 boards` (the PR 3 ruling), page name + page id only: the specimen frames `CMP-207 · BuildFooter / State=…` on board 01, [E09-D07-01-auth-card-and-build-footer.png](img/E09-D07-01-auth-card-and-build-footer.png), and its row on the band boards 08, 09 and 10 (dark, light, high contrast); specimen boards, no library component (BQ-2)
- [x] **Variants × States matrix** — table 1; the stories of the pack's §7 (A-50)
- [x] **Keyboard table** — N/A — not focusable (table 2 lists no key)
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — N/A — static chrome, no streaming value
- [x] **Motion pair** — N/A — none animated (E09-D08 S3 for secrets and factors)
- [x] **Density notes** — the density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — equal to the entry's Tokens field after PR 2 (A-49); the Penpot sets equal the token JSON under `packages/ui` at `a0132de011`
- [x] **Data contract confirmed** — `BuildInfo` (`version`, `commit`, `built_at`) and `Me.session.environment` after sign-in; the version label only before (`22-api-openapi.yaml`)
- [x] **Contrast and CVD** — computed by the tool (the pack's §6: P-10); no new colour pair is introduced, so `tools/contrast/pairs.mjs` gains none
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PR 3, on the boards
- [ ] **Sign-off** — the orchestrator's design approval (BQ-34) on PR 1, PR 2 and PR 3

### Table 1 — Variants × States

| Variant        | State              | Penpot variant                                   | Story name         |
| -------------- | ------------------ | ------------------------------------------------ | ------------------ |
| before sign-in | version only       | CMP-207 · BuildFooter / State=PreAuthVersionOnly | PreAuthVersionOnly |
| signed in      | demo               | CMP-207 · BuildFooter / State=SignedInDemo       | SignedInDemo       |
| signed in      | live               | CMP-207 · BuildFooter / State=SignedInLive       | SignedInLive       |
| any            | long version label | CMP-207 · BuildFooter / State=LongVersionLabel   | LongVersionLabel   |

### Table 2 — Keyboard

| Key | Action        | Focus after | Global conflict? | Notes                         |
| --- | ------------- | ----------- | ---------------- | ----------------------------- |
| —   | not focusable | —           | —                | the component has no Tab stop |

### Table 3 — Accessible name / role

| Element    | Role              | Accessible name (source) | States / properties |
| ---------- | ----------------- | ------------------------ | ------------------- |
| `<footer>` | contentinfo       | —                        | plain text          |
| commit     | text (selectable) | —                        | signed in only      |

### Table 4 — Motion pair

| Property | motion-safe   | motion-reduce | Duration / easing tokens |
| -------- | ------------- | ------------- | ------------------------ |
| —        | none animated | —             | —                        |

### Table 5 — Live data

| Field | Politeness | Cadence | Coalescing | Notes  |
| ----- | ---------- | ------- | ---------- | ------ |
| —     | none       | —       | —          | static |

### Density

| Mode        | Row / control height                                                | Padding tokens           | Smallest target                                                      |
| ----------- | ------------------------------------------------------------------- | ------------------------ | -------------------------------------------------------------------- |
| compact     | `size.control.height` (24<!--=TOKEN:size.control.compact--> px)     | the entry's Tokens field | 24<!--=TOKEN:size.target.min--> × 24<!--=TOKEN:size.target.min--> px |
| comfortable | `size.control.height` (32<!--=TOKEN:size.control.comfortable--> px) | the entry's Tokens field | 24<!--=TOKEN:size.target.min--> × 24<!--=TOKEN:size.target.min--> px |

### Essential exceptions

| Exception | Compensating control | Reviewer | Date |
| --------- | -------------------- | -------- | ---- |
| none      | —                    | —        | —    |

## Handoff checklist — CMP-097 OnboardingChecklist (E09-D07, #190)

- [x] **Final Penpot link** — page `E09-D07 auth band` (`e4de416d-a820-8072-8008-e06d290d694c`) of the per-set file `E09-D07 boards` (the PR 3 ruling), page name + page id only: the specimen frames `CMP-097 · OnboardingChecklist / State=…` on board 06, [E09-D07-06-onboarding-checklist.png](img/E09-D07-06-onboarding-checklist.png), and its row on the band boards 08, 09 and 10 (dark, light, high contrast); specimen boards, no library component (BQ-2)
- [x] **Variants × States matrix** — table 1; the stories of the pack's §7 (A-4)
- [x] **Keyboard table** — table 2
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — N/A — static chrome, no streaming value
- [x] **Motion pair** — N/A — none animated (E09-D08 S3 for secrets and factors)
- [x] **Density notes** — the density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — equal to the entry's Tokens field after PR 2 (inherits CMP-066 (`15`:1064, unchanged)); the Penpot sets equal the token JSON under `packages/ui` at `a0132de011`
- [x] **Data contract confirmed** — `OnboardingChecklist` (`22-api-openapi.yaml`): `key`, `state`, `unblock_at`, `action_route`; `reason` never rendered
- [x] **Contrast and CVD** — computed by the tool (the pack's §6: P-13); no new colour pair is introduced, so `tools/contrast/pairs.mjs` gains none
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PR 3, on the boards
- [ ] **Sign-off** — the orchestrator's design approval (BQ-34) on PR 1, PR 2 and PR 3

### Table 1 — Variants × States

| Variant | State                | Penpot variant                                               | Story name             |
| ------- | -------------------- | ------------------------------------------------------------ | ---------------------- |
| steps   | default              | CMP-097 · OnboardingChecklist / State=Default                | Default                |
| steps   | some done            | CMP-097 · OnboardingChecklist / State=PartiallyComplete      | PartiallyComplete      |
| a step  | role-denied (T2)     | CMP-097 · OnboardingChecklist / State=RoleDisabledWithReason | RoleDisabledWithReason |
| a step  | blocked until a time | CMP-097 · OnboardingChecklist / State=BlockedUntil           | BlockedUntil           |
| a step  | error                | CMP-097 · OnboardingChecklist / State=Error                  | Error                  |

### Table 2 — Keyboard

| Key   | Action                       | Focus after            | Global conflict? | Notes                     |
| ----- | ---------------------------- | ---------------------- | ---------------- | ------------------------- |
| Tab   | each step's action, in order | the next step          | none             | a T2 step stays focusable |
| Enter | follows the step's `onGo`    | the step's destination | none             | never on a T2 step        |

### Table 3 — Accessible name / role

| Element | Role                 | Accessible name (source) | States / properties                                                                    |
| ------- | -------------------- | ------------------------ | -------------------------------------------------------------------------------------- |
| list    | list                 | the card title           | —                                                                                      |
| step    | checkbox (read-only) | its label                | `aria-checked`; T2: `aria-disabled` + the reason as visible text by `aria-describedby` |

### Table 4 — Motion pair

| Property | motion-safe   | motion-reduce | Duration / easing tokens |
| -------- | ------------- | ------------- | ------------------------ |
| —        | none animated | —             | —                        |

### Table 5 — Live data

| Field | Politeness | Cadence | Coalescing | Notes  |
| ----- | ---------- | ------- | ---------- | ------ |
| —     | none       | —       | —          | static |

### Density

| Mode        | Row / control height                                                | Padding tokens           | Smallest target                                                      |
| ----------- | ------------------------------------------------------------------- | ------------------------ | -------------------------------------------------------------------- |
| compact     | `size.control.height` (24<!--=TOKEN:size.control.compact--> px)     | the entry's Tokens field | 24<!--=TOKEN:size.target.min--> × 24<!--=TOKEN:size.target.min--> px |
| comfortable | `size.control.height` (32<!--=TOKEN:size.control.comfortable--> px) | the entry's Tokens field | 24<!--=TOKEN:size.target.min--> × 24<!--=TOKEN:size.target.min--> px |

### Essential exceptions

| Exception | Compensating control | Reviewer | Date |
| --------- | -------------------- | -------- | ---- |
| none      | —                    | —        | —    |

## Handoff checklist — CMP-098 SessionTimeoutWarning (E09-D07, #190)

- [x] **Final Penpot link** — page `E09-D07 auth band` (`e4de416d-a820-8072-8008-e06d290d694c`) of the per-set file `E09-D07 boards` (the PR 3 ruling), page name + page id only: the specimen frames `CMP-098 · SessionTimeoutWarning / State=…` on board 07, [E09-D07-07-session-timeout-warning.png](img/E09-D07-07-session-timeout-warning.png), and its row on the band boards 08, 09 and 10 (dark, light, high contrast); specimen boards, no library component (BQ-2)
- [x] **Variants × States matrix** — table 1; the stories of the pack's §7 (A-9)
- [x] **Keyboard table** — table 2
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — table 5
- [x] **Motion pair** — table 4
- [x] **Density notes** — the density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — equal to the entry's Tokens field after PR 2 (inherits CMP-043 (`15`:1076, unchanged)); the Penpot sets equal the token JSON under `packages/ui` at `a0132de011`
- [x] **Data contract confirmed** — `authExtendSession`, `authLock` and `SessionState`'s `idle_deadline` (`22-api-openapi.yaml`)
- [x] **Contrast and CVD** — computed by the tool (the pack's §6: P-11, P-12); no new colour pair is introduced, so `tools/contrast/pairs.mjs` gains none
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** — PR 3, on the boards
- [ ] **Sign-off** — the orchestrator's design approval (BQ-34) on PR 1, PR 2 and PR 3

### Table 1 — Variants × States

| Variant     | State          | Penpot variant                                           | Story name                     |
| ----------- | -------------- | -------------------------------------------------------- | ------------------------------ |
| warning     | 60 s left      | CMP-098 · SessionTimeoutWarning / State=Default          | Default                        |
| warning     | extending      | CMP-098 · SessionTimeoutWarning / State=ExtendInProgress | ExtendInProgress               |
| warning     | with Lock now  | CMP-098 · SessionTimeoutWarning / State=WithLockNow      | WithLockNow                    |
| admin token | before its end | CMP-098 · SessionTimeoutWarning / State=AdminToken       | AdminToken (held, E09-D10 F-5) |

### Table 2 — Keyboard

| Key             | Action                                                   | Focus after                                              | Global conflict?        | Notes                   |
| --------------- | -------------------------------------------------------- | -------------------------------------------------------- | ----------------------- | ----------------------- |
| Tab / Shift+Tab | cycles "Stay signed in" and "Lock now" inside the dialog | the other action                                         | none                    | focus trapped (CMP-043) |
| Enter / Space   | activates the focused action                             | busy on "Stay signed in"; the lock card after "Lock now" | none                    | explicit server calls   |
| Esc             | dismisses; extends nothing                               | back to the page                                         | Esc untouched (05 §3.3) | never an extend         |

### Table 3 — Accessible name / role

| Element        | Role        | Accessible name (source) | States / properties                          |
| -------------- | ----------- | ------------------------ | -------------------------------------------- |
| dialog         | alertdialog | its visible heading      | `aria-modal`; announced once on arrival      |
| countdown      | text        | —                        | `aria-live="off"`                            |
| Stay signed in | button      | the visible label        | `aria-disabled`, focusable while `extending` |
| Lock now       | button      | the visible label        | rendered only with `authLock` wired          |

### Table 4 — Motion pair

| Property | motion-safe                                        | motion-reduce | Duration / easing tokens                       |
| -------- | -------------------------------------------------- | ------------- | ---------------------------------------------- |
| scrim    | fades over `motion.duration.normal` (`standard`)   | instant       | motion.duration.normal, motion.easing.standard |
| card     | a cut at frame 0; exits over `fast` (`accelerate`) | instant       | motion.duration.fast, motion.easing.accelerate |

### Table 5 — Live data

| Field     | Politeness               | Cadence                   | Coalescing       | Notes                                    |
| --------- | ------------------------ | ------------------------- | ---------------- | ---------------------------------------- |
| countdown | none (`aria-live="off"`) | 1 per second, visual only | the latest value | the warning is announced once on arrival |

### Density

| Mode        | Row / control height                                                | Padding tokens           | Smallest target                                                      |
| ----------- | ------------------------------------------------------------------- | ------------------------ | -------------------------------------------------------------------- |
| compact     | `size.control.height` (24<!--=TOKEN:size.control.compact--> px)     | the entry's Tokens field | 24<!--=TOKEN:size.target.min--> × 24<!--=TOKEN:size.target.min--> px |
| comfortable | `size.control.height` (32<!--=TOKEN:size.control.comfortable--> px) | the entry's Tokens field | 24<!--=TOKEN:size.target.min--> × 24<!--=TOKEN:size.target.min--> px |

### Essential exceptions

| Exception | Compensating control | Reviewer | Date |
| --------- | -------------------- | -------- | ---- |
| none      | —                    | —        | —    |
