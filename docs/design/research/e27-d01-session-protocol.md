# E27-D01 — Session protocol: key custody, rotation and compromise (ready to run; the owner runs it later)

- **Companion to:** [`e27-key-custody.md`](e27-key-custody.md) (E27-D01, issue #732), "the report"; RQ-, H-, W-,
  F-, RA-, CP-, CD-, AD- and OQ- ids refer to it, as do the `path:line` pin and shorthand (report front matter), and a
  bare "§n" is a section of this file.
- **Status:** not yet run. Every duration below is an allocation inside a 45-minute session, not an observation; no
  participant, timing, count or quote exists. Synthesised findings, never a participant's real key practice, are
  appended to the report as a dated addendum (§8).
- **Ready to run: partly.** The interview (part A) and the comprehension probes (part C) can run on paper today. The
  think-aloud tasks (part B) need the report's board 06 and figures in a keyboard-operable medium, and none exists yet
  (report §1 and OQ-15, ruled on #732 in comment 6364262239: an HTML click-through built in the boards PR). Until one
  exists, part B runs as a paper walkthrough the moderator drives, and the keyboard-only pass (§6) waits.
- **Roles:** the moderator is never the participant. The owner is tagged **P1** on every sheet, because the owner also
  approves the report; someone else moderates the owner's session. An agent may read the prompts aloud but receives no
  answer: the owner answers to a human note-taker, and no answer reaches an agent, a chat or this repository (§2).

## 1. Who takes part (recruiting rule)

- **The owner** (P1 wearing the P4 hat, `10:175`) is the one participant every run needs: only the owner creates,
  rotates and revokes keys (`CON:769-771`; `10:299`).
- **Delegates the owner names:** account managers (P2, `10:106`) for the manager task only (T6), since a Manager has
  no key task; a viewer (P3, `10:143`) for T7 if one exists. Comparable self-hosted-tool operators (the ticket's "2 to
  3") join only if the owner names them; none is assumed.
- **Accessibility:** at least one session runs keyboard-only (§6). A screen-reader user is recruited if the owner
  knows one; otherwise the report's expert review (§13) stands in (ticket Accessibility notes).
- **Never fabricate a participant.** If fewer than five sessions run, the report's AC1 row stays open and states how
  many ran; a single owner session is a valid first run.

## 2. Consent and data handling

**Opening script (read verbatim).** "Some rules in CandleViewer are fixed and are not what we test today. We want to
learn how you handle keys, when you rotate them and what you would do first if one leaked — not whether those rules
should change." The script names no rule on purpose: the rules are what parts A and C measure, so the moderator states
them only in the debrief (§7).

**Consent script (read verbatim; no recording without a yes).** "We record the screen and the audio. Everything you will
see is made up: no real key, account number or address appears. Please never read a real key, secret or account number
aloud, and never show one on your screen. The recording and the notes stay on the owner's encrypted host — never in the
repository, Penpot, GitHub, RelayRoom, any chat or any AI tool — and are deleted once the findings are written up. Is
that all right?"

**Data rules** (ticket Security notes; E42-D01's rule, `E42-D01:967-972`, because `04` has none — report G-9):

- **Placeholders only:** the account labels `Main`, `sub_001`, `sub_002` and `demo-1` with the catalogue's placeholder
  UIDs (`14:2422-2425`); key ids shown as `...a1b2`; the egress IP `203.0.113.10`, a documentation address
  (`22:14851`). No real key, secret, UID or IP appears in any prompt, prototype, sheet or note.
- **Nothing connected:** no account is linked and nothing signs; the stimulus is the boards and figures, never the
  live app.
- **Screens:** before any screen share the participant closes exchange, password-manager and wallet windows, and the
  note-taker checks the shared screen first. A real credential that appears anyway stops the session: it is redacted
  from the recording before storage, the unredacted copy is deleted at once, and the participant is told to treat it as
  compromised. For an API key: in every case, delete it in Bybit's dashboard at once (C-12.12); if it is also stored in
  CandleViewer, freeze its account and revoke it there, then C-12.12's KEK rotation, session invalidation and
  exposure-window audit, and only then a new key (report §7 gives the order). While the freeze and the revoke are not
  yet served (`MX:1533-1539`, `MX:589-595`), the stored key then fails its checks: order entry turns read-only for every
  account until the key can be revoked here (#898) and a restart passes the check, and its account is disarmed (`RB:53`;
  `RB:30-31`; `23:4262`); follow `docs/ops/runbooks/key-selfcheck.md`. Never rotate it: a compromise takes the revoke
  path (`22:2830-2831`). For a password or a two-factor secret: change it.
- **Redacted** means every real credential location, tool, host, UID, IP and account label is removed, not only
  names.
- **Confidential** (ticket): recordings and notes stay on the owner's encrypted host, not in the ticket's "research
  repository", because this repository is public (report Deviation 4); transcripts quote fixture names only; both are
  deleted after synthesis, and the deletion is noted on #732.
- **AI tools:** none receives a recording, a note or an answer. Whether one the owner approves for Confidential data may
  analyse a redacted written summary is in neither E42-D01's rule nor `04`; it goes to the `04` owner with G-9 (report
  §16), and until that rule exists no agent pass runs (§7). If it is set, the consent script says so before any session
  it covers.

## 3. Session plan (45 minutes, remote; ticket Technical notes)

| Part                                | Minutes | Content                                                                  |
| ----------------------------------- | ------- | ------------------------------------------------------------------------ |
| Consent and primer                  | 3       | §2 scripts; "what we will look at today", naming no fact the probes test |
| A Interview (RQ1–RQ4)               | 10      | A1–A5 below                                                              |
| B Think-aloud tasks (RQ5, RQ8, RQ9) | 20      | T1–T5 for the owner; T6 or T7 instead for a manager or a viewer (§4)     |
| C Comprehension probes (RQ6, RQ7)   | 8       | CP-1..CP-6 (§5)                                                          |
| Debrief                             | 4       | §7                                                                       |

**Interview guide (part A; probes, not a script; never correct a belief during the interview).**

- A1 "Where do your Bybit keys live today, and who else could reach them?" (RQ1)
- A2 "Who makes a new key when a manager joins? Walk me through the last time." (RQ1)
- A3 "Once you paste a key into CandleViewer, what can CandleViewer do with it, and what can it not do?" (RQ2; note
  each belief against report F-1)
- A4 "When did you last rotate a key? If you have not, what stopped you?" (RQ3, AC3; sort every reason into RA-1..RA-7
  or a new category)
- A5 "How do you plan around Bybit's 48-hour rule?" (RQ4; note which reading the participant holds, report OQ-5)

## 4. Think-aloud tasks (part B)

Stimulus: the report's board 06 and figures in a keyboard-operable medium once one exists (report §1), else on paper
with the moderator turning the pages; fixture data only. Prompts are read verbatim; after a pause the moderator waits
15 s before helping, and only on request.

| Task                                               | Prompt                                                                                                                                                                      | Observe and record                                                                                                                                                                        | Scores               |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- |
| T1 Add a key (SCR-126)                             | "Add the key you made at Bybit for `sub_001`." The validating state runs 8 s, once as a bare spinner and once naming the check and its 12 s limit, in counterbalanced order | whether they look for a test before saving; where they look for the allowlist; for each rendering, the moment they call it stuck or would retry                                           | H8; F-2, F-4, F-18   |
| T2 Rotate (SCR-127)                                | "`sub_002`'s key is due. Replace it." Then the refused-new-key frame, then the switched frame                                                                               | what they expect for open orders; whether they name the delete at Bybit unprompted; how they read the overlap                                                                             | H3; RA-1, RA-6; F-8  |
| T3 Suspected compromise (SCR-128 → revoke dialog)  | "You think `sub_001`'s key has leaked. It holds two open positions. You have 60 seconds." The compromise card; the two choices, counterbalanced; then a refused revoke      | the first three actions in order, and whether the delete at Bybit waits on any other step; whether they reach for rotate; the branch, its reason (verbatim) and the order it was shown in | H5; F-10, F-11, F-21 |
| T4 Disable or delete (SCR-129)                     | "You will not use `demo-1` again. Remove it." Then read the delete warning (CD-5)                                                                                           | disable or delete; what they believe is gone and what stays                                                                                                                               | H7; F-12             |
| T5 Read the list (SCR-125)                         | "Is withdrawal off on every account right now? How do you know?" One key's check has failed                                                                                 | the answer and the cue they cite; whether they see both the row and the system banner                                                                                                     | F-5, F-6             |
| T6 Manager: a pending, then a failed key (SCR-079) | "Your account shows a pending key. When can you trade live?" Then the failed-key frame                                                                                      | what they expect to see and whom they would ask                                                                                                                                           | H1, H4; F-15, F-16   |
| T7 Viewer: the drawer (SCR-079)                    | "Tell me what this account is allowed to do."                                                                                                                               | which facts they expect a viewer to see                                                                                                                                                   | F-16                 |

The 60 seconds in T3 are a stated budget, not a trap: a participant who runs out is asked what they would have done
next and the task continues; no destructive gate in the prototype times out (`05` §3.1 rule 4).

In T3 also record whether they would wait for a flatten before the delete at Bybit, and why (report OQ-16), and,
after the refused revoke, whether they go straight to the Bybit delete (report §7).

## 5. Comprehension probes (part C; AC4)

For each of CP-1..CP-6 (report §8): show the candidate copy for 10 s, remove it, ask the restate prompt and record the
restatement verbatim. The moderator states no CP-1..CP-6 fact before its probe. Score it **understood** (it matches the
report's "understood if" column), **partially understood** (a part is missing) or **misunderstood** (it contradicts the
fact). Then show the CD seed that carries the same fact and ask "What would you do next?". The pass rule is AC4's: "any
statement misunderstood by more than one participant is rewritten and retested" — the rewrite goes to E27-D03's copy
deck and is retested in the next session. **Until a session runs, every CP row is unmeasured**; no score may be written
without one.

## 6. Keyboard-only pass (at least one session)

The mouse is disconnected for T2 and T3. In T2: tab through the stepper, complete each step, reach the countdown and
close the dialog (the rotation continues; there is no cancel after the switch, report AD-6). In T3: open the revoke
dialog and check that focus starts on Cancel (`14:2491`); choose a branch with the arrow keys; type the account label
and press Enter inside the field, which must not confirm (`E42-D02:144`); then confirm with the button. Record the Tab
count to each control, any control that cannot be reached, any step that needs a pointer or a hold, whether the
countdown speaks only at its thresholds (`15:366`), and where focus lands when the dialog closes (`05` §3.4 item 4).
With a screen reader, also record whether "value is write-only" is read with the secret field (`14:2459`) and whether a
refusal is announced once.

## 7. Measures and analysis

- **Per session:** the interview reasons sorted into RA categories; per task the action sequence, the branch and its
  reason, the error and recovery points and, in T1, the retry moment per rendering; per probe the score and the
  verbatim restatement.
- **Hypotheses:** H1–H9 are scored confirmed, refuted or not tested; H10 waits for launch data (report §14).
- **Two coders** (ticket): two independent affinity passes, then reconciled. The owner never codes their own session:
  its two passes are a second human's, if the owner names one, and an agent's, or two independent agents', each agent
  pass on a redacted written summary, and only once the `04` owner sets the AI-tool rule (§2; report G-9); the owner
  reviews the reconciled codes. Until then no agent pass runs: a named second human's pass codes the owner's session
  once, and with no second human it stays uncoded; either way the two-coder item stays open (report AC trace). A pattern
  seen in one session is a **signal**; in two or more, a **finding**. The owner's sessions keep the P1 tag through both
  passes.
- **AC4:** comprehension is unmeasured until run; once run, a statement misunderstood by more than one participant is
  rewritten and retested.
- **Debrief (4 minutes):** first the moderator states the fixed rules the session held back: CandleViewer never stores a
  key that can withdraw, never shows a secret again and never deletes a key at Bybit, a passing Test never ends a
  read-only state, and a suspected compromise is deleted at Bybit at once and revoked here, never rotated. Then: "Which
  rule cost you the most time today, and what would have made it read as protection?" Recorded verbatim; it feeds
  E27-D03's copy and is never a reason to change a locked rule (report §12).

## 8. The addendum rule

Results are appended to the report as "Addendum YYYY-MM-DD — sessions", never as a new document, and carry synthesised
findings only: the number of sessions run, the H2 and H5–H9 scores, the CP scores, the RA list as revised from the
owner's walkthrough (report §15: a category named there in general terms, never one from part A, with its design
response), new findings with their F-ids and the AC rows they close. A
changed recommendation names the AD it changes. No participant's real key practice — where keys live, who can reach
them, when one was last rotated or why not — enters the addendum, the report or #732: it stays in the Confidential notes
(§2). H1, H3 and H4 and every RA category a participant named in part A, a new one included, come from answers about
their own keys, so they stay there too, and the addendum names none of them, even without a count or attribution: with
one key holder, a category is that person's practice. The owner's walkthrough answers (report §15) are about the mocks
only and are synthesised the same way, and
the deletion of the recordings is noted on #732 and in the addendum.

## 9. Recording sheet (template; empty until a session runs)

Session id · date · persona (P1 / P2 / P3 / operator) · keyboard-only (y/n) · screen reader (y/n) · stimulus build ·
A1–A5 notes · RA categories named · T1: test-before-save sought (y/n), allowlist place, retry moment per rendering
(spinner, named) · T2: orders expectation, delete at Bybit named (y/n), overlap reading · T3: first three actions,
delete at Bybit at once, waiting on nothing (y/n), rotate reached for (y/n), branch, order shown, reason, flatten wanted
before the delete (y/n, why), step after the refused revoke · T4: choice, what is gone, what stays · T5: answer and cue
· T6 / T7 notes · CP-1..CP-6 scores and restatements · keyboard pass counts and blockers · debrief verbatim.
