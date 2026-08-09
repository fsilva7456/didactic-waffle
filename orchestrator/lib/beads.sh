# shellcheck shell=bash
# Adapter over the `bd` (beads) CLI.
#
# Every beads call in the pipeline goes through this file. bd's JSON envelope
# has shifted between releases, so the shape-normalising helpers below are the
# single place to fix if your `bd` version disagrees. Run
# `orchestrator/bin/doctor.sh` to check the assumptions against your install.

BD_BIN="${BD_BIN:-bd}"

bd_available() { command -v "$BD_BIN" >/dev/null 2>&1; }

bd_raw() { "$BD_BIN" "$@"; }

# bd has shipped bare arrays, {"issues":[...]} and {"data":[...]}. Accept all
# three and always hand back a bare array.
_bd_unwrap_list() {
  jq -c 'if type=="array" then .
         elif has("issues") then .issues
         elif has("data") then .data
         elif has("results") then .results
         else [.] end'
}

# Reduce a bead to the fields the orchestrator depends on, so that extra or
# renamed fields upstream cannot break the loop.
_bd_normalise() {
  jq -c 'map({
    id:          (.id // .issue_id // .key),
    title:       (.title // .summary // ""),
    description: (.description // .body // ""),
    priority:    (.priority // .p // 2),
    status:      (.status // .state // "open"),
    type:        (.type // .issue_type // "task"),
    assignee:    (.assignee // null)
  }) | map(select(.id != null))'
}

# Beads with every dependency satisfied — the schedulable set.
bd_ready_json() {
  bd_raw ready --json 2>/dev/null | _bd_unwrap_list | _bd_normalise
}

bd_ready_ids() {
  bd_ready_json | jq -r '.[].id'
}

bd_show_json() {
  local id="$1"
  bd_raw show "$id" --json 2>/dev/null \
    | jq -c 'if type=="array" then .[0] else (.issue // .data // .) end'
}

bd_title() {
  bd_show_json "$1" | jq -r '.title // .summary // ""'
}

# Full text handed to an implementer: title, body, and acceptance criteria.
bd_brief() {
  local id="$1"
  bd_show_json "$id" | jq -r '
    "# " + (.title // .summary // "untitled") + "\n\n" +
    "- id: " + (.id // .issue_id // "?") + "\n" +
    "- type: " + ((.type // .issue_type // "task")|tostring) + "\n" +
    "- priority: " + ((.priority // .p // 2)|tostring) + "\n\n" +
    (.description // .body // "(no description)") + "\n" +
    (if (.acceptance_criteria // null) then
       "\n## Acceptance criteria\n" + (.acceptance_criteria|tostring) + "\n"
     else "" end)'
}

# Atomic claim. Two orchestrator loops racing for the same bead must not both
# win; a non-zero exit here means somebody else got it.
bd_claim() {
  local id="$1"
  bd_raw update "$id" --claim >/dev/null 2>&1
}

bd_set_status() {
  local id="$1" status="$2"
  bd_raw update "$id" --status "$status" >/dev/null 2>&1 || \
    log_warn "bd: could not set status=$status on $id"
}

bd_close() {
  local id="$1"
  bd_raw close "$id" >/dev/null 2>&1
}

# Park a bead the swarm could not land, with the reason attached so the next
# run (or a human) sees why without digging through logs.
bd_block() {
  local id="$1" reason="$2"
  bd_raw update "$id" --status blocked >/dev/null 2>&1 || true
  bd_raw comment "$id" "orchestrator: $reason" >/dev/null 2>&1 || \
    log_warn "bd: could not attach block reason to $id"
}

bd_open_count() {
  bd_raw list --json 2>/dev/null | _bd_unwrap_list | _bd_normalise \
    | jq '[.[] | select(.status != "closed" and .status != "done")] | length'
}

bd_blocked_count() {
  bd_raw list --json 2>/dev/null | _bd_unwrap_list | _bd_normalise \
    | jq '[.[] | select(.status == "blocked")] | length'
}
