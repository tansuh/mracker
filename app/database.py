import os 
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv(dbURL)

engine = create_engine(DATABASE_URL, future=True)
localSession = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
base = declarative_base() 

def get_db(): 
    db = localSession()
    try: 
        yield db
    finally:
        db.close()