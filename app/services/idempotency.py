import hashlib
import json
import time

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import IdempotencyKey, Transaction
from app.schemas import EntryInput
from app.services.ledger import post_transaction


class IdempotencyKeyReuseError(Exception):
    """Same Idempotency-Key used with a materially different request body."""


class IdempotencyInProgressError(Exception):
    """Another request with this key is still being processed; safe to retry shortly."""


def _fingerprint(entries: list[EntryInput], tx_type: str, metadata: dict | None) -> str:
    normalized_entries = sorted(
        (
            {"account_id": str(e.account_id), "amount": e.amount, "currency": e.currency}
            for e in entries
        ),
        key=lambda e: (e["account_id"], e["amount"], e["currency"]),
    )
    payload = {"entries": normalized_entries, "tx_type": tx_type, "metadata": metadata}
    raw = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def create_transaction_idempotent(
    db: Session,
    idempotency_key: str,
    entries: list[EntryInput],
    tx_type: str,
    metadata: dict | None = None,
    *,
    wait_attempts: int = 20,
    wait_interval: float = 0.1,
) -> Transaction:
    fingerprint = _fingerprint(entries, tx_type, metadata)

    claim = IdempotencyKey(key=idempotency_key, request_fingerprint=fingerprint, status="processing")
    db.add(claim)
    try:
        db.commit()
    except IntegrityError:
        # someone else's request already holds this key - don't retry the
        # write ourselves, wait for whoever is holding it
        db.rollback()
        return _await_result(db, idempotency_key, fingerprint, wait_attempts, wait_interval)

    # we won the claim - actually do the work
    try:
        txn = post_transaction(db, entries=entries, tx_type=tx_type, metadata={**(metadata or {}), "_idempotency_key": idempotency_key})
    except Exception:
        # the operation never completed - release the key so a corrected
        # retry isn't blocked forever. 
        db.query(IdempotencyKey).filter(IdempotencyKey.key == idempotency_key).delete()
        db.commit()
        raise

    row = db.query(IdempotencyKey).filter(IdempotencyKey.key == idempotency_key).one()
    row.transaction_id = txn.id
    row.status = "completed"
    db.commit()

    return txn


def _await_result(
    db: Session,
    idempotency_key: str,
    fingerprint: str,
    wait_attempts: int,
    wait_interval: float,
) -> Transaction:
    for _ in range(wait_attempts):
        row = db.query(IdempotencyKey).filter(IdempotencyKey.key == idempotency_key).first()

        if row is None:
            # the original claimant's failure-cleanup raced us; caller may retry
            raise IdempotencyInProgressError("idempotency key claim vanished mid-flight; retry the request")

        if row.request_fingerprint != fingerprint:
            raise IdempotencyKeyReuseError(
                "Idempotency-Key was already used with a different request body"
            )

        if row.status == "completed" and row.transaction_id is not None:
            return db.query(Transaction).filter(Transaction.id == row.transaction_id).one()

        db.rollback()  # release our read snapshot before sleeping so the next poll sees fresh commits
        time.sleep(wait_interval)

    raise IdempotencyInProgressError(
        "Another request with this idempotency key is still processing; retry shortly"
    )