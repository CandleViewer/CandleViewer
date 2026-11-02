#!/bin/sh
# Post-step and live checks for ONE drawn board, after render_exec.py has finished it.
#
# Usage (from the kit folder, e.g. E47-D05/):  sh ../common/board.sh NN "<page>" "<board name>" [probe]
# Env:   CV_REPO  the root of your own checkout (origin/main or later)
#        CV_MCP   your bridge arguments for the repo drivers, e.g. "--server <entry> --project <dir>"
#
# Steps (the same ones the E26 renders ran after each board):
#   post   run/post.tmpl.js with hatch and dash on: U+2215 -> "/" in every frame name, strokes of
#          "dashed · ..." shapes dashed, "hatch line · ..." rectangles rotated 45 degrees (idempotent)
#   lc     node count, frames (size, clip, spill), annotations / footer end and want = end + 80
#   lc3    every text against every clipping ancestor (cutN must be 0)
#   lintd  the cvsheet lint of the root (overlap findings left out)
#   probe  (only when the 4th argument is "probe"; it then runs alone) common/probe.tmpl.js: the active theme and
#          the board's color.surface.canvas fill against the token value, after a theme switch
# Output: out/js/<step>-NN.js and out/<step>-NN.out (one parsed JSON line each; never a raw answer).
set -u
[ $# -eq 3 ] || [ $# -eq 4 ] || { echo "usage: board.sh NN <page> <board name> [probe]"; exit 2; }
NN=$1 PAGE=$2 NAME=$3 STEPS="post lc lc3 lintd"
[ "${4:-}" = probe ] && STEPS=probe
: "${CV_REPO:?set CV_REPO to your checkout}"
RUN="$CV_REPO/docs/design/_tools/sheets/run"
COMMON=$(cd "$(dirname "$0")" && pwd -P)
mkdir -p out/js
fill() { # fill <template> <out> : replace the placeholders with JSON-safe text
  python3 -I -c '
import sys
t = open(sys.argv[1], encoding="utf-8").read()
for k, v in (("__PAGE__", sys.argv[3]), ("__ROOT__", sys.argv[4]), ("__NAME__", sys.argv[4]),
             ("__HATCH__", "true"), ("__DASH__", "true")):
    t = t.replace(k, v.replace("\\", "\\\\").replace("\"", "\\\""))
open(sys.argv[2], "w", encoding="utf-8").write(t)
' "$1" "$2" "$PAGE" "$NAME"
}
fill "$RUN/post.tmpl.js" "out/js/post-$NN.js"
for t in lc lc3 lintd probe; do fill "$COMMON/$t.tmpl.js" "out/js/$t-$NN.js"; done
rc=0
for t in $STEPS; do
  # shellcheck disable=SC2086
  python3 -I -B "$RUN/run_js.py" "out/js/$t-$NN.js" ${CV_MCP:-} > "out/$t-$NN.out" 2>&1 || rc=1
  printf '%s: %s\n' "$t" "$(cut -c1-700 "out/$t-$NN.out")"
done
exit $rc
