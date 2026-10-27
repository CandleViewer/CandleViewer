# E27-D03 — Per-component handoff checklist (`16` §11.4; the contracts the accounts and key-vault hi-fi changes)

Three checklists for the contributions (CMP-175 KeyPermissionBadge, CMP-176 AccountKeyRow, CMP-034 MaskedValue) with
every line of the `16` §11.4 block kept; one delta row per extended entry (CMP-028, CMP-035, CMP-044, CMP-066,
CMP-178, CMP-201, CMP-203, CMP-011 and CMP-033); Tables 1–5, the Density table and the Essential-exceptions table once
each with a leading `Component` column; the Storybook story lists with their cells; then §A, the `16` §12 design-QA
checklist, and §B, the `05` §10 template, for the eight screens. **E27-D06 (#819) embeds this file by reference**
(BQ-14, RULED: written now, beside the spec, because `16` §11.4 ties it to the contract change). Every number below is
`docs/design/_tools/e27_d03_hifi_audit.py`'s (spec §9). The boards are PENDING: the Penpot page is
`E27-D03 Accounts and key vault hi-fi`, named in spec §0 and referenced by name only until the boards step records its
id. Fixture values only; no key material, secret, real UID or real address appears anywhere. A `[~]` line (met in
text, its board or library half pending) and a `[ ] PENDING` line are open until the boards PR, and none may remain
at Done: `16` §11.4's grammar is `[x]` with its evidence or `[ ] N/A — <reason>`.

## Handoff checklist — CMP-175 KeyPermissionBadge (E27-D03, #816)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING: page `E27-D03 Accounts and key vault hi-fi` (spec §0), boards 01 and 02 (its
      light twin); exports `docs/design/E27/img/E27-D03-01-cmp-175-key-states.png` and
      `docs/design/E27/img/E27-D03-02-cmp-175-key-states-light.png` with their greyscale, deuteranopia and protanopia
      renders, all in the boards PR; no board exists yet
- [x] **Variants × States matrix** — thirteen states in the `key` scope (`badge` and `inline` forms) and the
      `aggregate` line's eight forms, each with its served source, class, glyph and word (spec §2.1); Table 1
- [x] **Keyboard table** — none of its own: static text, never focusable; the row's actions are CMP-176's (spec
      §2.1); Table 2
- [x] **Accessible name / role table** — the word is the text, the glyph `aria-hidden` beside it, the host's table
      cell naming the facet; the critical word leads with "BLOCKED" (spec §2.1); Table 3
- [x] **Live data** — no live region of its own: the host's shell announcer speaks a key's failure once, assertive,
      and a recovery polite; the aggregate line's negated forms stay silent while CMP-092's blocking row speaks
      (`15:935`; spec D03-C9); Table 5
- [x] **Motion pair** — none animated: a state changes by an instant token swap; any motion is E27-D04's (spec
      D03-H1); Table 4
- [x] **Density notes** — the badge 24 px (`size.control.compact`) or 32 px (`size.control.comfortable`), padding
      `space.inset.sm` or `space.inset.md`; type never changes with density (spec §2.1); Density table
- [x] **Essential-exceptions log** — none: static text has no target
- [x] **Tokens used** — fills `color.status.success.subtle`, `color.status.danger.subtle`,
      `color.status.warning.subtle`, `color.status.info.subtle`, `color.neutral.subtle`; words `color.text.primary`,
      the critical one `font.weight.bold`; glyphs `color.status.success.strong`, `color.status.danger.strong`,
      `color.status.warning.strong`, `color.status.info.strong`, `color.text.secondary`; the critical border
      `border.thick` in `color.status.danger.strong`; `size.icon`, `space.inset.xs`, `type.ui.caption`,
      `type.ui.body`, `radius.badge`; Penpot token sets = `packages/ui/tokens` at `e8bca4bb7` (spec §2.1, §9)
- [x] **Data contract confirmed** — `KeyVerification` (`withdraw_enabled`, sent only once the rights were read),
      `KeyVerificationNotRead`, `ApiKey` (`read_only`, `expires_at`, `last_verified_at`), the security summary's
      `keys[]` (`withdrawal_permission_present`, `ip_whitelist_matches_expected`) and the `system` read-only notices
      for the aggregate forms (spec §2.1); gaps: G-1 (per-row attribution, #895 / #896), G-2 (the verdict's time) and
      D03-G1 (the egress IP before a check, #896)
- [ ] **Contrast and CVD** — open on the `pairs.mjs` owner: 0 gated FAIL in spec §9, where `c175-pass-word`,
      `c175-pass-glyph`, `c175-danger-glyph`, `c175-critical-border`, `c175-unknown-word`, `c175-unknown-glyph` and
      `c175-info-glyph` are PROPOSED rows waiting for registration (spec D03-H7); ΔE76 and luma are reported (spec §9);
      the renders of boards 01 and 02 come with the boards PR
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A
      and B below
- [ ] **Sign-off** — owner approval pending (the owner's `approved` comment on #816, or the merged spec PR)

## Handoff checklist — CMP-176 AccountKeyRow (E27-D03, #816)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING: page `E27-D03 Accounts and key vault hi-fi`, boards 03 (the rows, blocked,
      both disabled forms, the 200 % card) and 04 with its light twin 05 (SCR-125's records); exports
      `docs/design/E27/img/E27-D03-03-components-and-looks.png`,
      `docs/design/E27/img/E27-D03-04-scr-125-128-accounts.png` and
      `docs/design/E27/img/E27-D03-05-scr-125-128-accounts-light.png`, in the boards PR
- [x] **Variants × States matrix** — the state slot's sixteen states in their precedence, the blocked danger
      treatment, the two disabled forms at full text contrast, the menu and the details disclosure, the 200 % card
      (spec §2.2, §3.2); Table 1
- [x] **Keyboard table** — Tab: [Start the compromise response] (blocked only) → Actions → Details; the menu on
      `Enter`, `Space` or `↓`; `Esc` back to its button; a plain table, never a grid (spec §2.2, §3.1; D22); Table 2
- [x] **Accessible name / role table** — two `tr` lines, the label cell `th scope="row"` with `rowspan="2"`; the
      buttons named "Actions for {label} · {ENV}" and "Details for {label} · {ENV}"; a gated item `aria-disabled` with
      its reason by `aria-describedby` (spec §2.2); Table 3
- [x] **Live data** — the row holds no live region; a state's transition goes once through the shell announcer, a
      failure assertive and a recovery polite, never on the 60 s refresh (D21; spec §3.6); Table 5
- [x] **Motion pair** — none animated: the details row and the menu open instantly; any motion is E27-D04's (spec
      D03-H1); Table 4
- [x] **Density notes** — lines 24 px (`size.row.compact`) or 32 px (`size.row.comfortable`), controls 24 px or
      32 px; SCR-125 draws comfortable, compact is the 125 % specimen; one card per account at 200 % (spec §2.2);
      Density table
- [x] **Essential-exceptions log** — none: every control reaches 24 × 24 px in compact and 32 × 32 px in comfortable
- [x] **Tokens used** — the row `color.surface.raised`, hover `color.surface.hover`; line 1 `color.text.primary`,
      line 2 and the notice `color.text.secondary`; the label `type.ui.body-strong`, numbers `type.num.base`; blocked
      `color.status.danger.subtle` with a 4 px `color.status.danger.strong` inline-start rule; rows apart
      `border.hairline` in `color.border.default`; focus `color.focus.ring` with `border.focus`; the environment badge
      `color.env.live` or `color.env.demo`; details links `color.text.link`; Penpot token sets = `packages/ui/tokens`
      at `e8bca4bb7` (spec §2.2, §9)
- [x] **Data contract confirmed** — `listExchangeAccounts` (`AdminAccountRow`: label, UID, environment, kind,
      `key_status`, `health`, `enabled`), `listApiKeys` (the key's metadata), `getSecuritySummary`'s `keys[]` for the
      facets and `AccountHealth` (spec §3.3); gaps: G-1 (per-row attribution, #895 / #896), D03-G2 (the off-by-policy
      state, #895) and G-12 (the re-arm, #3657)
- [ ] **Contrast and CVD** — open on the `pairs.mjs` owner: 0 gated FAIL in spec §9, where `row-link`, `row-hover`,
      `row-hover-secondary`, `row-pass-glyph`, `row-warning-glyph` and `blocked-secondary` are PROPOSED rows (spec
      D03-H7); the blocked row's rule against the row, `c175-critical-border`, is 9.32 / 4.11 / 9.32
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A
      and B below
- [ ] **Sign-off** — owner approval pending (the owner's `approved` comment on #816, or the merged spec PR)

## Handoff checklist — CMP-034 MaskedValue (E27-D03, #816)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — PENDING: page `E27-D03 Accounts and key vault hi-fi`, board 01 (the masked id beside
      CMP-175's set) and every screen board that names a key; exports in the boards PR
- [x] **Variants × States matrix** — one state, masked, in four hosts (a row, a dialog, a table cell, with its
      description) and forced colours; no reveal, timer or copy state exists (BQ-8, RULED; spec §2.3); Table 1
- [x] **Keyboard table** — none: not focusable, no control (spec §2.3); Table 2
- [x] **Accessible name / role table** — `role="group"` named by `label`; the `...` behind a visually hidden "ending
      in", so it reads "API key, ending in a1b2"; the write-only description, one node per page in the DOM at
      mount, named by every instance's `aria-describedby` (spec §2.3); Table 3
- [x] **Live data** — N/A in effect: static text, no live region (spec §2.3); Table 5
- [x] **Motion pair** — none animated (spec §2.3); Table 4
- [x] **Density notes** — none of its own: text in its host's line, alike in both modes (`16:125`)
- [x] **Essential-exceptions log** — none: no target
- [x] **Tokens used** — `type.num.base` in `color.text.primary` on its host's surface (`row-text` on a row,
      `dialog-text` in a dialog or the drawer); no box, so no fill, border or radius; Penpot token sets =
      `packages/ui/tokens` at `e8bca4bb7` (spec §2.3, §9)
- [x] **Data contract confirmed** — `ApiKey.key_id_masked`, `...` plus 4 characters, the rest never stored in clear;
      any other value renders nothing (spec §2.3; `22:16879-16882`); the masked id is the only key value any response
      carries (C-2.7, C-12.2)
- [x] **Contrast and CVD** — its two pairs are registered: `row-text` 14.35 / 15.62 / 16.25 and `dialog-text`
      13.27 / 14.37 / 15.02 (spec §9); it carries no colour state
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A
      and B below
- [ ] **Sign-off** — owner approval pending; the supersession of E05-D02's time-limited display stays the owner's
      (spec D03-C4, D03-A3), and no board draws a reveal meanwhile

## The extended entries — one delta row each

Each entry gains a variant or props, never a sibling component (spec §2.4, §2.5); the exact `15` edits are spec
Appendix A's copy-ready A-rows (D03-A1). CMP-044's and CMP-178's props are E42-D03's and CMP-066's statuses E42-D05's,
consumed by name with a "contract pending" stamp until they land (BQ-11, BQ-12, BQ-13).

| Entry                          | What changes (spec §)                                                                                                                        | Keyboard                                                                                                                                                                                | Name / role                                                                                  | Live data                                                                                                    | Motion                                  | Density                                              | Tokens                                                                                                                                                                                         | Stories                                                                                                                                                                |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | --------------------------------------- | ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CMP-028 Callout / Banner       | `blocking` (danger only): never dismissible, no live role, a stable `id` every blocked control's `aria-describedby` names (§2.4; BQ-9)       | none: no control                                                                                                                                                                        | static text in page order; its first sentence the reason node                                | none: CMP-092's blocking row is the one announcement (`15:935`)                                              | none                                    | `space.inset.sm` or `space.inset.md`                 | the danger subtle fill, `color.text.primary`, the octagon and a 2 px `border.thick` border in `color.status.danger.strong`                                                                     | DangerBlocking, DangerBlockingWithPointers, DangerBlockingForcedColors                                                                                                 |
| CMP-035 Countdown / Timer text | `showUntil`, `serverOffsetMs`, `announceAt`, `warnBelowS` (`null`); the served `overlap_until` first (§2.4; BQ-10)                           | none                                                                                                                                                                                    | text inside its sentence                                                                     | `aria-live="off"`; polite at 60 s and 10 s with the absolute time; the end on the server's state, never at 0 | none: no colour change at any threshold | alike in both                                        | `type.num.base`; the absolute time `color.text.primary`, the time left `color.text.secondary`                                                                                                  | RotationOverlap, OverlapAt60s, OverlapAt10s, OverlapAtZero, ServerCorrected                                                                                            |
| CMP-044 ConfirmDialog          | E42-D03's `rung`, `blastRadius`, `choices`, `stepUpState`, `auditCodes` by name; `consequenceState`, `environment` (§2.4; BQ-11)             | Cancel first and initially focused; E42-D03's DOM order; `Enter` in the typed field never confirms; a confirm in its validity form moves focus to the first unmet input; `Esc` = Cancel | `role="alertdialog"` described by its first consequence                                      | the summary's first sentence polite once; an exchange error `role="alert"` once                              | E27-D04's                               | 32 px controls (comfortable), 24 px (compact)        | `color.surface.overlay`, `elevation.dialog`; the confirm `color.text.primary` on `color.status.danger.subtle` with a 1 px `color.status.danger.strong` border                                  | ConsequencesLoading, ConsequencesLoadingSlow, EnvironmentSuffix, TypedLabelEnterNeverConfirms, ConfirmValidityHint, TwoChoicesNoneSelected, GatedChoice, ExchangeError |
| CMP-066 Stepper                | E42-D05's `status` set by name; `meta` (real elapsed time), `as` (`list` or `nav`), `collapsed` (§2.4; BQ-12)                                | focus moves to the stage heading on each change                                                                                                                                         | an `<ol>`, or the same list in a labelled `<nav>`; `aria-current="step"`; each status a word | `meta` is never live                                                                                         | E27-D04's, under reduced motion         | markers 24 px in both                                | done `color.status.success.strong`; `error` `color.status.danger.strong`; current `color.action.primary.default` with `color.text.on-action`                                                   | Nav, NavSixSteps, RotationStages, RotationRefused, Collapsed                                                                                                           |
| CMP-178 SystemHealthTile       | `variant: "inline"` with one `AccountHealth`; E42-D03's tile props by name (§2.4; BQ-13)                                                     | none                                                                                                                                                                                    | plain text in its cell: no region, heading or link                                           | none of its own: the shell announcer, once per transition                                                    | none                                    | alike in both                                        | the word `color.text.primary`, the age `color.text.secondary`, the glyph in its tone's strong token                                                                                            | InlineHealthy, InlineDegraded, InlineDown, InlineNeverConnected, InlineInRow, InlineInDrawer                                                                           |
| CMP-201 PasswordField          | `writeOnly`: no toggle, `autoComplete` `"off"`, cleared on leave and on the idle lock, paste allowed; E05-D02's S4–S7 move here (§2.3; BQ-8) | as CMP-007; paste never blocked                                                                                                                                                         | its label; the write-only sentence by `aria-describedby` at mount                            | the caps-lock warning, polite                                                                                | none                                    | `size.control.compact` or `size.control.comfortable` | CMP-007's well, `color.surface.app` with a 1 px `color.text.tertiary` boundary                                                                                                                 | WriteOnlyKey, WriteOnlySecret, WriteOnlyFormatError, WriteOnlyReadOnlyWhileVerifying, WriteOnlyClearedAfterRefusal, WriteOnlyPaste                                     |
| CMP-203 RequirementChecklist   | `checks` with three outcomes and a `detail` line, a pass that carries a served warning on the triangle (HD17); `live` (§2.5)                 | none: no control                                                                                                                                                                        | a list, each row "{check}: {outcome}" in words, the glyph `aria-hidden`                      | `live={false}` for the key gate: its host announces the verdict once                                         | none: the rows arrive with the answer   | alike in both                                        | passed `color.status.success.strong`, passed with a warning `color.status.warning.strong`, failed `color.status.danger.strong`, not checked `color.text.secondary`, words `color.text.primary` | KeyGateAllPassed, KeyGateRefusedRightsNotRead, KeyGateMixed, KeyGatePassedWithWarnings, KeyGateNotLive                                                                 |
| CMP-011 Tag / Chip             | `timeBased` (the clock on the warning tone); "OK" neutral with the check (§2.5; BQ-7)                                                        | none                                                                                                                                                                                    | its word                                                                                     | none                                                                                                         | none                                    | as CMP-011                                           | as CMP-011                                                                                                                                                                                     | TimeBasedWarning, AccountStates                                                                                                                                        |
| CMP-033 CopyButton             | the egress IP as the key screens' only copy, never a key id, UID or secret (§2.3)                                                            | as CMP-033                                                                                                                                                                              | "Copy"                                                                                       | "Copied", polite, its own                                                                                    | none                                    | 32 px on the comfortable screens                     | as CMP-033                                                                                                                                                                                     | EgressIp                                                                                                                                                               |

### Table 1 — Variants × States

| Component | Variant                | State (each a named frame on the boards and a story)                                                                                                                                                                                                                                                                                       | Penpot variant (planned)                                        | Story (planned)                   | Notes                                                       |
| --------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------- | --------------------------------- | ----------------------------------------------------------- |
| CMP-175   | `key` · `badge`        | verified, trade-only, read-only (stored), withdrawal-detected (critical), IP-missing, IP-mismatch, expiring, expired, not checked, check overdue, allowlist matches, allowlist not checked; read-only at import is the check list's failed row                                                                                             | `CMP-175 · KeyPermissionBadge / Scope=key, Form=badge, State=…` | `Atoms/KeyPermissionBadge/*`      | spec §2.1; the critical state is always the badge           |
| CMP-175   | `key` · `inline`       | the same states on the host's surface, the critical one excepted: `detected` stays a badge, also in SCR-079's statement list                                                                                                                                                                                                               | `… / Scope=key, Form=inline, State=…`                           | InlineForm                        | CMP-176's facet cells, SCR-128's table, SCR-079's key block |
| CMP-175   | `aggregate`            | dated, overdue, failed, unavailable, read failed, no keys, loading, cleared                                                                                                                                                                                                                                                                | `… / Scope=aggregate, Verdict=…`                                | AggregateDated … AggregateLoading | the verdict line under SCR-125's `h1`; never dismissible    |
| CMP-176   | the record             | OK, rotating, revoked, blocked, key refused, expired at Bybit, allowlist no match, allowlist none set, down, off by policy, check overdue, not checked, rotation overdue, degraded, rotation due, Bybit expiry, no key, disabled; KEK unavailable; menu open, details open, hover, focus-visible; 200 % card, 150 % text, compact at 125 % | `CMP-176 · AccountKeyRow / State=…`                             | `Molecules/AccountKeyRow/*`       | spec §2.2; one badge, the worst that applies                |
| CMP-034   | masked, its only state | on a row, in a dialog, in a table cell, with its description; a non-masked value renders nothing; forced colours                                                                                                                                                                                                                           | `CMP-034 · MaskedValue / Host=…`                                | `Atoms/MaskedValue/*`             | spec §2.3; no reveal, timer or copy exists                  |

### Table 2 — Keyboard

| Component | Key                                   | Action                                                                                                     | Focus after                                              | Global conflict? (`05` §3.2 / §3.3) | Notes                                                        |
| --------- | ------------------------------------- | ---------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- | ----------------------------------- | ------------------------------------------------------------ |
| CMP-175   | —                                     | none: static text                                                                                          | —                                                        | none                                | the row's actions carry the keys                             |
| CMP-176   | `Tab`                                 | [Start the compromise response] (blocked only) → Actions for {label} · {ENV} → Details for {label} · {ENV} | the next stop                                            | none                                | a plain table: no grid, no roving tabindex (D22)             |
| CMP-176   | `Enter`, `Space` or `↓` on Actions    | opens the menu                                                                                             | its first item                                           | none                                | CMP-041                                                      |
| CMP-176   | `↑` / `↓`, `Enter`, `Esc` in the menu | move (a T2 item is reachable), pick, close                                                                 | the picked item's dialog; after `Esc` the Actions button | none                                | `Enter` on a T2 item re-shows its reason once (E09-D09 §9.3) |
| CMP-176   | `Enter` or `Space` on Details         | toggles the details row (`aria-expanded`)                                                                  | stays                                                    | none                                | —                                                            |
| CMP-034   | —                                     | none: not focusable                                                                                        | —                                                        | none                                | —                                                            |

### Table 3 — Accessible name / role

| Component | Element                                           | Role                        | Accessible name (source)                                                                 | States / properties                                                                                      |
| --------- | ------------------------------------------------- | --------------------------- | ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| CMP-175   | a badge or an inline word                         | text                        | its word, e.g. "BLOCKED — fund right found"                                              | the glyph `aria-hidden`; no live region                                                                  |
| CMP-175   | the aggregate line                                | text under the `h1`         | its sentence, e.g. "Withdrawal: OFF on all 4 accounts with a key ✓ · verified 14:02 UTC" | the ✓ `aria-hidden`; never dismissible                                                                   |
| CMP-176   | the record                                        | two `tr` in a plain `table` | the label cell, `th scope="row"` with `rowspan="2"`: "Main · 1234567 · LIVE"             | the details `tr` hidden until Details (`aria-controls`)                                                  |
| CMP-176   | Actions · Details · Start the compromise response | button                      | "Actions for {label} · {ENV}" · "Details for {label} · {ENV}" · its text                 | `aria-haspopup="menu"`; `aria-expanded`; a T2 item `aria-disabled` with its reason by `aria-describedby` |
| CMP-034   | the masked id                                     | `group` named by `label`    | "API key, ending in a1b2"                                                                | `aria-describedby` → the page's one write-only description node, in the DOM at mount; not focusable      |

### Table 4 — Motion pair

| Component | Property                  | motion-safe        | motion-reduce | Duration / easing tokens                                         |
| --------- | ------------------------- | ------------------ | ------------- | ---------------------------------------------------------------- |
| CMP-175   | a state change            | instant token swap | identical     | `motion.duration.instant`                                        |
| CMP-176   | the details row, the menu | instant            | identical     | `motion.duration.instant`; any motion is E27-D04's (spec D03-H1) |
| CMP-034   | none animated             | —                  | —             | —                                                                |

### Table 5 — Live data

| Component | Field                                          | Politeness                              | Cadence             | Coalescing | Notes                                     |
| --------- | ---------------------------------------------- | --------------------------------------- | ------------------- | ---------- | ----------------------------------------- |
| CMP-175   | a key's state turning failed, critical or down | assertive, through the shell announcer  | once per transition | —          | never on a refresh (D21)                  |
| CMP-175   | a recovery                                     | polite                                  | once                | —          | —                                         |
| CMP-175   | the aggregate line's negated forms             | none: CMP-092's blocking row speaks     | —                   | —          | spec D03-C9; the cleared form polite once |
| CMP-176   | its state                                      | through the shell announcer, as CMP-175 | once per transition | —          | the row holds no live region              |
| CMP-034   | none                                           | —                                       | —                   | —          | static                                    |

### Density

| Component | Mode                  | Row / control height                                 | Padding tokens                                  | Smallest target |
| --------- | --------------------- | ---------------------------------------------------- | ----------------------------------------------- | --------------- |
| CMP-175   | compact               | 24 px (`size.control.compact`)                       | `space.inset.sm`                                | none: static    |
| CMP-175   | comfortable           | 32 px (`size.control.comfortable`)                   | `space.inset.md`                                | none: static    |
| CMP-176   | compact               | lines 24 px (`size.row.compact`), controls 24 px     | `space.inset.sm` inline, `space.inset.xs` block | 24 × 24 px      |
| CMP-176   | comfortable (SCR-125) | lines 32 px (`size.row.comfortable`), controls 32 px | `space.inset.md` inline, `space.inset.xs` block | 32 × 32 px      |
| CMP-034   | both                  | text in its host's line                              | none                                            | none: static    |

### Essential exceptions

| Component | Exception | Compensating control | Reviewer | Date |
| --------- | --------- | -------------------- | -------- | ---- |
| all three | none      | —                    | —        | —    |

## Storybook stories × themes × densities

Every story runs in six cells — dark, light and high contrast × compact and comfortable — with axe at zero serious or
critical findings and its keyboard path as an interaction test (spec §13; `15:38`, `15:41`); the PROPOSED stamps and
the "not yet served" strips are board annotations, never a story.

| Component             | Stories (spec §13)                                                                                                                                                                                                                                                                                                                                                                                                                                                             | Stories | Cells                                                              |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------- | ------------------------------------------------------------------ |
| CMP-175               | Default · WithdrawalVerified · WithdrawalDetected · WithdrawalNotChecked · WithdrawalCheckOverdue · RightsTrade · RightsMissingScopes · RightsReadOnly · AllowlistMatches · AllowlistNoneSet · AllowlistNoMatch · AllowlistNotChecked · ExpiryExpiring · ExpiryExpired · InlineForm · AggregateDated · AggregateOverdue · AggregateFailed · AggregateUnavailable · AggregateReadFailed · AggregateNoKeys · AggregateLoading · VariantSet · MissingStateNeverOff · ForcedColors | 25      | 150, and VariantSet also in greyscale, deuteranopia and protanopia |
| CMP-176               | Default · RotatingKey · Revoked · Blocked · KeyRefused · ExpiredAtBybit · AllowlistNoMatch · AllowlistNoneSet · Down · OffByPolicy · CheckOverdue · NotChecked · RotationOverdue · Degraded · RotationDue · BybitExpiry · NoKey · Disabled · KekUnavailable · MenuOpen · DetailsOpen · Hover · FocusVisible · Reflow200 · TextScale150 · CompactAt125                                                                                                                          | 26      | 156                                                                |
| CMP-034               | Default · InDialog · InTableCell · WithDescription · NonMaskedValueRendersNothing · ForcedColors                                                                                                                                                                                                                                                                                                                                                                               | 6       | 36                                                                 |
| CMP-201 (`writeOnly`) | WriteOnlyKey · WriteOnlySecret · WriteOnlyFormatError · WriteOnlyReadOnlyWhileVerifying · WriteOnlyClearedAfterRefusal · WriteOnlyPaste                                                                                                                                                                                                                                                                                                                                        | 6       | 36                                                                 |
| CMP-028               | DangerBlocking · DangerBlockingWithPointers · DangerBlockingForcedColors                                                                                                                                                                                                                                                                                                                                                                                                       | 3       | 18                                                                 |
| CMP-035               | RotationOverlap · OverlapAt60s · OverlapAt10s · OverlapAtZero · ServerCorrected                                                                                                                                                                                                                                                                                                                                                                                                | 5       | 30                                                                 |
| CMP-044               | ConsequencesLoading · ConsequencesLoadingSlow · EnvironmentSuffix · TypedLabelEnterNeverConfirms · ConfirmValidityHint · TwoChoicesNoneSelected · GatedChoice · ExchangeError                                                                                                                                                                                                                                                                                                  | 8       | 48, and E42-D03's rung stories once they land                      |
| CMP-066               | Nav · NavSixSteps · RotationStages · RotationRefused · Collapsed                                                                                                                                                                                                                                                                                                                                                                                                               | 5       | 30                                                                 |
| CMP-178               | InlineHealthy · InlineDegraded · InlineDown · InlineNeverConnected · InlineInRow · InlineInDrawer                                                                                                                                                                                                                                                                                                                                                                              | 6       | 36, and E42-D03's tile stories once they land                      |
| CMP-011               | TimeBasedWarning · AccountStates                                                                                                                                                                                                                                                                                                                                                                                                                                               | 2       | 12                                                                 |
| CMP-203               | KeyGateAllPassed · KeyGateRefusedRightsNotRead · KeyGateMixed · KeyGatePassedWithWarnings · KeyGateNotLive                                                                                                                                                                                                                                                                                                                                                                     | 5       | 30                                                                 |
| CMP-033               | EgressIp                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | 1       | 6                                                                  |
| all                   | —                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | 98      | 588                                                                |

## A. Design QA checklist (`16` §12) — SCR-125..129, SCR-079, SCR-016 step 3 and SCR-019

- [x] Only published Tier-2 and Tier-3 tokens: the spec binds names, never a hex; every unpublished name is marked —
      DS-3's alias bound to `color.text.tertiary` until it lands, CMP-015's skeleton name (spec D03-C12) and `15`'s
      non-token names, each replaced by an A-row (spec §9, Appendix A).
- [~] Verified in all three themes at both densities — the matrix is computed in dark, light and high contrast (spec
  §9); the boards draw dark with two light twins (spec §0); every story runs in six cells (above); the visual
  parity check runs on the drawn boards in the boards PR.
- [x] Passes the contrast matrix for every pair introduced or touched — 57 gated rows, 0 FAIL, 29 registered and 28
      PROPOSED for `tools/contrast/pairs.mjs` (spec D03-H7); the rejected looks are reported and never drawn.
- [~] CVD simulation reviewed — ΔE76 under protanopia, deuteranopia and tritanopia, and Rec. 601 luma, for every
  CMP-175 class (spec §9); the greyscale, deuteranopia and protanopia renders of boards 01 and 02 come with the
  boards PR (BQ-16).
- [~] Every documented State has a Penpot variant and a story — named (Table 1; spec §13) and drawn as named frames
  on the boards; the library variants and the stories are the implementing stories' (E27-S01..S05).
- [x] Disabled states use the disabled-with-reason pattern (CMP-079) — the one rule, view-as first (spec §10.1), with
      ten PROPOSED E27 reason keys (spec §12.2); busy, outcome, availability, the validity look, T4, T1 and T3 stay
      apart (spec §10.3).
- [x] Loading, empty and error states designed — SCR-125's loading, error and empty frames (7, 8), SCR-126's
      validating state (20), SCR-127's stage 3 (35), SCR-129's consequence loading (53), every refusal and no-verdict
      frame (22–28, 32, 36, 37, 56, 57).
- [x] Keyboard-interaction table completed (spec §11; Table 2) — a design table, to be matched by the stories' tested
      paths.
- [x] Accessible-name and role table completed (spec §11; Table 3).
- [x] No canvas or WebGL-adjacent component: every E27 surface is DOM — tables, lists, dialogs and a drawer.
- [x] Motion-safe and motion-reduce pair specified — nothing in this spec animates; the motion is E27-D04's (spec
      D03-H1); Table 4.
- [x] Hit targets ≥ 24 px everywhere (`16:126-127`): 32 px controls on the comfortable admin screens, 24 px in
      SCR-079's compact drawer and 32 px in its comfortable inset; no essential exception.
- [ ] Accessibility role sign-off — the owner's `approved` comment, pending; E27-D05 (#818) reviews the built screens
      (spec D03-H2).
- [x] Confirm-gate variant stated — revoke rung 1 with the `keys` step-up, or rung 3 with the typed label for an
      account's last active key; disable and delete rung 3 with the typed label, their step-up class stamped
      "not yet served — G-8, #895 / #898"; rotate rung 1 with the `keys` step-up; each keyboard path in spec §7, §11.
- [x] Every heuristic or estimated value is chip-tagged — E27 shows none; a stale balance is CMP-239's chip with its
      time (frame 66).
- [x] Demo and Live context unambiguous — the environment word, its weight and the dot's shape on every record, in
      every dialog title and in every name that leaves its group (spec §3.5); the TopBar badges (CMP-074).
- [x] Reuses an existing CMP-\* — every element on an existing entry, an extension or a documented composition (spec
      §2.5); no new id is requested.
- [~] Storybook stories match the Variants × States matrix — planned (Table 1; spec §13); none exists yet.
- [~] Composes only published-library components — the boards draw catalogued components (spec §0); not yet
  checked against the published library.

## B. Accessibility acceptance criteria (`05` §10) — SCR-125..129, SCR-079, SCR-016 step 3 and SCR-019

```gherkin
Feature: E27-D03 accounts and key vault — accessibility acceptance criteria

  Scenario: Keyboard-only operation
    Given the user has not used a pointing device
    When the Owner adds a key on SCR-126, rotates it on SCR-127 and revokes it on SCR-129
      using only the keyboard
    Then every control involved is reachable via Tab/arrow-key navigation (SCR-125's records
      are a plain table whose buttons are Tab stops; a menu moves with the arrows and lands on
      a T2 item without activating it; a rung dialog opens on Cancel)
    And every action has a documented non-drag keyboard equivalent (none drags)
    And focus is never silently moved by the 60 s refresh, a health transition or the
      overlap countdown
    And a visible focus indicator meeting >=3:1 contrast is present at every step (CMP-039's
      ring, 2 px at a 2 px offset: at least 4.57:1 on every E27 surface and fill, spec §9)

  Scenario: Screen-reader operation
    Given the user is using NVDA with the keyboard
    When the Owner reads SCR-125 and tests a key
    Then all labels, roles, and current values are announced correctly ("Main · 1234567 ·
      LIVE" as the row header, "Withdrawal OFF ✓ · verified 14:02 UTC" as words, "API key,
      ending in a1b2" with its write-only description)
    And live/streaming data is announced per the polite/assertive rules in
      05-accessibility-standard.md §6.2, without flooding (a failed key assertive once through
      CMP-092's row; a recovery polite; the countdown at 60 s and 10 s only; nothing per refresh)
    And any canvas-rendered data involved has a working DOM-mirror and/or
      "View as table" equivalent with full data parity (none: every E27 surface is DOM)

  Scenario: Colour-independence
    Given the feature displays status state
    When a CMP-175, CMP-011 or CMP-178 state is rendered
    Then the state is also conveyed via shape/icon and text, not colour alone (a word of its
      own, its class's glyph, and BLOCKED's bold word and 2 px border)
    And the feature passes deuteranopia/protanopia/tritanopia simulation review (ΔE76 per
      class in spec §9; the board renders of boards 01 and 02 come with the boards PR)

  Scenario: Contrast
    Given the feature is rendered in the default dark theme and the
      high-contrast theme
    Then all text meets >=4.5:1 (or >=3:1 for large text) and all meaningful
      non-text UI/chart elements meet >=3:1, per the token contrast matrix (spec §9: 57 gated
      rows PASS in dark, light and high contrast)

  Scenario: Reduced motion
    Given the user has prefers-reduced-motion enabled (OS or in-app override)
    When the feature would normally animate
    Then the feature uses the motion-reduce variant with no flashing content
      exceeding 3 times per second and no motion lasting >5s without a pause
      control (skeletons static; the validating state text only; motion is E27-D04's)

  Scenario: T2 press
    Given a T2 control (Rotate key… while the KEK is unavailable, the leave-positions radio
      while a position has no stop-loss, Change leverage… while viewing as another user)
    When Enter, Space or an arrow lands on it
    Then nothing is sent or opened
    And the reason is re-shown at the point of action and announced once, politely

  Scenario: Automated gates
    Given the feature's PR is opened
    Then axe-core reports zero new serious/critical violations
    And the affected screen's Lighthouse Accessibility score remains >= 95
    And the keyboard-only E2E smoke test covering this feature's primary
      task passes
```

Screen-reader spot test: deferred to E27-D05 (#818) and the release-level pass (`05` §8) — stated. Owner-approved
exceptions: none; the step-up's time limit is SCR-006's (E09-D06).
