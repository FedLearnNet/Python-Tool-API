#!/bin/sh
# Container entrypoint:
#   1. mirror everything the container prints to stdout AND to a log file
#   2. print a startup diagnostics banner
#   3. exec the CMD (so the app stays PID 1 and still receives SIGTERM)
#
# The banner exists so that a container that otherwise stays completely silent
# (app crashes early, wrong mount, missing package, wrong interpreter) still
# tells us what image, interpreter and environment it was started with.
#
# Env switches:
#   FEDDB_STARTUP_LOG=0    skip the diagnostics banner
#   FEDDB_LOG_TO_FILE=0    do not mirror output to a file
#   FEDDB_LOG_FILE=<path>  explicit log file (skips the directory search)
#   FEDDB_LOG_DIR=<dir>    preferred log directory

set -eu

log() {
  printf '[startup] %s\n' "$*"
}

section() {
  printf '[startup] --- %s ---\n' "$*"
}

# Never let a diagnostics command take the container down: everything below
# runs best-effort and falls back to "n/a".
try() {
  "$@" 2>&1 || printf 'n/a (command failed: %s)\n' "$*"
}

# ---------------------------------------------------------------------------
# 1. tee stdout/stderr into a log file
# ---------------------------------------------------------------------------

# First writable candidate wins; an unwritable mount must not stop the app.
resolve_log_file() {
  if [ -n "${FEDDB_LOG_FILE:-}" ]; then
    dir=$(dirname "${FEDDB_LOG_FILE}")
    if mkdir -p "$dir" 2>/dev/null && touch "${FEDDB_LOG_FILE}" 2>/dev/null; then
      printf '%s\n' "${FEDDB_LOG_FILE}"
    fi
    return 0
  fi

  for dir in ${FEDDB_LOG_DIR:-} /mnt/output/logs /app/logs /tmp; do
    [ -n "$dir" ] || continue
    if mkdir -p "$dir" 2>/dev/null && touch "$dir/pyfedappwrap.log" 2>/dev/null; then
      printf '%s\n' "$dir/pyfedappwrap.log"
      return 0
    fi
  done
}

LOG_FILE=""
TEE_ACTIVE=0
if [ "${FEDDB_LOG_TO_FILE:-1}" != "0" ]; then
  LOG_FILE=$(resolve_log_file || true)
fi

if [ -n "$LOG_FILE" ] && command -v tee >/dev/null 2>&1; then
  FIFO="/tmp/.pyfedappwrap-log.$$"
  if mkfifo "$FIFO" 2>/dev/null; then
    # tee reads the fifo and writes to the real stdout plus the log file.
    tee -a "$LOG_FILE" <"$FIFO" &
    # Point this script's stdout/stderr at the fifo. `exec "$@"` at the bottom
    # inherits these descriptors, so the app's output is mirrored too while the
    # app itself remains PID 1 and keeps receiving signals directly.
    exec >"$FIFO" 2>&1
    rm -f "$FIFO"
    TEE_ACTIVE=1
    printf '\n[startup] ===== new run: %s =====\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || echo unknown)"
  else
    rm -f "$FIFO" 2>/dev/null || true
  fi
fi

# ---------------------------------------------------------------------------
# 2. startup diagnostics banner
# ---------------------------------------------------------------------------

banner() {
  section "pyfedappwrap container"
  log "image family    : ${FEDDB_IMAGE_FAMILY:-unknown}"
  log "image version   : ${PYFEDAPPWRAP_VERSION:-unknown}"
  log "image built     : ${FEDDB_IMAGE_BUILD_DATE:-unknown}"
  log "base image      : ${FEDDB_BASE_IMAGE:-unknown}"
  log "started at      : $(try date -u '+%Y-%m-%dT%H:%M:%SZ')"
  log "hostname        : $(try hostname)"
  log "platform        : $(try uname -srm)"
  log "user            : $(try id)"
  log "workdir         : $(pwd)"
  log "command         : $*"
  if [ "$TEE_ACTIVE" = "1" ]; then
    log "log file        : ${LOG_FILE}"
  else
    log "log file        : disabled (stdout only)"
  fi

  section "python"
  log "python binary   : $(command -v python || echo 'not found')"
  log "python version  : $(try python -V)"
  log "pyfedappwrap    : $(python - <<'PY' 2>&1 || echo 'n/a'
try:
    from importlib.metadata import version
    print(version("FL-Net-Python-Tool-API"))
except Exception as exc:  # noqa: BLE001 - diagnostics only
    print(f"not installed ({exc})")
PY
)"
  log "sys.executable  : $(try python -c 'import sys; print(sys.executable)')"
  log "sys.path[0:5]   : $(try python -c 'import sys; print(sys.path[:5])')"

  if command -v R >/dev/null 2>&1; then
    section "R"
    log "R binary        : $(command -v R)"
    log "R version       : $(R --version 2>&1 | head -n 1 || echo 'n/a')"
    log "R_HOME          : ${R_HOME:-unset}"
    log "R_LIBS_USER     : ${R_LIBS_USER:-unset}"
  fi

  section "mounts"
  for d in /app /mnt/input /mnt/output; do
    if [ -d "$d" ]; then
      log "$d ($(ls -A "$d" 2>/dev/null | wc -l | tr -d ' ') entries): $(ls -A "$d" 2>/dev/null | tr '\n' ' ')"
    else
      log "$d: missing"
    fi
  done

  section "environment"
  # Redact anything that looks like a credential; keep the key names visible so
  # a missing/empty variable is still obvious.
  env | sort | awk -F= '
    {
      key = $1
      val = substr($0, index($0, "=") + 1)
      if (key ~ /KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL/) {
        val = (val == "") ? "<empty>" : "<redacted:" length(val) " chars>"
      }
      printf "[startup] %s=%s\n", key, val
    }'

  section "end of startup diagnostics"
}

if [ "${FEDDB_STARTUP_LOG:-1}" != "0" ]; then
  # Diagnostics must never abort the container start.
  set +e
  banner "$@"
  set -e
fi

# ---------------------------------------------------------------------------
# 3. hand over to the actual command
# ---------------------------------------------------------------------------

exec "$@"
