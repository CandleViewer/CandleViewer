#!/usr/bin/env bash
# infra/scripts/demo_host_owner_first_run.sh — the Owner's first run on the Bybit demo host (#3180).
#
# Interactive. The Owner runs it once on the host, from a terminal, with the stack up
# (docs/ops/runbooks/demo-host.md steps 6 and 7). In order:
#   1. the bootstrap (#4479): it stops api, runs #4479's CLI in the overlay's `bootstrap-owner`
#      service on this terminal (`--owner <email>`; DC-4479-02: no logging driver keeps the token
#      it prints once), starts api again and waits for it, then asks for that token;
#   2. the invite: getInvite, then redeemInvite with a new password (the otpauth URI for the
#      authenticator is shown once), then confirmInvite with its first code (the recovery codes
#      are shown once, to be sealed: SR-023);
#   3. the sign-in, with the email: authLogin, then authMfaVerify with a new code;
#   4. the `keys` step-up: authStepUp with the password and a new code. The served
#      createExchangeAccount needs it too, so it comes first, and its 5 minutes cover both writes;
#   5. the demo account: createExchangeAccount;
#   6. the key import: createApiKey with the key and secret typed at the prompt, and expected_uid.
# Past step 1 it calls the api on http://127.0.0.1:8000 only. stdout carries only the verification
# verdict fields of step 6, never the egress address (Confidential); prompts and messages go to
# stderr, the one-time URI and codes, and the account id a rerun needs, to the terminal. A run that
# succeeds asks the terminal to clear what it showed once (one may ignore that); one that stops
# says to clear it.
#
# Secrets are typed silently and never echoed or put on a command line: each request reaches curl
# as a config on stdin (`--config -`), and its JSON is written and read by python3 through pipes,
# so `ps` shows neither. Nothing is written to disk (no cookie jar, no temp file, no history); curl
# reads no ~/.curlrc and uses no proxy; every variable is cleared on exit. Needs bash, curl and
# python3, and docker compose for step 1. Exit status: 0 the key is imported, 1 a step was
# refused, 2 bad arguments, 130, 143 or 129 a signal (a run that stopped api then says how to
# start it again).
#   --skip-invite        the invite is redeemed already: start at the sign-in
#   --account-id UUID    the demo account is registered already: import its key

set +x +v
set -euo pipefail
umask 077
export LC_ALL=C
unset HISTFILE
unset -f curl docker python3 printf read command 2>/dev/null || true
trap - DEBUG RETURN

readonly API="http://127.0.0.1:8000"
# The app mounts its routers at the root: 22's operations are served with no `/api/v1` prefix,
# whatever 22's server URL says, so the paths below are 22's paths as they are.
readonly PROG="demo_host_owner_first_run"
readonly UUID_RE='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
readonly TOKEN_RE='^[A-Za-z0-9._~+/=-]{8,4096}$'
# JSON in and out, through pipes only: `obj NAME:TYPE...` reads NUL-ended values and writes one
# object (TYPE s a string, b a boolean); `get SPEC...` reads curl's head, body and status and
# prints one line per SPEC (:status, :csrf, or a .dotted.path); `lines .path` one line per item;
# `verdict` the verification verdict fields; `uuid` a version 4 UUID.
readonly PY='
import json, sys, uuid

def plain(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ",".join(plain(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return "".join(c if c.isprintable() else "?" for c in str(value))

def find(doc, parts):
    if not parts:
        return doc
    if isinstance(doc, list):
        return [find(item, parts) for item in doc]
    return find(doc.get(parts[0]), parts[1:]) if isinstance(doc, dict) else None

def answer():
    raw = sys.stdin.buffer.read().decode("utf-8", "replace")
    head, _, rest = raw.partition("\r\n\r\n")
    body, _, status = rest.rpartition("\n")
    cookies = {}
    for line in head.split("\r\n")[1:]:
        name, _, value = line.partition(":")
        if name.strip().lower() == "set-cookie":
            key, _, val = value.strip().split(";")[0].partition("=")
            cookies[key.strip()] = val.strip().strip("\"")
    try:
        doc = json.loads(body) if body.strip() else None
    except ValueError:
        doc = None
    return (status if status.isdigit() else "000"), cookies, doc

mode, args = sys.argv[1], sys.argv[2:]
if mode == "obj":
    values = sys.stdin.buffer.read().decode("utf-8", "surrogateescape").split("\0")[:-1]
    if len(values) != len(args):
        sys.exit("one value for each member")
    out = {}
    for spec, value in zip(args, values):
        name, _, kind = spec.partition(":")
        out[name] = value == "true" if kind == "b" else value
    sys.stdout.write(json.dumps(out, separators=(",", ":")))
elif mode == "uuid":
    print(uuid.uuid4())
else:
    status, cookies, doc = answer()
    if mode == "get":
        for spec in args:
            if spec == ":status":
                print(status)
            elif spec == ":csrf":
                print(plain(cookies.get("__Host-cv_csrf")))
            else:
                print(plain(find(doc, spec.strip(".").split("."))))
    elif mode == "lines":
        for item in find(doc, args[0].strip(".").split(".")) or []:
            print(plain(item))
    elif mode == "verdict":
        shown = find(doc, ["verification"])
        for name in ("passed", "uta", "read_only", "withdraw_enabled",
                     "ip_whitelist_matches_egress", "warnings", "probe_ret_code",
                     "clock_offset_ms"):
            if isinstance(shown, dict) and name in shown:
                print(name + ": " + (plain(shown[name]) or "-"))
'

TOKEN="" PASSWORD="" AGAIN="" CODE="" API_KEY="" API_SECRET="" ACCESS="" CSRF="" MFA_TOKEN=""
METHOD_ID="" BODY="" RESP="" STATUS="" IDENT="" EXCHANGE_UID="" LABEL="" KEY_LABEL=""
READ_ONLY=false READ_ONLY_ANSWER="" ACCOUNT_ID="" SKIP_INVITE=false OWNER_EMAIL=""
SHOWN=false API_STOPPED=false # something was shown once and is not cleared; the run stopped api
F=()
# The runbook's compose files and project (docs/ops/runbooks/demo-host.md), from this checkout.
HERE=${BASH_SOURCE[0]%/*}
[[ $HERE != "${BASH_SOURCE[0]}" ]] || HERE=.
ROOT=$(cd -P -- "$HERE/../.." && pwd) || exit 2
readonly COMPOSE=(docker compose -p cv-demo
  -f "$ROOT/infra/compose/docker-compose.yml"
  -f "$ROOT/infra/compose/docker-compose.vps.yml"
  -f "$ROOT/infra/compose/docker-compose.demo-host.yml")
# The command that starts api again, word for word, for a run that stopped it.
printf -v UP_API '%q ' "${COMPOSE[@]}" --profile core up -d --wait api
readonly UP_API="${UP_API% }"

cleanup() {
  TOKEN="" PASSWORD="" AGAIN="" CODE="" API_KEY="" API_SECRET="" ACCESS="" CSRF="" MFA_TOKEN=""
  BODY="" RESP="" F=()
  unset -v TOKEN PASSWORD AGAIN CODE API_KEY API_SECRET ACCESS CSRF MFA_TOKEN BODY RESP F
  [[ $SHOWN != true ]] || still_shown
  [[ $API_STOPPED != true ]] ||
    say "api may be stopped (the bootstrap stops it): start it with: $UP_API"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

say() { printf '%s\n' "$*" >&2; }
show() { printf '%s\n' "$@" >&3; } # the one-time display, a line each: the terminal, else stderr
die() {
  say "$PROG: $*"
  exit 1
}
usage() {
  say "usage: $PROG [--skip-invite] [--account-id UUID]"
  exit "${1:-2}"
}
py() { python3 -I -B -c "$PY" "$@"; }

still_shown() { # the run stops, or has no terminal to clear: what it showed once is still there
  SHOWN=false
  say "What was shown once is still in this terminal's scrollback: once you have read what is" \
    "above, clear it (clear; printf '\\033[3J'; in tmux also tmux clear-history), and any" \
    "clipboard history."
}

forget_shown() { # the run succeeded: ask the terminal to clear what it showed once
  [[ $SHOWN == true ]] || return 0
  [[ -t 3 ]] || {
    still_shown
    return 0
  }
  SHOWN=false
  printf '\033[H\033[2J\033[3J' >&3 # the screen (ED 2), then the scrollback (ED 3)
  if [[ -n ${TMUX-} ]]; then # tmux keeps a pane's history apart from the terminal's
    tmux clear-history ${TMUX_PANE:+-t "$TMUX_PANE"} </dev/null >/dev/null 2>&1 || true
  fi
  say "This terminal was asked to clear what was shown once from its screen and scrollback;" \
    "some terminals keep the scrollback, so scroll up and clear anything still there yourself" \
    "(clear; printf '\\033[3J'), and any clipboard history."
}

ask() { # ask NAME PROMPT [DEFAULT]: a visible answer, trimmed, else DEFAULT
  local _reply=""
  IFS= read -r -t 600 -p "$2" _reply || die "no answer to: $2"
  _reply=${_reply#"${_reply%%[![:space:]]*}"}
  _reply=${_reply%"${_reply##*[![:space:]]}"}
  printf -v "$1" '%s' "${_reply:-${3-}}"
}

ask_secret() { # ask_secret NAME PROMPT: typed silently, never echoed
  local _reply=""
  IFS= read -rs -t 600 -p "$2" _reply || die "no answer to: $2"
  [[ ! -t 0 ]] || printf '\n' >&2
  printf -v "$1" '%s' "$_reply"
  _reply=""
}

ask_code() { # ask_code PROMPT: CODE, six digits from the authenticator
  ask_secret CODE "$1"
  [[ $CODE =~ ^[0-9]{6}$ ]] || die "a code from the authenticator is 6 digits"
}

chars_within() { # chars_within MIN MAX: is PASSWORD MIN to MAX characters long? LC_ALL=C counts
  local bare=${PASSWORD//[$'\x80'-$'\xbf']/} n # bytes, so drop UTF-8's continuation bytes first
  n=${#bare} bare=""
  [[ $n -ge $1 && $n -le $2 ]]
}

encode() { # encode NAME:TYPE VALUE...: BODY becomes that JSON object
  local specs=() values=()
  while (($# >= 2)); do
    specs+=("$1")
    values+=("$2")
    shift 2
  done
  BODY=$(printf '%s\0' "${values[@]}" | py obj "${specs[@]}") ||
    die "python3 could not write a request"
  values=()
}

get() { # get SPEC...: F holds those fields of the last answer, one per SPEC
  local line
  F=()
  while IFS= read -r line; do F+=("$line"); done < <(printf '%s' "$RESP" | py get "$@")
}

call() { # call METHOD PATH [BODY [session [IDEMPOTENCY_KEY [MAX_TIME]]]]: RESP and STATUS
  local method=$1 path=$2 body=${3-} session=${4-} key=${5-} max=${6:-60} config rc=0
  config="url = \"$API$path\""$'\n'"request = \"$method\""$'\n'
  config+=$'header = "Accept: application/json"\nheader = "Expect:"\n'
  if [[ $session == session ]]; then
    config+="header = \"Authorization: Bearer $ACCESS\""$'\n'
    config+="header = \"Cookie: __Host-cv_csrf=$CSRF\""$'\n'
    config+="header = \"X-CSRF-Token: $CSRF\""$'\n'
  fi
  [[ -z $key ]] || config+="header = \"Idempotency-Key: $key\""$'\n'
  if [[ -n $body ]]; then
    body=${body//\\/\\\\}
    body=${body//\"/\\\"}
    config+=$'header = "Content-Type: application/json"\n'"data-binary = \"$body\""$'\n'
  fi
  RESP=$(printf '%s' "$config" | curl -q --silent --noproxy '*' --proto =http --max-time "$max" \
    --dump-header - --write-out '\n%{http_code}' --config - 2>/dev/null) || rc=$?
  config="" body="" STATUS=000
  if ((rc == 0)); then # the last line is --write-out's status
    STATUS=${RESP##*$'\n'}
    [[ $STATUS =~ ^[0-9]{3}$ ]] || STATUS=000
  fi
}

new_uuid() { # a version 4 UUID: the kernel's, else python3's
  local id=""
  { IFS= read -r id </proc/sys/kernel/random/uuid; } 2>/dev/null || id=$(py uuid)
  printf '%s' "$id"
}

unreachable() {
  die "the api at 127.0.0.1:8000 did not answer: is the stack up and healthy (runbook step 4)?"
}

invalid_invite() {
  die "the invite token is not valid: unknown, expired, used or revoked (#4479 mints another)"
}

refused() { # refused WHAT: the plain message for the last answer
  get .code .detail
  die "$* was refused: HTTP $STATUS${F[0]:+ ${F[0]}}${F[1]:+: ${F[1]}}"
}

bootstrap_refusal() { # bootstrap_refusal STATUS: #4479's exit status in words (its design note)
  case $1 in
    1) printf 'step_failed or a compose error (read the lines above)' ;;
    2) printf 'a usage or settings error' ;;
    3) printf 'mint_failed (nothing was minted: run again)' ;;
    4) printf 'host_fs_unavailable (the audit volume)' ;;
    5) printf 'api_running (cv-api, another run or a session of its database role is connected)' ;;
    6) printf 'audit_unavailable (no token was given: run again once audit_log takes records)' ;;
    7 | 8) printf 'live_flag (this host is demo: never --live)' ;;
    9) printf 'kek_unproven (no cv-api boot enrolled this KEK: runbook steps 4 and 5)' ;;
    11) printf 'no_tty (run this script from a terminal)' ;;
    12) printf 'confirmation_mismatch (the phrase was not retyped exactly)' ;;
    13) printf 'confirmation_timeout (the phrase was not retyped within 5 minutes)' ;;
    16) printf 'operator_cancelled' ;;
    17) printf 'owner_exists (an Owner is active: run again with --skip-invite)' ;;
    18)
      printf 'not_candidate (not a usable bootstrap email, or a user who cannot become the Owner)'
      ;;
    130) printf 'interrupted (its outcome is unknown: read the auth.bootstrap_owner_* records)' ;;
    *) printf 'status %s' "$1" ;;
  esac
}

bootstrap_invite() { # #4479's mint, in bootstrap-owner on this terminal: its token is never ours
  local rc=0
  ask OWNER_EMAIL "Owner email (the bootstrap invites it; it signs in with it): "
  [[ ${#OWNER_EMAIL} -le 254 && $OWNER_EMAIL =~ ^[A-Za-z0-9._-]{3,32}@[^@[:space:]]+$ ]] ||
    die "the owner is an email whose part before @ is 3 to 32 letters, digits, '.', '_' or '-'"
  command -v docker >/dev/null 2>&1 || die "docker is not installed"
  say "Stopping api: #4479's CLI runs only while it is stopped."
  API_STOPPED=true
  "${COMPOSE[@]}" stop api </dev/null || die "could not stop api: read the lines above"
  say "The bootstrap: retype the phrase it shows. It prints the invite token once: paste it at" \
    "the next prompt."
  say "Shown once from here on: the token, then the authenticator URI and the recovery codes." \
    "Run no session recorder (script, asciinema) and keep them out of any clipboard manager's" \
    "history; a run that succeeds asks this terminal to clear its scrollback at its end."
  SHOWN=true
  "${COMPOSE[@]}" --profile bootstrap-owner run --rm --no-deps bootstrap-owner \
    --owner "$OWNER_EMAIL" >&3 2>&3 || rc=$?
  if ((rc != 0)); then
    ((rc == 130)) || SHOWN=false # a refusal gives no token; an interrupted run may have shown it
    die "the bootstrap refused: $(bootstrap_refusal "$rc")."
  fi
  say "Starting api again."
  "${COMPOSE[@]}" --profile core up -d --wait api </dev/null ||
    die "api did not get healthy after the bootstrap: read its log (runbook step 4)"
  API_STOPPED=false
}

redeem_invite() {
  local try
  ask_secret TOKEN "Invite token (the bootstrap printed it once): "
  [[ $TOKEN =~ ^[A-Za-z0-9_-]{16,128}$ ]] ||
    die "that is not an invite token: 16 to 128 letters, digits, - or _"
  call GET "/invites/$TOKEN"
  case $STATUS in
    200) ;;
    000) unreachable ;;
    404) invalid_invite ;;
    429) die "too many invalid attempts from this address: wait, then run again" ;;
    *) refused "the invite check" ;;
  esac
  ask_secret PASSWORD "New password (12 to 512 characters): "
  ask_secret AGAIN "The same password again: "
  [[ $PASSWORD == "$AGAIN" ]] || die "the two passwords differ"
  AGAIN=""
  chars_within 12 512 || die "a password is 12 to 512 characters"
  encode password:s "$PASSWORD"
  call POST "/invites/$TOKEN" "$BODY"
  case $STATUS in
    200) ;;
    000) unreachable ;;
    404) invalid_invite ;;
    429) die "too many invalid attempts from this address: wait, then run again" ;;
    *) refused "the password" ;;
  esac
  get .method_id .otpauth_uri
  METHOD_ID=${F[0]-}
  [[ -n $METHOD_ID && ${F[1]-} == otpauth://* ]] ||
    die "the invite answered without a TOTP enrolment"
  show "" "Add CandleViewer to your authenticator app with this URI (shown once, keep no copy):"
  show "${F[1]}"
  if command -v qrencode >/dev/null 2>&1; then # the same URI as a QR code, from stdin
    printf '%s' "${F[1]}" | qrencode -t ANSIUTF8 >&3 || true
  fi
  F=()
  for try in 1 2 3; do
    ask_code "Its current code: "
    encode method_id:s "$METHOD_ID" code:s "$CODE"
    call POST "/invites/$TOKEN/confirm" "$BODY"
    [[ $STATUS == 422 ]] || break
    ((try == 3)) || say "That code was refused: wait for the next one."
  done
  case $STATUS in
    200) ;;
    000) unreachable ;;
    404) die "the enrolment is no longer open (expired or revoked): ask for a new invite (#4479)" ;;
    422)
      die "the code was refused three times: check the authenticator's clock," \
        "then ask for a new invite (#4479)"
      ;;
    *) refused "the enrolment" ;;
  esac
  show "" "Recovery codes (shown once): write them down and seal them now (SR-023)."
  printf '%s' "$RESP" | py lines .recovery_codes >&3
  get .role
  [[ ${F[0]-} == owner ]] ||
    die "the invite activated the role '${F[0]-}', not owner: stop and report it on #4479"
  TOKEN="" F=()
  say "The Owner account is active."
}

sign_in() {
  local try
  IDENT=$OWNER_EMAIL # the bootstrap's email, else asked
  [[ -n $IDENT ]] || ask IDENT "Owner username or email: "
  ((${#IDENT} >= 1 && ${#IDENT} <= 254)) || die "a username or email is 1 to 254 characters"
  if [[ -z $PASSWORD ]]; then
    ask_secret PASSWORD "Password: "
    chars_within 1 512 || die "a password is 1 to 512 characters"
  fi
  encode identifier:s "$IDENT" password:s "$PASSWORD"
  call POST /auth/login "$BODY"
  case $STATUS in
    200) ;;
    000) unreachable ;;
    401) die "the sign-in was refused: wrong username, email or password" ;;
    423) die "the account is locked for now: wait, then run again with --skip-invite" ;;
    *) refused "the sign-in" ;;
  esac
  get .status .mfa_token
  [[ ${F[0]-} == mfa_required && -n ${F[1]-} ]] ||
    die "the sign-in asked for no code (no authenticator enrolled?): redeem the invite first"
  MFA_TOKEN=${F[1]}
  for try in 1 2 3; do
    ask_code "A new code from the authenticator (not one used before): "
    encode mfa_token:s "$MFA_TOKEN" method:s totp code:s "$CODE"
    call POST /auth/mfa/verify "$BODY"
    [[ $STATUS == 401 ]] || break
    ((try == 3)) || say "That code was refused: wait for the next one."
  done
  case $STATUS in
    200) ;;
    000) unreachable ;;
    401)
      die "the code was refused three times: check the authenticator's clock," \
        "then run again with --skip-invite"
      ;;
    *) refused "the second factor" ;;
  esac
  get .status .tokens.access_token :csrf
  [[ ${F[0]-} == authenticated && ${F[1]-} =~ $TOKEN_RE && ${F[2]-} =~ $TOKEN_RE ]] ||
    die "the sign-in gave no session and CSRF cookie: is the api on the real backend?"
  ACCESS=${F[1]} CSRF=${F[2]} MFA_TOKEN="" F=()
  say "Signed in."
}

collect_key() {
  ask EXCHANGE_UID "Bybit demo account UID: "
  [[ $EXCHANGE_UID =~ ^[0-9]{4,20}$ ]] || die "a Bybit UID is 4 to 20 digits"
  if [[ -z $ACCOUNT_ID ]]; then
    ask LABEL "Account label [Bybit demo main]: " "Bybit demo main"
    [[ $LABEL =~ ^[[:print:]]{1,80}$ ]] || die "an account label is 1 to 80 printable characters"
  fi
  ask KEY_LABEL "Key label [demo host]: " "demo host"
  [[ $KEY_LABEL =~ ^[[:print:]]{1,80}$ ]] || die "a key label is 1 to 80 printable characters"
  ask READ_ONLY_ANSWER "Read-only key? [y/N]: " n
  case $READ_ONLY_ANSWER in
    [yY] | [yY][eE][sS]) READ_ONLY=true ;;
    [nN] | [nN][oO]) READ_ONLY=false ;;
    *) die "answer y or n" ;;
  esac
  ask_secret API_KEY "Bybit API key: "
  [[ $API_KEY =~ ^[!-~]{8,128}$ ]] || die "an API key is 8 to 128 characters, no spaces"
  ask_secret API_SECRET "Bybit API secret: "
  [[ $API_SECRET =~ ^[!-~]{8,256}$ ]] || die "an API secret is 8 to 256 characters, no spaces"
}

create_account() {
  local key
  key=$(new_uuid) || die "python3 could not make an idempotency key"
  encode exchange:s bybit environment:s demo kind:s main label:s "$LABEL" \
    exchange_uid:s "$EXCHANGE_UID"
  elevated /exchange-accounts "$BODY" "$key"
  BODY=""
  case $STATUS in
    201) ;;
    000) unreachable ;;
    404 | 405)
      die "this api does not serve POST /exchange-accounts (a build before #4484):" \
        "build the pinned main sha (runbook step 1)"
      ;;
    501) refused "the account registration (is the api on the real backend? runbook step 4)" ;;
    409)
      get .detail
      die "the account was not registered: ${F[0]:-a conflict}. If it is this demo account," \
        "run again with --skip-invite --account-id <its id> (the run that registered it printed it)"
      ;;
    *) refused "the account registration" ;;
  esac
  get .id
  ACCOUNT_ID=${F[0]-}
  [[ $ACCOUNT_ID =~ $UUID_RE ]] || die "the account registration answered without an account id"
  # L6: the one value --account-id needs, on the terminal alone (never stdout or stderr).
  show "Demo account $ACCOUNT_ID registered; it stays pending until its key is imported." \
    "A later run can reuse it: --skip-invite --account-id $ACCOUNT_ID"
}

step_up() { # step_up [CHALLENGE_ID]: elevate the session for the keys class
  local try again
  for try in 1 2; do
    ask_code "A new code for the keys step-up: "
    if [[ -n ${1-} ]]; then
      encode password:s "$PASSWORD" code:s "$CODE" challenge_id:s "$1"
    else
      encode password:s "$PASSWORD" code:s "$CODE" action_class:s keys
    fi
    call POST /auth/step-up "$BODY" session
    [[ $STATUS == 401 ]] || break
    ((try == 2)) || say "That code was refused: wait for the next one" \
      "(a third refusal makes the session read-only for 5 minutes)."
  done
  case $STATUS in
    200) ;;
    000) unreachable ;;
    401)
      again="--skip-invite"
      if [[ -n $ACCOUNT_ID ]]; then again+=" --account-id <the account id>"; fi
      die "the step-up was refused twice: wait 5 minutes, then run again with $again"
      ;;
    *) refused "the step-up" ;;
  esac
  # 22 (SR-013): a step-up rotates the session. The served code does not yet: take what it sends.
  get .tokens.access_token :csrf
  if [[ -n ${F[0]-} ]]; then
    [[ ${F[0]} =~ $TOKEN_RE ]] || die "the step-up answered with a malformed access token"
    ACCESS=${F[0]}
  fi
  if [[ -n ${F[1]-} ]]; then
    [[ ${F[1]} =~ $TOKEN_RE ]] || die "the step-up answered with a malformed CSRF cookie"
    CSRF=${F[1]}
  fi
  F=()
}

elevated() { # elevated PATH BODY KEY [MAX_TIME]: POST it on the session; a challenge once
  local challenge
  call POST "$1" "$2" session "$3" "${4-}"
  if [[ $STATUS == 403 ]]; then
    get .code .challenge_id
    if [[ ${F[0]-} == step_up_required ]]; then
      challenge=${F[1]-}
      [[ $challenge =~ $UUID_RE ]] || die "the api asked for a step-up without a challenge id"
      say "The api asks for the step-up again."
      step_up "$challenge"
      call POST "$1" "$2" session "$3" "${4-}" # the held request, sent again as it was
    fi
  fi
}

import_key() {
  local key held
  key=$(new_uuid) || die "python3 could not make an idempotency key"
  encode api_key:s "$API_KEY" api_secret:s "$API_SECRET" label:s "$KEY_LABEL" \
    read_only:b "$READ_ONLY" expected_uid:s "$EXCHANGE_UID"
  held=$BODY API_KEY="" API_SECRET=""
  elevated "/exchange-accounts/$ACCOUNT_ID/keys" "$held" "$key" 120 # it signs against Bybit
  held=""
  BODY=""
  case $STATUS in
    201)
      forget_shown
      printf '%s' "$RESP" | py verdict
      say "The key passed every check and is stored."
      ;;
    000)
      die "the api did not answer the import, which may have run:" \
        "read the account's keys before trying again"
      ;;
    422)
      printf '%s' "$RESP" | py verdict
      get .errors.rule .code
      die "the key was refused: ${F[0]:-${F[1]-}}"
      ;;
    502 | 503)
      refused "the key import (no verdict, nothing was stored: run again later" \
        "with --skip-invite --account-id <the account id>)"
      ;;
    *) refused "the key import" ;;
  esac
}

main() {
  while (($#)); do
    case $1 in
      --skip-invite) SKIP_INVITE=true ;;
      --account-id)
        (($# >= 2)) || usage
        ACCOUNT_ID=$2
        shift
        ;;
      -h | --help) usage 0 ;;
      *) usage ;;
    esac
    shift
  done
  if [[ -n $ACCOUNT_ID && ! $ACCOUNT_ID =~ $UUID_RE ]]; then
    say "$PROG: --account-id takes the account's UUID"
    exit 2
  fi
  command -v curl >/dev/null 2>&1 || die "curl is not installed"
  command -v python3 >/dev/null 2>&1 || die "python3 is not installed"
  if (: >/dev/tty) 2>/dev/null; then exec 3>/dev/tty; else exec 3>&2; fi
  say "CandleViewer demo host: the Owner's first run (the bootstrap, then $API only)."
  if [[ $SKIP_INVITE != true ]]; then
    bootstrap_invite
    redeem_invite
  fi
  sign_in
  collect_key
  step_up # createExchangeAccount and createApiKey both need the keys step-up
  [[ -n $ACCOUNT_ID ]] || create_account
  import_key
}

main "$@"
