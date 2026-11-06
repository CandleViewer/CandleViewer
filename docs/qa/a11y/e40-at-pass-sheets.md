# E40 alerts: screen-reader pass sheets (E40-Q02, Part B)

**Owner-run.** An agent cannot drive NVDA or VoiceOver; the owner runs each sheet and attaches the
evidence (screen recording or speech-viewer log) to #1203. Expected announcements are quoted from
`docs/design/a11y/e40-alerts-a11y-review.md` (E40-D01; clause ids in the last column); the review is a
desk review, so every expectation there is PROPOSED until a pass confirms it. Where wording differs, log
a finding in `docs/qa/a11y/e40-alerts-audit.md` s8 rather than editing the sheet. Blocked until the
surfaces ship (E40-S01 #1129 and E40-S02 #1130); the webhook channel is flagged off and untested by design.

Passes: **P1** NVDA + Firefox (Windows) · **P2** VoiceOver + Safari (macOS) · **P3** Electron shell with
NVDA. Evidence slot per step: `P1 / P2 / P3` result (pass / fail / n.a.) and file name.

## S1 Single firing

Precondition: One alert fires with no announcement in the previous 60 s.

| #   | Step                                                            | Expected announcement                                                                                                     | Source           | P1  | P2  | P3  | Evidence |
| --- | --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- | ---------------- | --- | --- | --- | -------- |
| 1   | Fire one non-critical alert (info/warning) on a watched symbol. | One polite sentence: "Alert: {name}, {symbol}, {metric} {value}, {time}" (E40-D01 LR-1, AR-1). Toast does not take focus. | LR-1, AR-1       |     |     |     |          |
| 2   | Tab to the toast, read it, press Esc.                           | Toast closes; its row stays in SCR-014 (T-1); focus returns to the prior element.                                         | T-1, KM-6        |     |     |     |          |
| 3   | Open SCR-014 by the bell.                                       | Bell name "Notifications, N unread"; drawer heading read on open; list is `role=log`, not auto-read.                      | LR-6, LR-7, KM-1 |     |     |     |          |

## S2 Burst of 25

Precondition: 25 firings in one minute (about 2.4 s apart).

| #   | Step                                                | Expected announcement                                                                                                                                  | Source     | P1  | P2  | P3  | Evidence |
| --- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------- | --- | --- | --- | -------- |
| 1   | Fire the 25-in-a-minute burst.                      | Firing 1 announced in full; firings 2-20 not announced (counted); 21-25 storm-suppressed on the server, no outbox row (AR-1, AR-2).                    | AR-1, AR-2 |     |     |     |          |
| 2   | Wait for the window to close (60 s).                | One polite digest: "{n} alerts fired in the last minute; newest: {title}. Open Notifications to read them." Pre-G13 n is 19 or 20 (not deterministic). | AR-3, LR-3 |     |     |     |          |
| 3   | Open SCR-014 before the window closes (repeat run). | Pending digest is dropped; no announcement per row.                                                                                                    | AR-3       |     |     |     |          |
| 4   | Navigate the rows by arrow keys.                    | Each item readable on demand, including suppressed history in SCR-090 Triggered.                                                                       | AR-6, KM-2 |     |     |     |          |

## S3 Order rejection during chatter

Precondition: An order is rejected while the S2 burst is in its digest window.

| #   | Step                                            | Expected announcement                                                                                                                                   | Source     | P1  | P2  | P3  | Evidence |
| --- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | --- | --- | --- | -------- |
| 1   | Start a burst, then trigger an order rejection. | Rejection announced once, assertive, in full: "Order rejected, {code}: {plain-language reason}"; never digested, not delayed by the burst (LR-5, AR-4). | LR-5, AR-4 |     |     |     |          |
| 2   | Check the digest afterwards.                    | The rejection is not counted in the alert digest.                                                                                                       | AR-4       |     |     |     |          |

## S4 Drawer opens on a new event

Precondition: SCR-014 or SCR-092 drawer is opened while an event arrives.

| #   | Step                                                | Expected announcement                                                                        | Source | P1  | P2  | P3  | Evidence |
| --- | --------------------------------------------------- | -------------------------------------------------------------------------------------------- | ------ | --- | --- | --- | -------- |
| 1   | With focus in a form field, let an event arrive.    | Focus does not move; no drawer opens by itself (KM-1; SCR-014 "does not steal focus").       | KM-1   |     |     |     |          |
| 2   | Open the SCR-092 detail drawer from a toast or row. | Non-modal dialog; heading read on open by focus; context table read as a table with headers. | LR-4   |     |     |     |          |
| 3   | Close with Esc.                                     | Focus returns to the trigger.                                                                | KM-6   |     |     |     |          |

## S5 Settings matrix incl. locked row

Precondition: SCR-115 notifications matrix.

| #   | Step                                    | Expected announcement                                                                                 | Source      | P1  | P2  | P3  | Evidence |
| --- | --------------------------------------- | ----------------------------------------------------------------------------------------------------- | ----------- | --- | --- | --- | -------- |
| 1   | Tab into the matrix.                    | One Tab stop; cell name "{category}, {channel}, checked / not checked".                               | KM-9, LR-10 |     |     |     |          |
| 2   | Move with arrows and Space.             | Row/column headers announced on movement; toggle state announced.                                     | KM-9        |     |     |     |          |
| 3   | Reach a locked (critical override) row. | Focusable; description "Cannot be muted — critical"; checked and `aria-disabled`; Space does nothing. | NC-9, LR-10 |     |     |     |          |
| 4   | Save; send a test notification.         | "Saved" once; test outcome (shown / blocked by the OS / failed) announced once.                       | LR-10       |     |     |     |          |
| 5   | Use the sound preview.                  | Reachable by keyboard; "Playing {sound}" announced.                                                   | KM-10, LR-9 |     |     |     |          |

Sign-off (owner): name, date, result of each pass, deviations: pending.
