# E15-D01 — Discussion guide: a 45-minute contextual interview over the participant's own terminal

- **Companion to:** [`findings.md`](findings.md) (E15-D01, issue #205), "the report"; F, AD, OQ and C ids refer to it.
  Consent: [`consent-form.md`](consent-form.md). Notes: [`note-template.md`](note-template.md). Stimulus block:
  [`sync-stimuli.md`](sync-stimuli.md) and [`preset-cards.md`](preset-cards.md).
- **Status:** not yet run. Every duration is an allocation, not an observation; no participant, timing or quote exists.
  Results go into the report as a dated addendum, never into a new document.
- **Roles (ticket Test plan 2):** a facilitator and a note-taker in every session; the facilitator is never the
  participant. The owner is a participant (P1), so someone else facilitates the owner's session, or an agent reads this
  script while the owner answers and a note-taker records (report OQ-1).
- **Shape:** Part 1 is this interview on the participant's own terminal: blocks A (the working screen), B (docking) and E
  (workspaces and saving), the ticket's methods a and d. Part 2, about 20 minutes on the same day or another, is block C
  (sync stimuli) and block D (card sort), methods c and b, run from their own files. None of it needs a prototype.

## 1. Pilot (ticket Test plan 1)

Run Parts 1 and 2 once with one internal participant and keep no data. Check for leading wording (a task that names its
answer, such as "use the sync menu", is reworded), the time per part, that the stimuli read at 16 px or more on the
session screen, and the recording quality. Give the corrected script a version id and write it on every note sheet.

## 2. Pre-session checklist (tick each before recording starts)

- [ ] The consent form has been read and signed, and the answer to "may we record?" is yes.
- [ ] The participant has closed every API-key, key-management, funding, wallet and transfer screen, and any account,
      balance or position view the session does not need.
- [ ] The facilitator has looked at the shared screen before recording starts.
- [ ] The recording goes to the private research drive only; no other upload or cloud sync is running.
- [ ] A note sheet is open under the session id, with profile, displays, scaling and input mode filled in.
- [ ] The participant knows they may stop, skip, pause the recording or ask for more time.

## 3. Budget (Part 1, 45 minutes)

Opening 3 · A1 tour of the working screen 10 · A2 a session change 8 · B docking-need probe 8 · E1 switching setups 6 ·
E2 saving 6 · debrief 4 = **45**. If the session runs late, shorten E1 first, never A1 or B. Time limits are relaxed on
request (ticket Accessibility notes); the note-taker records any extension.

## 4. Facilitator rules

- Ask to do, not to say: the screen shows what is done, and anything only said is marked "stated" on the sheet.
- Never name a key, a sync axis, a preset or a drop target before the participant acts; answer "is this right?" with
  "what would you expect?".
- After a stall, wait 15 seconds before a hint, and log the hint verbatim.
- Do not explain or defend a design decision; keep questions for the debrief.
- The pause rule (§8) overrides everything else.

## 5. Script

**Opening (read verbatim).** "We are learning how you arrange and switch the screens you trade from; we are not testing
you. Please work as you normally do. Nothing here touches an order. If anything private shows on screen, I will pause the
recording straight away."

| Part         | Ask the participant to do (verbatim)                                                                                                                                                                                                                                                               | Record (exactly)                                                                                                                                                   | Prediction and flip rule (report)                                                                                   |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| A1 Tour      | "Show me the screen you trade from on a normal day: all of it, every monitor."                                                                                                                                                                                                                     | panels per monitor by type (chart, order-flow view, DOM, tape, ticket, positions, other), counted from the screen; monitors, resolution, scaling; floating windows | more than four panels for an owner-type profile (F12); if no participant shows more than four, F12 drops to Pri 2   |
| A2 Change    | "Show me what you change when the session changes, say into the US open. Do it now if you can."                                                                                                                                                                                                    | each change with its recording time, its trigger and its method (drag, menu, hotkey, preset, other)                                                                | saved layouts or presets, not docking (§4); two or more participants dragging panels mid-session flip §4's demotion |
| B Docking    | "Move your order book to the other side of your chart, the way you normally would." Then: "How often do you do that?" Then read: "Some tools let you move a panel with the keyboard: you pick a place with the arrow keys, press Enter to drop it and Escape to cancel. Would you use that? When?" | the method, observed; the frequency, marked stated; the move-mode answer, verbatim                                                                                 | arranged at setup time (§4, reduce); a participant who re-docks mid-session is a signal against demoting drag       |
| E1 Switching | "Switch to the setup you use for another session or market."                                                                                                                                                                                                                                       | tabs, menu, hotkey (which one) or separate windows; the word the participant uses for a setup (layout, workspace, page, other)                                     | documents with a faster layer inside (§5.1); two or more switching whole setups mid-session promote the cycle chord |
| E2 Saving    | "Show me how you keep this setup." Then: "You moved a panel by mistake and the app closed. What do you expect to see when you open it again?" Then: "Would you rather press Ctrl+S or never think about saving?"                                                                                   | the save method in their tool, observed; the expectation (saved automatically, last saved version, asked me, other) and the answer, verbatim                       | explicit save with recovery (§5.2); if half or more expect silent autosave, OQ-4 goes back to the owner             |
| Debrief      | "What costs you the most time when you rearrange?" and "If you could change one thing, what would it be?"                                                                                                                                                                                          | verbatim                                                                                                                                                           | none                                                                                                                |

**Part 2 order.** The sync stimuli come before the cards, so preset names cannot prime the sync answers; the
participant sees one configuration at a time and gets no feedback until all six are answered.

## 6. Keyboard-dominant variant (ticket AC4 and Accessibility notes)

Run Part 1 with the mouse put aside and replace B's task with four probes; give each in neutral words and never name a
key.

- **K1** "Without the mouse, get from your chart to your order ticket." Record the first key tried (`Ctrl+\`, `F6`,
  `Ctrl+Tab`, `Ctrl+Alt+arrows`, `Tab`, `Ctrl+K`, other) and whether it worked; a first reach for `F6` flips OQ-8's
  advertised key.
- **K2** "Without the mouse, move this panel to the other side." Record the route and where it broke.
- **K3** On the report's board 05 focus frame, or on the participant's own screen: "Which panel has keyboard focus now?"
  Record right or wrong, and what they looked at.
- **K4** "Leave this panel without the mouse." Record the keys and any point where focus was trapped.

Then ask, and record verbatim: "Does a key that cycles through the regions of a window, such as F6, match what you
expect here?"

## 7. 1280×800 variant (ticket AC4)

On the participant's own laptop at 1280×800 (record the OS scaling), run A1 and A2 as written and add: what they hide or
collapse to make room, anything clipped or overlapping, which panels they give up first, and whether they zoom. Show the
Part 2 stimuli and cards on that screen at 16 px or more. Write these findings up separately; never average them in
(report §7).

## 8. Pause-recording rule (ticket Security notes)

If an API key, a secret, a password field, an account id, a balance or a real position size becomes visible, the
facilitator says "Pausing the recording" and pauses at once. The note-taker logs the time and the kind of item, never its
value. Recording resumes only after the participant has closed it, and the paused segment and any frame showing the item
are cut before the recording is stored.

## 9. After the session, and the two-analyst rule (ticket Test plan 3)

Within one working day: cut and redact, file the notes under the session id, and log each redaction with its time. Two
analysts code the notes and recordings independently against the report's ids (F, AD, OQ, C and the card groups); an AI
pass may be the second analyst, on de-identified notes only, never on a recording. The codes are compared item by item:
where the two analysts disagree on more than one item in five within a part, that part is re-coded together from the
recording, never averaged. Anything seen in one participant only is a signal, not a finding. Results enter the report as
a dated addendum, each `(heuristic)` label they support becomes `(session: Pn)`, and the owner's `approved` comment on
#205 ends the round.

## 10. Participants and recruitment (ticket Scope)

The owner (P1) and four or five comparable multi-chart traders (five keeps the ticket's P1..P6 ids), scalper and swing
profiles mixed, with at least one keyboard-dominant participant and at least one on a 1280×800 laptop. `10-personas.md`
holds no research protocol and no 1280×800 persona, so recruit for both and record each on the sheet. The v1 population
(the owner, 0–5 managers and 0–3 viewers, `10` §0) limits how many can be insiders. If fewer than four external
participants join within the sprint, run with the owner and whoever is available, and the report says so at the top
(ticket AC5). Record any assistive technology or colour-vision deficiency only if the participant offers it.
