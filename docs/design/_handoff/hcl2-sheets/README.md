# hcl-worker-2's board sheets, drawn by the hpe lanes

**READY (07:4xZ, 2026-10-23): #4180 batch 1 (30 boards, section below) for an idle hpe window, under the orchestrator's [DESIGN-THROUGHPUT] pull order (#4180, then #4193). Everything else stays on HOLD.**
**HOLD inside batch 1 (08:2xZ): rows 2 and 4, boards 03 and 06.** They still draw the forming bar 13:35 over 40 rows; boards 01, 02, 04 and 05 draw §4.1's five-level column (POC 64,011.0). Both are being regenerated; skip them and draw the other 28 in order. The fixed sheets come with batch 2. Earlier banner:

**HOLD (02:2xZ, 2026-10-23): draw nothing from this folder until the orchestrator names a batch for your window.**

- #4138 (E42-D03) and #4178 (E32-D02) are back in their standing-T2 gate (orchestrator, 01:38Z). The sheets of any
  board the fold changes will be regenerated here.
- #4070's and #4046's research boards are being drawn in hcl-worker-2's own window (since 01:5xZ, after [PENPOT-BACK]).

## What this is

RelayRoom part hcl-worker-2 (Anvil) prepared these Penpot board sheets for three design PRs:

- #4138: E42-D03, 23 boards.
- #4070: E35-D01, 6 research boards.
- #4046: E33-D01, 8 research boards.

Both hcl Penpot sessions are signed out. Under the orchestrator's [PENPOT-LOGIN] ruling (2026-10-22 22:56Z), the hpe
lanes draw these boards and export them in their own Penpot windows.

This folder is self-contained: every path is relative to it. It holds no Penpot host, team id, file id or URL. Pages
are named by page name only.

Every call is generated. A render agent never writes Penpot code by hand, except the small fixes that
`BRIEF-render.md` allows.

## What's in the folder

| Path | What it is |
| --- | --- |
| `tools/cvlib-v8.js` | cvlib v8, the Penpot build helpers, installed once per plugin session (`storage.cvd02`) |
| `tools/cvsheet-v4.js` | cvsheet v4.1, the sheet renderer (`storage.cvsheet`); `mkcall4.py install` prints it |
| `tools/mkcall4.py` | prints the exact `execute_code` body for each step; it reads `cvsheet-v4.js` from its own folder |
| `tools/compact.py` | compacts a sheet for cvsheet v4.1 and stamps `compactOf` (the original's path and sha256) |
| `tools/validate_sheet.py` | offline validator; its default `--tokens` is the `token-sync.json` beside it |
| `tools/components.offline.json` | approximate component inventory (`--components`) |
| `tools/token-sync.json` | the Penpot token dump that the validator checks names against |
| `sheets/<KEY>/` | the 37 original (not compact) sheets |
| `run/compact_all.sh` | validates and compacts every sheet into `run/compact/<KEY>/` on your machine |
| `run/.gitignore` | keeps `run/compact/`, `run/scratch/`, `run/STOP` and `run/shapes-since-reload` out of git |
| `BRIEF-render.md` | the brief for one render agent (one board per agent) |
| `MANIFEST.sha256` | sha256 and relative path of every other file, generated last |

Apart from `tools/validate_sheet.py`, the tools are byte-identical to hcl-worker-2's copies.
`tools/validate_sheet.py` changes only its default token path, from an absolute path to the file beside it, and says
so in its usage line.

## Order, pages, boards and PNG paths

Draw in this order, one board at a time:

1. #4138 boards 01–10. Board 09 (the tint proof) gates the rest of #4138.
2. #4138 boards 11–20, 93, 101 and 102.
3. #4138 boards 21–29, 94 and 103 (added 23:4xZ).
3a. #4138 boards 30–41 and 95 (added 01:2xZ, 2026-10-23: SCR-121 users list).
4. #4070's 6 boards.
5. #4046's 8 boards.

The pages are `E42-D03`, `E35-D01` and `E33-D01`. The render's `root` step creates a page that doesn't exist yet.

Each board is the root board named exactly by its sheet's `board.name`. Each PNG path is relative to the root of the
PR branch's checkout.

| # | PR | Page | Sheet (`sheets/…`) | Board name (`board.name`) | Sections | PNG path (from `export`) |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | #4138 | `E42-D03` | `E42-D03/01-shell-unlocked.json` | `E42-D03 / 01 CMP-087 / unlocked · 1280×800+2560×1440 · dark` | 9 | `docs/design/E42/img/E42-D03-01-shell-unlocked.png` |
| 2 | #4138 | `E42-D03` | `E42-D03/02-shell-5min.json` | `E42-D03 / 02 CMP-087 / 5min · 1280×800+2560×1440 · dark` | 8 | `docs/design/E42/img/E42-D03-02-shell-5min.png` |
| 3 | #4138 | `E42-D03` | `E42-D03/03-shell-1min.json` | `E42-D03 / 03 CMP-087 / 1min · 1280×800+2560×1440 · dark` | 9 | `docs/design/E42/img/E42-D03-03-shell-1min.png` |
| 4 | #4138 | `E42-D03` | `E42-D03/04-shell-expired.json` | `E42-D03 / 04 CMP-087 / expired · 1280×800+2560×1440 · dark` | 13 | `docs/design/E42/img/E42-D03-04-shell-expired.png` |
| 5 | #4138 | `E42-D03` | `E42-D03/05-shell-grace.json` | `E42-D03 / 05 CMP-087 / grace · 1280×800+2560×1440 · dark` | 3 | `docs/design/E42/img/E42-D03-05-shell-grace.png` |
| 6 | #4138 | `E42-D03` | `E42-D03/06-shell-per-action.json` | `E42-D03 / 06 CMP-087 / per-action · 1280×800+2560×1440 · dark` | 3 | `docs/design/E42/img/E42-D03-06-shell-per-action.png` |
| 7 | #4138 | `E42-D03` | `E42-D03/07-shell-after-idle.json` | `E42-D03 / 07 CMP-087 / after-idle · 1280×800+2560×1440 · dark` | 3 | `docs/design/E42/img/E42-D03-07-shell-after-idle.png` |
| 8 | #4138 | `E42-D03` | `E42-D03/08-shell-entry.json` | `E42-D03 / 08 CMP-087 / entry · 1280×800 · dark` | 3 | `docs/design/E42/img/E42-D03-08-shell-entry.png` |
| 9 | #4138 | `E42-D03` | `E42-D03/09-tint-proof.json` | `E42-D03 / 09 CMP-087 / tint-proof · 1280×800 · dark+light` | 5 | `docs/design/E42/img/E42-D03-09-tint-proof.png` (THEME-WINDOW) |
| 10 | #4138 | `E42-D03` | `E42-D03/10-shell-unlocked-light.json` | `E42-D03 / 10 CMP-087 / unlocked · 1280×800+2560×1440 · light` | 9 | `docs/design/E42/img/E42-D03-10-shell-unlocked-light.png` (THEME-WINDOW) |
| 11 | #4138 | `E42-D03` | `E42-D03/11-scr149-entry.json` | `E42-D03 / 11 SCR-149 / entry · 1280×800+2560×1440 · dark` | 3 | `docs/design/E42/img/E42-D03-11-scr149-entry.png` |
| 12 | #4138 | `E42-D03` | `E42-D03/12-scr149-verifying.json` | `E42-D03 / 12 SCR-149 / verifying · 1280×800+2560×1440 · dark` | 3 | `docs/design/E42/img/E42-D03-12-scr149-verifying.png` |
| 13 | #4138 | `E42-D03` | `E42-D03/13-scr149-wrong.json` | `E42-D03 / 13 SCR-149 / wrong · 1280×800+2560×1440 · dark` | 3 | `docs/design/E42/img/E42-D03-13-scr149-wrong.png` |
| 14 | #4138 | `E42-D03` | `E42-D03/14-scr149-read-only.json` | `E42-D03 / 14 SCR-149 / read-only · 1280×800+2560×1440 · dark` | 13 | `docs/design/E42/img/E42-D03-14-scr149-read-only.png` |
| 15 | #4138 | `E42-D03` | `E42-D03/15-scr149-expiry-mid-edit.json` | `E42-D03 / 15 SCR-149 / expiry-mid-edit · 1280×800+2560×1440 · dark` | 15 | `docs/design/E42/img/E42-D03-15-scr149-expiry-mid-edit.png` |
| 16 | #4138 | `E42-D03` | `E42-D03/16-scr149-not-saved.json` | `E42-D03 / 16 SCR-149 / not-saved · 1280×800+2560×1440 · dark` | 13 | `docs/design/E42/img/E42-D03-16-scr149-not-saved.png` |
| 17 | #4138 | `E42-D03` | `E42-D03/17-scr149-saved.json` | `E42-D03 / 17 SCR-149 / saved · 1280×800+2560×1440 · dark` | 9 | `docs/design/E42/img/E42-D03-17-scr149-saved.png` |
| 18 | #4138 | `E42-D03` | `E42-D03/18-scr149-outcome-pending.json` | `E42-D03 / 18 SCR-149 / outcome-pending · 1280×800+2560×1440 · dark` | 9 | `docs/design/E42/img/E42-D03-18-scr149-outcome-pending.png` |
| 19 | #4138 | `E42-D03` | `E42-D03/19-scr149-idle-lock.json` | `E42-D03 / 19 SCR-149 / idle-lock · 1280×800+2560×1440 · dark` | 11 | `docs/design/E42/img/E42-D03-19-scr149-idle-lock.png` |
| 20 | #4138 | `E42-D03` | `E42-D03/20-scr149-entry-light.json` | `E42-D03 / 20 SCR-149 / entry · 1280×800+2560×1440 · light` | 3 | `docs/design/E42/img/E42-D03-20-scr149-entry-light.png` (THEME-WINDOW) |
| 21 | #4138 | `E42-D03` | `E42-D03/93-scr149-unavailable.json` | `E42-D03 / 93 SCR-149 / unavailable · 1280×800+2560×1440 · dark` | 15 | `docs/design/E42/img/E42-D03-93-scr149-unavailable.png` |
| 22 | #4138 | `E42-D03` | `E42-D03/101-scr149-not-checked.json` | `E42-D03 / 101 SCR-149 / not-checked · 1280×800+2560×1440 · dark` | 16 | `docs/design/E42/img/E42-D03-101-scr149-not-checked.png` |
| 23 | #4138 | `E42-D03` | `E42-D03/102-scr149-challenge-ended.json` | `E42-D03 / 102 SCR-149 / challenge-ended · 1280×800+2560×1440 · dark` | 13 | `docs/design/E42/img/E42-D03-102-scr149-challenge-ended.png` |
| 24 | #4070 | `E35-D01` | `E35-D01/01-arming-journey.json` | `E35-D01-01-arming-journey` | 12 | `docs/design/E35/img/E35-D01-01-arming-journey.png` (`export`: `docs/design/E35/img/E35-D01-01-arming-journey`) |
| 25 | #4070 | `E35-D01` | `E35-D01/02-probe-stimuli.json` | `E35-D01-02-probe-stimuli` | 22 | `docs/design/E35/img/E35-D01-02-probe-stimuli.png` (`export`: `docs/design/E35/img/E35-D01-02-probe-stimuli`) |
| 26 | #4070 | `E35-D01` | `E35-D01/03-copy-annex.json` | `E35-D01-03-copy-annex` | 6 | `docs/design/E35/img/E35-D01-03-copy-annex.png` (`export`: `E35/img/E35-D01-03-copy-annex`) |
| 27 | #4070 | `E35-D01` | `E35-D01/04-terms-matrix.json` | `E35-D01-04-terms-matrix` | 4 | `docs/design/E35/img/E35-D01-04-terms-matrix.png` (`export`: `E35/img/E35-D01-04-terms-matrix`) |
| 28 | #4070 | `E35-D01` | `E35-D01/05-findings-decision-map.json` | `E35-D01-05-findings-decision-map` | 25 | `docs/design/E35/img/E35-D01-05-findings-decision-map.png` (`export`: `docs/design/E35/img/E35-D01-05-findings-decision-map`) |
| 29 | #4070 | `E35-D01` | `E35-D01/06-source-conflicts.json` | `E35-D01-06-source-conflicts` | 5 | `docs/design/E35/img/E35-D01-06-source-conflicts.png` (`export`: `E35/img/E35-D01-06-source-conflicts`) |
| 30 | #4046 | `E33-D01` | `E33-D01/01-three-cases.json` | `E33-D01-01-three-cases` | 13 | `docs/design/E33/img/E33-D01-01-three-cases.png` (`export`: `docs/design/E33/img/E33-D01-01-three-cases`) |
| 31 | #4046 | `E33-D01` | `E33-D01/02-caveat-candidates.json` | `E33-D01-02-caveat-candidates` | 14 | `docs/design/E33/img/E33-D01-02-caveat-candidates.png` (`export`: `docs/design/E33/img/E33-D01-02-caveat-candidates`) |
| 32 | #4046 | `E33-D01` | `E33-D01/03-parameter-defaults.json` | `E33-D01-03-parameter-defaults` | 13 | `docs/design/E33/img/E33-D01-03-parameter-defaults.png` (`export`: `docs/design/E33/img/E33-D01-03-parameter-defaults`) |
| 33 | #4046 | `E33-D01` | `E33-D01/04-monitor-must-show.json` | `E33-D01-04-monitor-must-show` | 29 | `docs/design/E33/img/E33-D01-04-monitor-must-show.png` (`export`: `docs/design/E33/img/E33-D01-04-monitor-must-show`) |
| 34 | #4046 | `E33-D01` | `E33-D01/05-pre-submit.json` | `E33-D01-05-pre-submit` | 9 | `docs/design/E33/img/E33-D01-05-pre-submit.png` (`export`: `docs/design/E33/img/E33-D01-05-pre-submit`) |
| 35 | #4046 | `E33-D01` | `E33-D01/06-findings-decision-map.json` | `E33-D01-06-findings-decision-map` | 16 | `docs/design/E33/img/E33-D01-06-findings-decision-map.png` (`export`: `docs/design/E33/img/E33-D01-06-findings-decision-map`) |
| 36 | #4046 | `E33-D01` | `E33-D01/07-source-conflicts.json` | `E33-D01-07-source-conflicts` | 5 | `docs/design/E33/img/E33-D01-07-source-conflicts.png` (`export`: `E33/img/E33-D01-07-source-conflicts`) |
| 37 | #4046 | `E33-D01` | `E33-D01/08-probe-a-stimulus.json` | `E33-D01-08-probe-a-stimulus` | 10 | `docs/design/E33/img/E33-D01-08-probe-a-stimulus.png` (`export`: `E33/img/E33-D01-08-probe-a-stimulus`) |

The research sheets (#4070, #4046) give a stem in `export`. The PNG path adds `docs/design/` in front where the stem
lacks it, and `.png` at the end. That gives the names their research docs plan:
`docs/design/E35/img/E35-D01-NN-<board>.png` and `docs/design/E33/img/E33-D01-NN-<board>.png`.

### Theme boards (THEME-WINDOW)

Boards 09, 10 and 20 are exported by the coordinator in a [THEME-WINDOW]. Token themes are file-wide, so a builder
never switches them. Board 10 and board 20 export under the light theme. Board 09's dark and light exports are composed
into its one PNG, as its sheet notes describe. Their render agents draw and lint them and return
`export deferred: THEME-WINDOW`.

The E42-D03 spec §0 also asks for greyscale and deuteranopia renders beside the export, for boards 01, 04, 09 and 10:
`<stem>-greyscale.png` and `<stem>-deuteranopia.png`, made by `docs/design/_tools/cvd_sim.py`. That is a PR-side step
after the export, not part of the brief.

## How to run

1. **Check the files.** From this folder, run `sha256sum -c MANIFEST.sha256`.
2. **Compact the sheets on your machine.** Run `sh run/compact_all.sh`. It validates every sheet and writes
   `run/compact/<KEY>/<file>.json`, then ends with `compact_all: 37 sheets, 37 compacted into run/compact/, 0 failed`
   and exit 0.
   - Each compact sheet's `compactOf` names your local original. `tools/mkcall4.py` refuses a compact sheet whose
     original went missing or changed; re-run the script then.
   - Never commit `run/compact/`: it holds your machine's absolute paths.
3. **Launch one agent per board,** in the order above, one after the other. Your Penpot window draws one board at a
   time. Prompt each agent:
   `START WORKING IMMEDIATELY WITH TOOL CALLS. Your instructions are in <F>/BRIEF-render.md: read it with the Read tool, then do its task exactly. F=<this folder's absolute path> SHEET=run/compact/<KEY>/<file> SLOT END=<HH:MM>Z REPO=<your checkout of the PR branch>`.
4. **Stop the queue on any status other than `built`.**
   - `partial` or `failed`: read the agent's error.
   - `not-writer`: tell the orchestrator and hcl-worker-2.
   - `needs-reload`: reload your own Penpot tab, write `0` to `run/shapes-since-reload`, then relaunch the same board.
   - `paused-slot-end`: relaunch later. Section calls are idempotent, so a relaunch continues where the board stopped.
5. **Pause.** Create `run/STOP`; agents stop at their next slot-clock check. Delete it to resume.
6. **Report each board** to the orchestrator and hcl-worker-2 in RelayRoom: board id, page id, PNG path, lint counts
   and any `SHEET-FIX:` lines. Committing the PNGs to the PR branches is up to your lane's main session, as the
   orchestrator directs.

Some boards may already exist on their page: E35-D01 board 04 is an earlier test board, and other boards may be
partial renders. The `root` step reuses a root board with the exact name, and the section calls replace its sections
in place, so continue rather than delete. Two root boards with the same name stop the render
(`duplicate root boards named …`, or `root boards named like this: 2`); report that.

## About the sheets

- **Only `board` and `sections` are drawn.** `notes` (sources, deviations, live checks) is read by people and by the
  QUALITY step, never drawn.
- **Path scrub.** 13 research sheets had hcl laptop paths in `notes` (keys `source`, `generator`, `notes`,
  `notes_md` and `worktree`). Those prefixes were replaced, and nothing else changed:
  - a PR worktree prefix → nothing, leaving the repo path `docs/design/research/...`;
  - a bare worktree path → `<#860 worktree>` or `<#857 worktree>`;
  - the lane's scratch prefix → `<hcl-worker-2 scratch>/`.
  `board`, `sections` and `export` are unchanged, and every call generated from these sheets is byte-identical to the
  hcl lane's (see "Checks run before shipping"). The other 24 sheets are byte-identical to hcl-worker-2's copies. Added at 23:4xZ: #4138's boards 21–29, 94 and 103 (11 sheets); one of them, `E42-D03/21-scr120-loading.json`, had a scratch path in `notes` replaced the same way (original sha256 `7f16f9b7e903…`), the other 10 are byte-identical.

  | Sheet | sha256 of hcl-worker-2's copy | sha256 here |
  | --- | --- | --- |
  | `E35-D01/01-arming-journey.json` | `29b432976e0498805c353963395e6771aa21c22164a5dd73f8c4a7c1e9f61831` | `67039b0e132bb29bfb5885d6c665156f62fa3922ee0a279705e9e0811a3c8be8` |
  | `E35-D01/02-probe-stimuli.json` | `4e0a90856ce5280d667bd4582dcb355af7bbda57803e68f2c3cf868ea3917907` | `16f1b64232f5142e87741ed24ee05ea78e00294b8caff18e200cf3ebbb3fa0c8` |
  | `E35-D01/03-copy-annex.json` | `d3031e9fffc89c15d1119c7848d8c063f94577cb4c5b8a381a8e59b4c6002ff7` | `6c3ea640b2f2da196d5e9d893d0158a22f2f5f5cad62e8a79f7d713e20d9e176` |
  | `E35-D01/04-terms-matrix.json` | `ec672efda74f548d63c621f251aece72a86dc861d628ddc5d2e7eadfc7dcf5bc` | `4fce2aec1d754fdeb4c2f162dab02b0a68dabd3d93d175fb550e901a79712128` |
  | `E35-D01/05-findings-decision-map.json` | `a3efa327ec713778a6044a616936be711bc10f8563b5048b2e548592a20eaa56` | `ebf640e8a9975925517b0531949f1785c12d4e7404acb5b4f3c7fc507fedf291` |
  | `E35-D01/06-source-conflicts.json` | `55077beb87e28c9050a072dedb8558e9e0901c55c6abea24bd619790bd5e42a0` | `60851065581797624558aab54d035e6cfed8c17ab0a8dd60ee8ea3785102d2d1` |
  | `E33-D01/01-three-cases.json` | `196d82d98a9879f8771fb6af579d812cb687db088ce49c5e5b99455d8b924bd4` | `e4b199b52c738f7c42d1a2fbd74e13afe34e149188daa07c791ddcad02f7e703` |
  | `E33-D01/02-caveat-candidates.json` | `c0836c641a1c662de6d0fa0574e9c935756ca1d08c422b9193afb9468c975eb7` | `d8b32bc69347ee24b8bf0efbbfd7586f44aa0fcf7f17491930caf9e88533c57d` |
  | `E33-D01/03-parameter-defaults.json` | `8427998d37f35b93cbb95d1fbbff681503356bda290e3514769cf8f86ce45b19` | `ed190a7327d14c226246511017cc79c828ab26b4906ca8a0436e3209c51efad3` |
  | `E33-D01/05-pre-submit.json` | `1519a4eebdc3156f20de7b3c74ef89b1704d69d61de523288ace6fdf18f18099` | `8bba03a702edaf095ad910675fd3e468189da7426ab9e208eb16e118f873d0cf` |
  | `E33-D01/06-findings-decision-map.json` | `a22a7e3e5c0a4d9f1b8d782a859a8def189461d827bacce3de670001898c5834` | `da079e802bac24884670e5aec42422ef8687861953f17ca74d27618fa8b752c7` |
  | `E33-D01/07-source-conflicts.json` | `27d939cb8ec0007ec2c1072942bccb3b278dafaf538e5e03e46bd0ee29bfa8e9` | `39c7ba52e132214403291827aa138ff79b8dc6da907dd207efcdacf6ed8c568a` |
  | `E33-D01/08-probe-a-stimulus.json` | `3bcf58b60a94c6da806f75c10fd9a81fa7bfc1aab37279a0189b69ed8589429e` | `04e50e653908ed40706d4dd52eca9ac30adbd724ad5bd98a2cb972f9e8ec7d9c` |

- **Sample data.** The CMP-087 and SCR-149 boards show the E42-D03 spec's worked-example data (spec §1), including the
  owner's handle. It is design copy and is drawn as is.
- **Validator warnings.** The validator also prints warnings (sheet and section sizes, Tier-1 primitive sizes). Only
  errors fail it.

## Checks run before shipping

- **Validation.** `python3 -I tools/validate_sheet.py <sheet> --components tools/components.offline.json` gave exit 0
  and 0 errors for all 37 sheets, with and without `--components`.
- **Selftest on a copy of this folder at another path:**
  - `sh run/compact_all.sh` compacted 37 of 37 sheets.
  - `python3 -I tools/mkcall4.py run/compact/E42-D03/01-shell-unlocked.json` with `root`, `install`, `0` and `lint`
    each printed JavaScript (it parses with `node --check` inside an async function) and exited 0.
  - The `root` call's GUARD requires cvsheet 4.1:
    `if (!storage.cvsheet || storage.cvsheet.v < 4.1) return { needSheetLib: true };`.
  - The compact sheet's `compactOf` names that copy's own original.
  - After one byte was appended to that original, and again with it missing, mkcall4 refused ("stale compact
    sheet", exit 1). With the original restored, mkcall4 worked again.
- **Identity.** For all 37 sheets, every generated call was compared with the call from the hcl lane's own compact
  sheets, for every step (root, install, each section, touch, relayout, report, lint). All 596 of 596 are
  byte-identical.

## Manifest

`MANIFEST.sha256` lists the sha256 and relative path of every file in this folder except itself, in `sha256sum`
format. It was generated after every other file. Verify the folder with `sha256sum -c MANIFEST.sha256`. The manifest's
own sha256 is in the transport message.

**Update (00:3xZ, 2026-10-23):** #4138's boards 24, 26 and 27 were regenerated for the orchestrator's Q11 ruling (#960 comment 6353767685): the reassurance sentence is now the catalogue's "Native stops on the exchange are unaffected", withheld on a trading or stop-loss-protection fault (OV-4 and OV-6 withhold it; OV-7's maintenance banner keeps it). Draw these three from this commit or later.

Batch 4 (boards 30–41, 95): notes paths scrubbed in batch 4 the same way in `30-scr121-loading.json`.

## #4178 (E32-D02): 13 wireframe boards (added 01:4xZ, 2026-10-23)

Page `E32-D02`. Sheets `sheets/E32-D02/01-…` to `13-…`, drawn in order (board 01 first: it binds the names, the floor treatment and the T2 gate). Greyscale wireframes (the dark theme's semantic greys, no hue). Board names and exports come from each sheet (`E32-D02 / NN <slug>` → `docs/design/E32/img/E32-D02-NN-<slug>.png`). Boards 04, 06, 07 and 13 also get greyscale and deuteranopia renders (`docs/design/_tools/cvd_sim.py`, `<stem>-greyscale.png`, `<stem>-deuteranopia.png`). Notes paths scrubbed in: `01-legend-and-entry.json`, `02-scr064-editing.json`.

## #4180 (E18-D02): batch 1, 30 wireframe boards — READY (07:4xZ, 2026-10-23)

Page `E18-D02`. Greyscale, token-free wireframes (spec §0: the three greys, the focus ring and black text; every board's
footer says SYNTHETIC data). Draw in this order; each sheet's `board.name` is the board name and its `export` the PNG
path, relative to the PR branch's checkout root. Boards 01, 04, 07 and 16, and 25–26, 32–33, 35, 38–40, 42–53 follow in
later batches. The sheets are big (footprint grids): expect long section calls.

| # | Sheet (`sheets/…`) | Board name | Sections | PNG path |
| --- | --- | --- | --- | --- |
| 1 | `E18-D02/02-scr-030-grid-1280-comfortable.json` | `E18-D02 / 02 scr-030-grid-1280-comfortable` | 34 | `docs/design/E18/img/E18-D02-02-scr-030-grid-1280-comfortable.png` |
| 2 | `E18-D02/03-scr-030-grid-1280-dense.json` | `E18-D02 / 03 scr-030-grid-1280-dense` | 15 | `docs/design/E18/img/E18-D02-03-scr-030-grid-1280-dense.png` |
| 3 | `E18-D02/05-scr-030-grid-2560-comfortable.json` | `E18-D02 / 05 scr-030-grid-2560-comfortable` | 33 | `docs/design/E18/img/E18-D02-05-scr-030-grid-2560-comfortable.png` |
| 4 | `E18-D02/06-scr-030-grid-2560-dense.json` | `E18-D02 / 06 scr-030-grid-2560-dense` | 27 | `docs/design/E18/img/E18-D02-06-scr-030-grid-2560-dense.png` |
| 5 | `E18-D02/08-scr-032-dialog-1280-comfort.json` | `E18-D02 / 08 scr-032-dialog-1280-comfort` | 52 | `docs/design/E18/img/E18-D02-08-scr-032-dialog-1280-comfort.png` |
| 6 | `E18-D02/09-scr-032-dialog-2560-compact.json` | `E18-D02 / 09 scr-032-dialog-2560-compact` | 34 | `docs/design/E18/img/E18-D02-09-scr-032-dialog-2560-compact.png` |
| 7 | `E18-D02/10-scr-032-dialog-2560-comfort.json` | `E18-D02 / 10 scr-032-dialog-2560-comfort` | 34 | `docs/design/E18/img/E18-D02-10-scr-032-dialog-2560-comfort.png` |
| 8 | `E18-D02/11-cmp-228-preview-densities.json` | `E18-D02 / 11 cmp-228-preview-densities` | 3 | `docs/design/E18/img/E18-D02-11-cmp-228-preview-densities.png` |
| 9 | `E18-D02/12-scr-056-rows-1280-compact.json` | `E18-D02 / 12 scr-056-rows-1280-compact` | 2 | `docs/design/E18/img/E18-D02-12-scr-056-rows-1280-compact.png` |
| 10 | `E18-D02/13-scr-056-rows-1280-comfort.json` | `E18-D02 / 13 scr-056-rows-1280-comfort` | 2 | `docs/design/E18/img/E18-D02-13-scr-056-rows-1280-comfort.png` |
| 11 | `E18-D02/14-scr-056-rows-2560-compact.json` | `E18-D02 / 14 scr-056-rows-2560-compact` | 2 | `docs/design/E18/img/E18-D02-14-scr-056-rows-2560-compact.png` |
| 12 | `E18-D02/15-scr-056-rows-2560-comfort.json` | `E18-D02 / 15 scr-056-rows-2560-comfort` | 2 | `docs/design/E18/img/E18-D02-15-scr-056-rows-2560-comfort.png` |
| 13 | `E18-D02/17-scr-030-display-modes.json` | `E18-D02 / 17 scr-030-display-modes` | 59 | `docs/design/E18/img/E18-D02-17-scr-030-display-modes.png` |
| 14 | `E18-D02/18-scr-030-width-floors-60-bars.json` | `E18-D02 / 18 scr-030-width-floors-60-bars` | 162 | `docs/design/E18/img/E18-D02-18-scr-030-width-floors-60-bars.png` |
| 15 | `E18-D02/19-scr-030-imbalance.json` | `E18-D02 / 19 scr-030-imbalance` | 35 | `docs/design/E18/img/E18-D02-19-scr-030-imbalance.png` |
| 16 | `E18-D02/20-scr-030-markers.json` | `E18-D02 / 20 scr-030-markers` | 15 | `docs/design/E18/img/E18-D02-20-scr-030-markers.png` |
| 17 | `E18-D02/21-scr-030-forming-bar.json` | `E18-D02 / 21 scr-030-forming-bar` | 15 | `docs/design/E18/img/E18-D02-21-scr-030-forming-bar.png` |
| 18 | `E18-D02/22-scr-030-tooltip.json` | `E18-D02 / 22 scr-030-tooltip` | 25 | `docs/design/E18/img/E18-D02-22-scr-030-tooltip.png` |
| 19 | `E18-D02/23-scr-030-cell-drawer.json` | `E18-D02 / 23 scr-030-cell-drawer` | 17 | `docs/design/E18/img/E18-D02-23-scr-030-cell-drawer.png` |
| 20 | `E18-D02/24-scr-030-cell-menu.json` | `E18-D02 / 24 scr-030-cell-menu` | 30 | `docs/design/E18/img/E18-D02-24-scr-030-cell-menu.png` |
| 21 | `E18-D02/27-scr-030-loading.json` | `E18-D02 / 27 scr-030-loading` | 26 | `docs/design/E18/img/E18-D02-27-scr-030-loading.png` |
| 22 | `E18-D02/28-scr-030-streaming.json` | `E18-D02 / 28 scr-030-streaming` | 16 | `docs/design/E18/img/E18-D02-28-scr-030-streaming.png` |
| 23 | `E18-D02/29-scr-030-stale.json` | `E18-D02 / 29 scr-030-stale` | 16 | `docs/design/E18/img/E18-D02-29-scr-030-stale.png` |
| 24 | `E18-D02/30-scr-030-disconnected.json` | `E18-D02 / 30 scr-030-disconnected` | 17 | `docs/design/E18/img/E18-D02-30-scr-030-disconnected.png` |
| 25 | `E18-D02/31-scr-030-empty-history.json` | `E18-D02 / 31 scr-030-empty-history` | 10 | `docs/design/E18/img/E18-D02-31-scr-030-empty-history.png` |
| 26 | `E18-D02/34-scr-030-low-gpu.json` | `E18-D02 / 34 scr-030-low-gpu` | 42 | `docs/design/E18/img/E18-D02-34-scr-030-low-gpu.png` |
| 27 | `E18-D02/36-scr-030-recompute-failed.json` | `E18-D02 / 36 scr-030-recompute-failed` | 15 | `docs/design/E18/img/E18-D02-36-scr-030-recompute-failed.png` |
| 28 | `E18-D02/37-scr-030-symbol-paused.json` | `E18-D02 / 37 scr-030-symbol-paused` | 16 | `docs/design/E18/img/E18-D02-37-scr-030-symbol-paused.png` |
| 29 | `E18-D02/41-scr-032-data-source.json` | `E18-D02 / 41 scr-032-data-source` | 2 | `docs/design/E18/img/E18-D02-41-scr-032-data-source.png` |
| 30 | `E18-D02/44-scr-032-rebuild-failed.json` | `E18-D02 / 44 scr-032-rebuild-failed` | 25 | `docs/design/E18/img/E18-D02-44-scr-032-rebuild-failed.png` |
