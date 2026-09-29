#!/usr/bin/env bash
set -u -o pipefail

usage() {
  cat <<'USAGE'
Usage: gh-ci-monitor RUN_ID [--repo OWNER/REPO] [--interval SECONDS] [--timeout SECONDS]

Reliable GitHub Actions polling:
- each gh query has a hard timeout;
- empty/malformed responses are transient failures;
- transient failures retry with bounded backoff;
- only status changes are printed;
- completed runs always exit (0=success, 1=non-success);
- an overall timeout exits 3 instead of hanging forever.
USAGE
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  '') usage >&2; exit 2 ;;
esac

RUN_ID="$1"; shift
REPO=""
INTERVAL=15
OVERALL_TIMEOUT=3600
GH_TIMEOUT=20

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; REPO="$2"; shift 2 ;;
    --interval) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; INTERVAL="$2"; shift 2 ;;
    --timeout) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; OVERALL_TIMEOUT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$INTERVAL" =~ ^[0-9]+$ ]] && (( INTERVAL > 0 )) || { echo "invalid interval" >&2; exit 2; }
[[ "$OVERALL_TIMEOUT" =~ ^[0-9]+$ ]] && (( OVERALL_TIMEOUT > 0 )) || { echo "invalid timeout" >&2; exit 2; }
command -v gh >/dev/null 2>&1 || { echo "gh is required" >&2; exit 2; }
command -v timeout >/dev/null 2>&1 || { echo "timeout is required" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 2; }

repo_args=()
[[ -n "$REPO" ]] && repo_args=(--repo "$REPO")
start_epoch=$(date +%s)
last_snapshot=""
failures=0

while :; do
  now=$(date +%s)
  if (( now - start_epoch >= OVERALL_TIMEOUT )); then
    echo "[ci-monitor] overall timeout after ${OVERALL_TIMEOUT}s" >&2
    exit 3
  fi

  json=""
  if ! json=$(timeout "${GH_TIMEOUT}s" gh run view "$RUN_ID" "${repo_args[@]}" \
      --json status,conclusion,jobs,url 2>/dev/null) || [[ -z "$json" ]]; then
    json=""
  fi

  parsed=""
  if [[ -n "$json" ]]; then
    parsed=$(python3 -c '
import json,sys
try:
    x=json.load(sys.stdin)
    status=x.get("status") or ""
    conclusion=x.get("conclusion") or "-"
    url=x.get("url") or ""
    jobs=" | ".join("%s=%s/%s" % (j.get("name", "?"), j.get("status", "?"), j.get("conclusion") or "-") for j in x.get("jobs", []))
    if not status or not url:
        raise ValueError("missing status/url")
    print("\t".join((status, conclusion, url, jobs)))
except Exception:
    sys.exit(1)
' <<<"$json" 2>/dev/null) || parsed=""
  fi

  if [[ -z "$parsed" ]]; then
    failures=$((failures + 1))
    backoff=$(( INTERVAL * failures ))
    (( backoff > 60 )) && backoff=60
    echo "[ci-monitor] invalid/failed query (streak=${failures}); retry in ${backoff}s" >&2
    sleep "$backoff"
    continue
  fi

  IFS=$'\t' read -r status conclusion url jobs <<<"$parsed"
  failures=0
  snapshot="run=${status}/${conclusion}"
  [[ -n "${jobs:-}" ]] && snapshot+=" | ${jobs}"
  if [[ "$snapshot" != "$last_snapshot" ]]; then
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$snapshot"
    last_snapshot="$snapshot"
  fi

  if [[ "$status" == "completed" ]]; then
    echo "[ci-monitor] completed: ${conclusion:-unknown} ${url}"
    [[ "$conclusion" == "success" ]] && exit 0 || exit 1
  fi

  sleep "$INTERVAL"
done
