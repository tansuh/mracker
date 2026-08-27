import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Account, LedgerEntry, Transaction  

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql://ledger:ledger@localhost:5432/mracker_test"
)


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DATABASE_URL, future=True)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture
def db(engine):
    # each test runs inside the cover transaction, rolled back at end 
    # prevents truncating tables between runs 
    connection = engine.connect()
    outer_txn = connection.begin()
    Session = sessionmaker(bind=connection, future=True)
    session = Session()

    yield session

    session.close()
    outer_txn.rollback()
    connection.close()
