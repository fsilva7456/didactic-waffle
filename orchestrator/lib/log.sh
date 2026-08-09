# shellcheck shell=bash
# Structured-ish logging. Human lines on stderr, machine lines to the run log.

_log_level_num() {
  case "$1" in
    debug) echo 10 ;;
    info)  echo 20 ;;
    warn)  echo 30 ;;
    error) echo 40 ;;
    *)     echo 20 ;;
  esac
}

_log() {
  local level="$1"; shift
  local want cur ts line
  want=$(_log_level_num "$PIPELINE_LOG_LEVEL")
  cur=$(_log_level_num "$level")
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  line="[$ts] [${level^^}] $*"

  # The run log keeps everything regardless of console verbosity.
  if [[ -n "${PIPELINE_RUN_LOG:-}" ]]; then
    printf '%s\n' "$line" >>"$PIPELINE_RUN_LOG"
  fi
  (( cur >= want )) && printf '%s\n' "$line" >&2
  return 0
}

log_debug() { _log debug "$@"; }
log_info()  { _log info  "$@"; }
log_warn()  { _log warn  "$@"; }
log_error() { _log error "$@"; }

die() { log_error "$@"; exit 1; }

# Emit a machine-readable event for dashboards and post-run analysis.
log_event() {
  local kind="$1"; shift
  [[ -n "${PIPELINE_EVENT_LOG:-}" ]] || return 0
  local payload
  payload=$(jq -cn --arg kind "$kind" --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --args '{ts:$ts, kind:$kind, args:$ARGS.positional}' "$@")
  printf '%s\n' "$payload" >>"$PIPELINE_EVENT_LOG"
}
