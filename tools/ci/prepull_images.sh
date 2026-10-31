#!/usr/bin/env bash
# #4301, CI-INFRA-001: pull the images a job needs before its tests, so no test pulls one.
#
#   tools/ci/prepull_images.sh [--list FILE] [--compose FILE] NAME...
#
# Each NAME is a row of the list (default infra/images/prepull.txt): `name source mirror`.
# `source` is a pinned `repo:tag@sha256:digest`, or `compose:<repo>` for the pin the compose file
# (default infra/compose/docker-compose.yml) already carries. `mirror` is a pinned ref of the same
# image on another registry, or `-` when the image has none. The source is pulled by digest with
# 5 attempts (waits PREPULL_BACKOFF, default 10 20 40 60 s); if every attempt fails, the mirror is
# tried (3 attempts, waits PREPULL_MIRROR_BACKOFF, default 30 60 s). Each pull is bounded to
# PREPULL_PULL_TIMEOUT seconds (default 120). The mirror's digest must equal the source's, before
# and after the pull. The image is then tagged `repo:tag` locally, where testcontainers looks, so
# it never pulls one. For a `compose:` row the compose file's own reference (`repo:tag@sha256:..`)
# must also resolve locally, else the step fails: a daemon that records a digest only for a direct
# pull would make the compose step pull that reference from the source again.
#
# Worst case per image, with T = PREPULL_PULL_TIMEOUT: source 5T + (10+20+40+60) s of waits, then
# mirror 3T + (30+60) s, so 8T + 220 s. T=120 gives 1180 s (the 20-minute job default covers one
# image); each py-perf shard sets T=45: 580 s, inside its 16-minute timeout (#5193). Fast
# failures return at once.
# The source of each image and its digest go to $GITHUB_STEP_SUMMARY.
set -euo pipefail

list=infra/images/prepull.txt
compose=infra/compose/docker-compose.yml
read -ra backoff <<<"${PREPULL_BACKOFF:-10 20 40 60}"
read -ra mirror_backoff <<<"${PREPULL_MIRROR_BACKOFF:-30 60}"
summary=${GITHUB_STEP_SUMMARY:-/dev/null}
PREPULL_TIMEOUT=${PREPULL_PULL_TIMEOUT:-120}
[[ "$PREPULL_TIMEOUT" =~ ^[0-9]+$ ]] || { echo "CI-INFRA-001: PREPULL_PULL_TIMEOUT must be whole seconds" >&2; exit 1; }

fail() {
  echo "CI-INFRA-001: $* - image pre-pull failed; re-run the job, never change a budget" >&2
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    --list) list=${2:?--list needs a file}; shift 2 ;;
    --compose) compose=${2:?--compose needs a file}; shift 2 ;;
    --) shift; break ;;
    -*) fail "unknown option $1" ;;
    *) break ;;
  esac
done
[ $# -gt 0 ] || fail "no image name given"
[ -r "$list" ] || fail "cannot read $list"

# pull_with_retries REF ATTEMPTS WAIT...: `docker pull` REF (each pull bounded), waiting
# between attempts; the last WAIT repeats.
pull_with_retries() {
  local ref=$1 attempts=$2 i
  shift 2
  local waits=("$@")
  for ((i = 1; i <= attempts; i++)); do
    if timeout "${PREPULL_TIMEOUT}" docker pull --quiet "$ref" >/dev/null; then
      return 0
    fi
    echo "pull of ${ref%%@*} failed (attempt $i of $attempts)" >&2
    if [ "$i" -lt "$attempts" ]; then
      local idx=$((i - 1))
      if [ "$idx" -ge "${#waits[@]}" ]; then
        idx=$((${#waits[@]} - 1))
      fi
      sleep "${waits[$idx]}"
    fi
  done
  return 1
}

# served_digest REF DIGEST: the daemon reports DIGEST among REF's repo digests.
served_digest() {
  local ref=$1 digest=$2 got
  got=$(docker image inspect --format '{{join .RepoDigests " "}}' "$ref") || return 1
  [[ " $got " == *"@sha256:$digest "* ]]
}

prepull() {
  local want=$1 src mirror repo_tag digest source_name="" ref
  local line
  line=$(awk -v n="$want" '$1 == n { print; exit }' "$list")
  [ -n "$line" ] || fail "$want is not a row of $list"
  read -r _ src mirror <<<"$line"
  local from_compose=0
  if [[ "$src" == compose:* ]]; then
    from_compose=1
    src=$(grep -m1 "image: ${src#compose:}:" "$compose" | awk '{print $2}') || true
    [ -n "$src" ] || fail "$want: no pinned image in $compose"
  fi
  [[ "$src" =~ ^([a-z0-9][a-z0-9._/:-]*)@sha256:([0-9a-f]{64})$ ]] || fail "$want: $src is not a digest-pinned ref"
  repo_tag=${BASH_REMATCH[1]}
  digest=${BASH_REMATCH[2]}

  local hub_ok=0
  if pull_with_retries "$src" 5 "${backoff[@]}"; then
    if served_digest "$src" "$digest"; then
      hub_ok=1
    else
      echo "$want: ${src%%@*} served a digest other than sha256:$digest" >&2
    fi
  fi
  if [ "$hub_ok" = 1 ]; then
    source_name="Docker Hub"
    ref=$src
  elif [ "${mirror:--}" != "-" ]; then
    [[ "$mirror" =~ ^[a-z0-9][a-z0-9._/:-]*@sha256:([0-9a-f]{64})$ ]] || fail "$want: $mirror is not a digest-pinned ref"
    [ "${BASH_REMATCH[1]}" = "$digest" ] || fail "$want: the mirror pin's digest differs from the source pin's sha256:$digest"
    echo "$want: falling back to the mirror ${mirror%%@*}" >&2
    pull_with_retries "$mirror" 3 "${mirror_backoff[@]}" || fail "$want: ${src%%@*} and ${mirror%%@*} both failed to pull"
    served_digest "$mirror" "$digest" || fail "$want: the mirror served a digest other than sha256:$digest"
    source_name="Public ECR mirror"
    ref=$mirror
  else
    fail "$want: ${src%%@*} failed to pull and it has no mirror"
  fi

  docker tag "$ref" "$repo_tag" || fail "$want: cannot tag $repo_tag"
  if [ "$from_compose" = 1 ]; then
    docker image inspect "${repo_tag}@sha256:${digest}" >/dev/null ||
      fail "$want: ${repo_tag}@sha256:${digest} does not resolve locally; the compose step would pull it"
  fi
  docker image inspect "$repo_tag" >/dev/null || fail "$want: $repo_tag is not in the daemon after the pull"
  echo "$want: $repo_tag from $source_name, sha256:$digest"
  printf '| %s | %s | %s | `sha256:%s` |\n' "$want" "$repo_tag" "$source_name" "$digest" >>"$summary"
}

{
  echo "### Image pre-pull (#4301)"
  echo
  echo "| Name | Image | Served by | Digest |"
  echo "| --- | --- | --- | --- |"
} >>"$summary"
for n in "$@"; do
  prepull "$n"
done
