import hashlib
import hmac
import json
import time
from typing import Callable

from app.schemas import EntryInput
from app.models import Transaction, WebhookEvent

DEFAULT_TOLERANCE_SECONDS = 300

BACKOFF_SCHEDULE_SECONDS = [30, 60, 300, 1800, 7200]
MAX_ATTEMPTS = len(BACKOFF_SCHEDULE_SECONDS) + 1


def enqueue_transaction_posted_event(
    db, txn: Transaction, entries: list[EntryInput]
) -> WebhookEvent:

    payload = {
        "event_type": "transaction.posted",
        "transaction": {
            "id": str(txn.id),
            "status": txn.status,
            "type": txn.type,
            "entries": [
                {"account_id": str(e.account_id), "amount": e.amount, "currency": e.currency}
                for e in entries
            ],
        },
    }
    event = WebhookEvent(
        transaction_id=txn.id,
        event_type="transaction.posted",
        payload=payload,
        status="pending",
    )
    db.add(event)
    return event


def sign_payload(raw_body: bytes, secret: str, timestamp: int) -> str:
    message = f"{timestamp}.{raw_body.decode()}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def build_signature_header(raw_body: bytes, secret: str, timestamp: int | None = None) -> str:
    ts = timestamp if timestamp is not None else int(time.time())
    return f"t={ts},v1={sign_payload(raw_body, secret, ts)}"


def verify_signature(
    raw_body: bytes,
    header_value: str,
    secret: str,
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
    now: int | None = None,
) -> bool:
    try:
        parts = dict(item.split("=", 1) for item in header_value.split(","))
        timestamp = int(parts["t"])
        provided_signature = parts["v1"]
    except (ValueError, KeyError):
        return False  # malformed header , never trust input from outside the process

    current_time = now if now is not None else int(time.time())
    if abs(current_time - timestamp) > tolerance_seconds:
        return False  # too old (or suspiciously from the future) , reject to block replay

    expected_signature = sign_payload(raw_body, secret, timestamp)
    return hmac.compare_digest(expected_signature, provided_signature)


def attempt_delivery(
    event: WebhookEvent, endpoint_url: str, secret: str, post_fn: Callable
) -> tuple[bool, str | None]:
    """
    Makes one delivery attempt. `post_fn` is injected (the worker passes
    requests.post) so this is testable without real network calls.
    """
    raw_body = json.dumps(event.payload, sort_keys=True).encode()
    signature_header = build_signature_header(raw_body, secret)

    try:
        response = post_fn(
            endpoint_url,
            data=raw_body,
            headers={"Content-Type": "application/json", "Mracker-Signature": signature_header},
            timeout=5,
        )
    except Exception as exc: 
        return False, str(exc)

    if 200 <= response.status_code < 300:
        return True, None
    return False, f"endpoint returned HTTP {response.status_code}"