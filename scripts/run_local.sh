#!/usr/bin/env bash
# Runs Redis (if installed) and all ten services locally with SQLite. No Docker needed.
# Ports: auth 8001, accounts 8002, transactions 8003, notification 8004, customers 8005,
#        fraud 8006, cards 8007, loans 8008, ledger 8009, audit 8010, redis 6390.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"
export JWT_SECRET="${JWT_SECRET:-local-dev-secret-that-is-long-enough-123}"
export INTERNAL_TOKEN="${INTERNAL_TOKEN:-local-internal-token}"
export ACCOUNTS_URL="http://127.0.0.1:8002"
export CUSTOMERS_URL="http://127.0.0.1:8005"
export FRAUD_URL="http://127.0.0.1:8006"
export REQUIRE_KYC="${REQUIRE_KYC:-true}"
mkdir -p "$ROOT/.run"

if command -v redis-server >/dev/null 2>&1; then
  redis-server --port 6390 --save "" --appendonly no > "$ROOT/.run/redis.log" 2>&1 &
  echo $! > "$ROOT/.run/redis.pid"
  export REDIS_URL="redis://127.0.0.1:6390/0"
  echo "started redis on :6390"
else
  echo "WARNING: redis-server not found. Services run, but events (notifications, ledger, audit) will not flow."
fi

start() {  # name port
  # cd is separated with ';' so '&' backgrounds ONLY python, and $! is python's real PID.
  ( cd "$ROOT/services/$1"; DATABASE_URL="sqlite:///$ROOT/.run/$1.db" \
    "$PY" -m uvicorn app.main:app --port "$2" > "$ROOT/.run/$1.log" 2>&1 & echo $! > "$ROOT/.run/$1.pid" )
  echo "started $1 on :$2"
}
start auth 8001; start accounts 8002; start transactions 8003; start notification 8004; start customers 8005
start fraud 8006; start cards 8007; start loans 8008; start ledger 8009; start audit 8010
echo "Stop with: scripts/stop_local.sh   Logs in .run/*.log"
