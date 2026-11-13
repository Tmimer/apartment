import json
import base64
import datetime
from typing import Optional, List, Literal
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models.groceries import GroceryItem, GROCERY_CATEGORIES
from models.ledger import LearnedItemRule, ReceiptScan, LedgerTransaction
from routers.groceries import record_purchase_event
from routers.ledger import compute_ledger_balance
from security import require_auth_api, get_active_profile
from services.gemini_service import (
    GeminiAPIKeyMissingError,
    classify_grocery_metadata,
    normalize_item_key,
    infer_grocery_category,
    process_and_enrich_receipt_items,
    calculate_receipt_totals,
    parse_receipt_with_gemini,
    parse_receipt_text_locally,
    parse_brain_dump_with_gemini,
    parse_brain_dump_locally,
    normalize_media_mime,
    _canonical_alias_groups,
)

receipts_router = APIRouter(tags=["receipts"])


# ===================== PYDANTIC SCHEMAS =====================
class LearnedRulePayload(BaseModel):
    item_name: str = Field(..., min_length=1)
    split_rule: Literal["SHARED_50_50", "MIKUSH_100", "TAMIR_100"]
    category: Optional[str] = None
    is_produce: Optional[bool] = False


class ReceiptRecalculatePayload(BaseModel):
    paid_by: Literal["Tamir", "Mikush"] = "Tamir"
    items: List[dict]


class ReceiptCommitPayload(BaseModel):
    merchant_name: Optional[str] = "Supermarket Receipt"
    receipt_type: Optional[str] = "supermarket"
    paid_by: Literal["Tamir", "Mikush"] = "Tamir"
    items: List[dict]
    auto_cross_off_groceries: bool = True
    save_flipped_rules: bool = True


# ===================== HELPERS =====================
def _load_learned_rules_map(db: Session) -> dict:
    rules = db.query(LearnedItemRule).all()
    return {
        r.normalized_name: {
            "id": r.id,
            "normalized_name": r.normalized_name,
            "display_name": r.display_name,
            "split_rule": r.split_rule,
            "category": r.category,
            "is_produce": r.is_produce,
        }
        for r in rules
    }


def _load_active_groceries(db: Session) -> List[dict]:
    active = db.query(GroceryItem).filter(GroceryItem.is_checked == False).all()
    return [
        {
            "id": g.id,
            "name": g.name,
            "category": g.category,
            "amount": g.amount,
            "unit": g.unit,
        }
        for g in active
    ]


def _upsert_learned_rule(
    db: Session,
    item_name: str,
    split_rule: str,
    category: Optional[str],
    is_produce: bool,
    updated_by: str,
) -> Optional[LearnedItemRule]:
    norm = normalize_item_key(item_name)
    if not norm or split_rule not in ("SHARED_50_50", "MIKUSH_100", "TAMIR_100"):
        return None

    now = datetime.datetime.utcnow()
    existing = db.query(LearnedItemRule).filter(LearnedItemRule.normalized_name == norm).first()
    if existing:
        existing.split_rule = split_rule
        existing.display_name = item_name.strip() or existing.display_name
        if category:
            existing.category = category
        existing.is_produce = bool(is_produce)
        existing.updated_by = updated_by
        existing.updated_at = now
        return existing

    rule = LearnedItemRule(
        normalized_name=norm,
        display_name=item_name.strip(),
        split_rule=split_rule,
        category=category,
        is_produce=bool(is_produce),
        updated_by=updated_by,
        updated_at=now,
    )
    db.add(rule)
    return rule


def _decode_base64_image(raw_b64: str) -> bytes:
    if "," in raw_b64 and raw_b64.startswith("data:"):
        raw_b64 = raw_b64.split(",", 1)[1]
    return base64.b64decode(raw_b64)


# ===================== RECEIPT SCANNER ENDPOINTS =====================
@receipts_router.post("/api/receipts/parse", dependencies=[Depends(require_auth_api)])
async def parse_receipt_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    paid_by: Optional[str] = Form(None),
    receipt_text: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """
    Parses an Israeli supermarket receipt, Wolt order, or utility bill using gemini-2.5-flash,
    or offline receipt text via LearnedItemRules + seed_hebrew_items.py fallback.
    """
    active_user = paid_by if paid_by in ("Tamir", "Mikush") else get_active_profile(request)
    learned_rules_map = _load_learned_rules_map(db)
    active_groceries = _load_active_groceries(db)

    image_bytes: Optional[bytes] = None
    mime_type: str = "image/jpeg"
    mock_items = None
    merchant_name = None
    receipt_type = None
    text_payload = receipt_text

    if file is not None:
        image_bytes = await file.read()
        mime_type = file.content_type or "image/jpeg"
    elif not receipt_text:
        try:
            body = await request.json()
        except Exception:
            body = {}
        if body.get("paid_by") in ("Tamir", "Mikush"):
            active_user = body["paid_by"]
        if body.get("image_base64"):
            image_bytes = _decode_base64_image(body["image_base64"])
            mime_type = body.get("mime_type") or "image/jpeg"
        mock_items = body.get("mock_items")
        merchant_name = body.get("merchant_name")
        receipt_type = body.get("receipt_type")
        text_payload = body.get("receipt_text") or text_payload

    if mock_items is not None:
        # Structured payload path (for deterministic testing/re-enrichment)
        enriched = process_and_enrich_receipt_items(
            mock_items,
            learned_rules_map=learned_rules_map,
            active_grocery_items=active_groceries,
        )
        totals = calculate_receipt_totals(enriched, paid_by=active_user)
        return {
            "status": "ok",
            "merchant_name": merchant_name or "Supermarket Receipt",
            "receipt_type": receipt_type or "supermarket",
            "receipt_date": datetime.date.today().isoformat(),
            "currency": "ILS",
            "paid_by": active_user,
            "items": enriched,
            "totals": totals,
            "parser_mode": "structured",
            "matched_grocery_items": [
                {"id": it["matched_grocery_id"], "name": it["matched_grocery_name"]}
                for it in enriched if it.get("matched_grocery_id")
            ],
        }

    if text_payload and text_payload.strip():
        parsed = parse_receipt_text_locally(
            receipt_text=text_payload,
            learned_rules_map=learned_rules_map,
            active_grocery_items=active_groceries,
            merchant_name=merchant_name,
            receipt_type=receipt_type,
        )
        totals = calculate_receipt_totals(parsed["items"], paid_by=active_user)
        return {
            "status": "ok",
            **parsed,
            "paid_by": active_user,
            "totals": totals,
            "matched_grocery_items": [
                {"id": it["matched_grocery_id"], "name": it["matched_grocery_name"]}
                for it in parsed["items"] if it.get("matched_grocery_id")
            ],
        }

    if not image_bytes:
        raise HTTPException(status_code=400, detail="Please upload a receipt photo or paste receipt text.")

    try:
        parsed = parse_receipt_with_gemini(
            image_bytes=image_bytes,
            mime_type=mime_type,
            learned_rules_map=learned_rules_map,
            active_grocery_items=active_groceries,
        )
    except GeminiAPIKeyMissingError as e:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "error_code": "GEMINI_API_KEY_MISSING",
                "detail": str(e),
            },
        )
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={
                "status": "error",
                "error_code": "GEMINI_PARSE_FAILED",
                "detail": f"Could not parse receipt image: {str(e)}",
            },
        )

    totals = calculate_receipt_totals(parsed["items"], paid_by=active_user)
    return {
        "status": "ok",
        **parsed,
        "paid_by": active_user,
        "totals": totals,
        "matched_grocery_items": [
            {"id": it["matched_grocery_id"], "name": it["matched_grocery_name"]}
            for it in parsed["items"] if it.get("matched_grocery_id")
        ],
    }


@receipts_router.post("/api/receipts/recalculate", dependencies=[Depends(require_auth_api)])
def recalculate_receipt_preview(payload: ReceiptRecalculatePayload):
    """Recalculates receipt totals and deposit inheritance after a user flips item owners."""
    items = [dict(it) for it in payload.items]
    for idx, it in enumerate(items):
        if it.get("is_deposit") and not it.get("user_flipped") and it.get("rule_source") != "learned" and idx > 0:
            it["split_rule"] = items[idx - 1].get("split_rule", "SHARED_50_50")
            it["rule_source"] = "deposit_inherited"
    totals = calculate_receipt_totals(items, paid_by=payload.paid_by)
    return {"status": "ok", "items": items, "totals": totals}


@receipts_router.get("/api/receipts/rules", dependencies=[Depends(require_auth_api)])
def list_learned_rules(db: Session = Depends(get_db)):
    rules = db.query(LearnedItemRule).order_by(LearnedItemRule.updated_at.desc()).all()
    return {
        "rules": [
            {
                "id": r.id,
                "normalized_name": r.normalized_name,
                "display_name": r.display_name,
                "split_rule": r.split_rule,
                "category": r.category,
                "is_produce": r.is_produce,
                "updated_by": r.updated_by,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rules
        ]
    }


@receipts_router.post("/api/receipts/rules", dependencies=[Depends(require_auth_api)])
def save_learned_rule(
    payload: LearnedRulePayload,
    request: Request,
    db: Session = Depends(get_db),
):
    """Persists a flipped item owner rule into learned_item_rules so future receipts auto-classify it."""
    active_user = get_active_profile(request)
    rule = _upsert_learned_rule(
        db=db,
        item_name=payload.item_name,
        split_rule=payload.split_rule,
        category=payload.category,
        is_produce=bool(payload.is_produce),
        updated_by=active_user,
    )
    if not rule:
        raise HTTPException(status_code=400, detail="Valid item_name and split_rule required.")
    db.commit()
    db.refresh(rule)
    return {
        "status": "ok",
        "message": f"Learned rule: '{rule.display_name}' -> {rule.split_rule}",
        "rule": {
            "id": rule.id,
            "normalized_name": rule.normalized_name,
            "display_name": rule.display_name,
            "split_rule": rule.split_rule,
        },
    }


@receipts_router.delete("/api/receipts/rules/{rule_id}", dependencies=[Depends(require_auth_api)])
def delete_learned_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(LearnedItemRule).filter(LearnedItemRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Learned rule not found")
    db.delete(rule)
    db.commit()
    return {"status": "ok", "message": "Deleted learned item rule"}


@receipts_router.post("/api/receipts/commit", dependencies=[Depends(require_auth_api)])
def commit_reviewed_receipt(
    payload: ReceiptCommitPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Commits the interactive receipt review:
    1. Saves any user-flipped items to learned_item_rules.
    2. Computes final asymmetric shares & creates ReceiptScan + LedgerTransaction.
    3. Auto-crosses off matching items currently on the active Grocery List.
    4. Logs non-deposit items to grocery_purchase_history for Depletion Radar.
    """
    active_user = get_active_profile(request)
    now = datetime.datetime.utcnow()

    # Load existing learned rules so non-flipped items respect rules, while user-flipped items override
    learned_rules_map = _load_learned_rules_map(db)
    active_groceries = _load_active_groceries(db)

    # Save any user-flipped items immediately to learned_item_rules
    saved_rules_count = 0
    if payload.save_flipped_rules:
        for raw_it in payload.items:
            if raw_it.get("user_flipped") or raw_it.get("save_rule"):
                rule_name = raw_it.get("normalized_name") or raw_it.get("raw_name") or raw_it.get("name")
                if rule_name and raw_it.get("split_rule") in ("SHARED_50_50", "MIKUSH_100", "TAMIR_100"):
                    _upsert_learned_rule(
                        db=db,
                        item_name=rule_name,
                        split_rule=raw_it["split_rule"],
                        category=raw_it.get("category"),
                        is_produce=bool(raw_it.get("is_produce")),
                        updated_by=active_user,
                    )
                    learned_rules_map[normalize_item_key(rule_name)] = {"split_rule": raw_it["split_rule"]}
                    saved_rules_count += 1

    # Re-enrich items to guarantee discount subtraction & deposit inheritance before finalizing
    final_items = process_and_enrich_receipt_items(
        payload.items,
        learned_rules_map=learned_rules_map,
        active_grocery_items=active_groceries,
    )
    totals = calculate_receipt_totals(final_items, paid_by=payload.paid_by)

    # Auto-cross off matching active grocery list items
    checked_off_names: List[str] = []
    if payload.auto_cross_off_groceries:
        matched_ids = {
            int(it["matched_grocery_id"])
            for it in final_items
            if it.get("matched_grocery_id")
        }
        if matched_ids:
            to_check = (
                db.query(GroceryItem)
                .filter(GroceryItem.id.in_(matched_ids), GroceryItem.is_checked == False)
                .all()
            )
            for g in to_check:
                g.is_checked = True
                g.checked_at = now
                g.updated_at = now
                checked_off_names.append(g.name)

    # Record purchase history for Depletion Radar
    for it in final_items:
        if not it.get("is_deposit"):
            record_purchase_event(
                db=db,
                item_name=it.get("normalized_name") or it.get("raw_name"),
                category=it.get("category"),
                amount=it.get("quantity"),
                unit=it.get("unit"),
                source="receipt_scan",
                purchased_by=payload.paid_by,
                purchased_at=now,
            )

    merchant = (payload.merchant_name or "Supermarket Receipt").strip()
    scan = ReceiptScan(
        merchant_name=merchant,
        receipt_type=payload.receipt_type or "supermarket",
        paid_by=payload.paid_by,
        total_amount=totals["total_amount"],
        shared_total=totals["shared_50_50_total"],
        mikush_only_total=totals["mikush_100_total"],
        tamir_only_total=totals["tamir_100_total"],
        tamir_final_share=totals["tamir_final_share"],
        mikush_final_share=totals["mikush_final_share"],
        items_json=json.dumps(final_items, ensure_ascii=False),
        auto_checked_items_json=json.dumps(checked_off_names, ensure_ascii=False),
        created_at=now,
    )
    db.add(scan)
    db.flush()

    tx = LedgerTransaction(
        description=f"🧾 {merchant}",
        category="Groceries" if (payload.receipt_type or "supermarket") in ("supermarket", "wolt") else "Utilities",
        paid_by=payload.paid_by,
        total_amount=totals["total_amount"],
        split_rule="ASYMMETRIC_RECEIPT",
        tamir_share=totals["tamir_final_share"],
        mikush_share=totals["mikush_final_share"],
        source_type="receipt_scan",
        receipt_scan_id=scan.id,
        is_settled=False,
        transaction_date=now,
        created_at=now,
    )
    db.add(tx)
    db.commit()
    db.refresh(scan)
    db.refresh(tx)

    return {
        "status": "ok",
        "receipt_scan_id": scan.id,
        "transaction_id": tx.id,
        "totals": totals,
        "saved_rules_count": saved_rules_count,
        "auto_checked_items": checked_off_names,
        "message": (
            f"Committed {merchant} (₪{totals['total_amount']:.2f})"
            + (f" · Crossed off {len(checked_off_names)} grocery item(s)" if checked_off_names else "")
        ),
        "summary": compute_ledger_balance(db),
    }


# ===================== UNIFIED BRAIN DUMP ENDPOINT =====================
def _match_grocery_row_for_checkoff(name: str, matched_id: Optional[int], active_rows: List[GroceryItem]) -> Optional[GroceryItem]:
    if matched_id:
        for row in active_rows:
            if row.id == matched_id:
                return row
    target_groups = _canonical_alias_groups(name)
    norm = normalize_item_key(name)
    for row in active_rows:
        r_groups = _canonical_alias_groups(row.name)
        if target_groups & r_groups:
            return row
        r_norm = normalize_item_key(row.name)
        if r_norm and norm and (r_norm in norm or norm in r_norm):
            return row
    return None


@receipts_router.post("/api/brain-dump", dependencies=[Depends(require_auth_api)])
async def execute_brain_dump(
    request: Request,
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """
    Unified Brain Dump bar: accepts JSON text/media, or multipart/form-data containing
    typed text, handwritten list photos (image/*), or recorded voice blobs (audio/*),
    transcribing & executing multi-intent actions in one pass.
    """
    active_user = get_active_profile(request)
    image_bytes: Optional[bytes] = None
    image_mime_type: Optional[str] = None
    audio_bytes: Optional[bytes] = None
    audio_mime_type: Optional[str] = None
    input_text = text

    if file is not None:
        raw_bytes = await file.read()
        clean_mime = normalize_media_mime(file.content_type, file.filename)
        if raw_bytes:
            if clean_mime.startswith("audio/"):
                audio_bytes = raw_bytes
                audio_mime_type = clean_mime
            elif clean_mime.startswith("image/") or not clean_mime:
                image_bytes = raw_bytes
                image_mime_type = clean_mime or "image/jpeg"
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file type '{clean_mime}'. Upload audio/* or image/*."
                )
    else:
        req_ct = (request.headers.get("content-type") or "").lower()
        body = {}
        if "application/json" in req_ct or input_text is None:
            try:
                body = await request.json()
            except Exception:
                body = {}
        input_text = body.get("text") or input_text
        if body.get("audio_base64"):
            audio_bytes = _decode_base64_image(body["audio_base64"])
            audio_mime_type = normalize_media_mime(body.get("mime_type") or "audio/webm") or "audio/webm"
        if body.get("image_base64"):
            decoded = _decode_base64_image(body["image_base64"])
            decoded_mime = normalize_media_mime(body.get("mime_type") or "image/jpeg") or "image/jpeg"
            if decoded_mime.startswith("audio/") and not audio_bytes:
                audio_bytes = decoded
                audio_mime_type = decoded_mime
            else:
                image_bytes = decoded
                image_mime_type = decoded_mime

    if (not input_text or not input_text.strip()) and not image_bytes and not audio_bytes:
        raise HTTPException(status_code=400, detail="Enter text, record voice audio, or attach a handwritten list photo.")

    active_groceries = _load_active_groceries(db)

    try:
        intents = parse_brain_dump_with_gemini(
            text_input=input_text.strip() if input_text else None,
            image_bytes=image_bytes,
            mime_type=image_mime_type,
            active_profile=active_user,
            active_grocery_items=active_groceries,
            audio_bytes=audio_bytes,
            audio_mime_type=audio_mime_type,
        )
    except GeminiAPIKeyMissingError as e:
        if input_text and input_text.strip():
            intents = parse_brain_dump_locally(
                text_input=input_text.strip(),
                active_profile=active_user,
                active_grocery_items=active_groceries,
            )
        else:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "error",
                    "error_code": "GEMINI_API_KEY_MISSING",
                    "detail": str(e),
                },
            )
    except Exception as e:
        if input_text and input_text.strip():
            intents = parse_brain_dump_locally(
                text_input=input_text.strip(),
                active_profile=active_user,
                active_grocery_items=active_groceries,
            )
        else:
            return JSONResponse(
                status_code=502,
                content={
                    "status": "error",
                    "error_code": "GEMINI_PARSE_FAILED",
                    "detail": f"Brain Dump AI error: {str(e)}",
                },
            )

    now = datetime.datetime.utcnow()
    active_rows = db.query(GroceryItem).filter(GroceryItem.is_checked == False).all()

    checked_off: List[str] = []
    added_items: List[dict] = []
    logged_expenses: List[dict] = []

    # 1. Execute items_to_check_off
    for ck in intents.get("items_to_check_off", []):
        ck_name = (ck.get("name") or "").strip()
        if not ck_name:
            continue
        matched_row = _match_grocery_row_for_checkoff(ck_name, ck.get("matched_grocery_id"), active_rows)
        if matched_row and not matched_row.is_checked:
            matched_row.is_checked = True
            matched_row.checked_at = now
            matched_row.updated_at = now
            checked_off.append(matched_row.name)
            record_purchase_event(
                db=db,
                item_name=matched_row.name,
                category=matched_row.category,
                amount=matched_row.amount,
                unit=matched_row.unit,
                source="brain_dump",
                purchased_by=active_user,
                purchased_at=now,
            )
        else:
            # Record purchase timestamp even if the item wasn't pre-listed
            checked_off.append(ck_name)
            record_purchase_event(
                db=db,
                item_name=ck_name,
                category=infer_grocery_category(ck_name),
                source="brain_dump",
                purchased_by=active_user,
                purchased_at=now,
            )

    # 2. Execute items_to_add
    for add_it in intents.get("items_to_add", []):
        name = (add_it.get("name") or "").strip()
        if not name:
            continue
        meta = classify_grocery_metadata(
            name,
            explicit_category=add_it.get("category"),
            explicit_split=add_it.get("default_split"),
        )
        aisle = meta["category"]
        default_split = meta["default_split"]
        typical_days = add_it.get("typical_depletion_days") or meta["typical_depletion_days"]

        existing_checked = (
            db.query(GroceryItem)
            .filter(func.lower(GroceryItem.name) == name.lower(), GroceryItem.is_checked == True)
            .first()
        )
        if existing_checked:
            existing_checked.is_checked = False
            existing_checked.checked_at = None
            existing_checked.category = aisle
            existing_checked.default_split = default_split
            existing_checked.typical_depletion_days = typical_days
            existing_checked.amount = add_it.get("amount") or existing_checked.amount
            existing_checked.unit = add_it.get("unit") or existing_checked.unit
            existing_checked.added_by = active_user
            existing_checked.updated_at = now
            added_items.append({
                "name": existing_checked.name,
                "category": aisle,
                "default_split": default_split,
                "typical_depletion_days": typical_days,
            })
        else:
            # Check if already unchecked
            already_open = (
                db.query(GroceryItem)
                .filter(func.lower(GroceryItem.name) == name.lower(), GroceryItem.is_checked == False)
                .first()
            )
            if not already_open:
                new_g = GroceryItem(
                    name=name,
                    amount=add_it.get("amount"),
                    unit=add_it.get("unit"),
                    category=aisle,
                    default_split=default_split,
                    typical_depletion_days=typical_days,
                    for_member=add_it.get("for_member"),
                    is_checked=False,
                    added_by=active_user,
                    created_at=now,
                    updated_at=now,
                )
                db.add(new_g)
            added_items.append({
                "name": name,
                "category": aisle,
                "default_split": default_split,
                "typical_depletion_days": typical_days,
            })

    # 3. Execute expenses_to_log
    for exp in intents.get("expenses_to_log", []):
        amt = float(exp.get("amount") or 0.0)
        if amt <= 0:
            continue
        payer = exp.get("paid_by") if exp.get("paid_by") in ("Tamir", "Mikush") else active_user
        split_rule = exp.get("split_rule") if exp.get("split_rule") in ("SHARED_50_50", "MIKUSH_100", "TAMIR_100") else "SHARED_50_50"
        if split_rule == "SHARED_50_50":
            t_share = round(amt / 2.0, 2)
            m_share = round(amt - t_share, 2)
        elif split_rule == "MIKUSH_100":
            t_share, m_share = 0.0, round(amt, 2)
        else:
            t_share, m_share = round(amt, 2), 0.0

        desc = (exp.get("description") or "Brain Dump Expense").strip()
        cat = (exp.get("category") or "Groceries").strip()
        tx = LedgerTransaction(
            description=desc,
            category=cat,
            paid_by=payer,
            total_amount=round(amt, 2),
            split_rule=split_rule,
            tamir_share=t_share,
            mikush_share=m_share,
            source_type="brain_dump",
            is_settled=False,
            transaction_date=now,
            created_at=now,
        )
        db.add(tx)
        logged_expenses.append({
            "description": desc,
            "amount": round(amt, 2),
            "category": cat,
            "paid_by": payer,
            "split_rule": split_rule,
        })

    db.commit()

    return {
        "status": "ok",
        "parser_mode": intents.get("parser_mode", "gemini"),
        "transcript": intents.get("transcript") or (input_text.strip() if input_text else None),
        "checked_off": checked_off,
        "added_items": added_items,
        "logged_expenses": logged_expenses,
        "summary_message": intents.get("summary_message") or (
            f"Checked {len(checked_off)} · Added {len(added_items)} · Logged {len(logged_expenses)} expense(s)"
        ),
        "ledger_summary": compute_ledger_balance(db),
    }
