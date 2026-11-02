# E49-Q02 exploratory run 1: run record (agent baseline)

- Ticket: E49-Q02 (#1336), PR 1 (`Partial:`) · Run: 2026-11-01, 23:54 to 23:55 UTC (56 s of scripted
  exploration; about 15 min of trace and screenshot review after it) · Base: `origin/main` at `ca49e693a`
- Charters: `docs/qa/charters/E49-README.md` · Harness: `docs/qa/e49-exploratory-harness.md` (tier A)
- Session: `apps/web/e2e/exploratory/run-1.explore.ts`, 14 committed sessions plus one held in the private
  report (§1), all completed; egress guard clean.
- **Agent baseline sweep, not a human 90-minute charter session.** It satisfies no DoD box on its own:
  charters 7 and 8 were explored on their built surfaces, charters 1 to 4 and 6 at route level only,
  charter 5 not reached. No backend ran (no docker on the run host); this is not the 03 §17 staging
  environment and no testnet smoke was done.
- **Browser-with-stubs only; backend charters NOT RUN here (no docker) — first run on the demo stack;
  owner: the E27 lane at E29-K01's first attended run.**

## §0 Honest scope

| Area                                          | At the base                       | Consequence here                                    |
| --------------------------------------------- | --------------------------------- | --------------------------------------------------- |
| Shell, route guards, 403 / 404, rail, hotkeys | Built (E10)                       | Explored (C7, C8, keyboard-only)                    |
| Sign-in, settings, invites, hotkey editor     | Built                             | Landed and Tab-swept; no form submitted             |
| 61 of 66 manifest routes                      | Stub screens naming an owner epic | Landing, heading and badge only                     |
| OMS, algos, rules, fan-out, replay UIs        | Not built                         | Charters 1 to 4 and 6: route level only (E49-R1-09) |
| A mounted chart                               | Not built                         | Charter 5 not reached                               |
| Backend, fake exchange                        | Exist; need tier B (docker host)  | Not run; every server-side oracle untested          |
| View as (SCR-124)                             | Not built                         | O7.6 checked: no control to use (E49-R1-08)         |
| WebSocket                                     | No WS stub in tier A              | Connection region shows "Reconnecting" (E49-R1-04)  |

## §1 Run log summary

| Charter | Sessions | Notes | `ok` | `suspect` | `info` | Oracles applied                                              |
| ------- | -------- | ----- | ---- | --------- | ------ | ------------------------------------------------------------ |
| C7      | 5        | 271   | 117  | 137       | 17     | O7.1 (108 probes), O-ALL.1                                   |
| C8      | 3        | 396   | 198  | 198       | 0      | O8.1, O8.2 (66 routes × 3 roles; no note when held), O-ALL.1 |
| KB      | 7        | 36    | 14   | 11        | 11     | O-KB.1 (no trap), O-KB.2 (visible focus), O-ALL.1            |

Of the 346 `suspect` notes, 322 are one console message repeated on every page (E49-R1-02) and 20 are the
browser's "failed to load resource" lines behind E49-R1-03; the other 4 are the two
E49-R1-01 landings and two from the held session, which is reported privately (#5405). One C7
session is held in the private report. An earlier attempt of the same run stopped on the egress
guard (E49-R1-07); the record above is the second, complete attempt.

## §2 Debrief per charter

- **C7 Admin and RBAC (explored).** 9 spellings of 7 guarded deep links as Manager and Viewer (O7.1,
  108 landings: 106 denied, 2 in E49-R1-01): every spelling denied except one that is not a bypass
  (E49-R1-01). Other results: no admin data fetched while denied; rail and hotkey offer Admin to the
  Owner only; signed-out links land on sign-in. Not reached: see §4's carried list. Keyboard-only: the
  admin invite screen (below).
- **C8 Cross-feature (route sweep).** Every manifest route for Owner, Manager and Viewer: every shell
  landing passes O8.1 (198 of 198): every shell screen shows the Demo badge, and the public, chromeless
  screens (sign-in, invite, 404, offline, maintenance) carry none by design; every landing has a level-1
  heading (O8.2, no blank route). The interplay areas (alerts in replay, armed ticket, workspace
  restore, environment switch) are not built: not reached. Findings: E49-R1-05, E49-R1-06.
- **Keyboard-only segment (03 §12).** Sign-in, Appearance, Hotkeys, Security settings, Admin invite,
  Terminal stub, 404: every page cycles back to its first stop, no trap, every stop has a visible focus
  style (O-KB.1, O-KB.2 held on all seven). Dead ends: none.
- **C1 to C4, C6.** Route level only (E49-R1-09); none of their oracles could be applied.
- **C5.** Not reached; nearest evidence is E11-Q04 session 1 (2026-10-31).

## §3 Findings

| ID        | Charter   | Oracle                | Area                 | Steps                                                                                       | Expected                                              | Actual                                                                                                                                                                                               | Severity | Status                                                                                                                     | Evidence                                                        |
| --------- | --------- | --------------------- | -------------------- | ------------------------------------------------------------------------------------------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| E49-R1-01 | C7        | O7.1                  | Route guards         | As Manager or Viewer, open `/trade-groups/new;x=1`                                          | The owner-only R-142 screen is not shown              | Lands on the trade-group detail stub (R-141, open to every role) for an id spelled `new;x=1`; R-142 is not shown                                                                                     | n/a      | not-a-defect: the id route matched, no owner-only screen showed                                                            | `C7-admin--94d26`                                               |
| E49-R1-02 | all       | O-ALL.1               | Console              | Open any screen                                                                             | No console error (O-ALL.1)                            | One console line per page: the browser ignores one policy directive delivered in the page's meta fallback                                                                                            | n/a      | not-a-defect: the meta copy is the documented fallback (SR-112)                                                            | every session                                                   |
| E49-R1-03 | C7, KB    | O-ALL.1               | Signed-out bootstrap | Signed out, open a deep link                                                                | Redirect to sign-in                                   | Redirects to sign-in; the bootstrap's preference and keymap reads answer 404 from the preview server (no stub when signed out)                                                                       | n/a      | not-a-defect: harness has no signed-out stub for them                                                                      | `C7-admin--a021b`                                               |
| E49-R1-04 | C8, KB    | none: trace review    | Shell status         | Open any shell screen                                                                       | Connection state of a live stack                      | "Reconnecting" everywhere; Security settings shows its "Try again" error state                                                                                                                       | n/a      | not-a-defect: tier A has no WS or sessions-list stub                                                                       | `keyboard--86445`, `keyboard--a2939`                            |
| E49-R1-05 | C1-C8     | none: trace review    | Stub screens         | Open `/admin/users`, `/positions`, `/rules`, `/journal`, `/settings/notifications` as Owner | The placeholder names the epic that builds the screen | Headings name other epics: admin routes "E18" (Footprint; admin is E42), positions and trade groups "E12" (Bar builders), rules and alerts "E14" (Drawing tools), journal "E17", notifications "E11" | P3       | pending filing; originating ticket E10-T01 #235 (route manifest, closed); owner E49-S03 #1363                              | `C8-cross--4e79e`                                               |
| E49-R1-06 | C8, KB    | none: trace review    | Chromeless screens   | Signed out, open `/login`; signed in, open `/404`                                           | Default dark theme on every screen                    | Sign-in renders with browser-default form styling on a light page; the 404 card sits on a light page                                                                                                 | P3       | pending filing; originating tickets E09 #36 (SCR-001, hi-fi E09-D03 #132), E10-S04 #306 (404, closed); owner E49-S03 #1363 | `keyboard--bb9b7`, `keyboard-only-segment-03-§12-Tab-sweep-404` |
| E49-R1-07 | C7        | egress guard (C-13.5) | Harness              | Probe the deep link `//admin/users` with a relative `goto`                                  | The path is probed on the preview server              | The browser read it as a host; the egress guard aborted the request and failed the session                                                                                                           | n/a      | not-a-defect: harness fixed (absolute URLs); the guard worked                                                              | attempt 1 log                                                   |
| E49-R1-08 | C7        | O7.6                  | View as              | As Owner, open a user's detail and look for "view as"                                       | SCR-124 read-only impersonation, if built             | Not built                                                                                                                                                                                            | n/a      | not-a-defect: unbuilt, E42 #63                                                                                             | `C7-admin--38911`                                               |
| E49-R1-09 | C1-C4, C6 | none: unbuilt         | Unbuilt areas        | Open each area's routes for every role                                                      | A screen to explore                                   | Stub screens only (OMS, algos, rules, fan-out, replay)                                                                                                                                               | n/a      | not-a-defect: unbuilt, E29 #55, E33 #65, E35 #56 / E36 #62 / E37 #66, E34 #58, E26 #49                                     | `C8-cross--4e79e`                                               |
| E49-R1-10 | C7        | withheld              | withheld             | withheld                                                                                    | withheld                                              | withheld                                                                                                                                                                                             | n/a      | security-private: reported privately (#5405)                                                                               | private report                                                  |

Security: **1 security-class finding reported privately (#5405)** (SECURITY.md route); the detail is withheld
from the run report, and the public tracker states the requirement only.

Evidence paths are session folders under `apps/web/test-results/explore/run-1.explore.ts-<folder>/`
(video, trace, screenshot, session log); they are not committed and contain stub values only.

## §4 Counts and routing

| Severity / disposition  | Count                                    |
| ----------------------- | ---------------------------------------- |
| P0                      | 0                                        |
| P1                      | 0                                        |
| P2                      | 0                                        |
| P3                      | 2 (E49-R1-05, E49-R1-06; pending filing) |
| Security-class, private | 1                                        |
| Not-a-defect            | 7                                        |
| Undecided               | 0                                        |

- Routings: none to E46 (no perf probe ran) or E49-Q03 (no screen-reader probe). The two P3 rows are folded into
  E49-S03 (#1363, open) once filed; filing is the orchestrator's (filing freeze), and the closing PR records
  their numbers.
- Carried to the next run: C7 privileged actions, the server half (tier B), lock and step-up expiry,
  and two tabs with different roles; C1 to C4 and C6 on tier B
  once their screens exist; C5 on the bench pages; C8 interplay areas; the two bug bashes.
