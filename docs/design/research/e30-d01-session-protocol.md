# E30-D01 — Session protocol and discussion guide (ready to run; owner or future moderator)

- **Companion to:** `docs/design/research/e30-order-entry-under-time-pressure.md` (E30-D01, issue #826), called
  "the report" below. F#, SC-#, DJ-#, OQ-# and "report §n" refer to it; a bare "§n" is a section of this file.
- **Status:** not yet run. Every planned duration below is an allocation inside a 60-minute session, not an
  observed time; the budget is summed in §3. **No participant, timing or quote exists yet**; results are
  appended to the report as a dated addendum (OQ-11).
- **Roles:** the moderator is never the participant. The owner is a participant (ticket Scope) and is tagged
  **P1** on the session sheet and in both affinity maps, because the owner also set the locked decisions and
  approves the report; a second human moderates the owner's session, or an agent runs this script with the
  owner answering and a note-taker recording. For the other sessions the owner may moderate.

## 1. Framing, participants, consent

**Opening script (read verbatim):** "Two things in this design are fixed and are not what we are testing today:
every order that opens a position carries a stop-loss held by the exchange, and trading controls are only
usable when the arm/lock state and the DEMO/LIVE badge are both visible. We want to learn how fast and how
reliably you can read those states and work with them, not whether you would keep them." (Ticket Context;
`CONSTITUTION.md` C-2.6, C-2.11; `30-release-roadmap.md` §7.2 E30 row — "no trading control is operable unless
both are visible"; E30-S04 Context; `14-screens-catalogue.md` §0.5 item 1.)

**Primer (2 min):** CandleViewer is self-hosted and single-owner, so there are no other tenants to reason about
(ticket Technical notes). One owner account plus up to a few sub-accounts, each with a per-account profile that
fixes sizing mode, leverage, protective offsets and server-enforced risk caps (`24-internal-schemas.md` §9.2);
a "trade group" fans one intent out to several accounts, each sized by its own profile (§9.4; SCR-061).

**Participants:** 5–6 remote sessions of 60 minutes: the owner, the account managers (P2a/P2b,
`10-personas.md` §3) and, where available, comparable discretionary futures traders. Recruit at least one
habitual keyboard-first user for Probe F (ticket Accessibility notes; `10-personas.md` §3 assumes one manager
prefers keyboard-first operation) and record self-reported colour-vision deficiency and assistive-technology use
on the session sheet (§5). Coordinate with E31-D01 on people and on questions: the same person is not recruited
for both studies in the same fortnight (ticket Out of scope), and E31-D01's "confirmation tolerance" and
"armed/disarmed chrome" items share CMP-229 with this study — exchange findings both ways rather than re-asking.

**Consent and data:** recording with consent, internal use only; the stimulus is exported frames and a clickable
prototype built from them, never the live app, so no order can be placed; no real account ids, balances or API
keys appear (ticket Security notes); in Probe E any screen share of the participant's own account is masked or
paused on balances, account ids and open positions; recordings live on the internal drive with access limited to
the design and product group and are deleted when the Epic closes. Recordings are viewed by humans only and are
never uploaded to any external service; if the second analysis pass is an AI agent, it works only on de-identified
notes and transcripts the moderator has redacted (names, account ids, balances). Read verbatim after the opening
script: "We record the screen and audio. People in the design and product group watch the recording; a redacted
written summary may also be analysed with an AI tool. Nothing is published, and the recording is deleted when
this project phase closes. Is that all right?" — record the answer.

**Analysis:** two independent affinity maps — the owner and a second pass (another human where available,
otherwise an AI-agent pass over the de-identified notes and transcripts only, per the consent above) — reconciled;
anything backed by a single participant is labelled a **signal**, not a finding (ticket Test plan); the owner's
own data carries the P1 tag through both maps. Read-out with product, design and the E30 engineering lead; the
owner's `approved` comment on #826 replaces CDO sign-off (Agent-delivery adaptations). **Pilot once** as a dry run
(moderator plus one colleague, no data kept) before the first participant.

## 2. Stimulus and declared assumptions

- **Stimulus:** two sources. Probes A, D and F use the E30-D02 SCR-060 frames (every state) and the E30-D03
  frames for SCR-076, SCR-077, SCR-158 and the SCR-061 selector slice, exported as a clickable prototype; Probe B
  uses the report's Board 2 (the 15-frame legibility matrix) and Probe C the report's Board 3 (segmented-control
  and mode-per-field tickets), both on Penpot page `E30-D01` and exported to `docs/design/E30/img/`
  (`E30-D01-<board>.png`). Sessions start when all of these exist (OQ-11). Numbers come from the instrument and
  profile fixtures named by E30-D02 / E30-Q01 (real tick and lot sizes), never from this document. **Timing
  source:** every time in this protocol is read from the screen recording at 30 fps (≈33 ms resolution, enough
  for second-scale answers); no instrumented prototype exists or is planned, and nothing here assumes one.
- **Declared key map (assumption pending OQ-1, SC-1):** `docs/generated/default-keymap.md` Ticket rows and
  SCR-060 Interactions — `B`/`S` set side, `1..4` quantity presets, `Alt+B`/`Alt+A`/`Alt+M` snap price, `R`
  reduce-only, `Ctrl+Shift+T` arm/disarm, `Ctrl+Enter` submit, `Esc` clear. Sizing-mode switching and stop entry
  have no default key in the keymap, 05 §3.2 or SCR-060 (E30-S05 lists a cycle-sizing-mode action and buy/sell
  limit at bid/ask without keys), so the stimulus reaches them by `Tab` (F14) until the owner binds them; if the
  owner decides otherwise, update this line and the stimulus before the first session. A hotkey that only
  _opens_ the Demo/Live switch dialog (`Ctrl+Shift+L` in 17 §7; SCR-074 says click-only) is recorded, not
  scored, in Probe F.
- **Declared arm variant (assumption pending OQ-2/OQ-3, SC-2/SC-3):** armed = server token with a visible
  remaining-time cue (F6); arming in DEMO is the chord; arming in LIVE is the chord plus an explicit confirm step
  (CMP-229 A11y "a deliberate second action"; E30-S04 "a single keystroke can never arm in Live"; F17); when
  armed in DEMO, any submit (preset or `Ctrl+Enter`) skips SCR-076 (policy "never when armed", E30-S04); in LIVE a
  market order always shows SCR-076 with no default-focused confirm button (SCR-076 checklist; E30-S04). Record
  the variant on every session sheet.
- **Declared stop entry (assumption pending SC-8):** the timed task enters the stop as a **price** in the SL
  field of CMP-119 BracketEditor; SCR-060 draws the unit list `ticks|%|R` and the API has `price` (22 `OffsetUnit`),
  so the prototype adds a price unit until the owner decides. Probe F tabs to that field.
- **Environment treatment (locked):** DEMO/LIVE band (CMP-074) plus local badge (CMP-075) plus the Live
  chrome accent and the accessible name (SCR-075); never colour-only (`05-accessibility-standard.md` §4).
- **Seeded rejections** (one per report §4 class plus the unknown-outcome state: six fixture frames, never a live
  call): post-only would cross with a "reprice" suggestion (correctable; US-ORD-002; E30-T02; E30-Q01 fixture — a
  tick-size violation reaching the exchange is a client defect per 13 §19 subsection 18.1, SC-10);
  `risk_limit_breached` with the binding limit in the chip (limit/account); `exchange_rate_limited` with a
  retry-after (transient); a `502 exchange_error` carrying `exchange.ret_code/ret_msg` (exchange/unknown); entry
  accepted with the native stop not attached, shown as "order live, protective stop pending" and resolving to
  retry, then flatten (protective-stop failure; C-2.6; US-ORD-013 scenario 2; 24 §8.8; 06 §5.2); and **no ack
  within 2 s** — "submitting" becomes "Awaiting exchange confirmation — reconciling" with duplicate submits
  blocked (SCR-060 Performance, States), resolving to accepted after a further 6 s (designer judgement). The
  report §4 table carries the pre-registered predicted first action per class; Probe D confirms or refutes each.
- **Lock-state frames (F4):** four frames — arm-locked (SCR-060 locked), idle session lock (13 §19 subsection
  18.6; the E09 SCR-005 re-auth modal over the ticket), daily-loss lockout ("Daily loss limit reached — trading
  locked until 00:00 UTC", SCR-060) and the viewer's read-only lock notice (SCR-060 RBAC). A frame that E30-D02 or
  E09-D02 did not draw is skipped and recorded as "not shown".

## 3. Probe sets and time budget

Budget: opening script and consent 3 · primer 2 · A 5 · B 12 · C 13 · D 11 · E 5 · debrief 3 = **54 min**. The
keyboard-first participant drops Probe E (its walkthrough is covered by the owner checklist, §6) and adds Probe
F 7 = **56 min**; if Probe F cannot start by minute 48, stop and run it as a separate 20–30-minute keyboard-only
session, or book that participant for 75 minutes when they agree. Think-aloud is used in Probes A, B condition
(a), D and E only — never during a timed trial (§4) and never during Probe B condition (b), whose times are logged.

**Probe A — pre-submit glance (RQ1, 5 min).** Show a filled SCR-060 for 2 seconds, then a blank screen. Ask:
"What was on it?" (free recall, record order of recall). Then forced choice from the report §2 inventory: "Before
pressing submit, what would you check?" (pick up to three, in order; three is designer judgement). Repeat once
with the armed LIVE variant. Record: items recalled in order; items chosen; any item named that is not on the
ticket. F3 (moving price helpers) is not testable with static frames and is not probed here.

**Probe B — armed/locked and demo/live, including concept probe (a) (RQ2, 12 min).** Three treatments
(persistent badge, banner, tinted chrome; order counterbalanced across participants); stimulus = report Board 2,
15 frames: per treatment armed/locked × DEMO/LIVE plus that treatment's own fail-closed `unknown` frame.
Condition (a), accuracy: the 15 colour frames in random order, each shown for about 2 seconds then masked; ask
"Armed or locked? Demo or live?" (answer options include "can't tell") and "How sure, 1–5?". Condition (b),
speed, within-subject: for each of the three treatments two frames, one in greyscale and one in a deuteranopia
simulation (`docs/design/_tools/cvd_sim.py`; 05 §4 item 2; `10-personas.md` §3), the frames chosen so that every
armed/locked × DEMO/LIVE cell appears across participants; self-paced — the frame stays until both answers are
given; no think-aloud; onset-to-answer is read from the recording (§2 timing source). With 5–6 participants every
between-treatment speed difference is a **signal** unless every participant shows it (ticket Test plan). The
protanopia and tritanopia check is computed on the token pairs, not run as a session task
(`docs/research/_tools/cvd_simulate.py` or `tools/contrast/color-math.mjs`; 05 §9.3 A11Y-C003; E30-D02 AC);
protan/tritan frame renders need `cvd_sim.py` extended or Chrome DevTools vision-deficiency emulation. Record:
answer, correctness, time, confidence, and the direction of every misread — LIVE read as DEMO and armed read as
locked are flagged. Then the four lock-state frames (§2; F4): "What is locked here, why, and how would you
resume?" Then ask: "You press a size preset in this state — what do you expect to happen? And in LIVE?" (SC-3
expectation, verbatim); arm in DEMO, then in LIVE with the second action — "What, if anything, about the second
step was unclear or slowed you down?" (verbatim; input for F17 copy, not a design change); which element told
them the state; whether an open or a closed padlock means "trading enabled" to them, and whether the glyph reads
as the current state or as the action (report §6 Bookmap); finally the arm indicator with the remaining-time cue
— what do they expect at zero? Optional noticing check (F6; E30-D04 requires auto-disarm to be noticeable): while
the participant answers the padlock question, the moderator advances the prototype to the auto-disarmed frame
("30 min inactivity", US-ORD-005) without comment; record whether, and after how long, they notice.

**Probe C — sizing, concept probe (b), stop legibility and the timed task (13 min).** Show the
segmented-control ticket and the mode-per-field ticket (report Board 3; counterbalanced). Each opens in the
**wrong mode** for the task (quantity mode when the task needs risk %, and the reverse on the second ticket) so
that a mode slip can occur. Task: "Set this to 0.5 % risk." Record the sizing mode they land in, whether the
computed quantity was visible to them without asking, and any mode slip (typing a quantity into a percentage
field or vice versa) — the DJ-8 flip rule counts these (report §5b: more slips on the segmented ticket than on
mode-per-field, with at least two participants slipping, flips F12). Stop legibility (F13), with the stop
filled: "Where does this stop value come from, and who holds it once the order is placed — the exchange or the
app?"; then clear the stop field so the blocked-submit state appears (E30-D02 "cannot be left empty") and ask
what they would do. Then run the timed task (§4) with the mouse twice, DEMO then LIVE or the reverse
(counterbalanced), on the sizing-mode ticket they prefer; the keyboard-first participant repeats both in Probe F.

**Probe D — seeded rejections (RQ3, 11 min).** Submit each of the six seeded cases from §2. **Do not prompt**
for the first 15 seconds (designer judgement): record whether they re-read the ticket, retry (as-is or after
editing), or abandon (`Esc`), and the first thing they name when asked "What happened?"; score each against the
report §4 predicted first action (confirmed / refuted). Then ask what they would want to see first, and whether
they believe the attempt was recorded (F11). For the transient case, ask what they expect the system to do when
the retry-after elapses (SC-6: nothing until they confirm, or an automatic retry). For the no-ack case, record
every submit press during the wait and what they expected a second press to do. For the protective-stop case,
ask "Are you protected right now? What is the system doing?" and what they would do meanwhile (OQ-12).

**Probe E — comparative walkthroughs on the participant's own strategy (5 min).** Products are assigned across
participants before the first session so that TradingView, Bookmap and Bybit are each walked by at least two
people where the pool allows; a product no participant can walk goes to the owner checklist (§6). Using the
participant's own setup as the task frame, walk one placement in the assigned product (screen share of their own
paper/demo account if they have one, masked per §1; otherwise the public pages whose URLs are in the report §6),
then the same placement on the stimulus. Record every point where they expect a behaviour the stimulus does not
have (report §6 sources: TradingView's one-click mode skipping the ticket, Bookmap's padlock opening when enabled
and doubling as a panel toggle, Bybit's "Demo Trading" header label and optional TP/SL checkbox) and what told
them so.

**Probe F — keyboard-only pass of the placement task (the keyboard-first participant, 7 min).** Mouse
disconnected. Arm in LIVE with the keyboard only (`Ctrl+Shift+T` plus the declared second action; record whether
it completes without a pointer). Run the §4 task with the declared key map: `Tab` to the sizing-mode control (or
the E30-S05 cycle action if the owner has bound a key), choose risk %, `Tab` to the SL field (price unit, §2) and
type the stop price the moderator gives, verify the computed quantity, `Ctrl+Enter`; in LIVE the SCR-076 modal
appears — confirm with `Enter` only after 400 ms (SCR-076 A11y) and before the 20 s inactivity auto-cancel.
Record: Tab count to each field, any unreachable control, focus returning to the invoker after the modal closes
(05 §3.4 item 4), no hotkey that switches environment (C-2.11; a hotkey that only opens the switch dialog is
recorded, not scored, §2), whether the 20 s countdown and the 400 ms delay were perceivable without sight of the
timer, and whether a keyboard-only user can complete the task without timing traps (WCAG 2.2.1; 05 §3.1 rules 1
and 4). Optional NVDA pass: the 05 §8.2 task — side, size and price heard before confirm; the rejection or fill
and the "protective stop pending" state heard in the assertive region (05 §6.2; E30-S03 `role="alert"`).

**Debrief (closing script, 3 min):** "Where did the stop-loss or the arm step cost you the most time or
attention, and what would have made it quicker to satisfy?" (record verbatim; input for F13/F6/F17 and E30-D02
copy, not a design change). "What would have made the armed state or the LIVE state more obvious?" Thank, stop
recording, note the session sheet's declared variants.

## 4. Timed task protocol (the human side of the 8 ms / 50 ms / ack budgets)

**Task text (verbatim):** "size this trade to risk 0.5% with a stop under that swing low, then place it".
The moderator gives the symbol, the side (buy), the order type (market), the account equity shown on the
stimulus, the swing-low price and the stop rule — **one tick below the swing low**, read out as the exact stop
price (no chart interaction, E31 scope).

**Stimulus requirements:** risk-based sizing computes quantity from risk amount ÷ (stop distance + round-trip
taker fee per unit), then clamps, then **floors** to the lot step (`24-internal-schemas.md` §9.3 steps 4–7), so
the implied risk the ticket displays reads at or below 0.5 % — the stimulus must show that number, not exactly
0.5 %. One trial uses a clamp case whose message reads "reduced from 1.2 to 0.8 by max_position_notional"
(§9.3.2). The stop is entered as a price (§2 declared stop entry); the stop unit list is pending SC-8.

**Start/stop events:** start = the first keystroke or click after the moderator says "go"; "first correct size"
= the computed quantity first equals the lot-floored quantity for 0.5 % risk at the given stop (§9.3 step 7;
within one lot step, the server's own tolerance per the US-ORD-004 NFR) with the risk input reading 0.5 and the
SL field holding the exact stop price given — a smaller quantity is not "correct" and is logged under
Corrections; "ack" = the ticket shows the accepted state (or, in LIVE, the moment the SCR-076 confirm is pressed,
recorded separately from the stimulus's accepted state). Two further events, the human analogues of the two
budgets the report §9 cites: "last input edit → submit" = the last keystroke or click that changed a field, to
the submit press; "hotkey press → submit" = in keyboard trials, the `Ctrl+Enter` keydown to the ticket's
submitting state. All times are read from the recording at 30 fps (§2). After each trial: the unprompted check
"Demo or live? Armed or locked?" (Probe B in-flow measure), then the retrospective cued review — replay the last
~2 s before the submit and ask "What were you looking at here?", logging pointer or focus position from the
recording (report §2 limitation).

**Trial set:** every participant runs trials 1–2 (order counterbalanced); the keyboard-first participant adds
trials 3–4 in Probe F. Input method = mouse or keyboard-only; sizing mode = the CMP-101 mode used.

| Trial | Input method  | Env  | Armed (declared variant) | Expected modal            | Sizing mode used | t first correct size | t last edit → submit | t hotkey → submit | t ack | Tab stops | Corrections | Mode slips | In-flow check | Notes |
| ----- | ------------- | ---- | ------------------------ | ------------------------- | ---------------- | -------------------- | -------------------- | ----------------- | ----- | --------- | ----------- | ---------- | ------------- | ----- |
| 1     | mouse         | DEMO | armed                    | none                      |                  | not yet available    |                      | n/a               |       | n/a       |             |            |               |       |
| 2     | mouse         | LIVE | armed                    | SCR-076, no default focus |                  | not yet available    |                      | n/a               |       | n/a       |             |            |               |       |
| 3     | keyboard-only | DEMO | armed                    | none                      |                  | not yet available    |                      |                   |       |           |             |            |               |       |
| 4     | keyboard-only | LIVE | armed                    | SCR-076, no default focus |                  | not yet available    |                      |                   |       |           |             |            |               |       |

Report p50 and the range per cell once data exist; never a single participant's time as a baseline. The budgets
these times are compared against are cited in the report §9 (≤8 ms recompute, SCR-060 Performance; ≤50 ms
hotkey→submit, US-ORD-006 NFR; submit→ack, 06 §5.2 budget #4); the human time is the context for those budgets,
not a pass/fail against them, and a 30 fps reading cannot resolve the millisecond budgets themselves.

## 5. Recording sheet and quote bank (per session)

Session id · date · participant persona (P1 = the owner / P2a / P2b / comparable trader) · self-reported
colour-vision deficiency and assistive-technology use · declared arm variant, key map and stop entry (§2) ·
stimulus build id · Probe A recall order and forced choices · Probe B per-frame answers, times, confidence,
misreads with direction, lock-state answers, preset expectation, second-action verbatims, padlock reading,
noticing-check result · Probe C starting mode, mode landed in, result visible (y/n), mode slips, stop-source and
stop-holder answers, cleared-stop reaction · Probe D per case (six): re-read / retry-as-is / retry-after-edit /
abandon, prediction confirmed or refuted, first thing named, "was it recorded?" (y/n/unsure), expectation at
retry-after, submit presses during the no-ack wait, protective-stop answers · Probe E assigned product and
expectation mismatches · Probe F Tab counts, unreachable controls, focus return (y/n), completion (y/n), LIVE arm
completed without a pointer (y/n), opener-only hotkey seen (record only) · the §4 trial fields, in-flow checks
and cued-review answers · debrief verbatims · moderator notes. Single-participant observations are marked
**signal** in the write-up.

**Quote bank (template; empty until a session runs):**

| Id  | Session | Persona | Probe | Verbatim          | Recording time | Theme | F# / OQ# | Signal or finding |
| --- | ------- | ------- | ----- | ----------------- | -------------- | ----- | -------- | ----------------- |
|     |         |         |       | not yet available |                |       |          |                   |

## 6. Owner walkthrough checklist (ready to post on issue #826; owner approval pending)

**Now, before E30-D02 starts:**

- [ ] Decide OQ-1..OQ-4, OQ-6 and OQ-9 (SC-8 stop units, SC-9 component placement, the sizing-control default) and give provisional copy for OQ-12; OQ-5 and OQ-13 (SC-10 correction offers) are due before E30-T02 (report §10)
- [ ] Confirm or override the report's concept-probe verdicts: §5a (badge first, optional short banner line, never tint alone) and §5b (segmented control kept as the status quo; heuristic preference mode-per-field)
- [ ] Confirm or override the proposed pass bars (DJ-5) and the Probe C flip rule (DJ-8)
- [ ] Hands-on walkthroughs the documentation review could not settle (report §6): place one paper order in TradingView, arm one-click in Bookmap, open Bybit Demo; record the armed indicator (if any), how a rejection is displayed and how the Demo label is styled
- [ ] Comment `approved` on issue #826, or leave rework notes citing F#, SC-#, DJ-# or OQ-#

**When the E30-D02 and E30-D03 frames and this ticket's Boards 2–3 exist (OQ-11):**

- [ ] Walk SCR-060 locked, then armed, in DEMO and then in LIVE (with the second action); write down what told you which state you were in
- [ ] Arm in LIVE with the keyboard only; note whether it completed without a pointer
- [ ] Do the 0.5 % task with the mouse; record (do not estimate) the time from first keystroke or click to the ack state
- [ ] Per placement, write down the three things you checked in the last two seconds before pressing submit (RQ1)
- [ ] Repeat the task keyboard-only; count the Tab stops and note any field you could not reach
- [ ] Trigger one rejection per class (correctable, limit, transient, exchange, protective-stop pending, no ack within 2 s); note the first thing you read and your next action
- [ ] Switch sizing mode both ways (qty → risk %, risk % → qty); note whether the computed result stayed visible
- [ ] Note where the stop-loss or the arm step cost you the most time or attention — verbatim; input for F13/F6/F17 copy, never a design change
- [ ] Note whether an open padlock read to you as "enabled" or as "unlocked / safe", and whether the glyph read as the state or as the action
- [ ] Try to make DEMO look like LIVE, or armed look like locked, in greyscale; note what still told them apart
