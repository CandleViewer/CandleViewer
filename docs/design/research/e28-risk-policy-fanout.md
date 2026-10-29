# E28-D01 — UX research: how the owner sets risk policy per account and thinks about fan-out

- **Ticket:** E28-D01 (issue #820) · **Status:** In Review, text-first — the research boards are PENDING (§1) and land
  with their exports in a second PR that closes #820 · **Owner approval pending** (agent-delivery adaptations, owner
  decision 2026-09-25) · **Method:** heuristic evaluation + persona walkthrough against the catalogued screens, the
  merged contracts and the rulings on #2701 (§2); **no session was run: no participant, timing, quote, card-sort score
  or concept-test result exists, and none is invented.**
- **Scope:** SCR-130 profiles list, SCR-131 profile editor, SCR-132 templates, SCR-133 symbol permissions matrix,
  SCR-062 trade-group manager and the preview half of SCR-061 (#820 §Context); US-PROF-001..008 (`11:521-688`); P1
  Owner, P1 wearing the P4 Admin hat, P2 Account Manager (`10` §2–§5). SCR-134 global risk policy and SCR-114 trading
  defaults are boundaries only, not walked. Feeds E28-D02 (#821) and, through it, E28-D03..D05 and E28-Q04.
- **Out of scope (ticket):** "Any visual design, wireframe or prototype (E28-D02 onward); usability testing of built
  software (E28-Q04's exploratory charter covers that)."
- **Deliverable form:** this report; its session protocol
  [`e28-d01-session-protocol.md`](e28-d01-session-protocol.md), ready for the owner to run; the owner walkthrough
  checklist (§16, to post on #820); at most eight research boards on the Penpot page `E28-D01` (§1). Every finding is
  labelled `(heuristic)`; every design proposal is **PROPOSED** until the owner approves it or a session confirms it.
  What #2701 has ruled is cited by its ledger row and carries no PROPOSED stamp.
- **In plain words.** Nothing here is observed. The contract and the owner-queue rulings have overtaken much of the
  ticket: two of its three blocking questions are answered by the schema, the third is a designer's call with a
  reason, and the money questions are ruled. Where a catalogue or story line disagrees, the shipped rule stands and the
  design explains it (§14); one catalogue control that contradicted C-2.6 is deleted by this PR (§14, S-1).
- **Ids:** RQ research question · H pre-registered hypothesis · W walkthrough · F finding · TK protocol task ·
  CD copy-deck seed · AD recommended decision · IM implication · C conflict with a locked rule · S safety correction ·
  AX accessibility review item · G input gap · OQ open question · N1–N10 Nielsen's ten heuristics, numbered as
  E27-D01 numbers them (`E27R:21-25`) · A-P / A-O / A-U the `05` §2 trading heuristics · T3, T4, T5, T7, T10, T11 the
  persona themes (`10:353-361`).
- **Pin and shorthand.** Every `path:line` is at `main` `e74121321ebb053b22e9877b7de340190ef21e0b`, before this PR's
  edits to `14`. `NN` = `docs/plan/NN-*.md` (`22` = `22-api-openapi.yaml`); `E28.json` = `docs/plan/backlog/E28.json`;
  `CON` = `CONSTITUTION.md`; `ADR8` = `docs/plan/27-adrs/ADR-0008-trade-group-fanout.md`; `ADR40` =
  `docs/plan/27-adrs/ADR-0040-per-trade-overrides-and-profile-propagation.md`; `TM` =
  `docs/security/threat-models/E28-profiles-trade-groups.md`; `E27R` = `docs/design/research/e27-key-custody.md`;
  `MX` = `services/api/tests/contract/rbac/matrix.yaml`; `PRT` = `.github/PULL_REQUEST_TEMPLATE.md`; `README` =
  `docs/design/README.md`. `L1 row N` = #2701 ledger 1 (issuecomment-6491680793) row N; `L2 row N` = #2701 ledger 2
  (issuecomment-6493096777) row N, both ruled by the orchestrator under the owner's delegation.

## Acceptance-criteria trace (issue #820)

Status key: **done** = delivered as worded · **answered** = settled by the contract or a ruling, cited · **heuristic-only**
= delivered through the adaptation, pending the owner's run · **substituted** = a live-session item replaced, under the
adaptation clause, by the heuristic run, the protocol and the walkthrough · **open** = needs the owner.

| Ticket AC or deliverable                                                                                 | Where                                            | Status                                                                                                 |
| -------------------------------------------------------------------------------------------------------- | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| AC1 "At least four sessions completed and synthesised, including the owner"                              | §6 walkthroughs; protocol §1–§9                  | substituted; the sessions are an optional post-GA line, not a gate (L1 rows 18, 61, 106 precedent)     |
| AC2 the three blocking questions each answered with evidence, or "no signal - designer's call"           | §5 B1–B3                                         | answered by `21`: B1, B3 directly; B2 no arm column, not drawing one a designer's call with its reason |
| AC3 the card sort's grouping is the proposed one or a documented alternative, and D02 draws it           | §8 (heuristic pre-sort); protocol §6 (card sort) | heuristic-only: the six sections hold, with deltas documented (AD-5)                                   |
| AC4 findings linked from SCR-130, SCR-131, SCR-132, SCR-133 and SCR-062 in `14`                          | this PR's pointer lines in `14`                  | done                                                                                                   |
| AC5 presented at a Design Review; decisions recorded in the ticket                                       | §16 walkthrough; owner's `approved` (adaptation) | open                                                                                                   |
| Scope: topic guide (risk per account, sizing model, daily loss, group model, partial fan-out, overrides) | §4 RQ1–RQ8; protocol §4                          | done; RQ3 and RQ6's money semantics answered by L2 rows 46 and 33                                      |
| Scope: concept test, risk in USDT vs risk in R                                                           | §7 cards; protocol §5                            | substituted; **unmeasured until run**                                                                  |
| Scope: card sort of the SCR-131 field set into the six sections                                          | §8; protocol §6                                  | heuristic-only                                                                                         |
| Scope: findings report with themes, quotes and implications tagged to a screen                           | §6, §13                                          | done (heuristic); no quote exists                                                                      |
| Scope: research-debt note                                                                                | §17                                              | done                                                                                                   |
| Technical notes: paper-and-whiteboard; counterbalanced cards                                             | protocol §3, §5                                  | substituted                                                                                            |
| Security notes: synthetic stimuli; recordings Confidential, deleted after sign-off                       | protocol §2                                      | done (rules stated; no recording exists)                                                               |
| Accessibility notes: a keyboard-only or screen-reader participant, else research debt + E28-D05          | §15; protocol §7; §17                            | substituted; recorded as debt for E28-D05                                                              |
| DoD: artefacts in the design tool, linked from the ticket and from `14`                                  | §1 (PENDING); `14` pointers                      | open — boards PENDING (Deviation 6)                                                                    |
| DoD: "every state drawn", component and token lines                                                      | E28-D02 / D03 (Deviation 5)                      | not applicable to research                                                                             |

## Deviations

1. **Method and deliverable form.** The 4–6 moderated sessions, the card sort and the concept test are replaced, per
   the ticket's adaptation clause, by the heuristic evaluation (§2–§15), the session protocol and the owner walkthrough
   (§16). The sessions are an optional post-GA line on the E28 epic, per the orchestrator's ruling of 2026-10-29, on the #2701 precedent for research tickets of this
   shape (L1 rows 18, 61, 106).
2. **Path.** The ticket commits "only the findings summary" from a research drive (#820 §Branch); this report follows
   the repo convention `docs/design/research/<epic>-<slug>.md` (coordinator ruling OQ-3 on #732, comment 6364262239,
   recorded at `E27R:72-75`).
3. **Start gate.** `blocked_by` lists E27-D01 (`E28.json:368-370`), and #732 is open: its memo merged (#4272) and its
   boards PR (#4936) is open. This report starts text-first on the orchestrator's ruling of 2026-10-29 (10:43Z), as
   E27-D01 started against its own open blocker (`E27R:76-83`). The dependency's reason is participant reuse (#820
   §Dependencies), which no session makes real yet; the boards PR waits until #732 closes.
4. **Recordings.** The ticket keeps recordings "in the project's research drive"; this repository is public, so the
   protocol reuses E27-D01's rule: recordings and notes stay on the owner's encrypted host and are deleted at sign-off
   (`E27R:84-89`; protocol §2).
5. **Template noise.** The brief's "Repo paths" (`apps/web/src/features/<feature>/`), its `pnpm --filter
@candleviewer/web` commands, "Figma" and the DoD lines on drawn states, components and tokens belong to E28-D02 /
   D03, not to research; Figma → Penpot (adaptation). This PR is text-first: `Refs #820` plus a `Partial:` line and
   no closing keyword (`PRT:25-28`).
6. **Boards.** Specified here, drawn in the boards PR; at most eight research boards (coordinator ruling OQ-2 on #732,
   recorded at `E27R:93-95`).
7. **Size.** This report, its protocol and the `14` edits exceed C-4.8's 400-line preference; one report is the
   ticket's deliverable and its ids cite each other, so the PR carries "Why this can't be split".

## 1. Research boards (Penpot) — PENDING

Page `E28-D01`, created by name at the boards step; its id is recorded then (`README:46-49`). Boards are named
`E28-D01 / NN slug` and exported to `docs/design/research/img/E28-D01-NN-slug.png`, the E27-D01 precedent
(`E27R:101-105`). Every word on a board comes from this report; a board that shows a recommendation carries a PROPOSED
stamp, and a ruled item carries its ledger row instead; fixture account names only (`Main`, `sub_001`, `sub_002`).

| #   | Board                                 | Content (section)                                                                                                   | State   |
| --- | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ------- |
| 01  | `E28-D01 / 01 personas-and-hats`      | P1, P1 as P4, P2a / P2b: what each may read and change on the six surfaces (§2, §6)                                 | PENDING |
| 02  | `E28-D01 / 02 policy-journey`         | create → bind → edit under positions → template → matrix → group → preview → changed under a ticket, F-ids per step | PENDING |
| 03  | `E28-D01 / 03 three-blocking-answers` | B1–B3 with the contract line behind each (§5)                                                                       | PENDING |
| 04  | `E28-D01 / 04 worked-example-cards`   | the two counterbalanced USDT / R cards, stamped "unmeasured" (§7)                                                   | PENDING |
| 05  | `E28-D01 / 05 editor-card-sort`       | six sections × as-built fields, deltas marked; the native stop as a fixed statement (§8)                            | PENDING |
| 06  | `E28-D01 / 06 fan-out-readiness`      | ready · skipped · leg rejected · refused whole · review, with the "2 of 3 ready" sentence (§10)                     | PENDING |
| 07  | `E28-D01 / 07 copy-deck-seed`         | CD-1..CD-12 with the fact each carries (§11; PROPOSED)                                                              | PENDING |
| 08  | `E28-D01 / 08 implications-conflicts` | IM-1..IM-16 beside C1–C12 and S-1 (§13, §14)                                                                        | PENDING |

## 2. Method note (agent-delivery adaptation, owner decision 2026-09-25)

The ticket asks for 4–6 moderated 45-minute sessions on paper, a card sort and a counterbalanced concept test (#820
§Scope, §Technical notes). Delivery is a solo agent with one human owner, so, per the adaptation clause and the E27-D01
precedent (`E27R:128-158`), they become:

1. A **heuristic evaluation** of the six surfaces against Nielsen's **N1–N10**; the `05` trading heuristics **A-P** (a
   state is never colour-only), **A-O** (every destructive gate is keyboard-operable, no timing trap) and **A-U**
   (plain-language errors, predictable focus); and the persona themes **T3** fan-out with per-account truth, **T4**
   server-enforced safety, **T7** unmistakable Demo vs Live, **T10** everything auditable, **T11** emergency separate
   from configuration (`10:353-361`).
2. **Persona walkthroughs** (§6): P1 wearing the P4 hat (`10:175`, G3 "Define per-account profiles … and trade groups",
   `10:184`) in scenario 1 "Onboard a manager" (`10:202`); P1 fanning one decision out to a group (G3, `10:78`); P2,
   both archetypes (`10:111-112`), whose goal is "Absolute clarity about their limits … visible _before_ they submit,
   not after a rejection" (`10:117`).
3. A **written session protocol** (the companion file) and an **owner walkthrough checklist** (§16).

**Honest limits.** No participant quotes, task timings, success rates, card-sort agreement or concept-test scores
exist, and none are invented. Confidence is the strength of the basis, not a measurement: **High** = stated in a
locked plan or contract document or a #2701 ruling; **Med** = sound heuristic reasoning from the catalogue text;
**Low** = persona inference only (`E27R:147-150`).

**Inputs that exist and inputs that do not.** The profile routes are served (`MX:616-645`); of the definition routes, list, create and read are
served (`MX:1480-1497`) and replace and delete are `not_mounted` (`MX:1498-1511`, gap G-6); the execution and its preview, `POST /trade-groups` and `POST /trade-groups/preview`,
are `not_mounted` (`MX:1519-1531`). E28-D02 (#821) does not exist yet. ADR-0040 still reads `proposed` at the pin
(`ADR40:3-7`); L2 row 33 ratifies it, and its status flip lands in its own docs PR.

## 3. Locked, not relitigated

These rules stand; where a catalogue or story line disagrees, §14 records it and the design explains it.

- **C-2.6:** every position-opening order, "including every leg of a trade-group fan-out, must carry a native
  exchange-side stop-loss", and "There is no configuration flag, environment, feature flag or 'advanced mode' that
  disables this" (`CON:128-134`); **C-4.14:** no flag disables the native SL, RBAC or audit (`CON:443-444`). In the
  schema, `require_native_sl` is `true` with `CHECK = true` (`21:1478`, `21:1545`); in the contract, setting
  `require_native_stop` to `false` is `422 validation_failed` / `native_stop_mandatory`, audited as
  `profile.save_refused` (`22:3500-3502`); `NativeStopGuard` "is not user-configurable" (`ADR8:45`).
- **C-2.12 / C-12.4:** RBAC, risk caps, profile resolution and sizing are server-side; "Frontend gating is cosmetic
  only" (`CON:164-166`, `CON:769-773`). A Manager may not edit profiles ("read-only view of own") or create groups
  ("may select from groups granted to them") (`10:294`, `10:300`).
- **C-12.5 and D6:** "a fan-out leg that violates a cap is rejected, not clamped silently" (`CON:775-778`); a submitted
  value beyond a cap is rejected with `risk_limit_breached`, and the sizer's own policy clamp is recorded and shown in
  the preview, never silent (`TM:479-482`).
- **D7, the ceiling:** "The default profile is the account's ceiling … alternates, templates, overrides and rules only
  narrow it" (`21:1447`; `TM:483-484`; `ADR8:117-122`).
- **Definitions** (ADR-0008 Amendment 2): a definition is not a trade group and "grants nothing: each leg's account is
  checked against the caller's grants at each use"; at most 20 legs, one per account; "The preview takes the submit's
  permission" (`ADR8:99-108`). A definition is single-environment and its `env` is write-once (`21:2044`).
- **Ruled on #2701** (no PROPOSED stamp): **D8** — group definitions are Owner-only, with the `risk_caps` step-up as the
  interim, until a later ADR widens it (L2 row 18; `22:6676-6678`). **D11** — the loss-bounding caps are NOT NULL on a
  trading-enabled profile, and "all symbols" is an explicit flag (L2 row 18; `21:1576-1580`). **ADR-0040** is ratified
  (L2 row 33): Decision 1's later-narrows comparator, the net risk ceiling, OPEN-1 (size may rise up to the caps) and
  OPEN-2 (a fail-closed isolated-margin liquidation estimate) (`ADR40:74-140`, `ADR40:477-507`). **The daily-loss
  netting** — the override risk ceiling nets daily-loss headroom − realised loss today − committed risk, failing
  closed on an unknown figure (L2 row 46; `ADR40:83-105`).

## 4. Research questions and pre-registered hypotheses `(heuristic; all untested)`

| RQ  | Question (ticket topic guide)                         | Hypothesis (pre-registered; the protocol scores it confirmed / refuted)                                                                                          | Probe       | Consumer      |
| --- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- | ------------- |
| RQ1 | How risk per account is decided today                 | H1: by habit per account, re-decided per trade only for an exceptional setup; the profile is the habit written down, and its default is read as the ceiling (D7) | A1–A2       | SCR-130, 131  |
| RQ2 | Default sizing model and fallback                     | H2: risk-based (percent of equity at the stop) is P1's default; a fixed quantity is the fallback a P2 sub-account gets                                           | A3; TK2     | SCR-131       |
| RQ3 | What "max daily loss" means                           | H3: owners read one number for two mechanisms; once shown, the lockout (realised only) and the ticket's headroom (net of open risk) are told apart (§9)          | A4; CD-7    | SCR-131, 061  |
| RQ4 | A group: a saved thing or an ad hoc multi-select      | H4: both — the saved definition is the habit, the ad hoc pick the exception; neither is read as a permission                                                     | A5; TK4     | SCR-062, 061  |
| RQ5 | Expectations when one account of a group cannot trade | H5: partial fan-out is expected if the skip and its reason are named before Send; a whole refusal is expected only when the request itself is too large          | TK5         | SCR-061, 062  |
| RQ6 | What makes an override feel exceptional               | H6: a text label plus a one-ticket lifetime, not colour; "capped by profile: 5x" is read as the policy, not as a fault                                           | TK7; CD-8   | SCR-061       |
| RQ7 | Worked example: risk in USDT vs risk in R             | H7: USDT is restated correctly first; R alone is misread as a price distance; R defined in USDT beside it is restated correctly                                  | protocol §5 | SCR-131, 061  |
| RQ8 | SCR-131 grouping                                      | H8: the six sections hold for the as-built fields, with the three order defaults the only cards sorted inconsistently (§8)                                       | protocol §6 | SCR-131 (D02) |

## 5. The three blocking questions — answers and evidence

**B1 — Is the profile list per account or per profile? Answered by the contract: per account.** Each account has
exactly one default (bound) profile, its ceiling, plus named alternates selectable per ticket (`21:1447`; one default
per account is a partial-unique index, `21:1590`; D7, `TM:483-484`). The default binding moves only through its own
operation, `setAccountDefaultProfile` (`22:3504-3508`). **What E28-D02 draws:** SCR-130 lists accounts, one row each,
naming the bound profile in text, with alternates nested under the account; an account without a default is flagged
"cannot trade until bound" (the catalogue's own checklist, `14:2641`). Confidence High.

**B2 — Does a group need an armed-for-live flag distinct from the global arm control? Answered by the contract — no arm
column on a definition (`21:2042-2075`); not drawing one is the designer's call.** Reason: arming is per account (`exchange_accounts.trading_enabled`, "Must be explicitly armed by
owner", `21:986`) and per profile (`trading_enabled`, which needs every loss-bounding cap set, `21:1458`,
`21:1576-1579`); a definition is single-environment, write-once in `env` (`21:2044`), and grants nothing (`ADR8:102`);
the definition tables carry no such column (`21:2046-2069`). A group-level flag would be a third arm for the same leg
and a contract change of its own. **What E28-D02 draws:** SCR-062 shows the definition's environment once and, per
member, the account's armed state and the bound profile's trading state in words; a member that is not armed reads as
not ready (§10; the preview's own answer is gap G-5). Confidence Med (designer's call on High facts).

**B3 — Is the symbol matrix's default allow-all or deny-all? Answered by the contract: deny-all.** "NULL/empty allows
nothing unless `all_symbols`"; `all_symbols` needs a NULL list; the block list applies after the allow list
(`21:1487-1489`, `21:1580`); US-PROF-003 flags the profile "allowing no symbol" or "allows all symbols" (`11:575-580`);
D11 is ruled (L2 row 18). **What E28-D02 draws:** SCR-133 cells carry three facts, not one toggle — allowed, blocked,
and the row-level "all symbols" state — and a new account's row reads "allows no symbol yet". Confidence High.

## 6. Persona walkthroughs and findings (all `(heuristic)`)

**W1 — P1 as P4 onboards `sub_001`'s profile** (scenario 1, `10:202`; SCR-130 → SCR-131). A new profile starts with
`trading_enabled` false and no symbol allowed (`21:1458`, `21:1488`); turning trading on needs a position cap, a
daily-loss cap, open positions, concurrent orders and a leverage cap (`21:1576-1579`). The save is Owner-only behind
the `risk_caps` step-up and needs `If-Match` (`22:3494-3495`, `22:3510-3513`).

**W2 — P4 edits `Main`'s profile while it holds a position** (`11:533-535`). The edit is a new `version`; "a position
sized from it keeps it" (`22:3499-3500`). A loosened cap or a widened symbol set is labelled `relaxing` in the audit
record and notifies the Owner (`22:3516-3520`).

**W3 — P4 applies a template to three accounts** (SCR-132). "Applying a template is a client-side prefill of SCR-131 -
it never writes directly" (`14:2681`); each account's save is its own step-up write.

**W4 — P4 restricts symbols and meets an empty intersection** (SCR-133, SCR-062). Three facts per account (B3); the
catalogue's "These accounts have no symbol in common" (`14:1452`) is computed from the members' allow and block lists.

**W5 — P1 defines "Core3" and previews a fan-out with one member not ready** (SCR-062 → SCR-061; `11:613-621`). The
definition is Owner-only (L2 row 18); the preview is the submit's dry run (`ADR8:107-108`) and answers per leg or
refuses whole (`22:13676-13681`).

**W6 — a profile changes under P1's open ticket** (`ADR40:356-370`). The ticket shows "profile changed — review",
before and after per changed number, and Send stays disabled until the review is confirmed (ADR-0040 Decision 4).

**W7 — P2a reads their limits before a trade** (`10:117`; SCR-061 for a granted account). The manager reads the
profile but may not edit it (`10:300`).

| #    | Finding `(heuristic)`                                                                                                                                                                                                                                                                                                                                                                                                  | Heuristic | Sev | Screen       |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- | --- | ------------ |
| F-1  | "One profile per account" (`14:2623`) hides the alternates and the ceiling: a reader cannot tell that an alternate may only narrow the default (`21:1447`)                                                                                                                                                                                                                                                             | N2, N6    | 3   | SCR-130      |
| F-2  | A profile that cannot trade looks like one that can: `trading_enabled` defaults false and needs five caps (`21:1458`, `21:1576-1579`), and the list mock has no state column for it (`14:2625-2631`)                                                                                                                                                                                                                   | N1, T4    | 3   | SCR-130, 131 |
| F-3  | "allows no symbol yet" is the default state of every new profile (`21:1488`) and the mock shows only the opposite warning, "allows all symbols" (`14:2630-2631`)                                                                                                                                                                                                                                                       | N1, N9    | 3   | SCR-130, 133 |
| F-4  | The worked example cannot be checked: "0.5 % of 21 300 USDT ≈ 106 USDT risk ≈ 0.08 BTC at a 25-tick stop" (`14:2667`) states no tick size, and 106 ÷ 0.08 implies a stop of about 1 325 USDT per BTC, or a tick of about 53 USDT                                                                                                                                                                                       | N2, A-U   | 4   | SCR-131      |
| F-5  | R is defined by the stop and never a stop unit (`21:1471`; `24:2636`); a card that leads with R before saying what 1 R is in USDT invites reading R as a price distance (H7)                                                                                                                                                                                                                                           | N2        | 3   | SCR-131, 061 |
| F-6  | The mock's Brackets section drew the native stop as a ticked checkbox, and Validation offered a typed opt-out (`14:2655`, `14:2666`): a control implies it can be cleared, against C-2.6 and the CHECK (S-1, deleted by this PR)                                                                                                                                                                                       | N2, T4    | 4   | SCR-131      |
| F-7  | Five mock controls have no column: max drawdown, "on breach", block while disconnected, cancel on lockout and the rounding select (`14:2653-2661`), and "max position [0.2] BTC" has no BTC column (the caps are USD notional and % of equity, `21:1479-1480`); the body "carries exactly its stored columns" (`ADR8:83-86`); rounding is always floor (`24:5956`)                                                     | N2, N4    | 3   | SCR-131      |
| F-8  | Three as-built fields have no section in the catalogue's six — `time_in_force_default`, `reduce_only_default`, `slippage_tolerance_bps` (`21:1490-1492`) — and eleven have no mock line: `max_leverage_cap`, `risk_fixed_amount_usd`, `min_leg_notional_usd`, `sl_atr_period`, `sl_atr_multiple`, `fallback_sl_offset_pct`, `tp_ladder`, `max_concurrent_orders`, `blocked_symbols`, `enabled`, `trading_enabled` (§8) | N4        | 2   | SCR-131      |
| F-9  | "Daily loss" names two mechanisms with two quantities: the lockout counts realised loss only (`24:3616`), the ticket's ceiling nets open risk (`ADR40:83-89`); one label for both misleads in either direction (§9)                                                                                                                                                                                                    | N2, N9    | 4   | SCR-131, 061 |
| F-10 | "applies to future orders only" is on SCR-131's checklist (`14:2672`) but the editor shows no version and no "positions keep their version" line (`22:3499-3500`)                                                                                                                                                                                                                                                      | N1, N6    | 2   | SCR-131      |
| F-11 | A relaxing save notifies the Owner (`22:3516-3520`) and the editor's diff summary (`14:2672`) does not say which change is relaxing; the owner learns it after the step-up                                                                                                                                                                                                                                             | N1, T10   | 2   | SCR-131      |
| F-12 | SCR-132's "aggressive templates … unavailable for LIVE accounts without an explicit acknowledgement" (`14:2683`) sits beside a server that judges each save the same way whatever its template; the acknowledgement adds friction, not safety                                                                                                                                                                          | N5, T4    | 2   | SCR-132      |
| F-13 | SCR-133's "allow/deny toggles" (`14:2687`) are one bit for three facts (B3); a toggle cannot show "blocked although allowed by pattern" (`21:1489`)                                                                                                                                                                                                                                                                    | N2, A-P   | 3   | SCR-133      |
| F-14 | SCR-062 lists "who may use it" and an "armed-for-live flag" (`14:1450`); a definition grants nothing and has no flag (`ADR8:102`; B2): both columns would state a permission the server never checks                                                                                                                                                                                                                   | N2, T4    | 3   | SCR-062      |
| F-15 | SCR-062 edits groups through `/trade-groups` and its amend / cancel (`14:1451`), which are executions; definitions have their own paths (`ADR8:99-101`; `22:6636-6806`)                                                                                                                                                                                                                                                | N2        | 3   | SCR-062      |
| F-16 | US-PROF-005's example cause for "2 of 3 ready", a member's key failing its self-check (`11:619-621`), cannot produce it: a failed stored-key check makes the whole system read-only (`E27R:247`, F-6), so 0 of 3 are ready                                                                                                                                                                                             | N1, T4    | 3   | SCR-061, 062 |
| F-17 | Two refusals look alike and mean different things: a request that would widen a leg is refused whole, while an account-state cap marks only its leg (`ADR8:117-122`; `22:13676-13681`); one red row for both hides which the trader can fix                                                                                                                                                                            | N9, A-U   | 4   | SCR-061      |
| F-18 | A leg below the minimum is skipped, not rejected (`21:1469`; `24:2625-2627`), while US-PROF-002 offers "the minimum as a one-click choice" (`11:556`), refused when the minimum breaks the budget (`ADR40:120-122`)                                                                                                                                                                                                    | N5, N9    | 3   | SCR-061      |
| F-19 | An unknown figure fails closed: a leg whose account figures are not cached is `blocked` with `figure_unknown` (`22:13691-13692`), and an unknown committed risk zeroes the headroom (`ADR40:102-105`); "unknown" must not read as "zero risk"                                                                                                                                                                          | N1, T5    | 3   | SCR-061      |
| F-20 | SCR-061's "[ ] Stagger sends 150 ms apart" (`14:1431`) has no request member: the rate budget is per UID on the server (`ADR8:47`)                                                                                                                                                                                                                                                                                     | N2, T4    | 2   | SCR-061      |
| F-21 | An override that a profile change turns into a widening is cleared and shown as "capped by profile" (`ADR40:362-364`); without the review state the trader would not know a number they set is gone                                                                                                                                                                                                                    | N1, N3    | 3   | SCR-061      |
| F-22 | P2's goal, limits "visible _before_ they submit" (`10:117`), has no surface: the read-only profile view has no catalogue screen and SCR-061's rows show the sizing rule, not the caps (`14:1423-1426`)                                                                                                                                                                                                                 | N6, T4    | 3   | SCR-061      |

## 7. The worked example: USDT and R (concept test, **unmeasured**)

Two static cards with the same numbers, taken from US-PROF-002's scenario so they need no invented figure: equity
10 000 USDT, risk 0.5 %, stop distance 120 USDT on BTCUSDT (`11:547-550`). The arithmetic: 0.5 % × 10 000 = 50 USDT;
50 ÷ 120 = 0.4166… BTC before fees, rounded down to the lot step. The server's figure is a little smaller, because the
risk includes the entry and exit taker fees (`24:2611-2616`), so each card says "about".

- **Card U (USDT first):** "If your stop is hit you lose about **50 USDT** — 0.5 % of your 10 000 USDT. At a 120 USDT
  stop that is about **0.41 BTC**."
- **Card R (R first):** "Risk **1 R** per trade — 1 R is the loss at your stop, here about 50 USDT. At a 120 USDT stop
  that is about **0.41 BTC**."
- **Restate prompt:** "If the stop is hit, how much do you lose, in USDT?" Pass: the number 50 (± fees) with no price
  read as the loss. Order counterbalanced (protocol §5).
- **PROPOSED default (AD-4):** both, as US-PROF-002 asks ("in USDT and in R", `11:550`), USDT first, R defined in text
  in the same sentence — the E32-D01 precedent of R on exits only (`14:1520`).

## 8. SCR-131 field grouping (heuristic pre-sort; the card sort is protocol §6)

Every writable `account_profiles` column (`21:1451-1492`) sorted into the catalogue's six sections (`14:2645`). The
binding (`is_default`) and the name sit in the header, not a section; `version` is read-only.

| Section           | Fields (as built)                                                                                                                                                                                                                                        | Delta from the mock (`14:2647-2663`)                                                                                    |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Leverage & margin | `leverage`, `max_leverage_cap`, `margin_mode`, `position_mode`                                                                                                                                                                                           | adds the cap; the cap is a risk bound, cross-referenced from Risk caps                                                  |
| Sizing            | `sizing_mode` and its one parameter (`size_fixed_qty` / `size_fixed_notional_usd` / `size_pct_equity` / `risk_pct_equity` xor `risk_fixed_amount_usd`), `min_leg_notional_usd`; order defaults sub-group: `time_in_force_default`, `reduce_only_default` | drops the rounding select (always floor, `24:5956`); adds the fixed-amount risk, the minimum leg and the order defaults |
| Brackets          | `sl_offset_value` + `sl_offset_unit` (ticks / percent / ATR, never R), `sl_atr_period`, `sl_atr_multiple`, `fallback_sl_offset_pct`, `tp_offset_value` + `tp_offset_unit`, `tp_ladder`                                                                   | the native stop is a fixed statement, not a field (S-1); adds ATR and fallback                                          |
| Risk caps         | `max_position_notional_usd`, `max_position_pct_equity`, `max_daily_loss_usd`, `max_daily_loss_pct`, `max_open_positions`, `max_concurrent_orders`, `max_orders_per_minute`                                                                               | drops max drawdown and "on breach" (no column, F-7; lockout policy is SCR-134's, `14:2697`)                             |
| Symbols           | `all_symbols`, `allowed_symbols`, `blocked_symbols`                                                                                                                                                                                                      | adds the block list and the explicit "all symbols"                                                                      |
| Safety            | the fixed native-stop statement (CD-6), `slippage_tolerance_bps`, `enabled`, `trading_enabled` (with the five caps it needs listed)                                                                                                                      | drops "block while disconnected" and "cancel on lockout" (no column, F-7)                                               |

**Chosen grouping for E28-D02 (AC3; AD-5, PROPOSED until the card sort runs):** the six sections hold; the two order
defaults are a sub-group at the end of Sizing, and the slippage guard sits in Safety ("guards market orders",
`21:1492`). The card sort tests exactly this; a seventh "Order defaults" section is the documented alternative if two
or more participants make one.

## 9. Daily loss: what counts (ruled — L2 row 46)

Two mechanisms, two definitions, both as the contract words them; the design states which number each surface shows.

1. **The lockout** counts **realised loss only**: `sys.daily_loss_lockout` fires on `realised_pnl_today <=
-max_daily_loss` and halts new orders until the next UTC day (`24:3616`; `21:1481` "triggers lockout").
2. **The override risk ceiling** on a trade-group leg is **net**: daily-loss headroom − realised loss today − committed
   risk, capped by the per-trade budget for a `risk_based` profile, and zero — every leg refused — when committed risk
   is unknown (L2 row 46; `ADR40:83-89`, `ADR40:102-105`).

US-PROF-004's "realised+unrealised loss reaches the daily cap" (`11:600`) is the UX framing of the net ceiling, not of
the lockout; C10 asks `11`'s owner to align that sentence. **Design consequence:** SCR-131 labels the cap once and
explains both uses in one line (CD-7); SCR-061 shows the remaining net headroom per leg, and an unknown figure as
"unknown", never as zero (F-19).

## 10. Overrides and fan-out readiness (ADR-0040 ratified — L2 row 33)

ADR-0040 Decision 1 settles the override questions and is not restated here (`ADR40:74-140`). What the design takes
from it: the bound profile is the ceiling; size may rise up to the caps and is refused above them (OPEN-1); leverage
may rise up to the effective cap only while the stop lies strictly inside a fail-closed isolated-margin liquidation
estimate (OPEN-2, `ADR40:138`); an override lives for one ticket (`ADR40:281-285`); "capped by profile: 5x" is text,
an override carries the text label "override", and the review state is a polite status announced once per change
(`ADR40:440-446`).

**Readiness states per leg** (SCR-061 preview, SCR-062 member rows), each with its words:

| State         | Cause (contract)                                                                                                                              | Group outcome                  |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| ready         | the leg sizes and passes every check                                                                                                          | sent                           |
| skipped       | below the instrument minimum or `min_leg_notional` (`24:2625-2627`; `21:1469`); a member disabled (`21:2044`); an account disabled (`21:985`) | the rest send; skip named      |
| leg rejected  | an account-state cap the request does not move: daily loss, open positions, margin (`ADR8:120-122`)                                           | the rest send; reason named    |
| blocked       | a figure unknown (`22:13691-13692`; `24:2600`)                                                                                                | the rest send; "unknown" named |
| refused whole | the request would widen any leg (`risk_limit_breached`, `22:13676-13679`); mixed environments (`22:13692-13695`)                              | nothing sends                  |
| review        | a bound profile changed under the ticket (`ADR40:358-364`)                                                                                    | Send disabled until confirmed  |

"2 of 3 ready" (`11:621`) is the sentence for the first four rows; the fifth is never "0 of 3 ready" but a refusal
naming the leg and the value that widens it (F-17).

## 11. Copy-deck seed for E28-D03 (PROPOSED; every string `(heuristic)` until §7 and protocol §5 run)

Fixture names only; API fields and audit codes keep their technical names.

| #     | Candidate string                                                                                                                   | Fact it carries                           | Screen       |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- | ------------ |
| CD-1  | "Default profile — the most this account may do. Alternates can only narrow it."                                                   | D7 ceiling (`21:1447`)                    | SCR-130, 131 |
| CD-2  | "Allows no symbol yet" / "Allows all symbols"                                                                                      | B3 deny-all; explicit flag (`11:575-580`) | SCR-130, 133 |
| CD-3  | "Trading off — set the position, daily-loss, open-positions, concurrent-orders and leverage caps to turn it on"                    | `ap_trading_caps` (`21:1576-1579`)        | SCR-131      |
| CD-4  | "If your stop is hit you lose about 50 USDT (1 R) — 0.5 % of 10 000 USDT."                                                         | worked example, USDT then R (§7)          | SCR-131      |
| CD-5  | "Applies to future orders only. Open positions keep the version they were sized with."                                             | versioned save (`22:3499-3500`)           | SCR-131      |
| CD-6  | "Every order carries a stop-loss at the exchange. This cannot be turned off."                                                      | C-2.6, `ap_native_sl` (S-1)               | SCR-131, 061 |
| CD-7  | "Daily loss cap: reaching it in realised loss locks the account until 00:00 UTC. New trades also count your open risk against it." | §9 (L2 row 46)                            | SCR-131, 061 |
| CD-8  | "Capped by profile: 5x"                                                                                                            | ADR-0040 a11y constraint (`ADR40:442`)    | SCR-061      |
| CD-9  | "2 of 3 ready — sub_002 skipped: below the 0.001 BTC minimum"                                                                      | partial fan-out named before Send (§10)   | SCR-061, 062 |
| CD-10 | "Not sent: sub_001 would exceed its daily-loss headroom. Lower the size or remove sub_001."                                        | refused whole (`22:13676-13679`)          | SCR-061      |
| CD-11 | "A trade group cannot mix Demo and Live"                                                                                           | US-PROF-005 (`11:618`); C-2.11            | SCR-062      |
| CD-12 | "Profile changed — review before sending"                                                                                          | ADR-0040 Decision 4 (`ADR40:358`)         | SCR-061      |

## 12. Recommended decisions AD-1..AD-10 (PROPOSED; testable by E28-D02)

| #     | Decision                                                                                                                                           | Basis             |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| AD-1  | SCR-130 is per account: one row per account naming its default in text, alternates nested, an unbound account flagged (B1)                         | F-1; `21:1447`    |
| AD-2  | Every profile row and the editor header show trading on / off in words, with the caps still missing when off                                       | F-2; CD-3         |
| AD-3  | The editor's worked example uses the live equity and a stated tick size or USDT distance, so every number in it can be checked                     | F-4               |
| AD-4  | USDT first, R defined in USDT in the same sentence; R never alone                                                                                  | §7; F-5           |
| AD-5  | The six sections with the §8 placements; no control without a column; the native stop a fixed statement                                            | §8; F-6, F-7, F-8 |
| AD-6  | One daily-loss cap, one label, a one-line explanation of both uses; the ticket shows the net headroom and "unknown" when it is                     | §9; F-9, F-19     |
| AD-7  | The diff summary before the step-up marks every relaxing change, as the audit record will (`22:3516-3520`)                                         | F-11              |
| AD-8  | SCR-133 cells show allowed / blocked as glyph + text, with the row's "all symbols" and "no symbol yet" states; no single toggle                    | B3; F-3, F-13     |
| AD-9  | SCR-062 edits definitions only, Owner-only; no "who may use it" and no group arm flag; each member row shows armed state and environment in words  | B2; F-14, F-15    |
| AD-10 | SCR-061 separates "not sent" (refused whole) from per-leg skip / reject / blocked, each with its reason, before Send; the review state blocks Send | §10; F-16..F-21   |

## 13. Implications, prioritised (screen · decision changed · confidence; PROPOSED)

| #     | Pri | Implication                                                                      | Screen       | Confidence |
| ----- | --- | -------------------------------------------------------------------------------- | ------------ | ---------- |
| IM-1  | P1  | The native stop drawn as a fixed statement, never a control (S-1)                | SCR-131, 061 | High       |
| IM-2  | P1  | Refused-whole and per-leg outcomes drawn as two distinct states                  | SCR-061      | High       |
| IM-3  | P1  | Daily-loss copy names both uses; the ticket shows net headroom and "unknown"     | SCR-131, 061 | High       |
| IM-4  | P1  | The list is per account, with the default named and alternates nested            | SCR-130      | High       |
| IM-5  | P1  | Symbols as allow + block + "all symbols"; deny-all default visible               | SCR-133, 130 | High       |
| IM-6  | P1  | No control without a stored column; five mock controls removed                   | SCR-131      | High       |
| IM-7  | P2  | Trading on / off with the missing caps listed                                    | SCR-130, 131 | High       |
| IM-8  | P2  | A checkable worked example, USDT first                                           | SCR-131      | Med        |
| IM-9  | P2  | Definitions edited on their own paths; no group permission or arm column         | SCR-062      | High       |
| IM-10 | P2  | The "profile changed — review" state with before / after per number              | SCR-061      | High       |
| IM-11 | P2  | Relaxing changes marked in the pre-save diff                                     | SCR-131      | Med        |
| IM-12 | P2  | A read-only limits view for a Manager, reachable from the ticket                 | SCR-061      | Med        |
| IM-13 | P3  | Order defaults as a Sizing sub-group                                             | SCR-131      | Low        |
| IM-14 | P3  | Templates prefill the editor only; the "aggressive" acknowledgement reconsidered | SCR-132      | Med        |
| IM-15 | P3  | No stagger checkbox; the rate budget shown as server state                       | SCR-061      | High       |
| IM-16 | P3  | The empty-intersection warning computed from allow and block lists               | SCR-062, 133 | Med        |

## 14. Conflicts register: the locked decision stands; the design explains (responses PROPOSED, except C10's and C12's, which follow L2 rows 46 and 18)

**S-1 — safety correction made by this PR (ruled 2026-10-29 10:43Z; not a C-row).** SCR-131's mock line "[x] require
a native stop-loss on every order" (`14:2655`) and its Validation clause "disabling the mandatory-stop flag requires an
extra typed acknowledgement because it removes the safety invariant" (`14:2666`) described a way to turn the native
stop off. C-2.6 says no flag, environment or mode disables it (`CON:128-134`), C-4.14 forbids a flag that gates it
(`CON:443-444`), the column is `CHECK = true` (`21:1478`, `21:1545`) and the contract refuses the attempt
(`22:3500-3502`). This PR deletes the mock line and the clause; the rest of the Validation line stays. The catalogue's
own checklist already asks for "the mandatory native-SL floor … shown as non-removable" (`14:2672`).

| #   | Catalogue or story text                                                                  | Locked source (stands)                                                    | Design response                                                                                        |
| --- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| C1  | "One profile per account" (`14:2623`)                                                    | one default plus alternates (`21:1447`)                                   | AD-1                                                                                                   |
| C2  | "mandatory-SL flag" listed as a profile field (`14:2623`)                                | `CHECK = true` (`21:1478`); C-2.6                                         | a fixed statement (CD-6), not a field                                                                  |
| C3  | "armed-for-live flag" on a group (`14:1450`)                                             | no column; arming per account and profile (`21:986`, `21:1458`)           | B2; AD-9                                                                                               |
| C4  | "who may use it" (`14:1450`); "groups granted to them" (`10:294`)                        | "A definition grants nothing" (`ADR8:102`)                                | use follows account grants; no group grant column                                                      |
| C5  | SCR-062 Data: `/trade-groups`, amend, cancel (`14:1451`)                                 | `/trade-group-definitions` (`ADR8:99-101`)                                | AD-9                                                                                                   |
| C6  | five editor controls with no column (`14:2653-2661`)                                     | "exactly its stored columns" (`ADR8:83-86`)                               | AD-5; lockout policy on SCR-134                                                                        |
| C7  | "allow/deny toggles" (`14:2687`)                                                         | allow list, block list, `all_symbols` (`21:1487-1489`)                    | AD-8                                                                                                   |
| C8  | "offering the minimum as a one-click choice" (`11:556`)                                  | a minimum above the budget is refused, never rounded up (`ADR40:120-122`) | offer it only when it passes; else name the refusal                                                    |
| C9  | "[ ] Stagger sends 150 ms apart" (`14:1431`)                                             | rate budget per UID, server-side (`ADR8:47`)                              | IM-15                                                                                                  |
| C10 | US-PROF-004 "realised+unrealised loss reaches the daily cap" → lockout (`11:600-601`)    | lockout realised only (`24:3616`); net ceiling (L2 row 46)                | ask `11`'s owner to word the lockout scenario as realised loss and the net ceiling as its own scenario |
| C11 | "2 of 3 ready" caused by a key failing its self-check (`11:619-621`)                     | a failed key check makes the system read-only (`E27R:247`)                | ask `11`'s owner for a cause that skips one member (§10)                                               |
| C12 | TM D8 and D11 still read "open, Owner" (`TM:485`, `TM:490`); `22:6678` "queued on #2701" | ruled (L2 row 18)                                                         | G-1: the labels follow in the threat model's owner PR                                                  |

## 15. Accessibility expert review (stands in for the a11y participant; for E28-D05; PROPOSED, `(heuristic)`)

| #    | Item                                                                                                                                    | Source              |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------- | ------------------- |
| AX-1 | SCR-133 cells: the accessible name combines account, symbol and state ("sub_001, ETHUSDT, blocked"), not account and symbol only        | `14:2688`; A-P      |
| AX-2 | Sticky row and column headers are real table headers, so a screen reader announces them in the virtualised grid                         | `14:2693`           |
| AX-3 | "Capped by profile: 5x" is the control's accessible description, announced on focus                                                     | `ADR40:442-443`     |
| AX-4 | The review state is `role="status"`, polite, once per change; Send's accessible name says why it is disabled                            | `ADR40:444-446`     |
| AX-5 | A refused-whole answer moves focus to its summary, which names each leg and value; per-leg reasons are text in the row                  | F-17; A-U           |
| AX-6 | The native-stop statement is plain text in the Safety section, never a disabled checkbox a screen reader announces as "checked, dimmed" | S-1; A-P            |
| AX-7 | The step-up on save keeps focus in the dialog and returns it to Save; no timing trap                                                    | `22:3494-3495`; A-O |
| AX-8 | Readiness is text ("skipped", "blocked"), never colour alone                                                                            | `14:1440`; A-P      |

## 16. Owner walkthrough checklist (ready to post on #820)

The lane posts the block below on #820 as one comment after the boards PR; the owner ticks what was walked and
answers about the mocks only. #820 is public: never a real balance, account number or position.

```markdown
## E28-D01 owner walkthrough (docs/design/research/e28-risk-policy-fanout.md)

Tick what you walked; one line per item on what you saw or expected. Answer about the mocks only — never paste a
real balance, account number, key or position.

- [ ] B1–B3: read the three answers (§5); say whether the per-account list, no group arm flag and deny-all match how
      you would set up `sub_001`
- [ ] Cards U and R (§7): restate the loss at the stop from each; say which you would want first
- [ ] SCR-131 grouping (§8): say where you would look for time-in-force and the slippage guard
- [ ] Daily loss (§9): read CD-7; say when the account locks and what a new trade counts
- [ ] Fan-out (§10): on the preview, tell "not sent" from "2 of 3 ready" and say what you would change in each
- [ ] Read the native-stop statement (CD-6) and the SCR-131 correction (§14, S-1)
- [ ] Comment `approved` on #820, or leave rework notes citing the F-, AD-, IM-, C-, CD- or OQ- ids
```

## 17. Research debt, open questions and input gaps

**Research debt** (what this report did not answer, and who answers it later): H1–H8 confirmations, the card sort and
the concept test → the optional post-GA sessions (protocol); the a11y participant → E28-D05; behaviour on built
software → E28-Q04.

| #    | Open question or gap                                                                                                                                                                    | Owner / route                    |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| G-1  | TM D8 / D11 labels and `22:6678`'s "queued on #2701" predate L2 row 18                                                                                                                  | threat-model and contract owners |
| G-2  | No served field gives a Manager the caps of a granted account on the ticket (F-22)                                                                                                      | E28-S01 (#971) as a comment      |
| G-3  | The preview returns no profile versions (`ADR40:370-372`), which the review state needs                                                                                                 | #909 / E28-S05 (#1144)           |
| G-4  | US-PROF-004 and US-PROF-005 wording (C10, C11)                                                                                                                                          | `11`'s owner                     |
| G-6  | Definitions cannot be edited or deleted yet: `PUT` and `DELETE /trade-group-definitions/{definitionId}` are `not_mounted` (`MX:1498-1511`), so SCR-062's edit path (AD-9) waits on them | #909 as a comment                |
| G-5  | The preview states no outcome for a member whose account (`21:986`) or bound profile (`21:1458`) is not armed; B2 draws it as not ready `(heuristic)`                                   | #909 as a comment                |
| OQ-1 | Are the order defaults a seventh section? The card sort decides (§8)                                                                                                                    | sessions; default AD-5           |
| OQ-2 | Does SCR-132's "aggressive" acknowledgement stay (F-12)?                                                                                                                                | E28-D02; default: keep, PROPOSED |

## 18. Constraints honoured

Nothing here relaxes: the native stop on every leg (C-2.6) with no flag (C-4.14) — S-1 removes the only catalogue text
that offered a way to turn it off; server-side RBAC, risk and sizing (C-2.12, C-12.4, C-12.5); later-narrows and the ceiling (D7,
ADR-0040); every profile and definition write audited (C-2.9); a definition in one environment (C-2.11); WCAG 2.2 AA
(C-14.1). No real key, UID, balance or position appears; numbers come from the stories' own scenarios.

## 19. References

At `main` `e74121321ebb053b22e9877b7de340190ef21e0b`: issue #820; `docs/plan/backlog/E28.json` · `CONSTITUTION.md`
C-2.6, C-2.9, C-2.11, C-2.12, C-4.8, C-4.14, C-12.4, C-12.5, C-14.1 · `05-accessibility-standard.md` §2 ·
`10-personas.md` §2–§5, §9 · `11-user-stories.md` US-PROF-001..008 · `14-screens-catalogue.md` SCR-061, SCR-062,
SCR-130..134 · `21-database-schema.md` §3.2.1, §3.2.4, §3.3.3a · `22-api-openapi.yaml` `updateAccountProfile`,
`setAccountDefaultProfile`, `createTradeGroupDefinition`, `previewTradeGroup` · `24-internal-schemas.md` §9.3,
§9.3.1, §9.3.2, §9.3.2a, the system rules table · ADR-0008 (binding rules, Amendments 1–3) · ADR-0040 ·
`docs/security/threat-models/E28-profiles-trade-groups.md` D6–D11 · `docs/design/research/e27-key-custody.md` ·
`services/api/tests/contract/rbac/matrix.yaml` · #2701 ledger 1 rows 18, 61, 106 and ledger 2 rows 18, 33, 46 ·
#732, #4272, #4936 (E27-D01) · #821, #909, #971, #1144.
