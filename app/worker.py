import os
import time
from datetime import datetime, timedelta, timezone

import requests

from app.database import SessionLocal
from app.models import WebhookEvent
from app.services.webhooks import BACKOFF_SCHEDULE_SECONDS, MAX_ATTEMPTS, attempt_delivery

WEBHOOK_ENDPOINT_URL = os.getenv("WEBHOOK_ENDPOINT_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
POLL_INTERVAL_SECONDS = 2.0


def _process_one(db, event: WebhookEvent) -> None:
    success, error = attempt_delivery(event, WEBHOOK_ENDPOINT_URL, WEBHOOK_SECRET, requests.post)
    event.attempts += 1

    if success:
        event.status = "delivered"
        event.last_error = None
    elif event.attempts >= MAX_ATTEMPTS:
        event.status = "failed"
        event.last_error = error
    else:
        wait_seconds = BACKOFF_SCHEDULE_SECONDS[event.attempts - 1]
        event.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=wait_seconds)
        event.last_error = error

    db.commit()
    print(f"event={event.id} status={event.status} attempts={event.attempts} error={error}")


def run(poll_interval: float = POLL_INTERVAL_SECONDS) -> None:
    if not WEBHOOK_ENDPOINT_URL or not WEBHOOK_SECRET:
        raise RuntimeError("WEBHOOK_ENDPOINT_URL and WEBHOOK_SECRET must be set")

    print(f"webhook worker started, polling every {poll_interval}s -> {WEBHOOK_ENDPOINT_URL}")
    while True:
        db = SessionLocal()
        try:
            due = (
                db.query(WebhookEvent)
                .filter(
                    WebhookEvent.status == "pending",
                    WebhookEvent.next_attempt_at <= datetime.now(timezone.utc),
                )
                .all()
            )
            for event in due:
                _process_one(db, event)
        finally:
            db.close()
        time.sleep(poll_interval)


if __name__ == "__main__":
    run()