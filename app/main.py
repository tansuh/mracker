from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import BalanceResponse, CreateTransactionRequest, TransactionResponse
from app.services.idempotency import (
    IdempotencyInProgressError,
    IdempotencyKeyReuseError,
    create_transaction_idempotent,
)
from app.services.ledger import (
    AccountNotFoundError,
    CurrencyMismatchError,
    UnbalancedTransactionError,
    get_balance,
)

from app.admin import router as admin_router

app = FastAPI(title="Mracker")
app.include_router(admin_router)


@app.post("/transactions", response_model=TransactionResponse, status_code=201)
def create_transaction(
    request: CreateTransactionRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> TransactionResponse:
    try:
        txn = create_transaction_idempotent(
            db,
            idempotency_key=idempotency_key,
            entries=request.entries,
            tx_type=request.tx_type,
            metadata=request.metadata,
        )
    except (UnbalancedTransactionError, CurrencyMismatchError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IdempotencyKeyReuseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IdempotencyInProgressError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return TransactionResponse.model_validate(txn)


@app.get("/accounts/{account_id}/balance", response_model=BalanceResponse)
def read_balance(account_id: UUID, db: Session = Depends(get_db)) -> BalanceResponse:
    balance = get_balance(db, account_id)
    return BalanceResponse(account_id=account_id, balance=balance)