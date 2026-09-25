#!/usr/bin/env bash
set -euo pipefail

ZERO_SHA="0000000000000000000000000000000000000000"
EVENT_NAME="${DSP_EVENT_NAME:-}"
PR_BASE_SHA="${DSP_PR_BASE_SHA:-}"
PUSH_BEFORE_SHA="${DSP_PUSH_BEFORE_SHA:-}"
DEFAULT_BRANCH="${DSP_DEFAULT_BRANCH:-}"
REMOTE_NAME="${DSP_REMOTE_NAME:-origin}"

fail() {
  echo "Ruff baseline resolution failed: $*" >&2
  exit 1
}

is_commit() {
  local candidate="$1"
  [[ -n "$candidate" ]] && git cat-file -e "${candidate}^{commit}" 2>/dev/null
}

canonical_commit() {
  git rev-parse "$1^{commit}"
}

head_parent() {
  local parent
  if ! parent="$(git rev-parse HEAD^ 2>/dev/null)"; then
    fail "HEAD has no parent for ${EVENT_NAME}"
  fi
  printf '%s\n' "$parent"
}

HEAD_SHA="$(git rev-parse HEAD 2>/dev/null)" || fail "HEAD is not resolvable"

case "$EVENT_NAME" in
  pull_request)
    [[ -n "$PR_BASE_SHA" ]] || fail "pull_request base SHA is missing"
    is_commit "$PR_BASE_SHA" || fail "pull_request base SHA is not resolvable: ${PR_BASE_SHA}"
    canonical_commit "$PR_BASE_SHA"
    ;;
  push)
    [[ -n "$PUSH_BEFORE_SHA" ]] || fail "push before SHA is missing"
    if [[ "$PUSH_BEFORE_SHA" == "$ZERO_SHA" ]]; then
      head_parent
      exit 0
    fi
    if is_commit "$PUSH_BEFORE_SHA"; then
      canonical_commit "$PUSH_BEFORE_SHA"
      exit 0
    fi

    [[ -n "$DEFAULT_BRANCH" ]] || fail "default branch is missing for push fallback"
    remote_ref="refs/remotes/${REMOTE_NAME}/${DEFAULT_BRANCH}"
    if ! git fetch --no-tags "$REMOTE_NAME" "+refs/heads/${DEFAULT_BRANCH}:${remote_ref}"; then
      fail "failed to fetch default branch ${REMOTE_NAME}/${DEFAULT_BRANCH}"
    fi
    is_commit "$remote_ref" || fail "fetched default branch is not resolvable: ${remote_ref}"

    if ! merge_base="$(git merge-base HEAD "$remote_ref" 2>/dev/null)"; then
      fail "no common ancestor between HEAD and ${REMOTE_NAME}/${DEFAULT_BRANCH}"
    fi
    [[ "$merge_base" != "$HEAD_SHA" ]] || fail "fallback baseline equals HEAD; refusing Ruff self-comparison"
    printf '%s\n' "$merge_base"
    ;;
  workflow_dispatch)
    head_parent
    ;;
  *)
    fail "unsupported event: ${EVENT_NAME:-<empty>}"
    ;;
esac
