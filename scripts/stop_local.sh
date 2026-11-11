#!/usr/bin/env bash
# Stops everything started by run_local.sh and waits (up to ~10s) for each process to actually exit.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
for f in "$ROOT"/.run/*.pid; do
  [ -f "$f" ] || continue
  pid="$(cat "$f")"
  kill "$pid" 2>/dev/null && echo "stopping $(basename "$f" .pid) (pid $pid)"
  for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
  rm -f "$f"
done
