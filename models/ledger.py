import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from database import Base

SPLIT_RULES = ["SHARED_50_50", "MIKUSH_100", "TAMIR_100"]


class LearnedItemRule(Base):
    """Persists user-overridden ownership rules (50/50 vs 100% Mikush vs 100% Tamir) by normalized item name."""
    __tablename__ = "learned_item_rules"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    normalized_name = Column(String(255), nullable=False, unique=True, index=True)
    display_name = Column(String(255), nullable=False)
    split_rule = Column(String(30), nullable=False, default="SHARED_50_50")
    category = Column(String(50), nullable=True)
    is_produce = Column(Boolean, nullable=False, default=False)
    updated_by = Column(String(50), nullable=False, default="Tamir")
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class ReceiptScan(Base):
    """Stores parsed and committed receipts/Wolt orders/utility bills with full item-level split metadata."""
    __tablename__ = "receipt_scans"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    merchant_name = Column(String(255), nullable=True)
    receipt_type = Column(String(50), nullable=False, default="supermarket")
    paid_by = Column(String(50), nullable=False, default="Tamir")
    total_amount = Column(Float, nullable=False, default=0.0)
    shared_total = Column(Float, nullable=False, default=0.0)
    mikush_only_total = Column(Float, nullable=False, default=0.0)
    tamir_only_total = Column(Float, nullable=False, default=0.0)
    tamir_final_share = Column(Float, nullable=False, default=0.0)
    mikush_final_share = Column(Float, nullable=False, default=0.0)
    items_json = Column(Text, nullable=False, default="[]")
    auto_checked_items_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class LedgerSettlement(Base):
    """Records explicit manual Settle-Up events (full or partial) without ever auto-resetting on dates."""
    __tablename__ = "ledger_settlements"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    settled_by = Column(String(50), nullable=False, default="Tamir")
    payer = Column(String(50), nullable=False)
    payee = Column(String(50), nullable=False)
    amount = Column(Float, nullable=False)
    is_full_settlement = Column(Boolean, nullable=False, default=True)
    balance_before = Column(Float, nullable=False, default=0.0)
    balance_after = Column(Float, nullable=False, default=0.0)
    note = Column(String(255), nullable=True)
    settled_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)


class LedgerTransaction(Base):
    """Splitwise-replacement continuous ledger transactions across receipts, bills, CSV imports & manual entries."""
    __tablename__ = "ledger_transactions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    description = Column(String(255), nullable=False)
    category = Column(String(50), nullable=False, default="Groceries")
    paid_by = Column(String(50), nullable=False, default="Tamir")
    total_amount = Column(Float, nullable=False)
    split_rule = Column(String(30), nullable=False, default="SHARED_50_50")
    tamir_share = Column(Float, nullable=False)
    mikush_share = Column(Float, nullable=False)
    source_type = Column(String(30), nullable=False, default="manual")
    receipt_scan_id = Column(Integer, ForeignKey("receipt_scans.id", ondelete="SET NULL"), nullable=True)
    is_settled = Column(Boolean, nullable=False, default=False, index=True)
    settlement_id = Column(Integer, ForeignKey("ledger_settlements.id", ondelete="SET NULL"), nullable=True, index=True)
    external_hash = Column(String(128), nullable=True, index=True)
    transaction_date = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
