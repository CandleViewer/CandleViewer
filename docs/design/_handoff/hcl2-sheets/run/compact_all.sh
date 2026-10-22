#!/bin/sh
# Validate and compact every board sheet in sheets/<KEY>/ into run/compact/<KEY>/ (cvsheet v4.1), on THIS machine.
#
# Usage:  sh run/compact_all.sh          (from any directory; needs python3 on PATH, or set PYTHON=<interpreter>)
#
# For each sheets/<KEY>/<NN-slug>.json it runs tools/validate_sheet.py (with tools/components.offline.json), then
# tools/compact.py, which writes run/compact/<KEY>/<NN-slug>.json stamped with "compactOf": {file: this machine's
# absolute path of the original, sha256: of its bytes}. tools/mkcall4.py refuses a compact sheet whose original is
# missing or changed ("stale compact sheet ... re-run compact.py"): run this script again then. Re-running is safe:
# every output is rewritten in place. run/compact/ holds local absolute paths, so it is never committed or shared.
# Exit 0 when every sheet validated and compacted, 1 otherwise (each failure is printed).
set -u
RUN=$(cd "$(dirname "$0")" && pwd -P) || exit 1
ROOT=$(dirname "$RUN")
cd "$ROOT" || exit 1
PY=${PYTHON:-python3}
n=0
bad=0
for f in sheets/*/*.json; do
  [ -f "$f" ] || continue
  key=$(basename "$(dirname "$f")")
  out="run/compact/$key/$(basename "$f")"
  n=$((n + 1))
  if ! v=$("$PY" -I tools/validate_sheet.py "$f" --components tools/components.offline.json 2>&1); then
    printf 'FAIL validate %s\n%s\n' "$f" "$v"
    bad=$((bad + 1))
    continue
  fi
  if ! "$PY" -I tools/compact.py "$f" "$out"; then
    printf 'FAIL compact %s\n' "$f"
    bad=$((bad + 1))
  fi
done
if [ "$n" -eq 0 ]; then
  echo "no sheets found under $ROOT/sheets"
  exit 1
fi
echo "compact_all: $n sheets, $((n - bad)) compacted into run/compact/, $bad failed"
[ "$bad" -eq 0 ]
