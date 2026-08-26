from uuid import uuid4

import pytest

from app.models import Account
from app.schemas import EntryInput
from app.services.ledger import (
    AccountNotFoundError,
    CurrencyMismatchError,
    UnbalancedTransactionError,
    get_balance,
    post_transaction,
)


@pytest.fixture
def gbp_accounts(db):
    customer = Account(name="Customer Balance", type="customer_balance", currency="GBP")
    cash = Account(name="Platform Cash", type="platform_cash", currency="GBP")
    revenue = Account(name="Platform Revenue", type="platform_revenue", currency="GBP")
    db.add_all([customer, cash, revenue])
    db.commit()
    return customer, cash, revenue


def test_balanced_transaction_posts_and_updates_balances(db, gbp_accounts):
    customer, cash, _ = gbp_accounts

    txn = post_transaction(
        db,
        entries=[
            EntryInput(account_id=customer.id, amount=-5000, currency="GBP"),
            EntryInput(account_id=cash.id, amount=5000, currency="GBP"),
        ],
        tx_type="payment",
    )

    assert txn.status == "posted"
    assert get_balance(db, customer.id) == -5000
    assert get_balance(db, cash.id) == 5000


def test_three_way_split_with_a_fee(db, gbp_accounts):
    """A payment where the platform also takes a fee — three entries, still zero-sum."""
    customer, cash, revenue = gbp_accounts

    post_transaction(
        db,
        entries=[
            EntryInput(account_id=customer.id, amount=-5000, currency="GBP"),
            EntryInput(account_id=cash.id, amount=4800, currency="GBP"),
            EntryInput(account_id=revenue.id, amount=200, currency="GBP"),
        ],
        tx_type="payment",
    )

    assert get_balance(db, customer.id) == -5000
    assert get_balance(db, cash.id) == 4800
    assert get_balance(db, revenue.id) == 200


def test_unbalanced_transaction_is_rejected_and_nothing_persists(db, gbp_accounts):
    customer, cash, _ = gbp_accounts

    with pytest.raises(UnbalancedTransactionError):
        post_transaction(
            db,
            entries=[
                EntryInput(account_id=customer.id, amount=-5000, currency="GBP"),
                EntryInput(account_id=cash.id, amount=4900, currency="GBP"), 
            ],
            tx_type="payment",
        )

    assert get_balance(db, customer.id) == 0
    assert get_balance(db, cash.id) == 0


def test_currency_mismatch_against_account_is_rejected(db, gbp_accounts):
    customer, cash, _ = gbp_accounts  

    with pytest.raises(CurrencyMismatchError):
        post_transaction(
            db,
            entries=[
                EntryInput(account_id=customer.id, amount=-5000, currency="USD"),
                EntryInput(account_id=cash.id, amount=5000, currency="USD"),
            ],
            tx_type="payment",
        )


def test_unknown_account_is_rejected(db, gbp_accounts):
    customer, _cash, _revenue = gbp_accounts

    with pytest.raises(AccountNotFoundError):
        post_transaction(
            db,
            entries=[
                EntryInput(account_id=customer.id, amount=-5000, currency="GBP"),
                EntryInput(account_id=uuid4(), amount=5000, currency="GBP"),
            ],
            tx_type="payment",
        )


def test_zero_amount_entry_is_rejected_at_the_schema_level():
    with pytest.raises(ValueError):
        EntryInput(account_id=uuid4(), amount=0, currency="GBP")


def test_single_entry_transaction_is_rejected(db, gbp_accounts):
    customer, _cash, _revenue = gbp_accounts

    with pytest.raises(UnbalancedTransactionError):
        post_transaction(
            db,
            entries=[EntryInput(account_id=customer.id, amount=-5000, currency="GBP")],
            tx_type="payment",
        )
