#!/usr/bin/env bash
# SR-093 restore drill (E07-X02): restore Postgres + one Parquet partition into a
# scratch environment and verify checksums. Fixtures only; throwaway key.
# Usage: restore_drill.sh <backup_dir> <scratch_dir>   (env: CV_BACKUP_KEY_FILE)
set -euo pipefail
BACKUP_DIR="${1:?backup dir}"; SCRATCH="${2:?scratch dir}"
: "${CV_BACKUP_KEY_FILE:?backup key file, distinct from runtime KEK}"
case "$SCRATCH" in
  / | "") echo "refusing unsafe scratch dir" >&2; exit 2 ;;
esac
mkdir -p "$SCRATCH/cold" "$SCRATCH/pg"
# 1. decrypt (must fail without the backup key: SR-092)
for f in "$BACKUP_DIR"/*.enc; do
  openssl enc -d -aes-256-cbc -pbkdf2 -in "$f" -out "$SCRATCH/$(basename "${f%.enc}")" \
    -pass "file:$CV_BACKUP_KEY_FILE"
done
# 2. Postgres restore into scratch DB (loopback only: SR-047)
if [ ! -f "$SCRATCH/postgres.dump" ]; then
  if [ "${CV_DRILL_ALLOW_NO_PG:-0}" != 1 ]; then
    echo "postgres.dump missing: full drill requires the PG leg (set CV_DRILL_ALLOW_NO_PG=1 for a PARTIAL file-level run)" >&2; exit 3
  fi
  echo "PARTIAL: postgres leg skipped"
else
  createdb -h 127.0.0.1 cv_restore_drill
  pg_restore -h 127.0.0.1 -d cv_restore_drill --no-owner "$SCRATCH/postgres.dump"
fi
# 3. Parquet partition: unpack and verify against the manifest checksums
tar -xzf "$SCRATCH/cold.tar.gz" -C "$SCRATCH/cold"
( cd "$SCRATCH/cold" && sha256sum -c _manifests/checksums.sha256 )
# 4. App start against the scratch environment (SR-093 "app starts"):
#    CV_DRILL_APP_CMD must start the app against cv_restore_drill and exit 0 once healthy.
if [ -n "${CV_DRILL_APP_CMD:-}" ]; then
  bash -c "$CV_DRILL_APP_CMD"; echo "app start OK"
elif [ "${CV_DRILL_ALLOW_NO_PG:-0}" != 1 ]; then
  echo "CV_DRILL_APP_CMD required for a full drill" >&2; exit 4
else
  echo "PARTIAL: app-start leg skipped"
fi
echo "restore drill OK $(date -u +%FT%TZ)"
