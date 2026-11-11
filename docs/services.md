# Service catalogue

All services: `GET /health`, `GET /ready`, `GET /metrics`, FastAPI docs at `/docs`. "JWT" = `Authorization: Bearer <token>` from `auth`. "Internal" = `X-Internal-Token` header, never exposed by the gateway. Money is always **integer cents**.

| Service (local port) | Public endpoints (JWT) | Internal endpoints |
|---|---|---|
| **auth** (8001) | `POST /register`, `POST /login` | |
| **customers** (8005) | `POST /customers`, `GET/PUT /customers/me` | `GET /internal/customers/{user_id}`, `POST /internal/customers/{user_id}/kyc` |
| **accounts** (8002) | `POST /accounts`, `GET /accounts`, `GET /accounts/{id}`, `POST /accounts/{id}/deposit` (demo only) | `POST /internal/transfer`, `POST /internal/credit` |
| **transactions** (8003) | `POST /transfers` (needs `Idempotency-Key`), `GET /transfers` | |
| **fraud** (8006) | | `POST /internal/check`, `GET /internal/decisions` |
| **cards** (8007) | `POST /cards`, `GET /cards`, `POST /cards/{id}/freeze|unfreeze|cancel` | `POST /internal/authorize` |
| **loans** (8008) | `POST /loans`, `GET /loans`, `GET /loans/{id}/schedule`, `POST /loans/{id}/repay` | |
| **ledger** (8009) | `GET /ledger/accounts/{id}/statement` | |
| **notification** (8004) | `GET /notifications` | |
| **audit** (8010) | | `GET /audit?type=&user_id=` |

## Events (Redis Stream `northbank.events`)

Every event has `event_id` (unique), `type`, `occurred_at`, `user_id`, plus type-specific fields.

| Event type | Published by | Read by |
|---|---|---|
| `customer.created`, `kyc.verified`, `kyc.rejected` | customers | audit, notification (kyc only) |
| `transfer.completed`, `transfer.failed`, `transfer.held` | transactions | notification, audit, ledger (completed only) |
| `card.issued`, `card.frozen` | cards | notification, audit |
| `loan.approved`, `loan.rejected`, `loan.repaid` | loans | notification (not repaid), audit |

Delivery is **at-least-once**, so every consumer ignores duplicates by `event_id`.

## Business rules worth knowing

- **KYC gate:** with `REQUIRE_KYC=true`, a customer needs a profile **and** `kyc_status=verified` before opening an account. Unreachable `customers` means 503 (fails closed).
- **Fraud rules** (defaults): more than 50,000.00 is denied; more than 10,000.00 is held for review; more than 5 checks in 60 seconds from one user is denied.
- **Loans:** maximum 50,000.00, 3 to 60 months, 12% a year, one active loan per customer, instant decision, payout into the customer's own account.
- **Cards:** only the last 4 digits are stored. The full number is shown once, at issue. Cancelled is permanent.
- **Transfers:** replaying the same `Idempotency-Key` returns the same result and moves no extra money.
