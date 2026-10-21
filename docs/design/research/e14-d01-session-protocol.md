# E14-D01 — Session protocol, screen-reader session, magnet harness and analysis sheet

- **Companion to:** [`e14-drawing-mental-models.md`](e14-drawing-mental-models.md) (E14-D01, issue #204), "the report". F#,
  AD-#, AM-# and OQ-# refer to it; a bare "§n" is a section of this file.
- **Status:** not yet run. Every duration is an allocation inside a 60-minute session, not an observed time; no participant,
  timing, count or quote exists. Results are appended to the report as a dated addendum, never as a new document.
- **Ready to run: partly.** Part 1 (contextual inquiry on the participant's own tool) can run now. Part 2 needs E14-D02's
  greyscale frames as a clickable Penpot prototype and the throwaway harness (§6); the screen-reader session (§5) needs a
  keyboard prototype (the E14-K01 spike, #356, or the harness extended with the CMP-191 flow) and NVDA 2024.x on Windows 11.
- **Roles:** the moderator is never the participant. The owner is a participant (ticket Scope), tagged **P1** on every sheet,
  and someone else moderates the owner's session, or an agent runs the script while the owner answers and a note-taker records
  (OQ-8). A note-taker attends every session.

## 1. Participants, consent and data handling

**Participants.** The owner (P1) and up to two prospective account managers (P2, `10` §3): three sessions, at least one of them
run keyboard-only with a screen reader (§5; ticket DoD and Accessibility notes). That participant must be able to write
drawings, so an Owner or a Manager (a Viewer cannot, report §6); record whether they use a screen reader habitually, since P3,
the persona most likely to (`10` §4), is read-only. Their session runs §5 in place of Part 2, and Part 1 only if their own tool
is accessible.

**Opening script (read verbatim).** "We are testing the drawing tools, not you, and there are no wrong answers. A few things are
fixed and are not what we are testing: the position tool never places an order, and anything it sends to an order ticket carries
a stop-loss held by the exchange. We want to learn how you pick, place, fix and tidy your drawings, and what you expect to
happen at each step."

**Consent script (read verbatim; no recording without a yes).** "We record the screen and audio. The recording stays on the
project's private Tailscale-only share, only the design group watches it, and it is deleted once the findings are signed off. A
redacted written summary may be analysed with an AI tool; the recording itself never leaves the share. Is that all right?"

**Data rules (ticket Security notes).**

- No production data, live accounts or API keys in any session. The prototype and the harness use the recorded-shape BTCUSDT
  fixture or the seeded synthetic series (§6); participants type no real notes or account details.
- Before any screen share in Part 1 the participant closes broker and exchange windows and any account, balance or key view; the
  moderator checks the shared screen before recording starts.
- Any account identifier, balance or key that appears anyway is redacted from the recording before it is stored; the note-taker
  logs its timestamp. Unredacted copies are deleted the same day.
- Recordings live only on the Tailscale-only internal share: never in the repository, Penpot, GitHub or chat. They are deleted
  when the owner signs off the findings (`approved` on #204), and the deletion date is written in the report addendum.
- An AI second pass works only on de-identified notes and transcripts the moderator has redacted (names, account ids, balances).
- After each session, within one working day: redact, file the sheet under its session id, log the redactions and their
  timestamps, and confirm in the sheet that no unredacted copy remains outside the share.

## 2. Pilot and pre-session checks

Run the whole script once with one internal participant before the first real session; keep no data. Check: (1) leading wording
(a task that names its answer, such as "use the magnet", is reworded); (2) the time per part against §4; (3) the harness gate on
the session machine (§6); (4) recording quality (30 fps screen capture, audible speech) and, for §5, that NVDA's speech viewer
log is captured. Correct the script, give it a version id, and write that id on every sheet.

Before every session, tick on the sheet:

- [ ] consent script ready; recording target is the Tailscale-only share; no other upload is configured
- [ ] the prototype build and the harness build are noted; the harness gate (§6) passed on this machine today
- [ ] the harness shows the fixture series, the §3 drawing set loads, and the clock and frame log write to the CSV
- [ ] the declared variants (§3) are filled in; the counterbalanced orders for Probes B and E (§4) are assigned
- [ ] for Part 1, the participant has closed broker, exchange and account windows; the moderator has checked the shared screen

## 3. Stimulus and declared variants

- **Part 1:** the participant's own charting tool (TradingView, Sierra Chart, ATAS or other), screen shared under §1's rules.
- **Part 2:** E14-D02's frames as a clickable greyscale Penpot prototype; the report's boards 03–06 as static prompts; the
  harness (§6) for Probe B.
- **Declared variants** (the report's recommended defaults, recorded on every sheet so a result can be read against them): keys
  per AD-1 (`Alt+L` trendline, `Alt+H` horizontal, `Alt+F` Fibonacci, `Alt+R` rectangle, `Alt+D` measure, `Ctrl+M` magnet);
  magnet `weak` at 12 CSS px (AD-4); revert to the cursor with "keep tool active" off (AD-2); the `Esc` ladder (AD-3); drawings
  shared across panes (AD-10); position tool entry → stop → target with risk in USDT first (AD-11).
- **Probe D density:** 200 drawings on BTCUSDT 1m, the B8 and SCR-037 density (report §5): a fixed seed, equal shares of the
  twelve tools in E14-Q01's `draw-mixed-24` set, anchors within the last three days, about 10 % locked and 10 % hidden (designer
  judgement). Until E14-Q01's seeded sets exist, the harness script generates it.

## 4. Session plan and probe sets A to E

Budget (60 min): opening, consent and primer 3 · Part 1, contextual inquiry 26 (CI-1 8, CI-2 6, CI-3 6, CI-4 6) · Part 2,
prototype and harness 29 (A 4, B 10, C 5, D 5, E 5) · debrief 2 = **60**. If the session runs late, drop CI-3 first, then CI-4's
note task, never Probe B or C. Think-aloud is welcome in Part 1 and in Probes A, C, D and E, never during Probe B's trials. The
predictions are pre-registered (`(heuristic)`, report §3–§5) so a result confirms or refutes them instead of becoming an
impression.

**Primer (read verbatim, 1 min).** "This is a chart for one symbol, BTCUSDT. The strip on the left holds the drawing tools. A
drawing is fixed to a time and a price, so it stays put when you zoom or change the interval. Nothing you do here touches a real
account."

**Moderator rules.** Never name a tool's key, the magnet mode or the expected gesture before the participant acts; answer "is
this right?" with "what would you expect?"; after a failure, wait 15 seconds before any hint and log the hint verbatim; record
what the participant does before what they say; and do not explain a design decision during the session (note the question for
the debrief instead).

| Probe                                   | Feeds                         | Task (say it verbatim) and stimulus                                                                                                                                                                                                                        | Record (exactly)                                                                                                                                                                                                                | Prediction and flip rule                                                                                          |
| --------------------------------------- | ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| CI-1 tool selection (own tool)          | AC1; Scope probe A; OQ-10     | "Show me how you put a trendline, a horizontal level, a Fibonacci and a rectangle on this chart, the way you normally do." Then: "Which drawing tools do you use every week, and which never?" "After one level, should the tool stay on?"                 | per tool: rail, hotkey (the exact chord), right-click or palette; click-click or press-drag-release; weekly or never per tool; stay-on expectation, verbatim                                                                    | the owner reaches for `Alt` chords (unverified premise, report §2)                                                |
| CI-2 editing and recovery (own tool)    | AC3; Scope probe C            | "Move this line, copy it, lock it, then delete it." With two close lines: "Move the upper one up a little, quickly." If the wrong one moves, wait; otherwise: "Now move the lower one by mistake and put it back."                                         | the recovery path verbatim (first key or click, then each step); time to recovery from the recording; what they expect `Ctrl+Z` to restore                                                                                      | `Ctrl+Z` first; flips if two of three go to the tree or redraw                                                    |
| CI-3 accumulation (own tool)            | Scope probe D                 | "Show me your busiest chart. What do you do when it gets cluttered?"                                                                                                                                                                                       | drawing count as self-reported (labelled so); hide, lock, delete and per-timeframe habits; tree use                                                                                                                             | hide-all before the tree (report §5)                                                                              |
| CI-4 position tool and notes (own tool) | Scope probe E; Security notes | "Plan one long trade with the long/short tool." Then hand over a neutral formatted snippet (a bold heading and a two-item list) and a link: "Paste this into a note. Now paste this link."                                                                 | the drag order used; the first number read; numbers visible without hovering; for the paste and the link, what they expected to happen, verbatim (formatting kept? link clickable?)                                             | risk or size read first (report §3 Q5)                                                                            |
| A hotkeys (prototype)                   | AC1; OQ-1                     | "Without looking at the rail, start a trendline." Then a horizontal level, a Fibonacci, a rectangle and a measurement. Then show the AD-1 keys: "Anything here you would trip over?"                                                                       | per tool the chord pressed (exact keys) and whether it matches AD-1, SCR-037 or TradingView; anything the press did instead; the trip-over answer verbatim                                                                      | `Alt+T` for the trendline; if two of three call the table opening a problem, OQ-1's alternative goes to the owner |
| B magnet (harness, §6)                  | AC2; OQ-2                     | "Place a horizontal level exactly at this swing high" (a marked bar), once per mode (off, weak 12 px, strong) in a Latin-square order; then "Place one exactly one tick above it" per mode. Then: "Which mode would you leave on?"                         | per trial: committed vs intended price in ticks; mis-snap (y/n, to which value); corrections (count; first press to final commit, from the harness log); snap noticed before commit (asked after); frame-log id; preferred mode | weak preferred; flip rules in report §3 Q1                                                                        |
| C editing and undo (prototype)          | AC3; AD-8                     | Frame: two lines 8 px apart, the upper one just moved by a drag, with the "from → to · Undo" line shown. "Something just changed. What happened, and what would you do?" Then: "Undo it. What came back?"                                                  | first action verbatim; whether the from → to line was read; what they expect undo to restore (position only, or style and lock too; in the other panes too)                                                                     | `Ctrl+Z` first; AD-8 holds either way                                                                             |
| D accumulation (prototype)              | Scope probe D; OQ-4           | The 200-drawing frame: "This chart is hard to read. Make it usable." Wait 15 s without prompting. Then show hide-all, lock-all, delete-all and the SCR-036 tree. Then: "You drew this level on the 1-minute chart. Should it be on your 4-hour chart too?" | first action; the bulk control chosen; reading of the delete-all confirm (count, locked kept); whether "200 drawings hidden" reads as hidden or empty; the sync answer, verbatim                                                | hide-all first; shared by default (flip rules in report §3 Q4, §5)                                                |
| E position tool (prototype)             | Scope probe E; OQ-5           | Frames for order A (entry → stop → target) and order B (entry → target → stop), counterbalanced: "Plan a long with the stop under this low." Then the over-cap frame: "What is this telling you?"                                                          | the order they expected; the first number named, verbatim; the numbers they need without hovering; the reading of the disabled send-to-ticket reason; whether the sizing account and environment line was noticed               | risk first; R:R becomes primary if two of three name it first                                                     |

**Orders (counterbalancing).** Probe B runs its three modes in a Latin square; Probe E alternates A and B:

| Participant | Probe B order       | Probe E order |
| ----------- | ------------------- | ------------- |
| P1          | off · weak · strong | A then B      |
| P2 (first)  | weak · strong · off | B then A      |
| P2 (second) | strong · off · weak | A then B      |

If the third session is the screen-reader session, Probes B and E run with two participants and SR5 (§5) covers the keyboard
case; the AC2 summary records the reduced count rather than padding it.

**Debrief (2 min, verbatim):** "Which part of drawing would cost you the most time on a busy day?" and "If you could change one
thing about how drawings behave, what would it be?" Thank the participant, stop the recording, and note the declared variants.

## 5. Keyboard-only screen-reader session (Probe F, 45 minutes)

**Set-up** (`05` §8.2 item 1): fresh profile, default hotkeys, default theme, the screen reader at default verbosity, keyboard
only with the mouse unplugged. NVDA 2024.x on Windows 11 with Chromium (`05` §8.1 row 3), or the Electron build once it has
drawing (`05` §8.1 row 1). Stimulus: the E14-K01 keyboard prototype or the §6 harness extended with the CMP-191 flow and a
`role="status"` region; record which, and its build id. Capture speech with NVDA's speech viewer log and the screen recording.

Budget (45 min): consent and set-up 5 · tasks SR1–SR10 30 · announcement variants 5 · SR11 and debrief 5. Give each task in
neutral words; never pre-fill or hint the expected key. Per task, mark **completed unaided / with a hint / not completed**, the
point where it broke, the recovery path verbatim, the speech verbatim and whether NVDA was in browse or focus mode. A task that
cannot be completed keyboard and screen reader only meets the P0 bar of `05` §8.2 item 5 for that screen.

| #    | Task (neutral wording)                                                                                                          | Record                                                                                                                                           | Report link                |
| ---- | ------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------- |
| SR1  | "Find the tool for a horizontal line without the mouse."                                                                        | path and keys; where focus landed                                                                                                                | report §6 step 0           |
| SR2  | "Start drawing a horizontal line." Once from the rail, once by its hotkey.                                                      | the arming announcement verbatim; focus afterwards; what the next `Enter` did                                                                    | F3; report §6 step 1       |
| SR3  | "Move to the price the moderator gives you" (60 USDT, 600 ticks, from the start).                                               | keys used and their count; whether announcements kept pace; overshoot; reading mode                                                              | F11, F16; report §6 step 3 |
| SR4  | "Place it."                                                                                                                     | how many `Enter` presses were tried; what the second one did                                                                                     | F3; report §6 step 4       |
| SR5  | SR3 and SR4 again with the magnet on                                                                                            | what was announced when the cursor reached an OHLC value; whether the participant expected the magnet to move the cursor (AD-5 says it does not) | AD-5                       |
| SR6  | "Cancel what you are doing", with a tool armed and nothing placed, with one trendline point placed, and with a drawing selected | each `Esc` outcome and its announcement                                                                                                          | F2; AD-3                   |
| SR7  | "Undo that", before and after a commit                                                                                          | what `Ctrl+Z` restored; whether the participant could name the object                                                                            | report §6 step 7           |
| SR8  | "Find your line again", first by Tab through the chart, then in the object tree                                                 | the order objects were met; the names heard; whether "item X of Y" was announced                                                                 | report §7 focus row        |
| SR9  | "Move it up a little, then a lot."                                                                                              | keys; announcements; how many undo steps the moves became                                                                                        | F12; AD-8                  |
| SR10 | "Delete it, then bring it back."                                                                                                | the announcements; where focus went after the delete and after the undo                                                                          | AD-12                      |
| SR11 | After the tasks: "How did you know which tool was active?" "What would you want to hear when you press Enter here?"             | verbatim only                                                                                                                                    | mode-change wording        |

**Announcement variants (after SR10; the ticket asks what a mode change should say).** Play each variant on arming, in a fixed
order that alternates across sessions, and ask "Which of these would you keep on all day?" Record the choice and the reason
verbatim, plus any variant the participant cut off before it finished.

1. Long: "Horizontal line tool on. Enter places it at the cursor. Escape cancels." (report §6, step 1) 2. Short: "Horizontal
   line on." 3. Tone only: no speech, an earcon on arming and disarming (needs the harness to play one; skip if it cannot)

## 6. Throwaway magnet harness (specification; not built in this PR, never promoted)

- **Purpose.** Probe B needs continuous snapping feedback during a drag, which static frames cannot show (ticket Technical
  notes). The harness is throwaway: it lives outside `main` (a scratch branch or the session machine) and is deleted with the
  recordings.
- **Scope.** One static candle series; a horizontal-level tool and a trendline tool placed click-click; three magnet modes: off,
  weak with a radius parameter of 8, 12 or 16 CSS px, and strong; snap candidates are the OHLC values of the bar under the
  pointer and its two neighbours (E14-S02); the snap marker and its value text appear before the commit. No persistence, no
  network, no sync, no other tool.
- **Data.** The recorded-shape BTCUSDT 1m kline pages `packages/fixtures/bybit/2026-10-05/rest/kline_BTCUSDT_1_page0.json` to
  `page2.json` (450 rows; documented shape, not a live capture, per `packages/fixtures/bybit/2026-10-05/manifest.json`), or the
  seeded synthetic series of `packages/chart-engine/bench/fixtures/bars.mjs` (the ticket allows a synthetic substitute). No
  account data.
- **Density.** Bar spacing of 4, 8 and 12 px (designer judgement; full candles need at least 3 px, `26` §3.6), with the §3
  200-drawing set preloaded for the frame-time check.
- **Logging (local CSV, no network).** Per frame, the `requestAnimationFrame` delta. Per pointer move, the event time and the
  time of the frame that drew the snap marker (pointer-to-marker latency, the input to report §13). Per trial: participant code,
  mode, radius, bar spacing, intended and committed price, ticks off, mis-snap flag, correction count, time from first press to
  final commit. Per session: browser, OS, display resolution and scale factor.
- **Gate.** Before each session a scripted 60-second drag across the densest setting must keep the 95th-percentile frame time at
  or under 17.2 ms (58 fps, the ticket's floor and SCR-037's drag target). A session that fails the gate is postponed; any trial
  with a frame above 17.2 ms is annotated "dropped frames" on the sheet, so harness latency is never read as a UX finding
  (ticket Performance notes).

## 7. Recording sheet, quote bank and analysis

**Sheet header:** session id · date · script version (§2) · persona (P1 owner, P2 manager, SR) · habitual screen-reader user
(y/n) · self-reported colour-vision deficiency and assistive technology · declared variants (§3) · stimulus build ids
(prototype, harness, keyboard prototype) · browser, OS and display scale. **Body:** one block per probe with the "Record" fields
of §4 and §5, plus moderator notes. Single-participant observations are marked **signal**.

**AC2 summary (empty until sessions run).** One row per participant and mode; never one participant's number as a baseline.

| Participant | Mode   | Trials | Mis-snaps         | Correction time (median, range) | Snap noticed before commit | Dropped-frame trials | Preferred mode |
| ----------- | ------ | ------ | ----------------- | ------------------------------- | -------------------------- | -------------------- | -------------- |
| P1          | off    |        | not yet available |                                 |                            |                      |                |
| P1          | weak   |        | not yet available |                                 |                            |                      |                |
| P1          | strong |        | not yet available |                                 |                            |                      |                |

**AC1 summary (empty until sessions run).** The chord pressed in CI-1 and in Probe A, per participant; the report's §2 table
takes these cells, and each divergence from AD-1 gets a keep-or-amend verdict there.

| Tool            | AD-1 key | P1 (CI-1 · A)     | P2 first (CI-1 · A) | P2 second or SR (CI-1 · A) | Verdict |
| --------------- | -------- | ----------------- | ------------------- | -------------------------- | ------- |
| Trendline       | `Alt+L`  | not yet available |                     |                            |         |
| Horizontal line | `Alt+H`  | not yet available |                     |                            |         |
| Fibonacci       | `Alt+F`  | not yet available |                     |                            |         |
| Rectangle       | `Alt+R`  | not yet available |                     |                            |         |
| Measure         | `Alt+D`  | not yet available |                     |                            |         |
| Magnet          | `Ctrl+M` | not yet available |                     |                            |         |

**Quote bank (template; empty until a session runs).**

| Id  | Session | Persona | Probe | Verbatim          | Recording time | F# / AD# | Signal or finding |
| --- | ------- | ------- | ----- | ----------------- | -------------- | -------- | ----------------- |
|     |         |         |       | not yet available |                |          |                   |

**Analysis.** Two independent affinity maps (the owner, and a second pass by another human or an AI pass over the de-identified
notes only), reconciled. With three participants a difference seen in one person is a signal, not a finding; the report's flip
rules decide each default. Each AD-n is then marked confirmed, amended or overturned with its evidence, every hotkey divergence
gets its keep-or-amend verdict from the AC1 summary, and any failed recovery in CI-2, C or SR7 is entered as a ranked friction
item for E14-D02. The results go into the report as a dated addendum; the owner's `approved` comment on #204 closes the round.

**Owner walkthrough.** The owner's own checklist (what to try in the Electron build, in TradingView and in the harness before
the sessions) is posted on #204; its answers feed OQ-1 to OQ-11 and are summarised in the same addendum.
