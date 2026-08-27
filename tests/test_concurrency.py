import threading
from uuid import uuid4

from sqlalchemy.orm import sessionmaker

from app.models import Account, IdempotencyKey, LedgerEntry, Transaction
from app.schemas import EntryInput
from app.services.idempotency import create_transaction_idempotent
from app.services.ledger import get_balance


def test_concurrent_requests_with_same_idempotency_key_create_exactly_one_transaction(engine):
    """
    Simulates N clients retrying the *same* request (same idempotency key,
    same body) at the same instant - e.g. a slow response causing a client
    to hit "pay" twice. Every caller must get back the SAME transaction,
    and the money must move exactly once, not N times.

    Each thread gets its own Session (own DB connection) deliberately -
    that's what real concurrent API requests look like. Sharing one Session
    across threads would hide the race instead of testing it.
    """
    Session = sessionmaker(bind=engine, future=True)

    setup = Session()
    customer = Account(name="Concurrency Customer", type="customer_balance", currency="GBP")
    cash = Account(name="Concurrency Cash", type="platform_cash", currency="GBP")
    setup.add_all([customer, cash])
    setup.commit()
    customer_id, cash_id = customer.id, cash.id
    setup.close()

    idempotency_key = str(uuid4())
    entries = [
        EntryInput(account_id=customer_id, amount=-1000, currency="GBP"),
        EntryInput(account_id=cash_id, amount=1000, currency="GBP"),
    ]

    results: list = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def attempt() -> None:
        session = Session()
        try:
            txn = create_transaction_idempotent(
                session,
                idempotency_key=idempotency_key,
                entries=entries,
                tx_type="payment",
            )
            with lock:
                results.append(txn.id)
        except Exception as exc:  # noqa: BLE001 - we want to see every failure mode here
            with lock:
                errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=attempt) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    try:
        assert not errors, f"one or more concurrent attempts raised: {errors}"
        assert len(results) == 10
        assert len(set(results)) == 1, "every caller should get back the same transaction id"

        verify = Session()
        assert get_balance(verify, customer_id) == -1000
        assert get_balance(verify, cash_id) == 1000  # NOT -10000 / 10000 - posted exactly once
        verify.close()
    finally:
        # this test commits real rows against the shared test DB (unlike the
        # rollback-per-test `db` fixture in conftest.py), so clean up explicitly.
        # order matters: children before parents, for the foreign keys.
        cleanup = Session()
        cleanup.query(LedgerEntry).filter(
            LedgerEntry.account_id.in_([customer_id, cash_id])
        ).delete(synchronize_session=False)
        cleanup.query(IdempotencyKey).filter(
            IdempotencyKey.key == idempotency_key
        ).delete(synchronize_session=False)
        cleanup.query(Transaction).filter(
            Transaction.id.in_(results)
        ).delete(synchronize_session=False)
        cleanup.query(Account).filter(
            Account.id.in_([customer_id, cash_id])
        ).delete(synchronize_session=False)
        cleanup.commit()
        cleanup.close()