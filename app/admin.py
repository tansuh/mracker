import html

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Account, Transaction
from app.services.ledger import get_balance

router = APIRouter(prefix="/admin", tags=["admin"])

_PAGE_STYLE = """
<style>
  body { font-family: -apple-system, sans-serif; margin: 2rem; color: #1a1a1a; }
  h1 { font-size: 1.25rem; }
  table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
  th, td { border: 1px solid #ddd; padding: 0.5rem 0.75rem; text-align: left; font-size: 0.9rem; }
  th { background: #f5f5f5; }
  code { background: #f0f0f0; padding: 0.1rem 0.3rem; border-radius: 3px; }
  nav a { margin-right: 1rem; }
</style>
"""

_NAV = '<nav><a href="/admin/accounts">Accounts</a><a href="/admin/transactions">Transactions</a></nav>'


@router.get("/accounts", response_class=HTMLResponse)
def admin_accounts(db: Session = Depends(get_db)) -> str:
    accounts = db.query(Account).order_by(Account.created_at.desc()).limit(100).all()

    rows = "".join(
        f"<tr><td><code>{a.id}</code></td><td>{html.escape(a.name)}</td>"
        f"<td>{html.escape(a.type)}</td><td>{html.escape(a.currency)}</td>"
        f"<td>{get_balance(db, a.id)}</td></tr>"
        for a in accounts
    )

    return f"""
    <html><head><title>Mracker Admin - Accounts</title>{_PAGE_STYLE}</head>
    <body>
      {_NAV}
      <h1>Accounts (most recent 100)</h1>
      <table>
        <tr><th>ID</th><th>Name</th><th>Type</th><th>Currency</th><th>Balance</th></tr>
        {rows}
      </table>
    </body></html>
    """


@router.get("/transactions", response_class=HTMLResponse)
def admin_transactions(db: Session = Depends(get_db)) -> str:
    transactions = (
        db.query(Transaction).order_by(Transaction.created_at.desc()).limit(100).all()
    )

    rows = ""
    for t in transactions:
        entries_html = "<br>".join(
            f"{e.account_id}: {e.amount:+d} {html.escape(e.currency)}" for e in t.entries
        )
        rows += (
            f"<tr><td><code>{t.id}</code></td><td>{html.escape(t.type)}</td>"
            f"<td>{html.escape(t.status)}</td><td>{t.created_at}</td><td>{entries_html}</td></tr>"
        )

    return f"""
    <html><head><title>Mracker Admin - Transactions</title>{_PAGE_STYLE}</head>
    <body>
      {_NAV}
      <h1>Transactions (most recent 100)</h1>
      <table>
        <tr><th>ID</th><th>Type</th><th>Status</th><th>Created</th><th>Entries</th></tr>
        {rows}
      </table>
    </body></html>
    """