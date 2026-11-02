# E38-D01 — Session protocol: telling demo from live, and trusting simulated fills

- **Ticket:** E38-D01 (issue #1002) · **Status:** ready to run, owner approval pending · **Report:**
  [`E38-paper-parity.md`](E38-paper-parity.md) owns the findings, the predicted answers and the design implications.
  This file owns the script, the measures and the scoring. Nothing in it has been run.

## 1. Purpose and what is locked

- **Purpose.** Confirm or refute the report's predictions for RQ1–RQ6 with the Owner and two account managers (`10`
  P1, P2a or P2b). Each probe has a pre-agreed correct answer and a decision rule, so a finding is measured, not
  asserted (#1002 AC2, AC4).
- **Locked (not tested):** C-2.11, server-side refusal (C-2.12), never colour-only (`14` §0.5 #1) and SR-179. A
  participant who prefers a hotkey switch is recorded but does not reopen C-2.11.

## 2. Participants, consent and data handling

- **Participants.** Three: the Owner, and two managers covering P2a (intraday) and P2b (swing). At least one session
  runs keyboard-only (Task K).
- **Consent.** Written consent before recording. Recordings are kept on the project's private research drive, never in
  the repo. The repo holds only the anonymised read-out (participant A, B, C), with no names.
- **Data.**
  - The stack runs `CV_ENV=demo`, `CV_FEED=synthetic` and the dev account fixture (`CV_ACCOUNT_FIXTURE`, `20`:961–972),
    with no Bybit key loaded and no live or funded demo account on screen. The screen shows the fixture's balances
    only.
  - The LIVE state is shown on the clickable stub (§3), never on a live session.
- **Prerequisites.** E30-X01 (#920), E30-K01 (#852) and E29-K01 (#843) merged, so that the ticket and the order flow
  are real (#1002 Dependencies). The D02 stubs are drawn for the LIVE frames.

## 3. Stimuli

| ST   | Stimulus                                                                                                                                                                            | Used by      |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| ST1  | The R2 build on the demo stack: shell, ticket, DOM ladder, positions                                                                                                                | Tasks 1–3, K |
| ST2  | Clickable stubs of the same workspace in LIVE: the band and each treatment under test (band only; band plus panel badges; band, badges and submit-label word)                       | Tasks 1–3    |
| ST3  | A stub of the SCR-074 switch: typed `LIVE`, the 2FA field, the transition, the 10 s banner                                                                                          | Task 4, K    |
| ST4  | A simulated results drawer with a strong equity curve (illustrative: +18 % over 40 trades), in two framings: as SCR-099 is catalogued today, and with the report's §5 rules applied | Probe 4      |
| ST5  | A reset confirm, in two framings: TradingView-style ("all paper data will be deleted") and the report's CA-7 and CA-8                                                               | Probe 5      |
| ST5b | The account drawer in a LIVE session in two treatments: the reset control hidden (US-PAPER-006) and the reset disabled with the environment reason (`14` §0.5 #5, E09-D09's T2)     | Probe 5b     |
| ST6  | A parity report list with three items (one fresh, one stale after 90 days, one runtime candidate) and a demo-only rejection drawer                                                  | Probe 6      |
| ST7  | Greyscale and three CVD versions of ST2's treatments, their colours from `docs/research/_tools/cvd_simulate.py` (`simulate`), as the report's §8                                    | Task 5       |

## 4. Session script (45 minutes)

| Min   | Step                                                                                                                                                                                                                                                                                                                             | RQ   |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 0–3   | Consent, the think-aloud explanation, "there are no wrong answers; we are testing the screens"                                                                                                                                                                                                                                   | —    |
| 3–15  | **Task 1–3, a trading round on ST1/ST2.** Place three orders from the ticket, the DOM and the chart, swapping treatments between rounds. **Interrupt** at three unprompted moments (just before a submit, after a panel is maximised, after switching monitor focus): "Which environment are you in right now? How do you know?" | 1, 2 |
| 15–22 | **Task 4, the switch (ST3).** Switch to LIVE, then back to DEMO. Then: "When did you last switch? What is the session in now?"                                                                                                                                                                                                   | 3    |
| 22–30 | **Probe 4 (ST4).** Show framing A, then framing B. "If this were your strategy, what size would your next live trade be?" Then: "What would make you trust these results more, or less?"                                                                                                                                         | 4    |
| 30–35 | **Probe 5 (ST5).** "Before pressing reset, what do you expect to lose? Does it touch anything else?" **Probe 5b (ST5b):** "In this LIVE session, can you reset anything? What does the drawer tell you?"                                                                                                                         | 5    |
| 35–40 | **Probe 6 (ST6).** Open the demo-only rejection. "What would you do now? Would you have read this list before?"                                                                                                                                                                                                                  | 6    |
| 40–43 | **Task 5 (ST7)** for the managers. Name the environment in each render.                                                                                                                                                                                                                                                          | AC3  |
| 43–45 | Debrief: "Anything about demo and live that worries you?"                                                                                                                                                                                                                                                                        | —    |

**Task K (keyboard-only, one session):** Task 4 with no pointer. Record each trap: focus lost, a field not reachable, or
`Enter` submitting before both fields are valid.

## 5. Measures, scoring and the decision rules

| Measure                                                         | Correct answer                                              | Decision rule (confirms or changes the report)                                                                                                                  |
| --------------------------------------------------------------- | ----------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Recall per treatment: 3 interrupts × 3 participants × treatment | the environment named correctly, with its cue               | Panel badges stay mandatory (report F2) whatever the rate. If band-only recall falls below the badge treatments, the submit-label word is required too (F1).    |
| The cue named at each interrupt                                 | —                                                           | If most answers name the ticket or DOM header rather than the band, F1 is confirmed.                                                                            |
| Time-since-switch recall (Task 4)                               | the session's actual environment                            | Any wrong answer confirms F4, so "LIVE since" is required.                                                                                                      |
| Keyboard traps (Task K)                                         | none                                                        | Any trap is a D05 defect against `05` §3.1 item 4.                                                                                                              |
| Sizing after ST4 (Probe 4)                                      | sizing not increased on simulated results alone             | A higher size under framing A than under B confirms F5. Any increase under B makes the §5 rules insufficient, so D04 adds a stronger caveat (OQ for the owner). |
| Reset expectation (Probe 5)                                     | positions and orders go; history and exchange accounts stay | A participant expecting history loss under CA-7 and CA-8 means the copy is changed in D03.                                                                      |
| Reset in LIVE (Probe 5b)                                        | no participant believes a live balance can be reset         | Recorded per treatment for D03's open conflict (report SC-8, OQ-3); either treatment that lets anyone think live data is resettable is rejected                 |
| Parity report (Probe 6)                                         | the rejection's link is used                                | If nobody reaches the item from the rejection, the entry point moves to the rejection message itself (F7).                                                      |
| Render naming (Task 5)                                          | 100 % correct by the word and glyph                         | Any miss in a render rejects that treatment for D02 (AC3).                                                                                                      |

The read-out goes to #1002 as a table per measure (participant A, B, C), with every changed decision named against
the report's F-id.

## 6. Owner walkthrough checklist (to post on #1002; owner approval pending)

- [ ] SC-1 to SC-9's recommended defaults (report §1) accepted or ruled otherwise
- [ ] SC-8 (OQ-3): the reset in Live hidden or disabled with a reason, decided for D03 after Probe 5b
- [ ] F2: per-panel badges mandatory, including popped-out windows
- [ ] F1 and OQ-4: the first LIVE order after a switch always confirmed
- [ ] §5's six framing rules for simulated results
- [ ] OQ-1 and OQ-2 owners named
- [ ] P-1 and P-2 written into `32` by E38-X01, or declined
- [ ] The session run scheduled once the prerequisites in §2 are merged
