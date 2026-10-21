# E33-D01 — Session protocol: configuring and trusting an emulated algorithm

- **Companion to:** the E33-D01 findings report in `docs/design/research/` (issue #857), "the report" below; RQ, F,
  SC and OQ ids are the report's. "§n" is a section of this file; a bare `NN` is `docs/plan/NN-*`.
- **Status:** not yet run. **No participant, session, timing, hit rate or quote exists**; every duration is an
  allocation inside 60 minutes. The report answers RQ1–RQ5 by heuristic evaluation; these sessions test it, and AC2
  (a caveat restated "in their own words") and AC3 (disputed defaults) need them. Results go into a dated addendum
  to the report (§5); its `(heuristic)` sections stay as written.
- **Roles:** the moderator is never the participant. The owner is participant **P1** (ticket Scope); someone else
  moderates that session, or an agent reads the script while a note-taker records. The owner may moderate the rest.
  The ticket's "existing research panel" and "research protocol and consent process" are documented nowhere (searched
  2026-10-21; E29-D01 OQ-12 records the same consent gap): this file is the protocol, §2 the consent script.

## 1. Purpose, research questions and what is locked

E33's four order types do not exist at the exchange; they work only while CandleViewer's backend is alive (ticket
Context). The sessions test whether traders understand that cost before E33-D02/D03 draw the builders and monitor.
Persona statement (`10-personas.md` §3; not a participant quote): "Not knowing whether a stop is exchange-native or
app-managed (and therefore whether it survives the app dying)."

- **RQ1** (B, C-f): which parameters do traders set, and which should default (slice count vs duration; visible
  size vs show-ratio; peg offset vs max chase distance)? Decides the defaults per strategy (AC3).
- **RQ2** (C-a–C-c): is "emulated / app-managed" read as residual risk or a technicality? Decides each caveat (AC2).
- **RQ3** (A, C-d, C-e): on disconnect, do they expect cancel everything, freeze or continue? The system's answer is
  `freeze` (`24-internal-schemas.md` §10.1). Decides the binding disconnect and resume messages.
- **RQ4** (D, F): what must the monitor show so that "nothing runs invisibly" (US-ALGO-010)? Decides SCR-070 rows.
- **RQ5** (E): the minimum pre-submit information — schedule preview, projected request rate, slippage estimate?
  Decides the SCR-066–069 pre-submit block.

**Locked, not tested:** the native exchange stop on every position-opening order (C-2.6, C-4.14); algos run on the
backend, never in the browser (E33 epic; `13-user-flows.md` §9); `freeze` stays the default, so RQ3 tests how to say
it (ticket RQ3); a risk halt never resumes without an explicit re-arm (E33 epic AC4); no built software is tested.

**Three "away" situations** (plan reading, Med; the report's case 1 = app-off, case 2 = Bybit-link-off, case 3 =
backend-off); the plan's copy ("algo pauses if the backend disconnects", SCR-066) covers all three, so Probe A runs
one vignette each. **app-off:** the app is closed or cut off; the backend keeps running the algo (`13` §9; US-ALGO-006
NFR). **Bybit-link-off:** the backend is cut off from Bybit; `freeze` sends nothing new and leaves orders at Bybit
working (`24` §10.1 rule 2; B5–B7 `WS_DISCONNECT`). **backend-off:** the backend stops; orders and native stops stay
at Bybit; a restart reconciles, then resumes or cancels (`20` §11.1 row F7). While it lasts, the app cannot tell
backend-off from app-off, so both show the same disconnect message (report §4).

## 2. Participants, recruiting, consent and data handling

**Participants.** The owner plus 4–6 active perpetual-futures traders: 5–7 remote sessions of at most 60 minutes
(ticket Scope; DoD "≥ 5 sessions"). Ask the account managers (P2a/P2b, `10-personas.md` §3) first, then traders
from the owner's network. Screener, kept on the session sheet (DJ = designer judgement):

- trades USDT perpetuals weekly (DJ); used a TWAP, iceberg, chase or OCO in any product in the last six months —
  all but at most one participant (DJ; the exception widens the jargon check);
- knows CandleViewer: no / seen it / uses it — at least one "no" (ticket Test plan); an E30-D01 session = "seen it";
- at least one keyboard-primary or screen-magnification user (ticket Accessibility notes; `10` §3 assumes a manager at
  125 % scale and keyboard-first, and one with a colour-vision deficiency); record the tool, zoom and colour vision;
- has not read the report or the E33 tickets — except the owner, tagged **informed** if the report came first (§5).

**Primer and consent (read verbatim; record two answers: recording yes/no, public quotes yes/no).** "CandleViewer
has two parts: the app on your screen, and a backend program on a server that connects to Bybit for you. We are
testing wording and screens, not you. Nothing today places an order: the screens are mock-ups and the positions
are made up. Please do not open or show any exchange account, and never say or type a password or API key. We record
the screen and audio. People working on this project watch it, and a summary with names removed may be analysed
with an AI tool. The recording is deleted when this study is signed off. Short quotes without your name may appear
in a public project document. You can refuse the quotes, skip any question or stop at any time. Is that all right?"

**Data handling.** `04-security-program.md` has no research section; this study applies its §15.3 principles:
minimisation (contact and screener answers only, camera off), purpose (E33-D01 only) and access (the owner and the
named second analyst). Recordings and raw notes are encrypted at rest, kept out of the repository and external
services, and deleted once the read-out is accepted (owner `approved` on #857), at the latest at E33 epic close (DJ;
§6 item 14). The repository is public: the quote bank and read-out carry session ids (S1–S7) only, never a name,
employer, account id, balance or position; a refusing participant's quotes are paraphrased and marked so. Mock-ups
need no credentials, demo or live, so nobody logs in; the moderator stops any exchange screen share at once; a key,
password or TOTP code on a recording is a secret exposure (stop, delete, follow `04` IR-02). An AI second pass sees
only de-identified transcripts. Pilot once with a colleague; keep no data.

## 3. Stimuli and how each is prepared

Build each stimulus from the report's recommended defaults and proposed copy at the version the owner approved (§6),
noting it on every session sheet; rebuild after any override. Every frame shows the DEMO badge (SCR-075) and only
synthetic positions. BTCUSDT tick 0.10, lot step 0.001, minimum order 0.001 and minimum notional 5 USDT come from
`packages/fixtures/bybit/2026-10-05/rest/instruments_before.json`; prices from `kline_BTCUSDT_1_page0.json` there, and
the copy's example prices are re-set to that range when the stimuli are built.

- **ST1 — paper prototype of the SCR-066..069 parameter sets (B).** One card per parameter of `24` §10.2–§10.5, the
  owner of the parameter model (`22` AlgoSpec differs), with the report's default on a separate reveal card; plus †
  cards for wanted fields with no backing field (TWAP spread guard, US-ALGO-006; TWAP start time, CMP-047 on
  SCR-066; iceberg show-ratio, SCR-067), which probe demand and are never drawn as controls (E33-D02 Test plan).
  Neutral names; no "emulated" label, caveat, CMP-158 notice or disconnect field, so Probe C's reading stays cold.
- **ST2 — competitor builders (B-d).** No public page could be read for this study (2026-10-21), so the owner
  captures the lead pages listed in the report's §7 (Bybit TWAP, iceberg, chase; Binance TWAP; OKX chase), with name,
  URL and access date and no account data, cropped to the parameter form: no text on where the strategy runs or what
  happens on a disconnect, so Probe C stays cold. Kept with the session materials, never in the repository.
- **ST3 — "the backend just died mid-TWAP" (A).** Frame 1 in plain text, no emulation label: a BTCUSDT TWAP buying 2
  BTC over 30 minutes in 10 slices (the US-ALGO-006 example), 4 of 10 filled, slice 5 resting at the bid, the long
  position with its native stop price; then one event card per situation. No banner, state change or caveat
  appears. The scenario is narrated, never staged by stopping a real process.
- **ST4 — terms and caveats (C-a–C-c).** Term cards "emulated", "app-managed", "client-side", "not
  exchange-native" (four of the plan's names for one idea), plus the report's recommended term if it differs; the
  report's caveat candidates per strategy in one type size, no styling cue, word counts on the moderator sheet.
  Strategy order rotates by session and candidate order alternates; three candidates rotate as pairs AB, BC, CA.
  OCO: candidate C is the entry-pair text; the exit-pair variant is read aloud in C-c only (preference, not scored).
- **ST5 — disconnect messages (C-d).** Per window text — lost the server (app-off and backend-off look alike, report
  §4) and Bybit-link-off — candidate A (the plan's wording) and candidate B (the report's proposed text), each over
  the ST3 frame with no event card naming the cause; for lost the server both sit inside SCR-152's three-line overlay
  and differ only in the algo line (A: SCR-070's "algos pause if backend down"; B: the report's line); the rotation
  gives each participant one candidate per text.
- **ST5b — resume messages (C-e).** Per situation, the report's proposed reconnect text and, where the plan has
  wording, candidate A (report §4), over the same frame after the return; the same rotation.
- **ST6 — monitor, SCR-070 (D, F).** TWAP, iceberg, chase and OCO rows: running, paused by you, paused after the Bybit
  link dropped, a TWAP whose window ended while paused (report SC-3), halted by risk control, failed, completed, and
  the two orphan order rows of report M10a and M10b; the degraded banner; the empty state; content per the report;
  field cards for D-b. Exported for 1920×1080 at 100 %, so a magnifier's zoom is real, and at 125 % (`10` §3), in
  greyscale and in the high-contrast theme for F (7).
- **ST7 — pre-submit cards (E):** one per item listed in Probe E, plus a blank card.
- **ST8 — keyboard build (F).** The E33-D02/D03 clickable prototype with the SCR-076 algo confirmation, else a
  Wizard-of-Oz deck (the participant names each key; the moderator shows the next focus). Signals only, until E33-D05
  and the a11y audit test built software.

**Moderator rules.** Questions on where an algo runs or what happens on disconnect go on a parking card, answered in
the debrief. No sort needs dragging: the participant names the card and the pile, and the note-taker moves it
(`05-accessibility-standard.md` §3.1 rule 6). Neither the primer nor a stimulus says which part runs an algo.

## 4. Session script (60 minutes)

Budget: opening, primer and consent 3 · warm-up 2 · A 8 · B 11 · C 15 · D 8 · E 5 · debrief 3 = **55 min**. The
keyboard-primary or magnification participant runs F (10) instead of E = **60 min**; if F cannot start by minute 47,
it becomes a separate 20-minute session. The disconnect scenario runs first, before anything explains emulation or
disconnects (ticket Test plan), so neither the parameter cards nor the competitor pages can prime it; the caveat comes
before the disconnect message, as in the product. No think-aloud during a restatement.

**Warm-up (2 min).** "Tell me about the last time you split an order up or chased a price. Which tool? What did you
set yourself?" Record tools, strategies and any incident. Show nothing.

**Probe A — the disconnect scenario, before any explanation (RQ3, 8 min).** Nothing about emulation, disconnects or
parameters has been shown. **A-a (4 min, backend-off, the ticket's scenario; always first).** Show ST3 frame 1 and
read: "This is a TWAP you started 12 minutes ago: buy 2 BTC over 30 minutes, in 10 slices. Four slices have filled.
The fifth is resting on the book. Your position has its stop-loss." Event card: "The computer that runs
CandleViewer's backend has just crashed. Your screen shows nothing new." Ask verbatim: (1) "What do you expect is
happening right now — to the TWAP, to the fifth slice, to your stop-loss?" (2) "What would you do now?" (3) Forced
choice: "(a) everything CandleViewer placed was cancelled · (b) nothing new is sent, and what is already on the book
stays · (c) the TWAP carries on as planned · (d) I don't know." (4) "How sure are you, from 1 to 5?" (5)
"CandleViewer comes back four minutes later. What will the TWAP do, and what about the slices it missed?" **A-b (2
min, Bybit-link-off)** and **A-c (2 min, app-off)**, order alternated, ask (1)–(4): "Another day, the same TWAP.
CandleViewer is fine, but its connection to Bybit drops for 20 seconds." / "Another day, the same TWAP. You close the
CandleViewer app for 10 minutes. The backend keeps running." Twenty seconds keeps the 30-second account-down rule and
its dead-man's-switch policy out of A-b (`20` §7.2 `CV_ACCOUNT_DOWN_S`; US-ACCT-010).

**Probe B — parameter sort (RQ1, 11 min).** B-a (6 min): per strategy, rotated, sort ST1 into "I set this myself",
"a default is fine", "unclear". B-b (2 min): per RQ1 pair (slice count vs duration; visible size vs show-ratio; peg
offset vs maximum chase distance): "Which do you set, and which may follow or default? What would you set for 2 BTC
on BTCUSDT?" B-c (2 min): for each "a default is fine" card, its reveal card: "Keep it, higher, lower, or would you
always set it?" Record any value given. B-d (1 min): ST2 for one strategy they use: "Does this ask for anything ours
does not, or the reverse? Would you move a card?" Record moves as "after competitor", apart from B-a.

**Probe C — caveat, restatement test, disconnect and resume messages (RQ2, RQ3, 15 min).** C-a (2 min): term cards one
at a time: "This word appears next to an order type: 'TWAP (…)'. What does it tell you about that order?" C-b (6 min):
per strategy, its ST1 builder layout with one caveat card in place: "Read this as you would on the builder. Now, in
your own words: what does it mean for you — what could go wrong, and what still protects you?" One neutral prompt is
allowed ("Anything else?"); then the second candidate, same question. C-c (1 min): "Which wording would you want on
the builder, and why?" — a preference, kept apart from the score. C-d (3 min): one ST5 candidate per window text: "In
your own words: what is happening to your TWAP and your position, and what can you do?" C-e (2 min): the ST5b card of
each situation, after the C-d card of its window text: "What happened while you were away, and is anything still
waiting on you?" C-f (1 min, RQ1): the policy card — "cancel this algo's working orders · freeze: send nothing new,
leave what is working · cancel everything and alert me": "Choose per algo, or one setting? Which?" (the plan disagrees
on whether this is a user choice). C-b, C-d and C-e are scored per §5.

**Probe D — monitor (RQ4, 8 min).** D-a (2 min), before ST6: "List what a panel must show for you to be sure no algo
runs that you don't know about." D-b (2 min): show ST6: "Is anything running here that you cannot see? How would you
know?" Then sort field cards into "in the row", "on demand", "not needed": type, symbol, account, side, environment
badge, progress, filled and remaining, average price, next action and countdown, state and its cause, who paused or
halted it, last reconciled time, child orders resting at Bybit, native-stop status, emulation tag, controls. D-c (2
min), on the three paused rows and the halted row: "Why is this one stopped? What makes it run again? What would you
do?" (the plan's one `paused` state has three causes and no stated trigger for leaving a freeze); answers are also
scored with K5 (§5). D-d (1 min): "You press Cancel on the TWAP row. What happens to its slice resting at Bybit?"
(US-ALGO-010: each algorithm's cancellation policy); "And if you close the position instead?" (report F29). D-e (1
min): "You are about to close the app. What tells you what keeps running?"

**Probe E — pre-submit information (RQ5, 5 min).** ST7: schedule preview table (SCR-066 A11y) · projected requests per
second against the account's remaining headroom, counting running algos (report §6; E33-S05) · slippage estimate
marked (estimated) (CMP-130) · total and per-slice quantity · expected finish time · end-of-window policy
(US-ALGO-006) · chase limit as a price · disconnect line · emulation caveat · native-stop notice (CMP-158) · account
and DEMO/LIVE badge (SCR-075). Sort: "must see before submit", "nice to have", "don't need"; then the top three in
order. Checks: slippage card, "Worked out from the book right now; the TWAP runs 30 minutes. What does it tell you?";
rate card, "It says: with your running chase, 4 of 4 requests a second. What would you do?"

**Probe F — accessibility pass (keyboard-primary or magnification participant, 10 min).** ST8 with the participant's
own setup, keyboard only or their magnifier at their zoom; in tasks (1)–(3) the focus ring is never hidden (`05` §3.4
item 6): (1) find the TWAP row and read its progress and next action; (2) pause it, then resume it; (3) cancel the
chase — the confirm names target and effect (SCR-070 A11y), and focus returns to the row (`05` §3.4 item 4); (4) with
focus on a row, find the degraded banner and the row's emulation tag at that zoom, with nothing lost or clipped (`05`
§5 item 7: WCAG 1.4.4, reflow per 1.4.10; CMP-118: text, not a tooltip); (5) tab through the TWAP builder to its
caveat and schedule preview table (SCR-066, SCR-067 A11y) while the moderator swaps in a "Waiting for Bybit" banner
card outside the magnified area (record if and when it is noticed unprompted), then submit and read the algo
confirmation at their own pace (record whether SCR-076's 20 s auto-cancel would have expired); (6) "Pause all": does
the confirm restate the count (SCR-070 sign-off)? (7) ST6 in greyscale, then in high contrast: "Which rows will act on
their own, and which wait for you?" (Paused by you, Waiting for Bybit and Halted by risk control told apart without
colour; E33-D05). Ask: "What did you have to pan or zoom to see? What did you miss?" Optional screen-reader pass: is
the degraded banner read once as a status, and is a halt heard once, as a summary (report §5; record only)?

**Debrief (3 min).** "What surprised you today?" Then explain the three situations and answer the parking card;
record reactions verbatim ("Is that what you would want?"). Thank, stop recording, note the stimulus version.

## 5. Measures, analysis, quote bank and read-out

**Session sheet.** Session id · date · type (owner, manager, outside trader) · informed · knows CandleViewer ·
assistive tech, zoom and colour vision · stimulus version · every §4 answer, verbatim where spoken. Codes: A
expectation cancel / freeze / continue / don't know / mixed; first action wait / act at Bybit / flatten / restart /
other; A-a return resumes / waits for me / cancels, missed slices at once / spread / skipped; F per task: done, Tab
stops, blockers; in (5) the banner noticed unprompted, and when, and the confirmation read inside 20 s or not.

**Restatement scoring (C-b, C-d, C-e).** **K1** who runs it: CandleViewer, not Bybit. **K2** what stops it: it acts
only while CandleViewer's backend runs and reaches Bybit. **K3** what still protects: the stop-loss held by Bybit.
**K4** the strategy's consequence — TWAP: no new slices are sent, a slice on the book can still fill, the schedule
falls behind. Iceberg: the visible slice can still fill and no new slice replaces it. Chase: the order stays at its
last price and stops following; it may fill there or not at all. OCO: the other leg stays live until CandleViewer is
back, so both can fill (two entries: twice the size). Disconnect message, lost the server: from here you cannot tell
whether the algo runs — if the server is up it continues; orders at Bybit can fill, the stop protects, and nothing
changes from this window until you reconnect; Bybit-link-off: nothing new is sent, and what is at Bybit stays — orders
can fill and the stop protects. **K5** (resume message) what happened while you were away and what waits on you: what
the run sent, filled or missed, whether it runs again by itself after a check with Bybit, and whether it needs your
action (a run paused because its account went down, or halted by risk control, waits for you). **Pass** = K2 and K4 in
the participant's own words (K4 alone for a disconnect message, K5 alone for a resume message), with nothing that
contradicts K1 or K3. **Partial** = one of the two (for a message, part of its code), no contradiction. **Fail** =
neither, or a false belief: FB1 Bybit runs it, or it carries on while the backend is down or cut off from Bybit; FB2
orders at Bybit were cancelled; FB3 there is no stop, or the algo is the stop; FB4 "emulated" means simulated or
paper; FB5 closing the app stops it; FB6 a run that waits for you carries on by itself. Reading the card back is not a
restatement; ask once, "And what does that mean for you?" The first candidate a participant sees for a strategy is the
**cold** reading; Probe A primes K2 but explains nothing.

**Choosing binding copy (AC2).** One rule for every binding text: per strategy for the caveat (C-b), per window text
for the disconnect message (C-d) and per situation for the resume message (C-e). The candidate with the most passes
wins; a tie goes to the one with fewer words. It is binding only if at least half its restatements pass (k of n) and
none is an FB1, FB5 or FB6 fail, each of which leaves a trader wrong about whether an algo is acting; a text or
situation with one candidate is held to that bar alone. Otherwise it is provisional, and the owner chooses between a
revised candidate tested in two more sessions and the provisional text (an open question in the report). Cold passes
are shown beside the totals; if they alone would pick another candidate, the read-out says so.

**Other probes.** C-a codes: risk-bearing (names a dependence on CandleViewer), technicality, simulated or paper
(FB4), don't know. RQ3: expectation matches the plan in a situation if at least half the forced choices give the
plan's answer, (c) for app-off and (b) for the other two; where it does not, the binding message must state the
difference. RQ4's "nothing runs invisibly" set is every field at least half the participants put "in the row";
RQ5's minimum set is every card at least half put in "must see before submit".

**Defaults (AC3).** A recommended default is **contested** when at least two participants (or a third, if more) want
another value, or the values given differ by more than a factor of two (DJ). The read-out states the disagreement,
recommends a default with its rationale and flags the parameter "revisit after the R3 soak" (`30-release-roadmap.md`
§7: demo, 7-day soak), naming what to read then: the value in the `algo.*_created` audit payload (SCR-066–069 Audit
lines); a parameter those payloads lack (for example TWAP catch-up or end-of-window policy) is named for E33-T02. No
default crosses a plan bound (chase reprice floor 200 ms, E33-S04; 450 children, `24` §10.1; TWAP slices ≥ 1 s apart,
E33-S03; iceberg visible size ≥ total ÷ 360, report SC-10; market slices only with a price limit or a participation
cap, the E33 threat model's SR-E33-03, Draft).

**Analysis.** Two passes, by the owner and a second analyst (a person where available, else an AI agent on
de-identified transcripts), reconciled. Counts are k of n, never percentages. A result from one participant is a
**signal**, not a finding. Informed owner data is reported apart and left out of the AC2 and AC3 counts.

**Quote bank (template; empty until a session runs).**

| Id  | Session | Type | Probe | Verbatim          | Recording time | Theme | RQ / F / OQ | Signal or finding |
| --- | ------- | ---- | ----- | ----------------- | -------------- | ----- | ----------- | ----------------- |
|     |         |      |       | not yet available |                |       |             |                   |

**Read-out template (a dated addendum to the report).** (1) Header: dates, sessions, participant types, who was new to
CandleViewer and who used keyboard or magnification, stimulus version, deviations. (2) Per RQ: answer, evidence
(counts, quote ids), finding or signal, screens affected (AC1), F ids confirmed or refuted. (3) Binding copy by the §5
rule, per strategy (caveat), per window text (disconnect message) and per situation (resume message): chosen text,
passes / partials / fails, FB1, FB5 or FB6 fails, cold passes, words, binding or provisional. (4) Defaults: strategy,
parameter, recommended default, keep / higher / lower / always set, values given, contested, rationale, R3-soak flag
and what to read. (5) Accessibility signals for E33-D05; OQ ids closed or opened. (6) Hand-offs: E33-D02/D03 (copy,
defaults), E33-T01 (config defaults), E33-X01 (residual risk), E33-D06 (exact copy).

## 6. Owner walkthrough checklist (ready to post on issue #857; owner approval pending)

Approval by exception: tick an item to accept it (yes); to override it (no), leave it unticked and comment with the
item number and the report id. Ticked items feed E33-D02/D03, E33-T01 and E33-X01. If you will be a participant,
run your own session before items 2–9, or it is tagged informed (§5).

1. [ ] Every source conflict (SC) and open question (OQ) keeps the report's recommended default, except those I list.
2. [ ] The report's disconnect and resume copy is provisional binding copy until steps C-d and C-e run, and it never
       says an algo pauses when only the app link is lost (app-off, §1).
3. [ ] The report's caveat for TWAP, iceberg, chase and OCO is provisional binding copy until step C-b runs.
4. [ ] One term names the emulation on every surface: the report's recommended term.
5. [ ] Claims about Bybit say "Bybit's API has no …", never "Bybit has no …": Bybit's own app lists iceberg, TWAP and
       chase orders (`docs/research/02-tradingview-trading.md` §2.1).
6. [ ] The TWAP row of the report's recommended-defaults table.
7. [ ] The iceberg row.
8. [ ] The chase row, with no "unlimited" chase distance and fall-back to market opt-in (E33-D02 Security notes).
9. [ ] The OCO row, sending the plain TP + SL case to Bybit's native attached TP/SL (`24` §10.2; E33-S01).
10. [ ] The report's default on whether the disconnect policy is a per-algo choice in R3.
11. [ ] The report's monitor rows, where every stopped row names its cause and what restarts it.
12. [ ] The report's minimum pre-submit set for SCR-066–069.
13. [ ] The report's viewer variant of SCR-070: controls disabled with the reason "Read-only role", never hidden
        (report SC-15).
14. [ ] §2 is this study's data-handling policy (deletion at read-out acceptance, at the latest at epic close).
15. [ ] I commented `approved` on #857, or left rework notes citing these item numbers and the report's ids.
16. [ ] Before S1: I opened the lead pages listed in the report's §7 (none could be read for the report) and
        confirmed or corrected its Low-confidence claims (where Bybit's TWAP, iceberg and chase run; a chase at its
        maximum distance; TWAP duration bounds) and checked what Sierra Chart's pages say about orders that need the
        platform running.
17. [ ] Before S1: ST1–ST8 are built from the approved version, and the pilot ran with no data kept.
18. [ ] After the sessions: ≥ 5 ran, including a CandleViewer newcomer and a keyboard-primary or magnification user.
19. [ ] Binding copy followed the §5 rule: a caveat per strategy, a disconnect message per window text and a resume
        message per situation, binding only where at least half passed and none was an FB1, FB5 or FB6 fail.
20. [ ] Contested defaults are stated, recommended and flagged for the R3 soak; defaults went to E33-D02/D03, E33-T01.
21. [ ] My acceptance of "emulated algos stop when the backend stops" (residual AS-D05 of the E33 threat model, §4.2,
        §11.2; queued on #2701) is recorded by the model's approval PR, with Probe A and C evidence for its input O-1.
22. [ ] Recordings and raw notes are deleted per §2.
