
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import IdempotencyKey, Transaction, WebhookEvent

STUCK_IDEMPOTENCY_KEY_GRACE_MINUTES = 5
STALE_WEBHOOK_PENDING_GRACE_MINUTES = 30


def reconcile_idempotency_keys(db: Session) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_IDEMPOTENCY_KEY_GRACE_MINUTES)
    stuck = (
        db.query(IdempotencyKey)
        .filter(IdempotencyKey.status == "processing", IdempotencyKey.created_at < cutoff)
        .all()
    )

    healed, cleaned_up = [], []
    for key_row in stuck:
        matching_txn = (
            db.query(Transaction)
            .filter(Transaction.metadata_["_idempotency_key"].astext == key_row.key)
            .one_or_none()
        )
        if matching_txn is not None:
            key_row.transaction_id = matching_txn.id
            key_row.status = "completed"
            healed.append(key_row.key)
        else:
            db.delete(key_row)
            cleaned_up.append(key_row.key)

    db.commit()
    return {"healed": healed, "cleaned_up": cleaned_up}


def reconcile_webhook_events(db: Session) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_WEBHOOK_PENDING_GRACE_MINUTES)
    stale_pending = (
        db.query(WebhookEvent)
        .filter(WebhookEvent.status == "pending", WebhookEvent.next_attempt_at < cutoff)
        .all()
    )
    failed = db.query(WebhookEvent).filter(WebhookEvent.status == "failed").all()

    return {
        "stale_pending": [str(e.id) for e in stale_pending],
        "failed": [str(e.id) for e in failed],
    }


def run_reconciliation(db: Session) -> dict:
    return {
        "idempotency_keys": reconcile_idempotency_keys(db),
        "webhook_events": reconcile_webhook_events(db),
    }


if __name__ == "__main__":
    from app.database import SessionLocal

    session = SessionLocal()
    try:
        print(run_reconciliation(session))
    finally:
        session.close()