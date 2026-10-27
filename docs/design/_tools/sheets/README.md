# cvsheet board tooling

Draws a design set's boards in Penpot from JSON board sheets, then exports them to PNG. Any lane with
its own Penpot tab and MCP plugin can run it. Everything here is offline except the calls the `run/`
drivers send through [`penpot_exec.py`](../penpot_exec.py). The board rules in
[`docs/design/README.md`](../../README.md) still apply.

| Folder   | What                                                                                                                                                                                                                                                                                    |
| -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `lib/`   | The plugin libraries the drawn boards use: `cvlib-v8.js` (v8.2) and `cvsheet-v4.3.js` (v4.3 places a node without `x`/`y` at its non-flex parent's origin; v4.2 left it at the page origin). Byte-identical vendored copies: never edit or reformat them (`MANIFEST.sha256` pins them). |
| `tools/` | `validate_sheet.py` (sheet checks, with `token-sync.json` and `components.offline.json`), `compact.py` (smaller sheet, same rendering), `mkcall4.py` (the code of each plugin call).                                                                                                    |
| `run/`   | The drivers (`render_exec.py`, `export_exec.py`, `run_js.py`, `set_render.py`, `set_post_export.py`) and the plugin scripts they run.                                                                                                                                                   |

`MANIFEST.sha256` lists every file's sha256: run `sha256sum -c MANIFEST.sha256` in this folder after
any change, and regenerate it in the same commit.

Run every Python file as `python3 -I -B <file> --help` first: each one documents its arguments and
exit codes. The drivers take `--server` (MCP entry name, default `PENPOT_MCP_SERVER`, else `penpot`),
`--project` (for a local-scope entry) and `--stop` (a file whose existence stops the run at a step
boundary; default `STOP` in the current directory).

## 1. Prepare the set (offline)

1. Keep the set outside the repository, one folder per set. Each board has an original sheet
   `NN-slug.json` and a sidecar `NN-slug.md`. Line 3 of the sidecar names the page in backticks after
   the word page, then `theme dark.`, `theme light.` or `theme high-contrast.`.
2. Validate every original sheet:
   `tools/validate_sheet.py <set>/NN-slug.json --components tools/components.offline.json`. Fix
   every error before you go on. The validator reads original sheets only, not compact ones.
3. Compact every sheet into a second folder with `tools/compact.py <set>/NN-slug.json <compact>/NN-slug.json`.
   A compact sheet records the original's absolute local path, so never commit it. `mkcall4.py`
   refuses a compact sheet whose original has changed: compact it again.
4. Draw at most 10 boards per design ticket (light and high-contrast twins at most a third of them).
   Mark the rest "not drawn: the text is binding" and name their ids in the PR.

## 2. Prepare the Penpot file

1. Create the set's own Penpot file (`E<nn>-D<nn> boards`) and open it in your own tab.
2. Recreate the tokens: run `../penpot_token_sets.py --check`, then save the output of
   `--emit-js <set>` for every set, and of `--emit-js themes` last, and run each file through
   `run/run_js.py`.
3. Run `run/local-icons.js` once (local `icon/*` components). It is idempotent.
4. Run `run/probe-ro.js` (read-only). It returns the page and the installed `cv` and `sheet` versions.
   The drivers install `lib/` themselves when a call answers `needLib` or `needSheetLib`.

## 3. Render

1. In a fresh file, render board 01 alone first:
   `run/set_render.py 01 --sheets <set> --compact <compact> --logs <logs>`. Look at it before you go
   on. Then render the rest with the same command and no board numbers.
2. Every board renders under the DARK theme. Light and high-contrast boards are themed at export.
3. Read the `report` and `lint` lines. `unmeasured` and `unbound` must be 0. Act on the other
   findings, and on each sheet's `notes.live_checks`, with small fixes on that board only. Never
   pad a padding problem.
4. Reload about every 1,500 shapes. `set_render.py` counts them in `<logs>/shapes-since-reload`.
   Past 1,500 it waits 25 s, runs `CVSHEET_RELOAD_CMD` (your lane's command that reloads your own
   tab), then `warmup.js`. Without that command it stops with `reload needed`: reload the tab
   yourself, or stop if it cannot be reloaded, then re-run the remaining boards. Never reload in the
   middle of a board. A reload empties plugin storage, and the libraries reinstall on the next call.
5. To resume one board, use `run/render_exec.py <compact sheet> --page <page> --from <step>`.
6. Draw at most ten boards per design ticket (light and high-contrast twins at most a third of
   them). Every other board is listed as "not drawn — the text is binding".

## 4. Post-steps and export

1. `run/set_post_export.py --sheets <set> --compact <compact> --logs <logs>` handles each board by
   theme (dark, light, high-contrast). It runs `post.tmpl.js` (U+2215 to `/` in frame names,
   `dashed · …` strokes dashed, `hatch line · …` rectangles rotated 45 degrees, as the live checks
   ask), then exports the PNG to the sheet's `export` path. Pass `--png-dir` to write the PNGs
   somewhere else.
2. Themes are file-wide. After every switch (`theme-*.js`) the driver WAITS 90 s before it exports a
   light or high-contrast board, because token binds re-resolve slowly. Keep that wait if you
   switch by hand. The driver switches back to dark at the end.
3. Open every PNG at 1x and zoomed in. Check for clipped or overlapping text, empty regions and
   order. Fix the board, then export it again.

## Bridge rules

- The bridge gives up on a call after about 120 s. Keep each call well below that (the sections of a
  compact sheet are sized for it). After a timeout, wait 30 s and read back (`report`) before you
  send anything again: a timed-out call may still have run.
- Never re-send a call blindly or start a second copy of a running driver or agent to nudge it. One
  writer per tab: every step is idempotent, but parallel writers duplicate shapes.
- Logs hold parsed fields only. Never print a raw answer, the MCP entry, a URL, a token or a
  file or team id. Name pages by page name.
