# Brief: render ONE board sheet in Penpot (cvsheet v4.1), lint it, export it

You draw one of hcl-worker-2's board sheets in your lane's Penpot window: one board per agent, one agent at a time.
`README.md` (beside this file) says what the sheets are, the board order, the pages and the PNG paths.

## Inputs (your prompt gives them)

- `F`: the absolute path of this folder on your machine. Paths below are relative to `F`. Shell state does not carry
  over between Bash calls, so start every command with `cd F &&`, writing `F` (and `SHEET`) out literally.
- `SHEET`: one compact sheet, `run/compact/<KEY>/<NN-slug>.json` (made by `sh run/compact_all.sh`, README "How to run").
- `SLOT END`: a time, HH:MM UTC.
- `REPO`: your checkout of the sheet's PR branch (#4138, #4070 or #4046); the PNG goes under it.

## Rules

- Do NOT commit, push, comment on GitHub or send RelayRoom messages: your lane's main session does those.
- NEVER use pkill/killall/kill by name. Never read ~/.claude.json, .mcp.json or credential files.
- Never write a Penpot hostname, team id, file id, URL, token or password anywhere: name a page by its page name.
- Windows: touch only your own lane's Penpot tab, and only for the OOM rule's reload and your lane's export method.
  Never another window.
- Write only under `run/scratch/<NN-slug>/` (never /tmp), plus `run/shapes-since-reload` and the PNG under `REPO`.
  `tools/`, `sheets/` and `run/compact/` are read-only for you; never hand-edit a sheet.
- Penpot access: your lane's Penpot MCP connection. Only its `execute_code` tool is needed (the tool name is your
  lane's). Every call's code comes from the generator below, pasted verbatim. Never hand-write a mutation except the
  small fixes that QUALITY allows.

## Slot clock, STOP file, pacing, timeouts

- Before every mutating call run `cd F && date -u +%H:%M; test -f run/STOP && echo STOP-FILE`. At or after SLOT END,
  or whenever it prints STOP-FILE, stop and return status `paused-slot-end` with exact progress (sections done, what
  is left). The lane creates `run/STOP` to pause the queue and deletes it to resume.
- Pacing: after a call whose code is under 8,000 bytes, sleep 5 s; after a larger one, sleep 15 s (Bash `sleep`).
  `G size <step>` prints a call's byte size without calling Penpot.
- Timeouts: if a call fails with "plugin tab appears to be suspended" or times out, sleep 30 s, then run `G report`
  (read-only). Re-send the SAME call only if its section is missing or incomplete. A refused or timed-out call may
  still have run, so always read back before re-sending. Section calls are idempotent: re-sending one replaces the
  same-named child in place. Never poll `penpot.currentFile.revn`.

## The calls (generated: paste the generator's stdout as the execute_code `code`, verbatim)

G = `cd F && python3 -I tools/mkcall4.py SHEET <step>`. The page is the sheet's page name and the root board is its
`board.name`. If G exits with "stale compact sheet ...", run `cd F && sh run/compact_all.sh` once and retry.

0. **Probe** (read-only), before your first call in this window:
   `return { cv: storage.cvd02 && storage.cvd02.v, inst: storage.cvd02inst || null, writer: storage.cvd02 && storage.cvd02.WRITER, sheet: storage.cvsheet && storage.cvsheet.v };`
   - **`cv` missing or null:** run one execute_code whose code is the stdout of
     `cd F && cat tools/cvlib-v8.js && printf '\nreturn storage.cvd02.v;\n'` (cvlib v8, about 12 KB). In a fresh storage
     it pins `inst` and `WRITER` to the same id.
   - **`sheet` missing or below 4.1:** run `G install` once per plugin session (cvsheet v4.1, about 23 KB). It returns
     `{ cvsheet: 4.1, was }`.
   - **`WRITER` not equal to `inst`:** every generated call waits 20 s and answers `{ skip: "not-writer" }` without
     drawing. `WRITER` is non-configurable: don't change it or reinstall over it. Stop and return status `not-writer`
     with the probe's answer. Your lane tells the orchestrator and hcl-worker-2, who pick another namespace.
1. **`G root`** enters (or creates) the page, then finds or creates the root board, and returns its report.
   - `{needLib}` (after 20 s): install cvlib as in step 0, then retry.
   - `{needSheetLib}`: run `G install`, then retry.
   - `{retry: "page"}`: sleep 5 s, then re-send.
   - Two root boards with this name (`duplicate root boards named …` from `G root`, or
     `{error: "root boards named like this: N"}` with N above 1 from a later step): stop with status `failed` and report
     it. Never delete a board. N = 0 on a later step means the root is gone: run `G root` again, then every section.
   A root that already exists (an earlier test or a partial render) is reused. Its sections are replaced in place.
2. **`G count`** gives N. Then run `G 0` … `G N-1`, one call each, in order. Each returns the section it made and a
   report. On an error, read it. Fix only a transient or bridge issue. If a section's JSON itself is wrong (unknown
   token, component, text layer or clone source), STOP and return status `partial` with the exact error.
3. **`G touch`** (a later call), then **`G relayout`** (a later call), then **`G report`**. `unmeasured` must be 0. If
   it isn't, run touch and relayout once more.
4. **`G lint`** (read-only) returns `{ counts, findings (at most 40), shapes }`. The finding kinds are text-overflow,
   outside-root, unmeasured, overlap and unbound.
   - **`unbound` must be 0.** It counts texts without their typography or fill token. Token binds land
     asynchronously, so if it isn't 0, sleep 15 s and lint again.
   - If it stays above 0, re-send the sections that hold those texts once, then run touch, relayout and lint again.
   - If it is still above 0, don't export. Return status `partial` with the findings.

## QUALITY

Act on lint findings, and on the sheet's own `notes.live_checks` that a read-back can verify. Print the live checks
with
`cd F && python3 -I -c "import json,sys;print(json.dumps(json.load(open(sys.argv[1],encoding='utf-8'))['notes'].get('live_checks',[]),indent=1,ensure_ascii=False))" SHEET`.

Small fixes are allowed, by a short script on shapes of THIS board found by name:

- widen a text box or a cell board;
- raise the root's height, up to the limit in the sheet's notes;
- set a gap.

Never fix another board, component mains or copies. Never rebind a token the sheet didn't ask for. NEVER add padding to
fix a padding problem: cvsheet v4.1 already applies one-sided paddings correctly, so report it instead. Re-run `G lint`
after fixes. List every fix as `SHEET-FIX: <json path> <what>`, so hcl-worker-2 can correct the generator later.

Known facts from the 2026-10-22 live tests:

- In a fix script, `parent.children.indexOf(child)` is always -1 (children are proxies): find a child by id or name.
- Token binds land asynchronously, so v4.1 never copies shapes in Penpot: repeated rows are expanded in JSON.
- Every string on a board comes from its spec or research doc, sample data included. Never "correct" a name or a
  value on a board.

## EXPORT (exports are ON)

After lint (`unbound` 0, findings acted on, lint re-run after any fixes), export the root board as PNG at scale 1, by
your lane's usual export method, to `REPO/<PNG path>`. The board's id is in its report.

- The PNG path is the sheet's `export` field. README's table lists every one.
- For the research boards (E35-D01, E33-D01), the field is a stem: add `docs/design/` in front when it doesn't start
  with that, and add `.png` at the end.

Then look at the PNG at 1x, and zoomed in over dense areas. Check for clipped or overlapping text, text running past
its cell, empty regions and wrong order. The QUALITY fixes apply; re-export after a fix.

**Theme boards: #4138 boards 09, 10 and 20.**

- Penpot token themes are file-wide. A theme switch is the coordinator's [THEME-WINDOW] step, never a builder's, so
  never switch the token theme.
- Draw and lint these three boards as usual, but don't export them. Return png `export deferred: THEME-WINDOW` with the
  board id.
- Their sheet notes say how the coordinator exports them: boards 10 and 20 under the light theme, and board 09 as dark
  and light exports composed into its one PNG.

## OOM rule (between boards only)

A Penpot tab that has built about 1,500 shapes since its last reload risks an "Out of Memory" crash.
`run/shapes-since-reload` holds one integer, the shapes built since the last reload; a missing file means 0.

- **Before your first call,** read the file. If it is 1,500 or more, reload your own lane's Penpot tab first.
  - Use your lane's usual method. Never reload another window, and never while a call is running.
  - Wait 15 s after the previous board's last call, so its saves land.
  - Reconnect the Penpot MCP plugin in that tab if your lane needs to.
  - Write 0 to the file, then probe. A reload empties the plugin storage, so expect to install cvlib and cvsheet again.
  - If you can't reload your tab yourself, return status `needs-reload` before drawing anything.
- **After your board's last call,** add the root's `shapes` from the last `G report` to the file.

Never reload mid-board.

## Final reply (structured)

- status: built, partial, paused-slot-end, not-writer, needs-reload, bridge-down or failed
- board id and page id
- png: the path written, or `export deferred: THEME-WINDOW`
- the SHEET-FIX list
- the lint counts before and after fixes
- other deviations
- notes, at most 12 lines: size, shapes, texts, unmeasured, and the live checks verified
