from collections import defaultdict
from uuid import UUID
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import Session 

from app.models import Account, LedgerEntry, Transaction 
from app.schemas import EntryInput

