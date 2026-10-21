# E35-D01 — Session protocol: deciding to trust an automated rule

- **Companion to:** `docs/design/research/e35-rule-arming-trust.md` (issue #860), "the report", whose ids (F-n, SC-n,
  OQ-n, CA-n, DJ) and sections ("report §n") are cited; "§n" is this file; `NN` is `docs/plan/NN-*`; AC1–AC3 are the
  ticket's three acceptance scenarios.
- **Status:** not yet run. **No participant, session, timing, score or quote exists**; durations are allocations in a
  45-minute session (ticket Technical notes); results go into a dated addendum to the report (§5). This file owns the
  session order, the correct answers written before any session (ticket Test plan), the codes K1–K11 and FB1–FB13 and
  the choice rule; the report cites them, and a change after S1 voids the scores.
- **Roles.** A neutral moderator: never the person who drafted the copy under test (ticket Technical notes), never the
  participant. The owner, a participant, does not moderate their own session: a manager who has done their own
  moderates it, else it runs **self-moderated**, a tagged exception to "never the participant"; a manager session the
  owner moderates is **owner-moderated** (DJ). A note-taker logs codes and feature requests; a second analyst codes.

## 1. Purpose, probes and what is locked

The sessions test what the owner and the account managers understand about an armed rule before E35-D02/D03 draw
SCR-084–086, and whether the plan's copy carries it. Persona statement (`10` §3), not a participant quote: "Not
knowing whether a stop is exchange-native or app-managed (and therefore whether it survives the app dying)".

- **Probe 1**: what a simulation result predicts (SCR-084; the ticket's "backtest bias"; report §2).
- **Probe 2**: an armed rule and the positions when "the backend" stops (SCR-085; report §3), as five events with
  their own answers (§5): **2.1 window closed**, **2.2 Bybit link lost**, **2.3 server down** (the ticket's "backend
  crashes"), **2.4 engine down** (the server up) and **2.5 feed stale**.
- **Probe 3**: what "(estimated)" on a detector metric means, and whether it changes arming (report §4).
- **Probe 4**: two rules that want the stop (SCR-086; report §5).
- **Journey** (report §6; `17` §1.5), **Terms** (trigger, condition, action, scope, simulate, arm, disarm; report §7)
  and the **keyboard pass** (K) of SCR-085.

**Locked, not tested** (report "Locked, not relitigated"; sessions test how to say these): the native stop-loss on
every position-opening order, rule-engine stops being "_additional_, never substitutes" (C-2.6, C-4.14); rules run on
the server, apart from windows and sessions (`11` US-ONB "Revoke all"); simulation before arming, server-checked
(`24` §11.7; `22` `setRuleMode`); DEMO by default, LIVE behind `rules:arm_live` (`24` §11.5 E12); R3 on Bybit demo
only (`30` §7); risk controls first (US-RULE-011); `(estimated)` and true history ranges (C-2.13, C-2.14).

## 2. Participants, consent and data handling

**Participants.** The closed user set of `10` §2–§3: the owner (P1) and the account managers (P2a/P2b, remote per
`10` §3), in 5–6 recorded sessions of 45 minutes, one per person (ticket Scope, Technical notes); no outsiders (ticket
Out of scope); with fewer than five people, run all and note it on #860. Record per person: role, automation used, any
rule armed, assistive setup (screen reader, magnifier or zoom, high contrast, keyboard only), colour vision. If anyone
uses an assistive setup, one session runs on it (ticket Accessibility notes); a participant who reports keyboard-only
use takes the keyboard pass (`10` names none; §3 assumes a manager with a colour-vision deficiency), else the owner's
session runs it. The owner approves this file and the report first (§6): an **informed** session, reported apart.

**Consent (verbatim; record yes/no for the recording and for public quotes).** "We are testing wording and screens,
not you. Nothing today places an order: the screens are mock-ups with made-up accounts. Do not show any exchange
account, and never say or type a password, an API key or a real 2FA code; where a screen asks for one, type 000000.
We record the screen and your voice; only the owner and one named analyst watch it, and a summary without names may
be analysed with an AI tool. It is deleted once the write-up is accepted. Short quotes without your name may appear in
a document anyone can read. You can refuse quotes, skip a question or stop at any time. Is that all right?"

**Data** (ticket Security notes; `04` §15.3 principles). Camera off; recordings and raw notes stay on the internal
research drive, encrypted, readable only by the owner and the second analyst (the ticket's "UX team"), never in the
repository or an external service, and are deleted when the owner accepts the read-out (`approved` on #860), noted
there. Quotes carry session ids (S1–S6), never a name, account id, balance or position. A real account on screen, or
a key, password or 2FA code said or typed, is a secret exposure: stop, delete it, follow `04` §10 IR-02. Pilot once.

## 3. Stimuli and how each is prepared

Build each stimulus from the report's defaults and copy as approved (§6 item 1), using Board 02 on Penpot page
`E35-D01` and any E35-D02/D03 frames, and note the version on each session sheet. Each frame also exists as text (an
HTML mock with real roles, or a read-aloud script) for assistive setups, shows the DEMO badge (`14` §0.5 item 1), uses
only the catalogue's fictional accounts "Main" and "sub_001" and BTCUSDT's 0.10 tick (`packages/fixtures/bybit/`).

- **ST1 — position card (Probe 2).** "Your BTCUSDT long on the Main account, in Demo: entry 62,000.0, stop-loss
  61,400.0. Two rules are on: 'BE after 1R' moves the stop to your entry plus 2 ticks when the trade reaches +1R;
  'Time stop' closes the trade if it is open too long and still below +0.2R." (The user's own rules, like SCR-080's
  "BE after 1R" row, here shown `ARMED-DEMO`; their logic copies the built-ins `sys.breakeven_at_1r` and
  `sys.time_stop`, both off by default, `24` §11.8; DJ; no "native", "backend" or banner.)
- **ST2 — event cards.** **2.3** "The computer that runs the CandleViewer server crashes. It is back ten minutes
  later." **2.1** "You close CandleViewer, every window, for the night. The server keeps running." **2.2** "The server
  keeps running, but its connection to Bybit drops for 20 seconds." **2.4** "The server and its link to Bybit work,
  but the part that runs rules has stopped; everything else works." **2.5** "Everything runs, but the market data the
  rules read stops updating for a minute."
- **ST3 — SCR-085 copy.** SCR-085 arming "BE after 1R" in Demo (DEMO preselected, not the mock's "(o) LIVE": SC-12)
  with, in one place and type, the plan sentence alone (CA-8), candidate A (CA-8–CA-10) or candidate B (report §3).
- **ST4 — SCR-084 partial result (Probe 1).** The catalogue mock for "ATR trail 2x" ("history available: 13 of 14 days
  (recording started 09-01)"; "fires 48 | stop moved 44 | flattened 0 | errors 0"; its timeline), with the `24` §11.9
  summary fields and the `22` example's `hypothetical_pnl_delta_usd: "412.80"`. A: no caveat; B: the required caveat
  (CA-1); C: SC-1's frame (CA-2–CA-5), the only one naming the day left out, 09-07 (CA-3; the plan names none, DJ).
- **ST5 — estimated detector (Probe 3).** SCR-085 for "Exit on stop run" (DJ: `stop_run_detected` → flatten), the
  plan's line in a "yes" form (DJ) "Uses estimated detectors? yes — stop_run_detected (estimated)", then CA-12.
- **ST6 — conflict (Probe 4).** User rules on the ST1 position: "BE after 1R" (at +1R, 62,600.0: stop to 62,000.2)
  and "ATR trail 2x" (ATR 150: stop to 62,300.0 at that bar close), report F18's pair; not built-ins, which E35-S07
  bands as risk controls. The SCR-086 frame as SC-10's default draws it (an ordered list, the risk band above it, a
  consequence per option, "arm anyway" behind an acknowledgement); the eight `24` §11.8 built-ins as cards.
- **ST7 — journey.** The J-a cards (§4) and a clickable lo-fi prototype SCR-080 → SCR-084 → SCR-085 → SCR-086 with
  SCR-085's states from E35-S08's Test plan plus pending (CA-16, CA-18); a manager sees LIVE disabled with its reason
  (SC-11 default; `14` §0.5 item 5). For K, the HTML mock or a Wizard-of-Oz deck (the participant names each key; the
  moderator shows the next focus): signals only, until E35-Q06 audits built software.

## 4. Session script (45 minutes)

Budget: opening 4 · Probe 2 12 · Probe 1 6 · Probe 3 4 · Probe 4 6 · Journey 6 · Terms 4 · debrief 3 = **45 min**;
whoever takes K (§2) runs it (6) instead of the Journey. Probes 1–4 are never cut (AC1 needs every score); if late,
cut 4c, then J-a to three cards, then Terms to arm, disarm, simulate. Rotation (S1/S4, S2/S5, S3/S6): events after 2.3
run 2.1-2.2-2.4-2.5, 2.2-2.4-2.5-2.1, 2.4-2.5-2.1-2.2; 2b's texts run plan-A-B, A-B-plan, B-plan-A; 1b/1c run B-C in
odd sessions, C-B in even. **Moderator rules:** explain nothing about where rules run, where stops live, "(estimated)"
or a term before the debrief (questions go on a parking card); neutral prompts only; never correct an answer in
session; think-aloud only in J-b and K; sorts need no dragging (`05` §3.1 rule 6). **Opening (4 min).** Consent (§2),
which says the screens are mock-ups; no primer on how CandleViewer works. Warm-up: "When did you last let software act
on a trade for you? What did you check?"

**Probe 2 (12 min), first and cold.** **2a (6 min):** read ST1, then card 2.3. Ask (1) "While this lasts, what happens
to the two rules?" (2) "And to your position and its stop-loss?" (3) "The stop-loss: (a) stays and still protects ·
(b) is cancelled or stops working · (c) works only while CandleViewer runs · (d) I don't know." (4) "How sure are you,
1 to 5?" (5) "Had 'BE after 1R' moved the stop to 62,000.2 before the crash, where would it be now?" (6) "The server
is back. Main's dead man's switch is set to notify only. What do the rules do, and about anything they missed?" Then
the other events in rotation with (1)–(4), and (6) for 2.2 ("The link is back. …"). **2b (6 min), AC2:** ST3, each
text in turn, under 2 min each: "Read this as you would before arming." (Q-a) "In your own words: what does this tell
you happens to this rule and to your positions, and when?" (Q-b) "You close CandleViewer for the night. Does this rule
keep working?" Reading back is not a restatement; ask once, "And what does that mean for you?" Close: "Which wording
would you want, and why?" (unscored).

**Probe 1 (6 min).** **1a (2 min), cold:** ST4 A: "This simulates the rule 'ATR trail 2x'. What does it tell you? If
you switch it on now, what do you expect over the next two weeks? What does '13 of 14 days' mean, and what happened on
the day left out? Where do these numbers come from?" **1b, 1c (2 min each):** B and C in rotation: "Read it as you
would before arming. In your own words, what does it tell you about what the rule will do from now on, and about the
day left out? Where do the numbers come from?" **Probe 3 (4 min).** **3a (2 min):** ST5, the plan's line: "What does
'(estimated)' mean here? Who works it out, Bybit or CandleViewer? Could it be wrong, and how?" **3b (1 min):** CA-12
in its place: "What does this tell you? Would you switch this rule on, in Demo or Live?" **3c (1 min):** "Some
simulation figures are also called estimated, such as 'estimated R impact' (US-RULE-009). Same kind of estimate?"

**Probe 4 (6 min).** **4a (2 min), cold:** ST6 cards: "'BE after 1R' is on and you switch on 'ATR trail 2x'. What do
you expect CandleViewer to do? At the 13:05 bar close the trade reaches +1R; 'BE after 1R' wants the stop at 62,000.2
and 'ATR trail 2x' at 62,300.0. What happens to the stop? What would you want to happen?" **4b (3 min):** the SCR-086
frame; the participant sets the order and says why. "At 13:05, which stop applies, and what happens to the other move?
Where would you see it?" Then: "Now the kill switch is engaged at 13:05, with 'ATR trail 2x' first in your list. Does
the trail move the stop?" Coded only: "At 13:20 only the trail wants to tighten. What happens?" **4c (1 min):** the
built-in cards: "Which of these act before your own rules, whatever the order?"

**Journey (6 min).** **J-a (3 min):** cards: restatement · accounts and symbols · Demo or Live · simulation and its
covered days · simulate-mode record · places orders or flattens · estimated detectors · conflicts · if the server
stops · the position's stop-loss · engine running · limits · firing log · how to switch it off · blank. "Before you
switch 'ATR trail 2x' on in Demo, which do you need, in the order you would look? Which more before Live? How would
you check them without a mouse?" (ticket Accessibility notes). **J-b (3 min), think-aloud:** the prototype from the
rules list to a Demo arm, blocked (CA-16), then ready, pending (CA-18), armed: "Stop me where you would give up, and
why." Record the point, the reason, what was read before confirming, whether pending was seen.

**Keyboard pass, K (6 min), mouse unplugged or the participant's own setup;** ask throughout "What are you checking,
and what is hard to reach?" (1) Reach "ATR trail 2x" and open its arm action. (2) Focus opens inside the dialog, the
restatement read as its description (`role="alertdialog"`, E35-D04; report §9d: on Cancel). (3) Arrow to LIVE; find
the confirmation fields by visible label and format hint (E35-S08 "Keyboard-only arming"; CA-17, SCR-006); `Enter` on
SCR-085's radios or rule-name field must not arm (in SCR-006 `Enter` submits the code, E09-D06 §5); a manager reaches
a disabled LIVE's reason. (4) Is the conflict warning announced? (5) `Esc` closes without arming; focus returns to the
row (`05` §3.4 item 4). (6) Arm in Demo: is pending perceivable without sight or motion until armed arrives (E35-S08
"Armed state is never optimistic")? Record per step: done, Tab stops, unreachable controls, announcements, focus
return, any time limit (`05` §3.1 rule 4; WCAG 2.2.1).

**Terms (4 min).** Cards in their catalogue context (SCR-081's "Scope", "Trigger [on bar close v]", "Conditions (all
of)", "Actions", "[ Simulate ]", "[ Arm... ]"; SCR-080's "disarm"), one at a time: "What does this word mean here?"
Then: "Do any mean something else in TradingView, DeepCharts, Bybit or another tool?" Then report §7's labels and
CA-20's states: "Which is clearer, and why?" (a preference). **Debrief (3 min).** "What would you need before a rule
acts on a live account?" Then say "CandleViewer is this app plus a server program connected to Bybit; rules run on the
server", answer the parking card and correct every false belief coded (§5): they trade real money.

## 5. Measures, scoring rules and read-out

**Correct answers, written before S1 (ticket Test plan).** A **pass** has the listed codes in the participant's own
words and no false belief (FB) of the probe; a **partial** (one code, no FB) is not a pass; the rest **fail**. **Probe
1** (AC1 step 1b). The result shows what this version of the rule would have done on the recorded days, with
modelled fills; it does not forecast what the rule will do or earn, and the day left out was not tested (SCR-084 Type
and "Caveat copy (required)"; `24` §11.9; E35-S05: "a rule-behaviour preview, not a backtester"; C-2.14). **K1** past,
recorded data: what the rule would have done, not what it will do. **K2** fills and money figures are modelled (coded
only). **K3** the day left out was not tested: no data, not "no fires" (09-07 where the stimulus names it).
Pass = K1 + K3. **FB1** it forecasts results, profit or R, or live will match it. **FB2** the fills or the PnL were
real. **FB3** the day left out had no fires, or all 14 days are covered. **FB4** it placed orders. **Probe 2** (AC1
step: 2.3 in 2a; AC2: 2b), per event:

| Event                      | The rules (K4)                                                              | The position and its stop (K5)                        | Return (K6, scored apart)                                                                                                                            | Sources                                                                  |
| -------------------------- | --------------------------------------------------------------------------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| 2.1 window closed          | keep running on the server; may move the stop or flatten while you are away | open; the stop stays at Bybit (a rule may tighten it) | none needed; the window reports what happened                                                                                                        | `11` US-ONB "Revoke all" and NFR; SCR-152 Behaviour                      |
| 2.2 Bybit link lost (20 s) | paused: nothing until the link is back and checked                          | open; the stop stays at Bybit and protects            | resume by themselves, check the current state once, replay nothing                                                                                   | `24` §11.7 "Disconnect guard"; `20` §11.1 F3; `28` §B9.3; `24` §11.5 E10 |
| 2.3 server down            | do nothing: no stop move, no flatten, no order                              | open; the stop stays at Bybit at its last level       | OQ-4 (SC-3) default: start again by themselves after reconciliation, replay nothing (`20` §11.1 F7); if the switch runs (SC-3), Main's only notifies | `24` §8.8 and rules 5–6; `13` §11 note; `20` §11.1 F7; US-RULE-013       |
| 2.4 engine down            | do not act: "armed rules are not evaluating"                                | open; the stop stays at Bybit, "unaffected"           | not stated in the plan                                                                                                                               | SCR-080 States; SCR-153                                                  |
| 2.5 feed stale             | stay armed; each evaluation is skipped as stale                             | open; the stop stays at Bybit and protects            | evaluate again on fresh data                                                                                                                         | `24` §11.5 E7: "Rules must never act on a frozen feed."                  |

Pass for an event: its K4 and K5 ("last level" includes a move the rule made: `24` §8.8 rules 5–6). K6 is scored
once OQ-4 is settled and never enters a pass, so no answer meets two correct answers. Twenty seconds is under the
30 s account-down time that calls the dead man's switch (`20` §7.2 `CV_ACCOUNT_DOWN_S`). After a crash, US-RULE-013
runs the account's policy "as soon as connectivity returns", but `20` §6.2 owes a boot episode only to an account
"still down after the restart" (no evidence for `CV_ACCOUNT_DOWN_S` once the boot pass tracks it), so whether 2.3
calls the switch is SC-3's (OQ-4); with notify only, K4–K6 are the same either way. **FB5** the stop is cancelled or
stops working when the server or the window stops. **FB6** a rule acts while the server is down, cut off or its engine
stopped (Bybit runs it; the trail keeps moving). **FB7** closing the window or signing out stops the rules. **FB8**
CandleViewer closes positions or cancels orders while it is down. **FB9** the stop goes back to an earlier level. In
2b a text passes when its Q-a meets row 2.3's K4 + K5 and its Q-b row 2.1's K4, with no FB (AC2 counts Q-a); a
question added for a further event a candidate names is coded, never part of the pass.

**Probe 3** (AC1 step 3a). CandleViewer infers the value from Bybit's trades and book with a heuristic (Bybit gives no
order-level feed): a guess that can be wrong, not a fact from Bybit (C-2.13; `25` §1 "Estimated"; SCR-058: "this is an
estimate, not exchange-provided fact"). **K7** worked out by CandleViewer, not reported by Bybit. **K8** it can be
wrong either way, so the rule can act wrongly or miss. Pass = K7 + K8. **FB10** Bybit reports it, or it is exact.
**FB11** it is exact but late, stale or rounded. 3b scores CA-12 the same way, never cold; its arming answer is a
preference (no precondition covers estimates: `22` `setRuleMode`; OQ-8). 3c is coded (modelled vs heuristic, SC-17).
**Probe 4** (AC1 step 4b). Arming the second rule surfaces the conflict; both stay armed only once the user sets the
order, narrows a scope, disarms one or arms anyway with an acknowledgement; a risk control goes first whatever the
order (US-RULE-011; SCR-086; E35-S07; `28` INV-B9-f). **K9** found at arming, an order needed (coded in 4a). **K10**
same moment: the stop the approved precedence gives (OQ-5 default: the tighter, 62,300.0, whichever is first; the
plan: the first in the list), the other move logged, not applied. **K11** the kill switch goes first: no rule moves
the stop after it (`24` §8.11 `disarm_rules`; `28` INV-B8-g). Pass = K10 + K11. **FB12** both moves apply, the last
wins, or it is random. **FB13** a rule placed first beats a risk control. 4a is coded **matches** the plan
(US-RULE-011, same tick) or **differs** (tighter wins, last wins, both, random, unsure); wants are preferences for
OQ-5. Not scored: 13:20 (report F19) and 4c, coded against SC-19's default (every enabled built-in is a risk control).

**Terms, journey and K.** A term reading is a **match**, **competing** (code its source: TradingView, DeepCharts,
Bybit, the one-click chart-trading arm CMP-229, demo or paper trading, other) or **unsure**; two or more competing or
unsure readings make a term **ambiguous** and reopen report §7 (OQ-15). Matches (`24` §11.2, §11.5 E1, §11.6, §11.9;
`22` `setRuleMode`; SCR-080): _trigger_, the event that makes the rule check its conditions; _condition_, the tests
that must be true for it to act; _action_, what it does when it fires; _scope_, the accounts, symbols, positions and
environment it may act on; _simulate_, run it sending nothing, recording what it would have done; _arm_, switch it on
to act by itself; _disarm_, switch it off, keeping it saved. Journey: per card, k of n "before Demo" and "before Live"
and its median rank; a card most need before Demo shows on SCR-084/085 without a click (report §6); an abandonment
point two or more name is a finding, matched to report §9c's events. K: per step, for E35-D04.

**AC2 and the choice rule.** Per tested slot (the SCR-085 sentence, the SCR-084 caveat) count passes per text as k of
n, n counting participants other than the informed owner, with cold passes (text seen first) beside them; a majority
is more than half of n (2 of 3, 3 of 4, 3 of 5; DJ). The read-out states, for the plan's SCR-085 sentence, how many of
n met row 2.3's K4 + K5 in Q-a with no FB (AC2) and recommends revised copy unless that is a majority. The text with
most full passes (Q-a and Q-b) wins, a tie going to the shorter; it is **binding** only with n ≥ 3, a majority of
passes and no critical fail (FB1 for SCR-084; FB5, FB6 or FB7 for SCR-085), else **provisional** and the owner decides
on #860 (OQ-1); a text retested on people already seen yields signals only. The read-out notes if cold passes alone
pick another text. A required sentence changes only by the owner's decision on #860 (SC-16, OQ-1), and E35-D05's copy
deck then freezes it ("a product decision requiring design and security review"). **AC3.** A finding contradicts the
planned design when a plan text fails this rule, a probe's AC1 passes are not a majority, a majority's cold answer
(2a, 4a) differs from the plan's behaviour, or a majority abandon at a step the design adds. Each goes on #860 before
E35-D02/D03 start (if they have, the day the read-out confirms it and before their sign-off, linked from their issues;
OQ-14) with the finding id, the evidence (counts, quote ids), the plan text it contradicts, the decision (keep,
change, defer), who decided and the consuming ticket; a declined finding is posted with its reason.

**Feature requests and analysis.** When a participant judges what the engine can do rather than what the screen
says, the moderator says once, "Noted for the product list; for now, what does this screen tell you?", and the
note-taker logs it verbatim with its time (ticket Technical notes); it never becomes a finding or moves a score, and
the owner files each after the read-out (editor requests go to E36/E37). The session sheet holds every §4 answer,
the §2 record, the stimulus version and rotation; the owner and a second analyst (a person, else an AI agent on
de-identified transcripts) code it apart, then reconcile to the stricter code. Counts are k of n, never percentages;
one participant's result is a **signal**, not a finding. **Read-out (a dated addendum to the report):** header
(dates, n, types, informed, owner- or self-moderated sessions, assistive setups, stimulus version, deviations) · AC1
pass, partial or fail per session and probe, with a design implication per probe · AC2 and the SCR-084 caveat by the
choice rule · Probe 2 per event (FB codes, K6) · Probe 3 CA-12 and arming choices · Probe 4 wants · journey cards,
order, abandonment points, report §9c events, `17` §1.5 scores kept or changed · terms · AC3 list · K for E35-D04 ·
hand-offs to E35-D02–D05, E35-S07/S08, E36/E37. Quote bank (empty until a session runs):

| Quote id | Session | Type | Probe or step | Verbatim          | Recording time | Codes | F / SC / OQ | Signal or finding |
| -------- | ------- | ---- | ------------- | ----------------- | -------------- | ----- | ----------- | ----------------- |
|          |         |      |               | not yet available |                |       |             |                   |

## 6. Owner walkthrough checklist (ready to post on issue #860; owner approval pending)

Approval by exception: tick an item to accept it; to override one, leave it unticked and comment its number and id.

1. [ ] Every SC and OQ keeps the report's recommended default (report §1a, §10), except those I list.
2. [ ] §5's correct answers, codes and choice rule are final; none changes after S1 (ticket Test plan).
3. [ ] §5's five Probe 2 events match how I expect CandleViewer to behave; the return after a restart follows OQ-4.
4. [ ] Candidates A and B for the SCR-085 sentence (report §3, OQ-1) and SC-1's SCR-084 frame (OQ-2) are tested
       against the plan text; a required sentence changes only by my decision on #860.
5. [ ] The defaults behind the stimuli: "(estimated)" and CA-12 (OQ-8), precedence (OQ-5), the blocked and pending
       copy (CA-16, CA-18), the LIVE confirmation (OQ-7), the terms (report §7) and the a11y notes (report §9d).
6. [ ] §2 is the data-handling policy, and I commented `approved` on #860 or left rework notes citing items and ids.
7. [ ] Once ST1–ST7 exist, I armed "ATR trail 2x" in Demo and noted the evidence I read, in order, and where I would
       have stopped; for each Probe 2 event I wrote what the rules and my stop do and compared it with §5.
8. [ ] I read SCR-084's partial result (what about the day left out?) and opened its no-history and failed states.
9. [ ] Keyboard only, I opened SCR-085, moved to LIVE, pressed `Esc`, re-opened and armed in Demo, noting Tab stops,
       announcements and focus return; I resolved the SCR-086 conflict and noted what told me which rule acts first;
       in greyscale and a deuteranopia simulation (`docs/design/_tools/cvd_sim.py`) the rule states still tell apart.
10. [ ] The pilot kept no data; a manager who had done theirs moderated mine (else tagged self-moderated), tagged
        informed; at least five sessions ran (or the shortfall is on #860), with any assistive participant.
11. [ ] AC2 and AC3 followed §5, each contradiction on #860 with its decision before E35-D02/D03 start; feature
        requests were filed apart; recordings and raw notes are deleted, and the deletion is noted on #860.
