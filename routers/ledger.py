import csv
import io
import hashlib
import datetime
from typing import Optional, List, Literal, Dict
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models.ledger import LedgerTransaction, LedgerSettlement, LearnedItemRule, ReceiptScan
from security import require_auth_api, get_active_profile

ledger_router = APIRouter(prefix="/api/ledger", tags=["ledger"])

RECURRING_BILL_PRESETS = [
    {"category": "Rent", "icon": "🏠", "label": "Rent (שכירות)", "hebrew": "שכירות", "cadence": "Monthly"},
    {"category": "Arnona", "icon": "🏛️", "label": "Arnona (ארנונה)", "hebrew": "ארנונה", "cadence": "Bi-Monthly"},
    {"category": "Electricity", "icon": "⚡", "label": "Electricity (חשמל)", "hebrew": "חשמל", "cadence": "Bi-Monthly"},
    {"category": "Water", "icon": "💧", "label": "Water (מים)", "hebrew": "מים", "cadence": "Bi-Monthly"},
    {"category": "Internet", "icon": "🌐", "label": "Internet / Fiber", "hebrew": "אינטרנט", "cadence": "Monthly"},
    {"category": "Gas / Vaad Bayit", "icon": "🔥", "label": "Gas / Vaad Bayit (גז / ועד)", "hebrew": "גז / ועד בית", "cadence": "Monthly"},
    {"category": "Date Night / Takeout", "icon": "🍕", "label": "Date Night / Takeout", "hebrew": "בילויים", "cadence": "Flexible"},
]

_BILL_CATEGORIES = {
    "rent", "arnona", "electricity", "water", "internet",
    "gas / vaad bayit", "gas", "vaad bayit", "utilities",
}
_DATE_NIGHT_CATEGORIES = {
    "date night / takeout", "date night", "takeout", "wolt",
    "restaurants", "dining out", "entertainment",
}


# ===================== PYDANTIC SCHEMAS =====================
class LedgerTransactionCreate(BaseModel):
    description: str = Field(..., min_length=1)
    category: Optional[str] = "Other"
    paid_by: Literal["Tamir", "Mikush"] = "Tamir"
    total_amount: float = Field(..., gt=0)
    split_rule: Literal["SHARED_50_50", "MIKUSH_100", "TAMIR_100", "CUSTOM"] = "SHARED_50_50"
    tamir_share: Optional[float] = None
    mikush_share: Optional[float] = None
    source_type: Optional[str] = "manual"
    transaction_date: Optional[str] = None


class InitialBalancePayload(BaseModel):
    ahead_user: Literal["Tamir", "Mikush"]
    amount: float = Field(..., ge=0)
    mode: Literal["replace_starting", "add_adjustment"] = "replace_starting"
    note: Optional[str] = "Starting balance migration"


class SettleUpPayload(BaseModel):
    amount: Optional[float] = None
    note: Optional[str] = None
    settled_by: Optional[str] = None


class SplitwiseCsvJsonPayload(BaseModel):
    csv_content: str


# ===================== BALANCE CALCULATION ENGINE =====================
def _serialize_transaction(tx: LedgerTransaction) -> dict:
    return {
        "id": tx.id,
        "description": tx.description,
        "category": tx.category,
        "paid_by": tx.paid_by,
        "total_amount": round(float(tx.total_amount), 2),
        "split_rule": tx.split_rule,
        "tamir_share": round(float(tx.tamir_share), 2),
        "mikush_share": round(float(tx.mikush_share), 2),
        "source_type": tx.source_type,
        "receipt_scan_id": tx.receipt_scan_id,
        "is_settled": tx.is_settled,
        "settlement_id": tx.settlement_id,
        "transaction_date": tx.transaction_date.isoformat() if tx.transaction_date else None,
        "created_at": tx.created_at.isoformat() if tx.created_at else None,
    }


def compute_ledger_balance(db: Session) -> dict:
    """
    Computes continuous running balance across ALL unsettled transactions.
    NEVER auto-resets on calendar dates.
    Convention:
      net_balance > 0 -> Mikush owes Tamir (Tamir is ahead)
      net_balance < 0 -> Tamir owes Mikush (Mikush is ahead)
    """
    unsettled = (
        db.query(LedgerTransaction)
        .filter(LedgerTransaction.is_settled == False)
        .order_by(LedgerTransaction.transaction_date.desc(), LedgerTransaction.id.desc())
        .all()
    )

    net_tamir_balance = 0.0
    total_unsettled_spend = 0.0
    for tx in unsettled:
        total_unsettled_spend += float(tx.total_amount or 0.0)
        if tx.paid_by == "Tamir":
            net_tamir_balance += float(tx.mikush_share or 0.0)
        elif tx.paid_by == "Mikush":
            net_tamir_balance -= float(tx.tamir_share or 0.0)

    net_balance = round(net_tamir_balance, 2)
    if abs(net_balance) < 0.01:
        net_balance = 0.0
        status_key = "settled"
        debtor = None
        creditor = None
        headline = "All Settled Up! ✨"
    elif net_balance > 0:
        status_key = "mikush_owes_tamir"
        debtor = "Mikush"
        creditor = "Tamir"
        headline = f"Mikush owes Tamir ₪{net_balance:.2f}"
    else:
        status_key = "tamir_owes_mikush"
        debtor = "Tamir"
        creditor = "Mikush"
        headline = f"Tamir owes Mikush ₪{abs(net_balance):.2f}"

    return {
        "net_balance": net_balance,
        "abs_balance": round(abs(net_balance), 2),
        "status": status_key,
        "debtor": debtor,
        "creditor": creditor,
        "headline": headline,
        "unsettled_count": len(unsettled),
        "total_unsettled_spend": round(total_unsettled_spend, 2),
        "active_transactions": [_serialize_transaction(tx) for tx in unsettled],
    }


def _resolve_shares(payload: LedgerTransactionCreate) -> tuple[float, float]:
    total = round(float(payload.total_amount), 2)
    if payload.split_rule == "SHARED_50_50":
        t_share = round(total / 2.0, 2)
        m_share = round(total - t_share, 2)
        return t_share, m_share
    if payload.split_rule == "MIKUSH_100":
        return 0.0, total
    if payload.split_rule == "TAMIR_100":
        return total, 0.0
    # CUSTOM
    if payload.tamir_share is not None and payload.mikush_share is not None:
        return round(float(payload.tamir_share), 2), round(float(payload.mikush_share), 2)
    t_share = round(total / 2.0, 2)
    return t_share, round(total - t_share, 2)


# ===================== API ENDPOINTS =====================
@ledger_router.get("/summary", dependencies=[Depends(require_auth_api)])
def get_ledger_summary(db: Session = Depends(get_db)):
    """Returns continuous running net balance, unsettled transactions, and collapsible settlement history."""
    balance_data = compute_ledger_balance(db)

    settlements = (
        db.query(LedgerSettlement)
        .order_by(LedgerSettlement.settled_at.desc(), LedgerSettlement.id.desc())
        .all()
    )

    history = []
    for st in settlements:
        archived_txs = (
            db.query(LedgerTransaction)
            .filter(LedgerTransaction.settlement_id == st.id)
            .order_by(LedgerTransaction.transaction_date.desc(), LedgerTransaction.id.desc())
            .all()
        )
        history.append({
            "id": st.id,
            "settled_by": st.settled_by,
            "payer": st.payer,
            "payee": st.payee,
            "amount": round(float(st.amount), 2),
            "is_full_settlement": st.is_full_settlement,
            "balance_before": round(float(st.balance_before), 2),
            "balance_after": round(float(st.balance_after), 2),
            "note": st.note,
            "settled_at": st.settled_at.isoformat() if st.settled_at else None,
            "archived_count": len(archived_txs),
            "archived_transactions": [_serialize_transaction(t) for t in archived_txs],
        })

    learned_rules_count = db.query(LearnedItemRule).count()

    # Attach latest amount for 1-tap autofill on recurring bill templates
    enriched_presets = []
    for preset in RECURRING_BILL_PRESETS:
        latest_tx = (
            db.query(LedgerTransaction)
            .filter(LedgerTransaction.category == preset["category"])
            .order_by(LedgerTransaction.transaction_date.desc(), LedgerTransaction.id.desc())
            .first()
        )
        enriched_presets.append({
            **preset,
            "last_amount": round(float(latest_tx.total_amount), 2) if latest_tx else None,
            "last_paid_by": latest_tx.paid_by if latest_tx else None,
        })

    breakdown = compute_ledger_breakdown(db)

    return {
        **balance_data,
        "settlement_history": history,
        "learned_rules_count": learned_rules_count,
        "recurring_bill_presets": enriched_presets,
        "spending_breakdown": breakdown,
    }


def _classify_tx_into_buckets(tx: LedgerTransaction, scan: Optional[ReceiptScan]) -> Dict[str, float]:
    """Maps a spending LedgerTransaction into the 4 breakdown buckets (+ 'other')."""
    amt = round(float(tx.total_amount or 0.0), 2)
    cat_low = (tx.category or "").strip().lower()
    buckets = {
        "shared_groceries": 0.0,
        "produce_mikush_100": 0.0,
        "apartment_bills": 0.0,
        "date_nights_takeout": 0.0,
        "other": 0.0,
    }

    if scan:
        if scan.receipt_type == "wolt":
            buckets["date_nights_takeout"] = amt
            return buckets
        if scan.receipt_type == "utility":
            buckets["apartment_bills"] = amt
            return buckets
        # Supermarket / general receipt split cleanly between Produce (MIKUSH_100) and Shared Groceries
        mikush_prod = round(float(scan.mikush_only_total or 0.0), 2)
        shared_part = round(max(0.0, amt - mikush_prod), 2)
        buckets["produce_mikush_100"] = mikush_prod
        buckets["shared_groceries"] = shared_part
        return buckets

    if tx.source_type == "recurring_bill" or cat_low in _BILL_CATEGORIES:
        buckets["apartment_bills"] = amt
    elif cat_low in _DATE_NIGHT_CATEGORIES:
        buckets["date_nights_takeout"] = amt
    elif cat_low == "produce" or (cat_low == "groceries" and tx.split_rule == "MIKUSH_100"):
        buckets["produce_mikush_100"] = amt
    elif cat_low == "groceries":
        buckets["shared_groceries"] = amt
    else:
        buckets["other"] = amt
    return buckets


def compute_ledger_breakdown(
    db: Session,
    month: Optional[str] = None,
    include_settled: bool = True,
) -> dict:
    """Computes monthly and category spending totals across groceries, produce, bills, and date nights."""
    query = db.query(LedgerTransaction)
    if not include_settled:
        query = query.filter(LedgerTransaction.is_settled == False)

    all_rows = query.order_by(LedgerTransaction.transaction_date.desc(), LedgerTransaction.id.desc()).all()
    spending_rows = [
        tx for tx in all_rows
        if tx.source_type not in ("initial_balance", "partial_settlement")
        and tx.split_rule != "SETTLEMENT"
    ]

    scan_ids = [tx.receipt_scan_id for tx in spending_rows if tx.receipt_scan_id]
    scan_map: Dict[int, ReceiptScan] = {}
    if scan_ids:
        for sc in db.query(ReceiptScan).filter(ReceiptScan.id.in_(scan_ids)).all():
            scan_map[sc.id] = sc

    totals = {
        "shared_groceries": 0.0,
        "produce_mikush_100": 0.0,
        "apartment_bills": 0.0,
        "date_nights_takeout": 0.0,
        "other": 0.0,
    }
    tamir_total_share = 0.0
    mikush_total_share = 0.0
    monthly_map: Dict[str, dict] = {}
    filtered_count = 0

    for tx in spending_rows:
        dt = tx.transaction_date or tx.created_at or datetime.datetime.utcnow()
        month_key = dt.strftime("%Y-%m")
        tx_buckets = _classify_tx_into_buckets(tx, scan_map.get(tx.receipt_scan_id))

        if month_key not in monthly_map:
            monthly_map[month_key] = {
                "month": month_key,
                "label": dt.strftime("%b %Y"),
                "total": 0.0,
                "count": 0,
                "shared_groceries": 0.0,
                "produce_mikush_100": 0.0,
                "apartment_bills": 0.0,
                "date_nights_takeout": 0.0,
                "other": 0.0,
            }
        m_entry = monthly_map[month_key]
        m_entry["count"] += 1
        for k, v in tx_buckets.items():
            m_entry[k] = round(m_entry[k] + v, 2)
        m_entry["total"] = round(m_entry["total"] + float(tx.total_amount or 0.0), 2)

        if month and month != "all" and month_key != month:
            continue

        filtered_count += 1
        for k, v in tx_buckets.items():
            totals[k] = round(totals[k] + v, 2)
        tamir_total_share = round(tamir_total_share + float(tx.tamir_share or 0.0), 2)
        mikush_total_share = round(mikush_total_share + float(tx.mikush_share or 0.0), 2)

    grand_total = round(sum(totals.values()), 2)

    def _pct(val: float) -> float:
        return round((val / grand_total) * 100.0, 1) if grand_total > 0 else 0.0

    category_cards = [
        {
            "key": "shared_groceries",
            "label": "Shared Groceries",
            "subtitle": "50/50 split staples & home",
            "amount": totals["shared_groceries"],
            "pct": _pct(totals["shared_groceries"]),
        },
        {
            "key": "produce_mikush_100",
            "label": "Produce",
            "subtitle": "Mikush 100% fruits & veggies",
            "amount": totals["produce_mikush_100"],
            "pct": _pct(totals["produce_mikush_100"]),
        },
        {
            "key": "apartment_bills",
            "label": "Apartment Bills",
            "subtitle": "Rent, Arnona, Electric, Water, Fiber, Gas",
            "amount": totals["apartment_bills"],
            "pct": _pct(totals["apartment_bills"]),
        },
        {
            "key": "date_nights_takeout",
            "label": "Date Nights & Takeout",
            "subtitle": "Wolt, dining & treats",
            "amount": totals["date_nights_takeout"],
            "pct": _pct(totals["date_nights_takeout"]),
        },
        {
            "key": "other",
            "label": "Other Shared",
            "subtitle": "Miscellaneous expenses",
            "amount": totals["other"],
            "pct": _pct(totals["other"]),
        },
    ]

    monthly_series = [monthly_map[k] for k in sorted(monthly_map.keys(), reverse=True)]

    return {
        "month_filter": month or "all",
        "include_settled": include_settled,
        "transaction_count": filtered_count,
        "total_spend": grand_total,
        "tamir_share_total": tamir_total_share,
        "mikush_share_total": mikush_total_share,
        "totals": totals,
        "categories": category_cards,
        "available_months": [{"month": m["month"], "label": m["label"], "total": m["total"]} for m in monthly_series],
        "monthly_series": monthly_series,
    }


@ledger_router.get("/breakdown", dependencies=[Depends(require_auth_api)])
def get_ledger_breakdown(
    month: Optional[str] = Query(None),
    include_settled: bool = Query(True),
    db: Session = Depends(get_db),
):
    """Returns Monthly & Category Spending Breakdown for the Ledger drawer."""
    return {
        "status": "ok",
        **compute_ledger_breakdown(db, month=month, include_settled=include_settled),
    }


@ledger_router.get("/export.csv", dependencies=[Depends(require_auth_api)])
def export_ledger_csv(
    month: Optional[str] = Query(None),
    include_settled: bool = Query(True),
    db: Session = Depends(get_db),
):
    """Exports ledger transactions to a UTF-8 BOM CSV compatible with Excel and Hebrew text."""
    query = db.query(LedgerTransaction)
    if not include_settled:
        query = query.filter(LedgerTransaction.is_settled == False)

    rows = query.order_by(LedgerTransaction.transaction_date.desc(), LedgerTransaction.id.desc()).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "ID", "Date", "Description", "Category", "Paid By",
        "Total Amount (ILS)", "Split Rule", "Tamir Share (ILS)", "Mikush Share (ILS)",
        "Source", "Status",
    ])
    for tx in rows:
        dt = tx.transaction_date or tx.created_at
        dt_str = dt.strftime("%Y-%m-%d") if dt else ""
        if month and month != "all" and not dt_str.startswith(month):
            continue
        writer.writerow([
            tx.id,
            dt_str,
            tx.description,
            tx.category,
            tx.paid_by,
            f"{float(tx.total_amount or 0.0):.2f}",
            tx.split_rule,
            f"{float(tx.tamir_share or 0.0):.2f}",
            f"{float(tx.mikush_share or 0.0):.2f}",
            tx.source_type,
            "Settled" if tx.is_settled else "Active",
        ])

    csv_bytes = buf.getvalue().encode("utf-8-sig")
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="apartment_ledger_export.csv"'},
    )


@ledger_router.post("/transactions", dependencies=[Depends(require_auth_api)])
def create_ledger_transaction(
    payload: LedgerTransactionCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Logs a manual expense, Date Night/Takeout, or recurring apartment bill."""
    tamir_share, mikush_share = _resolve_shares(payload)

    tx_date = datetime.datetime.utcnow()
    if payload.transaction_date:
        try:
            tx_date = datetime.datetime.fromisoformat(payload.transaction_date.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            pass

    tx = LedgerTransaction(
        description=payload.description.strip(),
        category=(payload.category or "Other").strip(),
        paid_by=payload.paid_by,
        total_amount=round(float(payload.total_amount), 2),
        split_rule=payload.split_rule,
        tamir_share=tamir_share,
        mikush_share=mikush_share,
        source_type=payload.source_type or "manual",
        is_settled=False,
        transaction_date=tx_date,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)

    return {
        "status": "ok",
        "transaction": _serialize_transaction(tx),
        "summary": compute_ledger_balance(db),
    }


@ledger_router.delete("/transactions/{tx_id}", dependencies=[Depends(require_auth_api)])
def delete_ledger_transaction(tx_id: int, db: Session = Depends(get_db)):
    """Deletes an unsettled transaction."""
    tx = db.query(LedgerTransaction).filter(LedgerTransaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if tx.is_settled:
        raise HTTPException(status_code=400, detail="Cannot delete an already settled/archived transaction")

    db.delete(tx)
    db.commit()
    return {
        "status": "ok",
        "message": f"Deleted '{tx.description}'",
        "summary": compute_ledger_balance(db),
    }


@ledger_router.post("/initial-balance", dependencies=[Depends(require_auth_api)])
def set_initial_balance(payload: InitialBalancePayload, db: Session = Depends(get_db)):
    """1-click 'Set Starting Balance' tool (e.g., Tamir is ₪X ahead or Mikush is ₪X ahead)."""
    if payload.mode == "replace_starting":
        db.query(LedgerTransaction).filter(
            LedgerTransaction.is_settled == False,
            LedgerTransaction.source_type == "initial_balance",
        ).delete()

    amt = round(float(payload.amount), 2)
    if amt > 0:
        if payload.ahead_user == "Tamir":
            paid_by = "Tamir"
            split_rule = "MIKUSH_100"
            tamir_share = 0.0
            mikush_share = amt
            default_desc = f"Starting Balance (Tamir ₪{amt:.2f} ahead)"
        else:
            paid_by = "Mikush"
            split_rule = "TAMIR_100"
            tamir_share = amt
            mikush_share = 0.0
            default_desc = f"Starting Balance (Mikush ₪{amt:.2f} ahead)"

        tx = LedgerTransaction(
            description=(payload.note or default_desc).strip(),
            category="Initial Balance",
            paid_by=paid_by,
            total_amount=amt,
            split_rule=split_rule,
            tamir_share=tamir_share,
            mikush_share=mikush_share,
            source_type="initial_balance",
            is_settled=False,
            transaction_date=datetime.datetime.utcnow(),
        )
        db.add(tx)

    db.commit()
    return {
        "status": "ok",
        "message": f"Updated starting balance ({payload.ahead_user} ₪{amt:.2f} ahead)",
        "summary": compute_ledger_balance(db),
    }


def _identify_member_columns(headers: List[str]) -> tuple[Optional[int], Optional[int]]:
    tamir_idx = None
    mikush_idx = None
    for idx, h in enumerate(headers):
        hl = (h or "").strip().lower()
        if any(k in hl for k in ("tamir", "תמיר")):
            tamir_idx = idx
        elif any(k in hl for k in ("mikush", "mika", "מיקוש", "מיקה")):
            mikush_idx = idx

    # Fallback: Splitwise puts the two group members in the last two columns
    if tamir_idx is None or mikush_idx is None:
        if len(headers) >= 7:
            if tamir_idx is None and mikush_idx != len(headers) - 2:
                tamir_idx = len(headers) - 2
            if mikush_idx is None and tamir_idx != len(headers) - 1:
                mikush_idx = len(headers) - 1
    return tamir_idx, mikush_idx


def _parse_float(val: Optional[str]) -> float:
    if not val:
        return 0.0
    cleaned = val.replace(",", "").replace("₪", "").replace("$", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _ingest_splitwise_csv_text(csv_text: str, db: Session) -> dict:
    reader = csv.reader(io.StringIO(csv_text.lstrip("\ufeff")))
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        raise HTTPException(status_code=400, detail="CSV file is empty")

    # Find header row
    header_idx = 0
    for i, r in enumerate(rows[:5]):
        joined = ",".join(c.lower() for c in r)
        if "description" in joined and "cost" in joined:
            header_idx = i
            break

    headers = [h.strip() for h in rows[header_idx]]
    header_lower = [h.lower() for h in headers]

    try:
        date_idx = header_lower.index("date")
    except ValueError:
        date_idx = 0
    try:
        desc_idx = header_lower.index("description")
    except ValueError:
        desc_idx = 1
    try:
        cat_idx = header_lower.index("category")
    except ValueError:
        cat_idx = 2
    try:
        cost_idx = header_lower.index("cost")
    except ValueError:
        cost_idx = 3

    tamir_idx, mikush_idx = _identify_member_columns(headers)
    if tamir_idx is None or mikush_idx is None:
        raise HTTPException(
            status_code=400,
            detail="Could not identify Tamir & Mikush columns in Splitwise CSV header."
        )

    imported_count = 0
    skipped_duplicates = 0

    for row in rows[header_idx + 1:]:
        if len(row) <= max(desc_idx, cost_idx, tamir_idx, mikush_idx):
            continue

        date_str = row[date_idx].strip()
        desc = row[desc_idx].strip()
        if not desc or desc.lower() == "total balance" or date_str.lower() == "total balance":
            continue

        category = row[cat_idx].strip() if cat_idx < len(row) and row[cat_idx].strip() else "Splitwise Import"
        cost = abs(_parse_float(row[cost_idx]))
        tamir_net = _parse_float(row[tamir_idx])
        mikush_net = _parse_float(row[mikush_idx])

        if cost <= 0 and abs(tamir_net) <= 0 and abs(mikush_net) <= 0:
            continue

        row_sig = f"{date_str}|{desc}|{cost:.2f}|{tamir_net:.2f}|{mikush_net:.2f}"
        ext_hash = hashlib.sha256(row_sig.encode("utf-8")).hexdigest()

        exists = db.query(LedgerTransaction).filter(LedgerTransaction.external_hash == ext_hash).first()
        if exists:
            skipped_duplicates += 1
            continue

        # Parse transaction date
        tx_date = datetime.datetime.utcnow()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
            try:
                tx_date = datetime.datetime.strptime(date_str, fmt)
                break
            except ValueError:
                continue

        is_payment = category.lower() == "payment" or "paid" in desc.lower() or "שילם" in desc.lower()

        if tamir_net >= 0 and mikush_net <= 0:
            paid_by = "Tamir"
            mikush_share = round(abs(mikush_net), 2)
            tamir_share = round(max(0.0, cost - mikush_share), 2)
        elif mikush_net >= 0 and tamir_net <= 0:
            paid_by = "Mikush"
            tamir_share = round(abs(tamir_net), 2)
            mikush_share = round(max(0.0, cost - tamir_share), 2)
        else:
            paid_by = "Tamir"
            tamir_share = round(cost / 2.0, 2)
            mikush_share = round(cost - tamir_share, 2)

        if is_payment:
            split_rule = "SETTLEMENT"
        elif abs(tamir_share - mikush_share) < 0.02:
            split_rule = "SHARED_50_50"
        elif tamir_share == 0:
            split_rule = "MIKUSH_100"
        elif mikush_share == 0:
            split_rule = "TAMIR_100"
        else:
            split_rule = "CUSTOM"

        db.add(LedgerTransaction(
            description=desc,
            category=category,
            paid_by=paid_by,
            total_amount=round(cost if cost > 0 else max(tamir_share, mikush_share), 2),
            split_rule=split_rule,
            tamir_share=tamir_share,
            mikush_share=mikush_share,
            source_type="splitwise_csv",
            is_settled=False,
            external_hash=ext_hash,
            transaction_date=tx_date,
        ))
        imported_count += 1

    db.commit()
    return {
        "status": "ok",
        "imported_count": imported_count,
        "skipped_duplicates": skipped_duplicates,
        "message": f"Imported {imported_count} Splitwise transaction(s)" + (f" ({skipped_duplicates} duplicates skipped)" if skipped_duplicates else ""),
        "summary": compute_ledger_balance(db),
    }


@ledger_router.post("/import-splitwise", dependencies=[Depends(require_auth_api)])
async def import_splitwise_csv(
    request: Request,
    file: Optional[UploadFile] = File(None),
    csv_content: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Imports a standard Splitwise .csv export (multipart upload or JSON csv_content)."""
    text_data = csv_content
    if file is not None:
        raw_bytes = await file.read()
        text_data = raw_bytes.decode("utf-8", errors="replace")
    elif not text_data:
        try:
            body = await request.json()
            text_data = body.get("csv_content")
        except Exception:
            text_data = None

    if not text_data or not text_data.strip():
        raise HTTPException(status_code=400, detail="Please upload a Splitwise CSV file or paste CSV content.")

    return _ingest_splitwise_csv_text(text_data, db)


@ledger_router.post("/settle", dependencies=[Depends(require_auth_api)])
def settle_up_ledger(
    payload: SettleUpPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Explicit manual Settle-Up button handler (supporting full or partial amounts).
    - Full settle-up zeroes the running balance and archives all unsettled transactions into Settlement History.
    - Partial settle-up logs the payment and inserts an offsetting adjustment so the remaining balance stays active.
    """
    active_user = payload.settled_by or get_active_profile(request)
    balance_info = compute_ledger_balance(db)
    balance_before = balance_info["net_balance"]

    if abs(balance_before) < 0.01:
        raise HTTPException(status_code=400, detail="Everything is already settled up (₪0.00 balance).")

    payer = "Mikush" if balance_before > 0 else "Tamir"
    payee = "Tamir" if balance_before > 0 else "Mikush"
    abs_before = abs(balance_before)

    if payload.amount is None or payload.amount >= (abs_before - 0.01):
        settle_amount = round(abs_before, 2)
        is_full = True
    else:
        if payload.amount <= 0:
            raise HTTPException(status_code=400, detail="Settlement amount must be greater than 0.")
        settle_amount = round(float(payload.amount), 2)
        is_full = False

    now = datetime.datetime.utcnow()

    if is_full:
        balance_after = 0.0
        settlement = LedgerSettlement(
            settled_by=active_user,
            payer=payer,
            payee=payee,
            amount=settle_amount,
            is_full_settlement=True,
            balance_before=balance_before,
            balance_after=balance_after,
            note=(payload.note or f"Full Settle-Up ({payer} paid {payee} ₪{settle_amount:.2f})").strip(),
            settled_at=now,
        )
        db.add(settlement)
        db.flush()

        # Archive all currently unsettled transactions under this settlement
        unsettled_rows = db.query(LedgerTransaction).filter(LedgerTransaction.is_settled == False).all()
        for tx in unsettled_rows:
            tx.is_settled = True
            tx.settlement_id = settlement.id
        db.commit()
    else:
        # Partial settlement: reduce running balance by settle_amount
        balance_after = round(balance_before - settle_amount, 2) if balance_before > 0 else round(balance_before + settle_amount, 2)
        settlement = LedgerSettlement(
            settled_by=active_user,
            payer=payer,
            payee=payee,
            amount=settle_amount,
            is_full_settlement=False,
            balance_before=balance_before,
            balance_after=balance_after,
            note=(payload.note or f"Partial Settle-Up ({payer} paid {payee} ₪{settle_amount:.2f})").strip(),
            settled_at=now,
        )
        db.add(settlement)
        db.flush()

        # Insert offsetting transaction so running balance reflects exact remaining debt
        offset_tx = LedgerTransaction(
            description=f"Partial Settle-Up ({payer} -> {payee})",
            category="Settlement Adjustment",
            paid_by=payer,
            total_amount=settle_amount,
            split_rule="SETTLEMENT",
            tamir_share=settle_amount if payer == "Mikush" else 0.0,
            mikush_share=settle_amount if payer == "Tamir" else 0.0,
            source_type="partial_settlement",
            is_settled=False,
            transaction_date=now,
        )
        db.add(offset_tx)
        db.commit()

    return {
        "status": "ok",
        "is_full_settlement": is_full,
        "settled_amount": settle_amount,
        "payer": payer,
        "payee": payee,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "message": (
            f"Settled up! {payer} paid {payee} ₪{settle_amount:.2f}. Balance is now ₪0.00."
            if is_full
            else f"Recorded partial payment of ₪{settle_amount:.2f} ({payer} -> {payee})."
        ),
        "summary": compute_ledger_balance(db),
    }
