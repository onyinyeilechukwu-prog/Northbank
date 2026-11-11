#!/usr/bin/env bash
# Copies shared/*.py into each service. We copy (instead of a shared package) to keep every service
# independently buildable: a classic microservices trade-off (duplication vs coupling).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ALL="auth accounts transactions notification customers fraud cards loans ledger audit"
EVENTS="transactions notification customers cards loans ledger audit"
for s in $ALL; do [ -d "$ROOT/services/$s/app" ] && cp "$ROOT/shared/observability.py" "$ROOT/services/$s/app/observability.py"; done
for s in $EVENTS; do [ -d "$ROOT/services/$s/app" ] && cp "$ROOT/shared/events.py" "$ROOT/services/$s/app/events.py"; done
echo "synced shared modules"
