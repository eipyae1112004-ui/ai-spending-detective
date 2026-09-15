"""The AI categorization agent: reads uncategorized transactions, assigns categories,
flags anomalies (subscription creep, unusual spends), and logs its reasoning.
"""

import json
import os

from anthropic import Anthropic
from dotenv import load_dotenv

from src.db import get_session
from src.models import AgentAction, Budget, Category, Transaction

load_dotenv()

MODEL = "claude-sonnet-5"  # swap to "claude-haiku-4-5-20251001" for a cheaper/faster pass

TOOL_SCHEMA = {
    "name": "record_categorizations",
    "description": "Record the category, anomaly flag, and reasoning for each transaction in the batch.",
    "input_schema": {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "transaction_id": {"type": "integer"},
                        "category": {
                            "type": "string",
                            "description": "A short category name, e.g. 'Food & Dining', 'Transport', 'Subscriptions'.",
                        },
                        "is_anomaly": {
                            "type": "boolean",
                            "description": "True only for genuine subscription creep (3+ overlapping subscriptions), a same-day duplicate charge, or a spend roughly 3x+ larger than typical for that merchant/category. Normal repeat visits are NOT anomalies.",
                        },
                        "anomaly_reason": {
                            "type": "string",
                            "description": "One sentence explaining the anomaly. Empty string if is_anomaly is false.",
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "One short sentence on why this category was chosen.",
                        },
                    },
                    "required": ["transaction_id", "category", "is_anomaly", "anomaly_reason", "reasoning"],
                },
            }
        },
        "required": ["results"],
    },
}

SYSTEM_PROMPT = """You are a meticulous personal finance auditor. For each transaction you are given, \
choose a concise spending category and decide whether it looks anomalous.

Be conservative — most transactions are normal. Repeat visits to the same grocery store, food court, \
or shop across a month are ordinary behavior and must NOT be flagged just because they recur.

Flag is_anomaly = true only for:
- Subscription creep: three or more overlapping recurring subscription services (streaming, software, gym, etc.)
  billed in the same period. Two unrelated subscriptions (e.g. one streaming + one utility) is normal, not creep.
- True duplicate billing: the same merchant charging the same (or near-identical) amount on the SAME calendar date,
  which looks like an accidental double charge — not two separate visits on different days.
- A single transaction that is dramatically larger (roughly 3x or more) than a typical spend for that merchant
  or category, based on the other transactions in the batch.

Reuse an existing category name from the provided list whenever the transaction reasonably fits it. \
Only introduce a new category name if nothing in the list fits."""


BUDGET_TOOL_SCHEMA = {
    "name": "record_budget_recommendation",
    "description": "Record a recommended budget amount for each spending category for next month, with reasoning.",
    "input_schema": {
        "type": "object",
        "properties": {
            "overall_reasoning": {
                "type": "string",
                "description": "1-2 sentences summarizing the overall budgeting strategy and expected savings margin versus income.",
            },
            "categories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "Must exactly match one of the category names given in the prompt — do not reword or rename.",
                        },
                        "recommended_amount": {"type": "number"},
                        "reasoning": {"type": "string", "description": "One short sentence justifying this amount."},
                    },
                    "required": ["category", "recommended_amount", "reasoning"],
                },
            },
        },
        "required": ["overall_reasoning", "categories"],
    },
}

BUDGET_SYSTEM_PROMPT = """You are a careful, practical personal financial advisor. Given a person's income \
and their actual spending by category last month, recommend a realistic budget for each expense category \
for next month.

Be encouraging but realistic:
- Keep essential categories (groceries, utilities, transport) close to their historical actual spend —
  don't slash necessities.
- For discretionary categories (shopping, dining out, entertainment), nudge the amount down slightly if
  total spending left little or no savings margin versus income — but keep it achievable, not punishing.
- If income already comfortably covers spending with room to spare, keep budgets close to actual spend
  rather than cutting for no reason.
- Use the exact category names given. Do not invent new categories or rename existing ones."""


def _next_month_str(month: str) -> str:
    year, mon = (int(x) for x in month.split("-"))
    return f"{year + 1}-01" if mon == 12 else f"{year}-{mon + 1:02d}"


def recommend_budgets(month: str | None = None) -> dict:
    """Analyze one month's actual income/spending and recommend next month's budget per category.

    Saves the recommendation as Budget rows for next month and logs the reasoning to agent_actions.
    Returns a dict with the month analyzed, the target month, and the recommendation details.
    """
    session = get_session()
    client = _get_client()

    all_txns = session.query(Transaction).all()
    if not all_txns:
        session.close()
        raise ValueError("No transactions to analyze yet.")

    if month is None:
        month = max(t.date for t in all_txns).strftime("%Y-%m")

    month_txns = [t for t in all_txns if t.date.strftime("%Y-%m") == month]
    income = sum(t.amount for t in month_txns if t.amount > 0)

    category_totals: dict[str, float] = {}
    for t in month_txns:
        if t.amount < 0 and t.category:
            category_totals[t.category.name] = category_totals.get(t.category.name, 0.0) + (-t.amount)

    if not category_totals:
        session.close()
        raise ValueError(f"No categorized expenses found for {month}. Run the categorization agent first.")

    target_month = _next_month_str(month)

    message = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=BUDGET_SYSTEM_PROMPT,
        tools=[BUDGET_TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": "record_budget_recommendation"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Income for {month}: ${income:,.2f}\n"
                    f"Actual spending by category for {month}:\n{json.dumps(category_totals, indent=2)}\n\n"
                    f"Recommend a budget for each of these categories for {target_month}."
                ),
            }
        ],
    )

    tool_use = next(b for b in message.content if b.type == "tool_use")
    result = tool_use.input

    for item in result["categories"]:
        category = session.query(Category).filter_by(name=item["category"]).one_or_none()
        if category is None:
            continue  # AI returned a category name we don't recognize — skip rather than invent one

        existing = session.query(Budget).filter_by(category_id=category.id, month=target_month).one_or_none()
        if existing:
            existing.allocated_amount = item["recommended_amount"]
        else:
            session.add(Budget(category_id=category.id, month=target_month, allocated_amount=item["recommended_amount"]))

    session.add(
        AgentAction(
            action_type="budget_recommendation",
            summary=f"Recommended {target_month} budget based on {month} actuals (income ${income:,.2f})",
            reasoning=result["overall_reasoning"],
        )
    )
    session.commit()
    session.close()

    return {
        "month_analyzed": month,
        "target_month": target_month,
        "income": income,
        "actual_spend": category_totals,
        **result,
    }


def _get_client() -> Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key."
        )
    return Anthropic(api_key=api_key)


def categorize_batch(session, transactions: list[Transaction], client: Anthropic) -> None:
    existing_categories = [c.name for c in session.query(Category).all()]

    payload = [
        {
            "transaction_id": t.id,
            "date": str(t.date),
            "merchant": t.merchant or t.description,
            "amount": t.amount,
        }
        for t in transactions
    ]

    message = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        tools=[TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": "record_categorizations"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Existing categories: {existing_categories}\n\n"
                    f"Transactions to categorize:\n{json.dumps(payload, indent=2)}"
                ),
            }
        ],
    )

    tool_use = next(b for b in message.content if b.type == "tool_use")
    results = tool_use.input["results"]

    by_id = {t.id: t for t in transactions}
    for r in results:
        txn = by_id.get(r["transaction_id"])
        if txn is None:
            continue

        cat_type = "income" if txn.amount > 0 else "expense"
        category = session.query(Category).filter_by(name=r["category"]).one_or_none()
        if category is None:
            category = Category(name=r["category"], type=cat_type)
            session.add(category)
            session.flush()

        txn.category = category
        txn.is_anomaly = r["is_anomaly"]
        txn.anomaly_reason = r["anomaly_reason"] or None

        session.add(
            AgentAction(
                action_type="flag_anomaly" if r["is_anomaly"] else "categorize",
                transaction_id=txn.id,
                summary=f"{txn.merchant}: categorized as '{r['category']}'"
                + (f" — ANOMALY: {r['anomaly_reason']}" if r["is_anomaly"] else ""),
                reasoning=r["reasoning"],
            )
        )

    session.commit()


def run_agent(batch_size: int = 150) -> int:
    """Categorize every uncategorized transaction in the database. Returns count processed.

    Default batch_size covers a full month's statement in a single call, so the agent
    can compare transactions against each other (e.g. spotting subscription creep across
    the whole month) instead of missing patterns that span multiple batches.
    """
    session = get_session()
    client = _get_client()

    uncategorized = session.query(Transaction).filter(Transaction.category_id.is_(None)).all()
    total = 0
    for i in range(0, len(uncategorized), batch_size):
        batch = uncategorized[i : i + batch_size]
        categorize_batch(session, batch, client)
        total += len(batch)
        print(f"Categorized {total}/{len(uncategorized)}")

    session.close()
    return total


if __name__ == "__main__":
    n = run_agent()
    print(f"Done. Categorized {n} transactions.")
