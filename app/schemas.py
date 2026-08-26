from uuid import UUID
from pydantic import BaseModel, field_validator

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


    