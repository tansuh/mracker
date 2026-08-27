import time

import pytest

from app.models import Account, WebhookEvent
from app.schemas import EntryInput
from app.services.ledger import post_transaction
from app.services.webhooks import build_signature_header, sign_payload, verify_signature

SECRET = "test-secret"


def test_signature_round_trip_verifies():
    body = b'{"hello":"world"}'
    header = build_signature_header(body, SECRET)
    assert verify_signature(body, header, SECRET)


def test_signature_rejects_tampered_body():
    body = b'{"hello":"world"}'
    header = build_signature_header(body, SECRET)
    assert not verify_signature(b'{"hello":"WORLD"}', header, SECRET)


def test_signature_rejects_wrong_secret():
    body = b'{"hello":"world"}'
    header = build_signature_header(body, SECRET)
    assert not verify_signature(body, header, "wrong-secret")


def test_signature_rejects_stale_timestamp():
    body = b'{"hello":"world"}'
    old_timestamp = int(time.time()) - 1000
    header = f"t={old_timestamp},v1={sign_payload(body, SECRET, old_timestamp)}"
    assert not verify_signature(body, header, SECRET, tolerance_seconds=300)


def test_signature_rejects_malformed_header():
    assert not verify_signature(b"{}", "not-a-real-header", SECRET)


@pytest.fixture
def gbp_accounts(db):
    customer = Account(name="Customer", type="customer_balance", currency="GBP")
    cash = Account(name="Cash", type="platform_cash", currency="GBP")
    db.add_all([customer, cash])
    db.commit()
    return customer, cash


def test_posting_a_transaction_enqueues_a_webhook_event(db, gbp_accounts):
    customer, cash = gbp_accounts

    txn = post_transaction(
        db,
        entries=[
            EntryInput(account_id=customer.id, amount=-500, currency="GBP"),
            EntryInput(account_id=cash.id, amount=500, currency="GBP"),
        ],
        tx_type="payment",
    )

    event = db.query(WebhookEvent).filter(WebhookEvent.transaction_id == txn.id).one()
    assert event.status == "pending"
    assert event.attempts == 0
    assert event.payload["event_type"] == "transaction.posted"
    assert event.payload["transaction"]["id"] == str(txn.id)
    amounts = {e["account_id"]: e["amount"] for e in event.payload["transaction"]["entries"]}
    assert amounts[str(customer.id)] == -500
    assert amounts[str(cash.id)] == 500


def test_rejected_transaction_does_not_enqueue_a_webhook_event(db, gbp_accounts):
    customer, cash = gbp_accounts
    before = db.query(WebhookEvent).count()

    with pytest.raises(Exception):
        post_transaction(
            db,
            entries=[
                EntryInput(account_id=customer.id, amount=-500, currency="GBP"),
                EntryInput(account_id=cash.id, amount=400, currency="GBP"),
            ],
            tx_type="payment",
        )

    assert db.query(WebhookEvent).count() == before