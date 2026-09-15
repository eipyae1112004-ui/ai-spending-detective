"""SQLAlchemy ORM models — the database schema for AI Spending Detective."""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Category(Base):
    """A spending/income bucket, e.g. 'Food & Dining' or 'Income'."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    type: Mapped[str] = mapped_column(String(16))  # "expense" or "income"

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="category")
    budgets: Mapped[list["Budget"]] = relationship(back_populates="category")


class Transaction(Base):
    """One line from a bank statement, receipt, or the synthetic data generator."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date]
    description: Mapped[str] = mapped_column(String(256))  # raw statement text
    merchant: Mapped[str | None] = mapped_column(String(128), nullable=True)  # AI-cleaned name
    amount: Mapped[float] = mapped_column(Float)  # negative = expense, positive = income

    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    category: Mapped["Category | None"] = relationship(back_populates="transactions")

    source: Mapped[str] = mapped_column(String(32))  # bank_csv | bank_pdf | receipt_ocr | synthetic

    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    anomaly_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Budget(Base):
    """Allocated spend for one category in one month, e.g. 'Food & Dining' / '2026-09' / $400."""

    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("category_id", "month", name="uq_budget_category_month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    category: Mapped["Category"] = relationship(back_populates="budgets")
    month: Mapped[str] = mapped_column(String(7))  # "YYYY-MM"
    allocated_amount: Mapped[float] = mapped_column(Float)


class AgentAction(Base):
    """A log entry of something the AI agent did — powers the live activity feed."""

    __tablename__ = "agent_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    action_type: Mapped[str] = mapped_column(String(32))  # import | categorize | flag_anomaly | budget_decision
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    summary: Mapped[str] = mapped_column(String(256))  # short line for the live feed
    reasoning: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # fuller AI explanation
