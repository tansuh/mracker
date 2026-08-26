from collections import defaultdict
from uuid import UUID
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session 

from app.models import Account, LedgerEntry, Transaction 
from app.schemas import EntryInput

class LedgerError(Exception):
    """default class for errors"""

class UnbalancedTransactionError(LedgerError):
    pass

class CurrencyMismatchError(LedgerError):
    pass

class AccountNotFoundError(LedgerError):
    pass

def post_transaction(
    db: Session,
    entries: list[EntryInput],
    tx_type: str,
    metadata: dict | None = None,
) -> Transaction:

    # creates transactions and ledger entries 
    # validation before session is touched
    # meaning rejected transfer never leaves partial stae behind y.

    if len(entries) < 2:
        raise UnbalancedTransactionError("a transaction needs at least two entries")

    # 1. entries must sum to zero for same cyurrency
    totals: dict[str, int] = defaultdict(int)
    for entry in entries:
        totals[entry.currency] += entry.amount

    for currency, total in totals.items():
        if total != 0:
            raise UnbalancedTransactionError(
                f"Entries in {currency} sum to {total}, expected 0"
            )

    # 2. every referenced account must exist
    account_ids = {entry.account_id for entry in entries}
    accounts = {
        a.id: a
        for a in db.query(Account).filter(Account.id.in_(account_ids)).all()
    }
    missing = account_ids - accounts.keys()
    if missing:
        raise AccountNotFoundError(f"Unknown account(s): {missing}")

    # 3. currency needs to match for each entry and accoutn 
    for entry in entries:
        account_currency = accounts[entry.account_id].currency
        if account_currency != entry.currency:
            raise CurrencyMismatchError(
                f"Account {entry.account_id} is {account_currency}, "
                f"entry is {entry.currency}"
            )

    
    txn = Transaction(type=tx_type, status="posted", metadata_=metadata)
    db.add(txn)
    db.flush()  

    for entry in entries:
        db.add(
            LedgerEntry(
                transaction_id=txn.id,
                account_id=entry.account_id,
                amount=entry.amount,
                currency=entry.currency,
            )
        )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise

    db.refresh(txn)
    return txn


def get_balance(db: Session, account_id: UUID) -> int:
    """
    Balance is never stored directly — it's derived from the ledger every
    time. This is slower than a cached counter, but it makes an entire class
    of "balance silently drifted from reality" bugs structurally impossible.
    """
    total = (
        db.query(func.coalesce(func.sum(LedgerEntry.amount), 0))
        .filter(LedgerEntry.account_id == account_id)
        .scalar()
    )
    return int(total)