# NorthBank: a DevOps practice platform

NorthBank is a **fictional, educational** banking platform made of **10 microservices**. It exists so you can practise the full DevOps lifecycle on something realistic: Git workflow, CI/CD, containers, Infrastructure as Code, configuration management, Kubernetes, GitOps, monitoring, security and reliability.

> **Not for real money.** It has no real authentication hardening, no regulatory controls and a deliberately insecure default secret. Never put real customer data in it.

## What is already built (and tested)

Ten small Python (FastAPI) services. The app code is **done**. Your job is everything *around* it.

| Service | What it does | Calls | Events |
|---|---|---|---|
| `auth` | Register, login, issues JWT tokens | | |
| `customers` | Customer profile and **KYC** (identity verification) status | | publishes `customer.created`, `kyc.verified/rejected` |
| `accounts` | Accounts, balances, deposits, internal transfer and credit. Can require KYC before opening an account. | `customers` (when `REQUIRE_KYC=true`) | |
| `transactions` | Transfers with **idempotency keys** | `fraud`, then `accounts` | publishes `transfer.completed/failed/held` |
| `fraud` | Scores a transfer **before** money moves: allow, review or deny | | |
| `cards` | Issue virtual cards, freeze/unfreeze/cancel, authorize spending | `accounts` | publishes `card.issued`, `card.frozen` |
| `loans` | Apply, instant decision by rules, payout, amortization schedule, repayments | `accounts` | publishes `loan.approved/rejected/repaid` |
| `ledger` | Append-only double-entry record of completed transfers, and statements | `accounts` | **consumes** `transfer.completed` |
| `notification` | Stores customer-facing messages | | **consumes** most events |
| `audit` | Keeps a copy of **every** event for compliance (internal only) | | **consumes** everything |

Plus an **nginx gateway** (front door), **Redis** (event bus, using Redis Streams) and one database per service (SQLite locally, Postgres when containerized).

Every service exposes `GET /health` (am I alive?), `GET /ready` (can I serve traffic? checks dependencies), `GET /metrics` (Prometheus format) and writes **JSON logs**. See [docs/services.md](docs/services.md) for every endpoint.

## Try it in 2 minutes (no Docker needed)

You need Python 3.11+ and, for the events, `redis-server` (`sudo apt install redis-server` on Ubuntu/WSL; on Windows use WSL). Without Redis everything still runs, but notifications, ledger and audit stay empty.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt   # every service's dependencies, pinned
scripts/run_local.sh        # starts Redis + all 10 services (ports 8001-8010)
python3 scripts/smoke_test.py   # a customer's whole journey, 26 checks
scripts/stop_local.sh
```

Run one service's unit tests: `cd services/loans && python -m pytest -q`. There are **94** across the ten services.

Ports locally: auth 8001, accounts 8002, transactions 8003, notification 8004, customers 8005, fraud 8006, cards 8007, loans 8008, ledger 8009, audit 8010, Redis 6390.

## The contract your infrastructure must satisfy

- Every container listens on **port 8000**.
- Service hostnames: `auth`, `customers`, `accounts`, `transactions`, `fraud`, `cards`, `loans`, `ledger`, `notification`, `audit`.
- Environment variables:

| Variable | Used by | Meaning |
|---|---|---|
| `DATABASE_URL` | all ten | e.g. `postgresql://user:pass@db:5432/auth` (default is SQLite) |
| `JWT_SECRET` | all except `fraud` and `audit` | **must be identical everywhere**, 32+ chars |
| `INTERNAL_TOKEN` | accounts, transactions, customers, fraud, cards, loans, audit | shared secret for service-to-service (`/internal/*`) calls |
| `ACCOUNTS_URL` | transactions, cards, loans, ledger | e.g. `http://accounts:8000` |
| `CUSTOMERS_URL` | accounts | where to check KYC, e.g. `http://customers:8000` |
| `REQUIRE_KYC` | accounts | enforce KYC before opening accounts (default `false`) |
| `FRAUD_URL` | transactions | e.g. `http://fraud:8000`. Empty = fraud check skipped |
| `FRAUD_FAIL_OPEN` | transactions | if fraud is down: `false` (default) returns 503, `true` lets transfers through |
| `REDIS_URL` | transactions, notification, customers, cards, loans, ledger, audit | e.g. `redis://redis:6379/0`. Empty = events disabled |
| `EVENT_STREAM` | same as `REDIS_URL` | stream name, default `northbank.events` |
| `DENY_ABOVE_CENTS` | fraud | deny transfers above this (default 5000000 = 50,000.00) |
| `REVIEW_ABOVE_CENTS` | fraud | hold transfers above this for review (default 1000000) |
| `VELOCITY_MAX` | fraud | max checks per user per window (default 5) |
| `VELOCITY_WINDOW_SECONDS` | fraud | the window length (default 60) |
| `MAX_LOAN_CENTS` | loans | largest loan the rules approve (default 5000000) |
| `ANNUAL_RATE_BPS` | loans | yearly interest in basis points (default 1200 = 12%) |

- For Postgres you also need the driver: add `psycopg2-binary` to each service's `requirements.txt` (not pinned or tested here).
- Consumers (`notification`, `ledger`, `audit`) each start a background worker and read the stream through **their own consumer group**, so every one of them gets every event.
- `gateway/nginx.conf` routes `/auth/`, `/customers`, `/accounts`, `/transfers`, `/cards`, `/loans`, `/ledger`, `/notifications`. It deliberately does **not** expose `fraud`, `audit` or any `/internal/*` path.
- Shared code (`shared/observability.py`, `shared/events.py`) is **copied** into each service by `scripts/sync_shared.sh`. Edit the shared copy, then run the script.

## Your roadmap

Start at [docs/00-start-here.md](docs/00-start-here.md). Then work through the phases in order. Each phase has: goal, tools, tasks, **acceptance criteria**, "break it on purpose" tests, hints (not answers), cost notes and what to say in an interview.

| Phase | Topic | Cost |
|---|---|---|
| 0 | Repo, branching, hooks, conventions | $0 |
| 1 | Run it and map it | $0 |
| 2 | Containerize (Dockerfiles, Compose) | $0 |
| 3 | CI with GitHub Actions | $0 |
| 4 | Infrastructure as Code (Terraform) | AWS, small |
| 5 | Configuration management (Ansible) | AWS or local VM |
| 6 | CD and blue/green | AWS or local |
| 7 | Kubernetes and Helm | $0 (kind) |
| 8 | GitOps with Argo CD | $0 (kind) |
| 9 | Monitoring and observability | $0 |
| 10 | Security and secrets | $0 |
| 11 | Reliability: chaos, backup, load | $0 |
| 12 | Capstone and portfolio | $0 |
