#!/usr/bin/env bash
# E49-Q02 (#1336): a local backend tier for the exploratory sessions (tier B, docs/qa/e49-exploratory-harness.md).
# It follows the real-backend CI lane (.github/workflows/e2e-auth-real.yml): Postgres and QuestDB from compose,
# migrations, one Owner, one Manager and one Viewer, the API on this host (testnet, synthetic feed, no exchange
# key) and the built SPA behind `vite preview`. Credentials are made per run into a mode-0700 directory and are
# never printed. The stack and that directory are removed when the script exits.
# Limits: no exchange and no order path, so it serves charters C7 and C8 only.
set -euo pipefail
set -m

usage() {
  printf '%s\n' \
    'usage: tools/qa/explore_stack.sh [--bind HOST] [--api-port N] [--preview-port N] [--skip-build]' \
    '  --bind HOST         loopback only (127.0.0.1, localhost or ::1); default 127.0.0.1' \
    '  --api-port N        API port, default 8000' \
    '  --preview-port N    SPA port, default 4174' \
    '  --skip-build        reuse an existing apps/web/dist' \
    'Needs docker (compose v2), uv, pnpm, openssl and curl. Stop with Ctrl-C: the stack is removed.'
}

die() {
  echo "explore_stack: $*" >&2
  exit 2
}

bind=127.0.0.1
api_port=8000
preview_port=4174
skip_build=0
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    --bind) [ $# -ge 2 ] || die "--bind needs a value"; bind=$2; shift 2 ;;
    --api-port) [ $# -ge 2 ] || die "--api-port needs a value"; api_port=$2; shift 2 ;;
    --preview-port) [ $# -ge 2 ] || die "--preview-port needs a value"; preview_port=$2; shift 2 ;;
    --skip-build) skip_build=1; shift ;;
    *) usage >&2; die "unknown argument: $1" ;;
  esac
done

case "$bind" in
  127.0.0.1 | localhost | ::1) ;;
  *) die "refused: --bind must be a loopback address, got a non-loopback value" ;;
esac
for port in "$api_port" "$preview_port"; do
  case "$port" in
    '' | *[!0-9]*) die "a port must be a number" ;;
  esac
  { [ "${#port}" -le 5 ] && [ "$((10#$port))" -ge 1 ] && [ "$((10#$port))" -le 65535 ]; } \
    || die "a port must be between 1 and 65535"
done
[ "$((10#$api_port))" -ne "$((10#$preview_port))" ] || die "--api-port and --preview-port must differ"
api_port=$((10#$api_port))
preview_port=$((10#$preview_port))

# The exchange guards of the real lane: testnet only, and no exchange key variable of any kind.
case "${CV_ENVIRONMENT:-testnet}" in
  testnet) ;;
  *) die "refused: CV_ENVIRONMENT must be testnet (or unset) for exploration" ;;
esac
for name in $(compgen -v); do
  case "$name" in
    CV_BYBIT_API_*) die "refused: an exchange key variable (CV_BYBIT_API_*) is set; unset it first" ;;
  esac
done
# The API and metrics binds are loopback too: an inherited non-loopback value is refused, not overridden.
case "${CV_METRICS_BIND:-127.0.0.1:9108}" in
  127.0.0.1:* | localhost:* | \[::1\]:*) ;;
  *) die "refused: CV_METRICS_BIND must be a loopback address" ;;
esac
case "${CV_BIND_HOST:-$bind}" in
  127.0.0.1 | localhost | ::1) ;;
  *) die "refused: CV_BIND_HOST must be a loopback address" ;;
esac
metrics_bind=${CV_METRICS_BIND:-127.0.0.1:9108}

for tool in docker uv pnpm openssl curl; do
  command -v "$tool" >/dev/null 2>&1 || die "refused: $tool is not available on PATH"
done
docker compose version >/dev/null 2>&1 || die "refused: docker compose v2 is not available"

# A fixed host port (the stack's four, the API metrics port, and the two chosen ones) that is already bound means another stack (yours or a sibling worktree's) is up.
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
for port in 5432 8812 9009 9000 9108 "$api_port" "$preview_port"; do
  if port_busy "$port"; then die "refused: port $port is already in use; stop that stack first"; fi
done

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
umask 077
work=$(mktemp -d "${TMPDIR:-/tmp}/cv-explore.XXXXXXXX")
chmod 700 "$work"
mkdir -m 700 "$work/data" "$work/audit" "$work/lane" "$work/kek" "$work/clock"
api_pid=""
preview_pid=""
project=""

# Safe to run at any point after mktemp: empty pids and a not-yet-named compose project are skipped.
cleanup() {
  trap - EXIT INT TERM
  # Each background job is its own process group (set -m): stop the whole group, not just the wrapper.
  for pid in "$preview_pid" "$api_pid"; do
    if [ -n "$pid" ]; then kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true; fi
  done
  # A bounded grace (about 5 s) for the groups to end, then a forced stop of whatever remains.
  for _ in $(seq 25); do
    alive=0
    for pid in "$preview_pid" "$api_pid"; do
      if [ -n "$pid" ] && kill -0 -- "-$pid" 2>/dev/null; then alive=1; fi
    done
    [ "$alive" -eq 1 ] || break
    sleep 0.2
  done
  for pid in "$preview_pid" "$api_pid"; do
    if [ -n "$pid" ]; then
      kill -KILL -- "-$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
  if [ -n "$project" ]; then docker compose down -v >/dev/null 2>&1 || true; fi
  rm -rf "$work"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

suffix=$(openssl rand -hex 3)
project="cv-explore-$suffix"
export COMPOSE_PROJECT_NAME="$project"
export COMPOSE_FILE="$root/infra/compose/docker-compose.yml"
export COMPOSE_PROFILES=core
# The stack's host ports and DSN are this script's own: pin what the compose file reads, drop the API override.
export POSTGRES_PORT=5432 QUESTDB_PG_PORT=8812 QUESTDB_ILP_PORT=9009 QUESTDB_HTTP_PORT=9000
unset CV_BIND_PORT
export GF_SECURITY_ADMIN_PASSWORD=unused-local MINIO_ROOT_PASSWORD=unused-local
export CV_ALERT_PAGE_WEBHOOK_URL=http://127.0.0.1:1/unused
export CV_ALERT_TICKET_WEBHOOK_URL=http://127.0.0.1:1/unused
export CV_ALERT_DEADMAN_URL=http://127.0.0.1:1/unused

POSTGRES_PASSWORD=$(openssl rand -hex 32)
CV_AUTH_PEPPER=$(openssl rand -hex 32)
CV_AUTH_TOTP_KEY_HEX=$(openssl rand -hex 32)
CV_AUTH_RECOVERY_HMAC_KEY_HEX=$(openssl rand -hex 32)
CV_AUTH_CSRF_KEY_HEX=$(openssl rand -hex 32)
export POSTGRES_PASSWORD CV_AUTH_PEPPER CV_AUTH_TOTP_KEY_HEX CV_AUTH_RECOVERY_HMAC_KEY_HEX CV_AUTH_CSRF_KEY_HEX
openssl rand -hex 32 >"$work/password"
openssl rand -hex 32 >"$work/lane/lane.key"
openssl rand 32 >"$work/kek/kek"

docker compose up -d --wait --wait-timeout 180 postgres questdb

export CV_ENVIRONMENT=testnet
export CV_PG_DSN="postgresql+asyncpg://cv:${POSTGRES_PASSWORD}@127.0.0.1:5432/candleviewer"
(
  cd "$root/services/api"
  uv sync --frozen
  uv run --frozen alembic upgrade head
  for role in owner manager viewer; do
    CV_SEED_USERNAME="explore-$suffix-$role" CV_SEED_PASSWORD="$(cat "$work/password")" \
      uv run --frozen python scripts/seed_fixture_user.py --role "$role" \
      --totp-secret-out "$work/$role.totp"
  done
)

if [ "$skip_build" -eq 0 ]; then
  (cd "$root" && pnpm i --frozen-lockfile \
    && pnpm --filter "@candleviewer/web^..." run build && pnpm --filter @candleviewer/web run build)
fi

host_url=$bind
case "$bind" in *:*) host_url="[$bind]" ;; esac
origin="http://$host_url:$preview_port"
(
  cd "$root/services/api"
  export CV_STORAGE_BACKEND=real CV_FEED=synthetic CV_QUESTDB_PG=127.0.0.1:8812 CV_QUESTDB_ILP=127.0.0.1:9009
  export CV_BIND_HOST="$bind" CV_BIND_PORT="$api_port" CV_METRICS_BIND="$metrics_bind"
  export CV_KEK_SOURCE=file CV_KEK_HANDLE="$work/kek/kek" CV_KEK_VERSION=1
  export CV_TEST_CLOCK=true CV_TEST_CLOCK_FILE="$work/clock/offset" CV_ALLOWED_ORIGINS="$origin"
  export CV_AUDIT_LANE_KEY_FILE="$work/lane/lane.key" CV_AUDIT_WAL_PATH="$work/audit/audit.wal"
  export CV_PARQUET_ROOT="$work/data/parquet" CV_BACKUP_ROOT="$work/data/backups"
  mkdir -m 700 "$CV_PARQUET_ROOT" "$CV_BACKUP_ROOT"
  exec uv run --frozen python -m candleviewer.server >"$work/api.log" 2>&1 </dev/null
) &
api_pid=$!
healthy=0
for _ in $(seq 60); do
  if curl -fsS --max-time 5 -o /dev/null "http://$host_url:$api_port/healthz" 2>/dev/null; then healthy=1; break; fi
  kill -0 "$api_pid" 2>/dev/null || break
  sleep 2
done
# The API log is written by the app with its redaction filter on, so it holds no session values.
[ "$healthy" -eq 1 ] || { tail -n 50 "$work/api.log" >&2; die "the API did not answer /healthz"; }

(
  cd "$root/apps/web"
  export CV_E2E_REAL_API="http://$host_url:$api_port"
  exec pnpm exec vite preview -c e2e/vite.real.config.ts --port "$preview_port" --host "$bind"
) >"$work/preview.log" 2>&1 </dev/null &
preview_pid=$!

echo "users: explore-$suffix-owner explore-$suffix-manager explore-$suffix-viewer"
echo "preview: $origin"
echo "Sign-in values are in the run directory $(basename "$work") under ${TMPDIR:-/tmp}, mode 0700; they are never printed. Ctrl-C stops and removes the stack."
while kill -0 "$api_pid" 2>/dev/null && kill -0 "$preview_pid" 2>/dev/null; do sleep 1; done
if ! kill -0 "$api_pid" 2>/dev/null; then
  tail -n 50 "$work/api.log" >&2
  die "the API exited"
fi
die "the preview exited"
