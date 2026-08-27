from uuid import UUID
from typing import Any
from pydantic import BaseModel, ConfigDict, field_validator


class EntryInput(BaseModel):

    account_id: UUID
    amount: int
    currency: str

    @field_validator("amount")
    @classmethod
    def amount_not_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("amount cannot be 0 for entry")
        return value

    @field_validator("currency")
    @classmethod
    def currency_valid(cls, value: str) -> str:
        if len(value) != 3:
            raise ValueError("currency must be a 3 letter ISO code")
        return value.upper()


class CreateTransactionRequest(BaseModel):
    tx_type: str
    entries: list[EntryInput]
    metadata: dict[str, Any] | None = None


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: UUID
    amount: int
    currency: str


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    entries: list[EntryOut]


class BalanceResponse(BaseModel):
    account_id: UUID
    balance: int

