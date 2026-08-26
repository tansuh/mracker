from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base

class Account(Base):
    __tablename__ = "accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False) 
    currency = Column(String(3), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    entries = relationship("LedgerEntry", back_populates="account")

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    type = Column(String, nullable=False) 
    status = Column(String, nullable=False, default="posted")
    metadata_ = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    entries = relationship(
        "LedgerEntry", back_populates="transaction", cascade="all, delete-orphan"
    )

class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    transaction_id = Column(UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=False)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    amount = Column(BigInteger, nullable=False)  
    currency = Column(String(3), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("amount != 0", name="ck_entry_amount_nonzero"),
        Index("ix_ledger_entries_account_id_created_at", "account_id", "created_at"),
    )

    transaction = relationship("Transaction", back_populates="entries")
    account = relationship("Account", back_populates="entries")