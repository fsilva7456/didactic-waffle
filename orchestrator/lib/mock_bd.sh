#!/usr/bin/env bash
# A minimal stand-in for the `bd` CLI, backed by a JSON file.
#
# Used only by orchestrator/bin/test-swarm.sh, which puts it on PATH as `bd`.
# It implements the handful of verbs the orchestrator actually calls, with the
# same JSON shapes, so the swarm loop can be tested without installing beads.
set -Eeuo pipefail

STORE="${MOCK_BD_STORE:?MOCK_BD_STORE must be set}"
[[ -f "$STORE" ]] || echo '[]' >"$STORE"

_write() { local tmp; tmp=$(mktemp); cat >"$tmp"; mv "$tmp" "$STORE"; }

case "${1:-}" in
  ready)
    # Open beads whose dependencies are all closed.
    jq -c '[ .[] as $i
             | select($i.status == "open")
             | select( [ $i.deps[]? as $d
                         | (map(select(.id == $d)) | .[0].status // "closed") ]
                       | all(. == "closed") )
             | $i ]' "$STORE"
    ;;
  show)
    jq -c --arg id "$2" 'map(select(.id == $id)) | .[0] // {}' "$STORE"
    ;;
  list)
    jq -c '.' "$STORE"
    ;;
  update)
    id="$2"; shift 2
    if [[ "${1:-}" == "--claim" ]]; then
      # Atomic-ish: refuse a bead somebody already holds.
      current=$(jq -r --arg id "$id" 'map(select(.id==$id))|.[0].status // "missing"' "$STORE")
      [[ "$current" == "open" ]] || exit 1
      jq --arg id "$id" 'map(if .id==$id then .status="in_progress" else . end)' \
        "$STORE" | _write
      exit 0
    fi
    [[ "${1:-}" == "--status" ]] || exit 0
    jq --arg id "$id" --arg s "$2" 'map(if .id==$id then .status=$s else . end)' \
      "$STORE" | _write
    ;;
  close)
    jq --arg id "$2" 'map(if .id==$id then .status="closed" else . end)' \
      "$STORE" | _write
    ;;
  comment)
    jq --arg id "$2" --arg c "$3" \
      'map(if .id==$id then .comments = ((.comments // []) + [$c]) else . end)' \
      "$STORE" | _write
    ;;
  create)
    jq --arg t "$2" --arg id "bd-$(printf '%04x' $RANDOM)" \
      '. + [{id:$id, title:$t, description:"", status:"open", priority:2, deps:[]}]' \
      "$STORE" | _write
    ;;
  *) exit 0 ;;
esac
