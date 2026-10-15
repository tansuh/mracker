# mracker

[![CI](https://github.com/tansuh/mracker/actions/workflows/ci.yml/badge.svg)](https://github.com/tansuh/mracker/actions/workflows/ci.yml)

A double-entry financial ledger and payment processing API built with FastAPI and PostgreSQL.

Every money movement is recorded as a transaction made of two or more ledger entries that must sum to zero per currency. Balances are never stored; they are derived from the ledger on every read, so a balance can't drift away from the entries behind it.

## Features

- **Double-entry ledger.** Transactions are validated before anything is written: at least two entries, entries balance to zero per currency, every account exists, and each entry's currency matches its account.
- **Integer amounts.** Amounts are stored as `BIGINT` in minor units (for example pence or cents), so there is no floating-point rounding.
- **Idempotent writes.** `POST /transactions` requires an `Idempotency-Key` header. Retrying with the same key and body returns the original transaction. Reusing a key with a different body is rejected. Concurrent requests with the same key create exactly one transaction.
- **Signed webhooks.** Each posted transaction enqueues a `transaction.posted` event in the same database transaction (an outbox pattern). A background worker delivers it with an HMAC-SHA256 signature and retries with exponential backoff.
- **Reconciliation.** A job heals or cleans up stuck idempotency keys and reports webhook events that are stale or have failed.
- **Admin views.** Read-only HTML pages list recent accounts (with balances) and transactions.

## Tech stack

Python 3.12 · FastAPI · SQLAlchemy · Pydantic v2 · PostgreSQL 16 · Docker Compose · pytest · GitHub Actions

## Project structure

```
app/
├── main.py              # FastAPI app and public endpoints
├── admin.py             # /admin HTML views
├── worker.py            # Webhook delivery worker
├── database.py          # Engine, session, DATABASE_URL
├── models.py            # SQLAlchemy models
├── schemas.py           # Pydantic request/response schemas
└── services/
    ├── ledger.py          # Transaction validation, posting, balances
    ├── idempotency.py     # Idempotency-key claim/wait logic
    ├── webhooks.py        # Event enqueueing, signing, delivery
    └── reconciliation.py  # Cleanup and reporting job
tests/                   # Ledger, webhook and concurrency tests
schema.sql               # Reference SQL schema
```

## Getting started

### With Docker Compose

```bash
export WEBHOOK_ENDPOINT_URL=https://example.com/webhooks   # where events are delivered
export WEBHOOK_SECRET=change-me                            # used to sign payloads
docker compose up --build
```

This starts four services:

| Service    | Purpose                                                   |
|------------|-----------------------------------------------------------|
| `postgres` | PostgreSQL 16 on port 5432 (user/password `ledger`, database `mracker`) |
| `migrate`  | Creates the schema and then exits                         |
| `api`      | The API on http://localhost:8000                          |
| `worker`   | Polls for pending webhook events and delivers them        |

Interactive API docs are at http://localhost:8000/docs.

### Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

docker compose up -d postgres     # or point DATABASE_URL at your own Postgres
export DATABASE_URL=postgresql://ledger:ledger@localhost:5432/mracker

python -c "from app.database import Base, engine; from app import models; Base.metadata.create_all(engine)"
uvicorn app.main:app --reload
```

In a second terminal, start the webhook worker:

```bash
WEBHOOK_ENDPOINT_URL=... WEBHOOK_SECRET=... python -m app.worker
```

### Configuration

Settings come from environment variables. A `.env` file in the project root is also loaded (it is gitignored).

| Variable               | Used by      | Default                                                  |
|------------------------|--------------|----------------------------------------------------------|
| `DATABASE_URL`         | API, worker  | `postgresql://ledger:ledger@localhost:5432/ledger`       |
| `TEST_DATABASE_URL`    | tests        | `postgresql://ledger:ledger@localhost:5432/mracker_test` |
| `WEBHOOK_ENDPOINT_URL` | worker       | none (required)                                          |
| `WEBHOOK_SECRET`       | worker       | none (required)                                          |

## API

### `POST /transactions`

Posts a balanced transaction. Requires an `Idempotency-Key` header.

```bash
curl -X POST http://localhost:8000/transactions \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 7f1c2e9a-payment-001" \
  -d '{
    "tx_type": "transfer",
    "entries": [
      {"account_id": "<source-account-uuid>", "amount": -2500, "currency": "GBP"},
      {"account_id": "<dest-account-uuid>",   "amount":  2500, "currency": "GBP"}
    ],
    "metadata": {"reference": "invoice-42"}
  }'
```

Response `201 Created`:

```json
{
  "id": "…",
  "status": "posted",
  "entries": [
    {"account_id": "…", "amount": -2500, "currency": "GBP"},
    {"account_id": "…", "amount": 2500, "currency": "GBP"}
  ]
}
```

| Status | Meaning                                                                    |
|--------|----------------------------------------------------------------------------|
| `201`  | Transaction posted, or the original result returned for a repeated key    |
| `404`  | One or more accounts don't exist                                           |
| `409`  | Key was reused with a different body, or the same key is still in progress |
| `422`  | Unbalanced entries, fewer than two entries, currency mismatch, zero amount, or invalid currency code |

### `GET /accounts/{account_id}/balance`

```json
{"account_id": "…", "balance": 2500}
```

The balance is the sum of all ledger entries for the account, in minor units.

### Admin

- `GET /admin/accounts` lists the 100 most recent accounts with their balances.
- `GET /admin/transactions` lists the 100 most recent transactions with their entries.

> **Note:** The admin pages have no authentication. Don't expose them publicly.

> **Note:** There is no endpoint for creating accounts yet. Insert rows into the `accounts` table directly.

## Webhooks

Each posted transaction produces a `transaction.posted` event:

```json
{
  "event_type": "transaction.posted",
  "transaction": {
    "id": "…",
    "status": "posted",
    "type": "transfer",
    "entries": [{"account_id": "…", "amount": -2500, "currency": "GBP"}, …]
  }
}
```

Requests are sent with a `Mracker-Signature` header in the form `t=<unix_timestamp>,v1=<hex_signature>`. The signature is `HMAC-SHA256(secret, "<timestamp>.<raw_body>")`.

To verify a delivery on the receiving end, use `verify_signature` from `app/services/webhooks.py`. It compares in constant time and rejects timestamps more than 5 minutes off to prevent replays.

Any non-2xx response or network error is retried after 30s, 1m, 5m, 30m and 2h. After 6 failed attempts the event is marked `failed`.

## Reconciliation

```bash
python -m app.services.reconciliation
```

- **Idempotency keys** stuck in `processing` for over 5 minutes are marked `completed` if a matching transaction exists, and deleted otherwise so the client can retry.
- **Webhook events** that have been `pending` for over 30 minutes past their scheduled attempt, or that are `failed`, are reported for follow-up.

## Testing

Tests run against a real PostgreSQL database. Each test runs inside a transaction that is rolled back at the end.

```bash
docker compose up -d postgres
docker compose exec postgres createdb -U ledger mracker_test
pytest tests/ -v
```

The suite covers:

- ledger validation (balanced and unbalanced entries, currency mismatches, unknown accounts, single entries)
- webhook signing and verification (tampered bodies, wrong secrets, stale timestamps, malformed headers)
- outbox enqueueing
- concurrent requests sharing an idempotency key

CI runs the tests and a Docker build on every push to `main` and on every pull request.

## Limitations / Items left to do 
1. No authentication. Anyone who can reach it can move money and see every account.
2. Too few endpoints. You can't create or list accounts, fetch a single transaction, or list an account's history. A client can post money but can barely read anything back.
3. No overdraft protection. A customer account can go negative, which a payments API has to prevent.
4. The responses are thin. A transaction response has no type, metadata or created_at, and the balance reponse has no currency
