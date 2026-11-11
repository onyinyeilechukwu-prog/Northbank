# Phase 1: Run it and map it

**Maps to:** Weeks 1, 2, 4 (Linux, networking, Python), Week 10 (architecture).

## Goal
Understand the application as an operator, before you automate anything. You cannot containerize or monitor what you do not understand.

## Tools
Python venv, curl, `jq` (optional), your browser (FastAPI serves interactive docs at `/docs` on each service).

## Tasks
1. Create a virtual environment, install the requirements, run the unit tests for each service. Note how many tests pass.
2. Start everything with `scripts/run_local.sh`, run `python3 scripts/smoke_test.py`, then read the script to see what each step proves.
3. Open `http://127.0.0.1:8001/docs` and try `/register` and `/login` by hand. Copy the token and call `accounts` with it.
4. Read the service logs in `.run/*.log`. Find the JSON log line for your transfer.
5. Look at `http://127.0.0.1:8002/metrics`. Find `http_requests_total` and explain each label.
6. Draw the architecture yourself on paper or in a diagram tool, **from memory**, then compare with `docs/00-start-here.md`. Commit your version as `docs/architecture.md`.
7. Fill in a table in `docs/runbook.md`: for each service, its port, its environment variables, its dependencies, and what you would check first if it were down.

## Acceptance criteria
- [ ] All ten services' tests pass on your machine (94 tests).
- [ ] You can explain, without notes, why `transactions` returns 503 when `accounts` is down.
- [ ] You can explain the difference between `/health` and `/ready`.
- [ ] Your `docs/runbook.md` lists env vars for every service.

## Break it on purpose
- Stop only `accounts` (kill its PID from `.run/accounts.pid`) and make a transfer. Predict the response first, then check.
- Send the same transfer twice with the same `Idempotency-Key`; then with a new key. Compare balances.
- Use a token signed with a different `JWT_SECRET` and read the 401.
- Send an `amount_cents` of `-5` and `0` and read the 422 message.

## Hints
- `python3 -m venv .venv && source .venv/bin/activate`.
- If you see "address already in use", a previous run is still shutting down: run `scripts/stop_local.sh` and wait a few seconds.
- Ports: auth 8001, accounts 8002, transactions 8003, notification 8004, customers 8005, fraud 8006, cards 8007, loans 8008, ledger 8009, audit 8010, Redis 6390.
- No Redis? `sudo apt install redis-server`. Without it, events (notifications, ledger, audit) do not flow.

## Cost
$0.

## Interview talking points
Walk through one request across services. Explain idempotency, why money is stored as integer cents, and why each service owns its database.
