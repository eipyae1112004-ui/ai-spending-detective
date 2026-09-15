"""Statement import pipeline: turns a bank CSV or PDF export into raw Transaction rows.

No categorization happens here — that's the agent's job (src/agent.py). This module's
only responsibility is: read a file, recognize its columns, and produce well-formed,
uncategorized Transaction rows.
"""

from datetime import datetime
from pathlib import Path

import pandas as pd

from src.db import get_session
from src.models import AgentAction, Transaction

# Column-header spellings this parser recognizes, across common bank export formats.
DATE_COLUMNS = ["date", "transaction date", "value date", "posting date"]
DESC_COLUMNS = ["description", "narrative", "details", "transaction details", "particulars"]
AMOUNT_COLUMNS = ["amount", "transaction amount"]
DEBIT_COLUMNS = ["debit", "withdrawal", "debit amount", "withdrawal amount"]
CREDIT_COLUMNS = ["credit", "deposit", "credit amount", "deposit amount"]


def _find_column(columns, candidates) -> str | None:
    lower = {str(c).lower().strip(): c for c in columns}
    for candidate in candidates:
        if candidate in lower:
            return lower[candidate]
    return None


def _parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%d %b %Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return pd.to_datetime(value).date()


def dataframe_to_transactions(df: pd.DataFrame, source: str) -> list[Transaction]:
    """Map a loosely-structured statement DataFrame onto our Transaction schema."""
    columns = list(df.columns)
    date_col = _find_column(columns, DATE_COLUMNS)
    desc_col = _find_column(columns, DESC_COLUMNS)
    amount_col = _find_column(columns, AMOUNT_COLUMNS)
    debit_col = _find_column(columns, DEBIT_COLUMNS)
    credit_col = _find_column(columns, CREDIT_COLUMNS)

    if date_col is None or desc_col is None:
        raise ValueError(
            f"Could not find date/description columns in: {columns}. "
            "Statement format not recognized — check the column headers."
        )
    if amount_col is None and (debit_col is None or credit_col is None):
        raise ValueError(f"Could not find an amount column, or a debit/credit pair, in: {columns}.")

    transactions = []
    for _, row in df.iterrows():
        if pd.isna(row[date_col]) or pd.isna(row[desc_col]):
            continue  # skip blank rows / statement footers

        if amount_col is not None:
            amount = float(row[amount_col])
        else:
            debit = float(row[debit_col]) if pd.notna(row[debit_col]) and row[debit_col] != "" else 0.0
            credit = float(row[credit_col]) if pd.notna(row[credit_col]) and row[credit_col] != "" else 0.0
            amount = credit - debit  # money in is positive, money out is negative

        description = str(row[desc_col]).strip()
        transactions.append(
            Transaction(
                date=_parse_date(row[date_col]),
                description=description,
                merchant=description,  # cleaned up into a proper name later by the AI agent
                amount=amount,
                source=source,
            )
        )
    return transactions


def import_csv(path: str | Path, session=None) -> int:
    """Import a bank CSV export. Returns the number of transactions inserted."""
    df = pd.read_csv(path)
    transactions = dataframe_to_transactions(df, source="bank_csv")
    return _save(transactions, path, session)


def import_pdf(path: str | Path, session=None) -> int:
    """Import a bank PDF statement by extracting its transaction table.

    Best-effort: PDF statement layouts vary a lot between banks. If this fails on a
    real statement, the usual fix is adding that bank's column-header spelling to
    DATE_COLUMNS / DESC_COLUMNS / etc. above. Scanned/image-only PDFs aren't supported —
    they'd need OCR, which isn't implemented here.
    """
    import pdfplumber

    header = None
    rows = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if not table or len(table) < 2:
                    continue
                if header is None:
                    header = table[0]
                    rows.extend(table[1:])
                elif table[0] == header:
                    rows.extend(table[1:])
                else:
                    rows.extend(table)

    if not rows or header is None:
        raise ValueError(
            "No transaction table found in this PDF. This parser expects a tabular "
            "statement layout."
        )

    df = pd.DataFrame(rows, columns=header)
    transactions = dataframe_to_transactions(df, source="bank_pdf")
    return _save(transactions, path, session)


def _save(transactions: list[Transaction], path, session) -> int:
    owns_session = session is None
    if owns_session:
        session = get_session()

    for txn in transactions:
        session.add(txn)

    session.add(
        AgentAction(
            action_type="import",
            summary=f"Imported {len(transactions)} transactions from {Path(path).name}",
            reasoning="Raw statement import — not yet categorized.",
        )
    )
    session.commit()

    if owns_session:
        session.close()
    return len(transactions)
