import os
import datetime
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Configure isolated test DB before importing plants_app / database
TEST_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_apartment.db")
if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)

import database
from database import Base, get_db
from security import create_session_token, COOKIE_NAME
from models.groceries import (
    GroceryItem, GroceryStaple, GroceryPurchaseHistory, GROCERY_CATEGORIES
)
from models.meals import Meal, MealIngredient
from models.ledger import LearnedItemRule, ReceiptScan, LedgerSettlement, LedgerTransaction
from plants_app import app
from services.gemini_service import (
    process_and_enrich_receipt_items,
    calculate_receipt_totals,
    infer_grocery_category,
)

test_engine = create_engine(f"sqlite:///{TEST_DB_PATH}", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c.cookies.set(COOKIE_NAME, create_session_token())
        yield c
    app.dependency_overrides.clear()
    test_engine.dispose()
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


@pytest.fixture(autouse=True)
def clean_zero_entry_tables():
    """Reset Zero-Entry tables between tests while keeping starter data tests clean."""
    db = TestingSessionLocal()
    try:
        db.query(LedgerTransaction).delete()
        db.query(LedgerSettlement).delete()
        db.query(ReceiptScan).delete()
        db.query(LearnedItemRule).delete()
        db.query(GroceryPurchaseHistory).delete()
        db.query(GroceryItem).delete()
        db.commit()
    finally:
        db.close()


def test_existing_hub_modules_non_regression(client):
    """Ensure Plants, Dates, Movies, Maintenance, Status Note, Meals, and Groceries all return 200 OK."""
    endpoints = [
        "/health",
        "/plants/api/list",
        "/dates/api/spots",
        "/dates/api/movies",
        "/dates/api/presets",
        "/maintenance/api/tasks",
        "/api/status-note",
        "/meals/api/meals",
        "/meals/api/plan",
        "/meals/api/fridge",
        "/groceries/api/items",
        "/",
        "/groceries",
        "/ledger",
    ]
    for ep in endpoints:
        resp = client.get(ep)
        assert resp.status_code == 200, f"Endpoint {ep} failed with {resp.status_code}: {resp.text}"


def test_missing_gemini_key_returns_friendly_json_without_crashing(client, monkeypatch):
    """Guardrail 3: Missing GEMINI_API_KEY returns 503 JSON for image-only calls and uses local fallback for text Brain Dump."""
    monkeypatch.setenv("GEMINI_API_KEY", "")
    resp = client.post(
        "/api/receipts/parse",
        files={"file": ("receipt.jpg", b"fake-image-bytes", "image/jpeg")},
        headers={"X-Apartment-User": "Tamir"},
    )
    assert resp.status_code == 503
    data = resp.json()
    assert data["error_code"] == "GEMINI_API_KEY_MISSING"
    assert "GEMINI_API_KEY" in data["detail"]

    # Image-only Brain Dump without text returns friendly 503
    img_bd_resp = client.post(
        "/api/brain-dump",
        files={"file": ("note.jpg", b"fake-handwritten-list", "image/jpeg")},
        headers={"X-Apartment-User": "Tamir"},
    )
    assert img_bd_resp.status_code == 503
    assert img_bd_resp.json()["error_code"] == "GEMINI_API_KEY_MISSING"

    # Text Brain Dump gracefully uses deterministic local fallback
    bd_resp = client.post(
        "/api/brain-dump",
        json={"text": "out of milk"},
        headers={"X-Apartment-User": "Tamir"},
    )
    assert bd_resp.status_code == 200
    bd_data = bd_resp.json()
    assert bd_data["parser_mode"] == "local_fallback"
    assert any(it["name"].lower() == "milk" for it in bd_data["added_items"])


def test_israeli_receipt_edge_cases_and_asymmetric_math(client):
    """
    Tests all 4 Israeli supermarket receipt edge cases:
    1) Weighted produce (שקילה: 0.645 kg * 12.90 = 8.32) -> MIKUSH_100
    2) Next-line store promotion (מבצע -4.90) subtracted from parent item BEFORE splitting
    3) Bottle deposit (פיקדון 0.30) inheriting the split_rule of the beverage line above it
    4) LearnedItemRule overriding default classification on future parses
    5) Auto-crossing off active grocery items on commit
    """
    # Seed active grocery items that should get auto-crossed off on commit
    client.post("/groceries/api/items", json={"name": "Milk", "category": "Dairy/Eggs"})
    client.post("/groceries/api/items", json={"name": "Cucumber", "category": "Produce"})

    raw_items = [
        # 1. Weighted produce (שקילה): 0.645 kg * 12.90 = 8.32 -> MIKUSH_100
        {
            "raw_name": "מלפפון (שקילה)",
            "normalized_name": "cucumber",
            "quantity": 0.645,
            "unit": "kg",
            "unit_price": 12.90,
            "gross_price": 0.0,  # let post-processor compute 0.645 * 12.90 = 8.32
            "net_price": 0.0,
            "is_produce": True,
        },
        # 2. Shared item with next-line מבצע promotion printed as separate negative row
        {
            "raw_name": "חלב תנובה 3%",
            "normalized_name": "milk",
            "quantity": 2,
            "unit": "L",
            "unit_price": 7.00,
            "gross_price": 14.00,
            "net_price": 14.00,
            "category": "Dairy/Eggs",
        },
        {
            "raw_name": "מבצע זוגות חלב",
            "gross_price": -4.00,
            "net_price": -4.00,
            "is_discount_row": True,
        },
        # 3. Beverage + bottle deposit (פיקדון) below it -> deposit inherits beverage's rule
        # First teach that "diet coke" is TAMIR_100 via LearnedItemRule
        {
            "raw_name": "קולה זירו 1.5 ליטר",
            "normalized_name": "diet coke",
            "quantity": 1,
            "unit": "pcs",
            "unit_price": 8.00,
            "gross_price": 8.00,
            "net_price": 8.00,
            "category": "Pantry/Dry",
        },
        {
            "raw_name": "דמי פיקדון",
            "normalized_name": "bottle deposit",
            "quantity": 1,
            "unit": "pcs",
            "unit_price": 0.30,
            "gross_price": 0.30,
            "net_price": 0.30,
            "is_deposit": True,
        },
        # 4. Avocado (produce) with inline discount -> net 10.00 -> MIKUSH_100
        {
            "raw_name": "אבוקדו",
            "normalized_name": "avocado",
            "quantity": 1,
            "unit": "kg",
            "unit_price": 15.00,
            "gross_price": 15.00,
            "discount_amount": 5.00,
            "discount_label": "הנחת מועדון",
            "net_price": 15.00,  # unsubtracted by mock LLM -> must become 10.00
            "is_produce": True,
        },
    ]

    # Save LearnedItemRule for "diet coke" -> TAMIR_100 BEFORE parsing
    rule_resp = client.post(
        "/api/receipts/rules",
        json={"item_name": "diet coke", "split_rule": "TAMIR_100", "category": "Pantry/Dry"},
    )
    assert rule_resp.status_code == 200

    parse_resp = client.post(
        "/api/receipts/parse",
        json={
            "merchant_name": "Shufersal Deal",
            "paid_by": "Tamir",
            "mock_items": raw_items,
        },
    )
    assert parse_resp.status_code == 200
    parsed = parse_resp.json()
    items = parsed["items"]

    # Standalone discount row must be collapsed into parent Milk
    assert len(items) == 5

    cucumber = items[0]
    assert cucumber["net_price"] == 8.32
    assert cucumber["split_rule"] == "MIKUSH_100"

    milk = items[1]
    assert milk["discount_amount"] == 4.00
    assert milk["net_price"] == 10.00  # 14.00 - 4.00
    assert milk["split_rule"] == "SHARED_50_50"

    coke = items[2]
    assert coke["split_rule"] == "TAMIR_100"
    assert coke["rule_source"] == "learned"

    deposit = items[3]
    assert deposit["is_deposit"] is True
    assert deposit["split_rule"] == "TAMIR_100"  # Inherited from Diet Coke!
    assert deposit["rule_source"] == "deposit_inherited"

    avocado = items[4]
    assert avocado["net_price"] == 10.00  # 15.00 - 5.00
    assert avocado["split_rule"] == "MIKUSH_100"

    totals = parsed["totals"]
    # Shared: 10.00 (5.00 each)
    # Mikush 100%: 8.32 + 10.00 = 18.32
    # Tamir 100%: 8.00 + 0.30 = 8.30
    assert totals["shared_50_50_total"] == 10.00
    assert totals["mikush_100_total"] == 18.32
    assert totals["tamir_100_total"] == 8.30
    assert totals["total_amount"] == 36.62
    assert totals["tamir_final_share"] == 13.30  # 5.00 + 8.30
    assert totals["mikush_final_share"] == 23.32  # 5.00 + 18.32

    # Commit receipt -> check ledger & auto-crossed groceries
    commit_resp = client.post(
        "/api/receipts/commit",
        json={
            "merchant_name": "Shufersal Deal",
            "receipt_type": "supermarket",
            "paid_by": "Tamir",
            "items": items,
            "auto_cross_off_groceries": True,
        },
    )
    assert commit_resp.status_code == 200
    cdata = commit_resp.json()
    assert set(cdata["auto_checked_items"]) == {"Milk", "Cucumber"}
    assert cdata["summary"]["net_balance"] == 23.32  # Tamir paid, so Mikush owes Tamir ₪23.32

    # Verify groceries are now checked off
    g_items = client.get("/groceries/api/items").json()["items"]
    assert all(it["is_checked"] is True for it in g_items)

    # Verify flipping an item during review teaches learned_item_rules for future scans
    client.post(
        "/api/receipts/rules",
        json={"item_name": "avocado", "split_rule": "SHARED_50_50"},
    )
    re_parse = client.post(
        "/api/receipts/parse",
        json={"paid_by": "Tamir", "mock_items": [{"raw_name": "Avocado", "net_price": 12.0, "is_produce": True}]},
    ).json()
    assert re_parse["items"][0]["split_rule"] == "SHARED_50_50"
    assert re_parse["items"][0]["rule_source"] == "learned"


def test_splitwise_ledger_csv_import_initial_balance_and_settle_up(client):
    """
    Tests Guardrail 4:
    - 1-click Set Starting Balance
    - Splitwise .csv import with duplicate skipping
    - Manual bills
    - Partial Settle-Up & Full Settle-Up archiving into Settlement History
    """
    # 1. Set Starting Balance: Tamir is ₪100.00 ahead
    ib = client.post(
        "/api/ledger/initial-balance",
        json={"ahead_user": "Tamir", "amount": 100.0, "note": "Splitwise starting balance"},
    )
    assert ib.status_code == 200
    assert ib.json()["summary"]["net_balance"] == 100.0

    # 2. Import Splitwise CSV (Mikush paid ₪120 shared 50/50 -> Tamir owes Mikush ₪60, so net becomes 100 - 60 = +40)
    csv_sample = (
        "Date,Description,Category,Cost,Currency,Tamir,Mikush\n"
        "2026-11-01,Electricity Bill,Utilities,120.00,ILS,-60.00,60.00\n"
        "2026-11-02,Total balance, , ,ILS,-60.00,60.00\n"
    )
    imp = client.post("/api/ledger/import-splitwise", json={"csv_content": csv_sample})
    assert imp.status_code == 200
    assert imp.json()["imported_count"] == 1
    assert imp.json()["summary"]["net_balance"] == 40.0

    # Re-importing same CSV skips duplicate
    imp2 = client.post("/api/ledger/import-splitwise", json={"csv_content": csv_sample})
    assert imp2.status_code == 200
    assert imp2.json()["imported_count"] == 0
    assert imp2.json()["skipped_duplicates"] == 1

    # 3. Log manual 50/50 bill paid by Tamir (₪200 -> Mikush owes +100 -> net = 140)
    tx_resp = client.post(
        "/api/ledger/transactions",
        json={
            "description": "Internet Fiber",
            "category": "Internet",
            "paid_by": "Tamir",
            "total_amount": 200.0,
            "split_rule": "SHARED_50_50",
        },
    )
    assert tx_resp.status_code == 200
    assert tx_resp.json()["summary"]["net_balance"] == 140.0

    # 4. Partial Settle-Up of ₪40 -> net becomes 100.0
    partial = client.post("/api/ledger/settle", json={"amount": 40.0, "note": "Partial Bit"})
    assert partial.status_code == 200
    assert partial.json()["is_full_settlement"] is False
    assert partial.json()["summary"]["net_balance"] == 100.0

    # 5. Full Settle-Up -> zeroes balance and archives all active transactions into Settlement History
    full = client.post("/api/ledger/settle", json={"note": "Final Bit transfer"})
    assert full.status_code == 200
    assert full.json()["is_full_settlement"] is True
    assert full.json()["summary"]["net_balance"] == 0.0
    assert full.json()["summary"]["unsettled_count"] == 0

    summary = client.get("/api/ledger/summary").json()
    assert summary["net_balance"] == 0.0
    assert len(summary["settlement_history"]) == 2
    assert summary["settlement_history"][0]["is_full_settlement"] is True
    assert summary["settlement_history"][0]["archived_count"] >= 3


def test_brain_dump_multi_intent_execution(client, monkeypatch):
    """Tests Unified Brain Dump executing check-offs, aisle-sorted adds, and ledger expenses in 1 pass."""
    client.post("/groceries/api/items", json={"name": "Milk", "category": "Dairy/Eggs"})
    client.post("/groceries/api/items", json={"name": "Eggs", "category": "Dairy/Eggs"})

    def fake_brain_dump_parser(**kwargs):
        return {
            "items_to_check_off": [
                {"name": "Milk", "matched_grocery_id": None},
                {"name": "Eggs", "matched_grocery_id": None},
            ],
            "items_to_add": [
                {"name": "Trash Bags", "amount": 1, "unit": "pack", "category": "Household"},
                {"name": "Garlic", "amount": 3, "unit": "pcs", "category": "Produce"},
            ],
            "expenses_to_log": [
                {"description": "Milk and eggs", "amount": 45.0, "category": "Groceries", "paid_by": "Tamir", "split_rule": "SHARED_50_50"},
                {"description": "Electricity", "amount": 320.0, "category": "Electricity", "paid_by": "Tamir", "split_rule": "SHARED_50_50"},
            ],
            "summary_message": "Checked off Milk & Eggs, added Trash Bags & Garlic, logged ₪45 + ₪320.",
        }

    monkeypatch.setattr("routers.receipts.parse_brain_dump_with_gemini", fake_brain_dump_parser)

    resp = client.post(
        "/api/brain-dump",
        json={"text": "Bought milk and eggs for 45, we're out of trash bags and garlic, and log 320 for electricity paid by Tamir"},
        headers={"X-Apartment-User": "Tamir"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert set(data["checked_off"]) == {"Milk", "Eggs"}
    assert len(data["added_items"]) == 2
    assert len(data["logged_expenses"]) == 2
    # (45 + 320) / 2 = 182.50 owed by Mikush to Tamir
    assert data["ledger_summary"]["net_balance"] == 182.50

    items = client.get("/groceries/api/items").json()["items"]
    by_name = {it["name"]: it for it in items}
    assert by_name["Milk"]["is_checked"] is True
    assert by_name["Eggs"]["is_checked"] is True
    assert by_name["Trash Bags"]["is_checked"] is False
    assert by_name["Trash Bags"]["category"] == "Household"
    assert by_name["Garlic"]["is_checked"] is False
    assert by_name["Garlic"]["category"] == "Produce"


def test_supermarket_walking_order_and_meal_to_cart(client):
    """Tests 8-aisle Supermarket Walking-Order sorting and 1-Click Meal-to-Cart excluding kitchen stock."""
    # Add items out of order -> GET /groceries/api/items must return them in walking order
    client.post("/groceries/api/items", json={"name": "Frozen Peas", "category": "Frozen"})
    client.post("/groceries/api/items", json={"name": "Cumin", "category": "Spices/Oils"})
    client.post("/groceries/api/items", json={"name": "Challah", "category": "Bakery"})
    client.post("/groceries/api/items", json={"name": "Tomatoes", "category": "Produce"})

    items = client.get("/groceries/api/items").json()["items"]
    categories_returned = [it["category"] for it in items if not it["is_checked"]]
    assert categories_returned == ["Produce", "Bakery", "Spices/Oils", "Frozen"]

    # Verify infer_grocery_category maps Olive Oil to Spices/Oils
    assert infer_grocery_category("Olive Oil", "Produce") == "Spices/Oils"

    # 1-Click Meal-to-Cart: pick a saved meal, exclude 1st ingredient (already in kitchen)
    meals = client.get("/meals/api/meals").json()["meals"]
    assert len(meals) >= 1
    meal = meals[0]
    first_ing_id = meal["ingredients"][0]["id"]
    remaining_ids = [ing["id"] for ing in meal["ingredients"][1:]]

    push_resp = client.post(
        f"/meals/api/meals/{meal['id']}/push-to-cart",
        json={"ingredient_ids": remaining_ids, "multiplier": 1.0},
    )
    assert push_resp.status_code == 200
    pdata = push_resp.json()
    assert pdata["pushed_count"] == len(remaining_ids)
    pushed_names = {it["name"] for it in pdata["items"]}
    assert meal["ingredients"][0]["ingredient_name"] not in pushed_names


def test_depletion_radar_interval_calculation(client):
    """Tests rolling average repurchase interval and >= 80% threshold surfacing in Depletion Radar."""
    now = datetime.datetime.utcnow()
    db = TestingSessionLocal()
    try:
        # Seed 3 Milk purchases spaced 5 days apart, with the last one 4.5 days ago (4.5 / 5.0 = 90% >= 80%)
        for days_ago in (14.5, 9.5, 4.5):
            db.add(GroceryPurchaseHistory(
                item_name="Milk",
                normalized_name="milk",
                category="Dairy/Eggs",
                amount=1.0,
                unit="L",
                source="grocery_check",
                purchased_by="Tamir",
                purchased_at=now - datetime.timedelta(days=days_ago),
            ))
        # Seed 3 Coffee purchases spaced 20 days apart, last one 5 days ago (25% < 80% -> should NOT appear)
        for days_ago in (45.0, 25.0, 5.0):
            db.add(GroceryPurchaseHistory(
                item_name="Coffee Beans",
                normalized_name="coffee beans",
                category="Pantry/Dry",
                amount=1.0,
                unit="pack",
                source="grocery_check",
                purchased_by="Tamir",
                purchased_at=now - datetime.timedelta(days=days_ago),
            ))
        db.commit()
    finally:
        db.close()

    radar = client.get("/groceries/api/depletion-radar").json()["radar_items"]
    names = [r["normalized_name"] for r in radar]
    assert "milk" in names
    assert "coffee beans" not in names

    milk_entry = next(r for r in radar if r["normalized_name"] == "milk")
    assert milk_entry["avg_interval_days"] == 5.0
    assert milk_entry["cycle_pct"] >= 88

    # Once Milk is added back onto the active grocery list, Radar stops nagging about it
    client.post("/groceries/api/items", json={"name": "Milk", "category": "Dairy/Eggs"})
    radar_after = client.get("/groceries/api/depletion-radar").json()["radar_items"]
    assert all(r["normalized_name"] != "milk" for r in radar_after)


def test_phase1_hebrew_dictionary_grocery_wiring_and_day1_radar(client):
    """Phase 1: Grocery addition without explicit category/split uses seed_hebrew_items + Day-1 Radar prior."""
    items_to_create = [
        {"name": "עגבניות שרי"},
        {"name": "קוטג' תנובה 5%"},
        {"name": "טחינה גולמית"},
        {"name": "שום"},
    ]
    created = {}
    for payload in items_to_create:
        res = client.post("/groceries/api/items", json=payload)
        assert res.status_code == 200
        it = res.json()["item"]
        created[payload["name"]] = it

    assert created["עגבניות שרי"]["category"] == "Produce"
    assert created["עגבניות שרי"]["default_split"] == "MIKUSH_100"
    assert created["עגבניות שרי"]["typical_depletion_days"] == 5

    assert created["קוטג' תנובה 5%"]["category"] == "Dairy/Eggs"
    assert created["קוטג' תנובה 5%"]["default_split"] == "SHARED_50_50"
    assert created["קוטג' תנובה 5%"]["typical_depletion_days"] == 6

    assert created["טחינה גולמית"]["category"] == "Pantry/Dry"
    assert created["טחינה גולמית"]["default_split"] == "SHARED_50_50"
    assert created["טחינה גולמית"]["typical_depletion_days"] == 21

    # Shared pantry aromatic in Produce aisle stays SHARED_50_50
    assert created["שום"]["category"] == "Produce"
    assert created["שום"]["default_split"] == "SHARED_50_50"

    # Day-1 Depletion Radar prior (ONLY 1 purchase timestamp recorded!)
    now = datetime.datetime.utcnow()
    db = TestingSessionLocal()
    try:
        # Cottage Cheese (typical 6d) bought ONCE 5.5 days ago -> 5.5/6 = 92% >= 80% -> surfaced!
        db.add(GroceryPurchaseHistory(
            item_name="קוטג'",
            normalized_name="קוטג",
            category="Dairy/Eggs",
            source="receipt_scan",
            purchased_by="Tamir",
            purchased_at=now - datetime.timedelta(days=5.5),
        ))
        # Tahini (typical >=30d) bought ONCE 6 days ago -> < 80% -> NOT surfaced!
        db.add(GroceryPurchaseHistory(
            item_name="טחינה",
            normalized_name="טחינה",
            category="Pantry/Dry",
            source="receipt_scan",
            purchased_by="Tamir",
            purchased_at=now - datetime.timedelta(days=6.0),
        ))
        db.commit()
    finally:
        db.close()

    # While "קוטג' תנובה 5%" is STILL unchecked on active list, Radar suppresses duplicate "קוטג'" nagging!
    radar_suppressed = client.get("/groceries/api/depletion-radar").json()["radar_items"]
    assert all("קוטג" not in r["normalized_name"] for r in radar_suppressed)

    # Remove from active list -> Day-1 Depletion Radar immediately surfaces "קוטג'"!
    cottage_id = created["קוטג' תנובה 5%"]["id"]
    client.delete(f"/groceries/api/items/{cottage_id}")
    radar = client.get("/groceries/api/depletion-radar").json()["radar_items"]
    cottage_r = next((r for r in radar if "קוטג" in r["normalized_name"]), None)
    assert cottage_r is not None
    assert cottage_r["purchase_count"] == 1
    assert cottage_r["avg_interval_days"] == 6.0
    assert cottage_r["prior_source"] == "seed_dictionary"
    assert all("טחינה" not in r["normalized_name"] for r in radar)


def test_phase1_receipt_deterministic_hebrew_and_local_brain_dump(client, monkeypatch):
    """Phase 1: Offline receipt text + LearnedItemRules + seed_hebrew_items + Local Brain-Dump fallback."""
    monkeypatch.setenv("GEMINI_API_KEY", "")

    # 1. LearnedItemRule overrides seed dictionary; otherwise seed_hebrew_items deterministically fixes uncertain inputs
    client.post("/api/receipts/rules", json={"item_name": "טחינה", "split_rule": "TAMIR_100", "category": "Pantry/Dry"})

    # Test deterministic cross-check even when an uncertain LLM guessed wrong splits/categories
    uncertain_parse = client.post(
        "/api/receipts/parse",
        json={
            "paid_by": "Tamir",
            "mock_items": [
                {"raw_name": "קוטג'", "net_price": 6.50, "category": "Produce", "split_rule": "TAMIR_100"},
                {"raw_name": "חלב תנובה 3%", "net_price": 6.90, "category": "Pantry/Dry", "split_rule": "MIKUSH_100"},
                {"raw_name": "טחינה", "net_price": 18.00, "category": "Dairy/Eggs", "split_rule": "SHARED_50_50"},
                {"raw_name": "מלפפון", "net_price": 8.00, "category": "Pantry/Dry", "split_rule": "SHARED_50_50"},
            ],
        },
    ).json()
    by_raw = {it["raw_name"]: it for it in uncertain_parse["items"]}
    assert by_raw["קוטג'"]["category"] == "Dairy/Eggs"
    assert by_raw["קוטג'"]["split_rule"] == "SHARED_50_50"
    assert by_raw["חלב תנובה 3%"]["category"] == "Dairy/Eggs"
    assert by_raw["חלב תנובה 3%"]["split_rule"] == "SHARED_50_50"
    assert by_raw["טחינה"]["split_rule"] == "TAMIR_100"  # LearnedItemRule wins #1!
    assert by_raw["מלפפון"]["category"] == "Produce"
    assert by_raw["מלפפון"]["split_rule"] == "MIKUSH_100"

    # 2. Offline multi-line Hebrew receipt text fallback with מבצע promotion
    text_receipt = client.post(
        "/api/receipts/parse",
        json={
            "paid_by": "Tamir",
            "receipt_text": (
                "שופרסל שלי\n"
                "עגבניות 12.90\n"
                "מבצע עגבניות -3.00\n"
                "קוטג' 5% 6.50\n"
                "חלב 3% 6.90\n"
                "מלפפון 8.00\n"
            ),
        },
    )
    assert text_receipt.status_code == 200
    tr_data = text_receipt.json()
    assert tr_data["parser_mode"] == "local_fallback"
    assert tr_data["merchant_name"] == "שופרסל שלי"
    assert len(tr_data["items"]) == 4
    tomato = tr_data["items"][0]
    assert tomato["discount_amount"] == 3.00
    assert tomato["net_price"] == 9.90
    assert tomato["split_rule"] == "MIKUSH_100"

    # 3. Local Brain-Dump fallback: "milk, eggs, and 85 for groceries"
    bd1 = client.post(
        "/api/brain-dump",
        json={"text": "milk, eggs, and 85 for groceries"},
        headers={"X-Apartment-User": "Tamir"},
    )
    assert bd1.status_code == 200
    d1 = bd1.json()
    assert d1["parser_mode"] == "local_fallback"
    added_names = {it["name"].lower() for it in d1["added_items"]}
    assert {"milk", "eggs"} <= added_names
    assert len(d1["logged_expenses"]) == 1
    assert d1["logged_expenses"][0]["amount"] == 85.0
    assert d1["logged_expenses"][0]["category"] == "Groceries"

    # Hebrew offline Brain Dump
    bd2 = client.post(
        "/api/brain-dump",
        json={"text": "נגמר קוטג' ועגבניות. שילמתי 420 על חשמל"},
        headers={"X-Apartment-User": "Mikush"},
    )
    assert bd2.status_code == 200
    d2 = bd2.json()
    assert len(d2["added_items"]) >= 2
    assert any(it["category"] == "Produce" and it["default_split"] == "MIKUSH_100" for it in d2["added_items"])
    assert len(d2["logged_expenses"]) == 1
    assert d2["logged_expenses"][0]["category"] == "Electricity"
    assert d2["logged_expenses"][0]["amount"] == 420.0


def test_phase2_recurring_bills_breakdown_and_csv_export(client):
    """Phase 2: 6 Israeli recurring bill templates, Monthly Breakdown Drawer totals, and UTF-8 CSV export."""
    # Check presets exist including Arnona & Gas / Vaad Bayit
    summary0 = client.get("/api/ledger/summary").json()
    preset_cats = [p["category"] for p in summary0["recurring_bill_presets"]]
    for expected in ("Rent", "Arnona", "Electricity", "Water", "Internet", "Gas / Vaad Bayit", "Date Night / Takeout"):
        assert expected in preset_cats

    # Add starting balance migration (must NOT count toward spending breakdown)
    client.post("/api/ledger/initial-balance", json={"ahead_user": "Tamir", "amount": 500.0, "note": "Old balance"})

    # Log 1 of each breakdown category
    client.post("/api/ledger/transactions", json={
        "description": "Arnona Bi-Monthly ארנונה", "category": "Arnona", "paid_by": "Tamir",
        "total_amount": 900.0, "split_rule": "SHARED_50_50", "source_type": "recurring_bill",
    })
    client.post("/api/ledger/transactions", json={
        "description": "Gas & Vaad Bayit", "category": "Gas / Vaad Bayit", "paid_by": "Mikush",
        "total_amount": 300.0, "split_rule": "SHARED_50_50", "source_type": "recurring_bill",
    })
    client.post("/api/ledger/transactions", json={
        "description": "Wolt Thai Dinner", "category": "Date Night / Takeout", "paid_by": "Tamir",
        "total_amount": 200.0, "split_rule": "SHARED_50_50", "source_type": "manual",
    })
    # Commit supermarket receipt with shared 50/50 + produce MIKUSH_100
    client.post("/api/receipts/commit", json={
        "merchant_name": "שופרסל",
        "receipt_type": "supermarket",
        "paid_by": "Tamir",
        "items": [
            {"raw_name": "עגבניות שרי", "normalized_name": "עגבניות שרי", "net_price": 40.0, "category": "Produce", "is_produce": True, "split_rule": "MIKUSH_100"},
            {"raw_name": "חלב", "normalized_name": "חלב", "net_price": 60.0, "category": "Dairy/Eggs", "is_produce": False, "split_rule": "SHARED_50_50"},
        ],
    })

    # Verify preset autofill picked up last_amount on Arnona & Gas / Vaad Bayit
    summary1 = client.get("/api/ledger/summary").json()
    by_cat = {p["category"]: p for p in summary1["recurring_bill_presets"]}
    assert by_cat["Arnona"]["last_amount"] == 900.0
    assert by_cat["Gas / Vaad Bayit"]["last_amount"] == 300.0

    # Verify breakdown endpoint
    bd = client.get("/api/ledger/breakdown").json()
    assert bd["totals"]["apartment_bills"] == 1200.0
    assert bd["totals"]["date_nights_takeout"] == 200.0
    assert bd["totals"]["shared_groceries"] == 60.0
    assert bd["totals"]["produce_mikush_100"] == 40.0
    assert bd["total_spend"] == 1500.0  # Starting balance excluded!

    # Verify UTF-8 BOM CSV export
    csv_resp = client.get("/api/ledger/export.csv")
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    csv_text = csv_resp.content.decode("utf-8-sig")
    assert "Arnona Bi-Monthly ארנונה" in csv_text
    assert "Gas & Vaad Bayit" in csv_text
    assert "שופרסל" in csv_text


def test_brain_dump_multimodal_audio_upload_and_fallback(client, monkeypatch):
    """Tests MediaRecorder audio/* MIME uploads, Gemini inline audio Part, transcript return, and 503 missing-key fallback signal."""
    from services.gemini_service import normalize_media_mime, parse_brain_dump_with_gemini

    # 1. MIME normalization across browser codecs & mobile extensions
    assert normalize_media_mime("audio/webm;codecs=opus") == "audio/webm"
    assert normalize_media_mime("audio/mp4") == "audio/mp4"
    assert normalize_media_mime("audio/x-m4a") == "audio/mp4"
    assert normalize_media_mime("audio/ogg;codecs=opus") == "audio/ogg"
    assert normalize_media_mime("audio/x-wav") == "audio/wav"
    assert normalize_media_mime("application/octet-stream", "voice-recording.m4a") == "audio/mp4"

    # 2. Missing GEMINI_API_KEY returns 503 GEMINI_API_KEY_MISSING for audio-only uploads (triggering SpeechRecognition fallback on client)
    monkeypatch.setenv("GEMINI_API_KEY", "")
    missing_audio_resp = client.post(
        "/api/brain-dump",
        files={"file": ("voice-recording.webm", b"webm-audio-bytes", "audio/webm;codecs=opus")},
        headers={"X-Apartment-User": "Tamir"},
    )
    assert missing_audio_resp.status_code == 503
    assert missing_audio_resp.json()["error_code"] == "GEMINI_API_KEY_MISSING"

    # 3. Unsupported non-audio/non-image file returns 400 and multipart text-only uses local fallback when key absent
    bad_file_resp = client.post(
        "/api/brain-dump",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers={"X-Apartment-User": "Tamir"},
    )
    assert bad_file_resp.status_code == 400

    mp_text = client.post(
        "/api/brain-dump",
        data={"text": "out of onions"},
        headers={"X-Apartment-User": "Tamir"},
    )
    assert mp_text.status_code == 200
    assert mp_text.json()["parser_mode"] == "local_fallback"
    assert mp_text.json()["transcript"] == "out of onions"
    assert any(it["name"].lower() == "onions" for it in mp_text.json()["added_items"])

    # 4. Audio upload execution (webm / mp4 / ogg / wav) + bilingual transcript extraction
    client.post("/groceries/api/items", json={"name": "חלב", "category": "Dairy/Eggs"})
    captured_calls = []

    def fake_gemini_audio_brain_dump(**kwargs):
        captured_calls.append(kwargs)
        return {
            "transcript": "קניתי חלב ב-12 שקל ונגמר עגבניות שרי",
            "items_to_check_off": [{"name": "חלב", "matched_grocery_id": None}],
            "items_to_add": [{"name": "עגבניות שרי", "amount": 1, "unit": "pack", "category": "Produce"}],
            "expenses_to_log": [
                {"description": "חלב", "amount": 12.0, "category": "Groceries", "paid_by": "Tamir", "split_rule": "SHARED_50_50"}
            ],
            "summary_message": "Transcribed bilingual voice Brain Dump.",
        }

    monkeypatch.setattr("routers.receipts.parse_brain_dump_with_gemini", fake_gemini_audio_brain_dump)

    for filename, raw_mime, expected_mime in [
        ("voice-recording.webm", "audio/webm;codecs=opus", "audio/webm"),
        ("voice-recording.m4a", "audio/mp4", "audio/mp4"),
        ("voice-recording.ogg", "audio/ogg;codecs=opus", "audio/ogg"),
        ("voice-recording.wav", "audio/wav", "audio/wav"),
    ]:
        resp = client.post(
            "/api/brain-dump",
            files={"file": (filename, b"fake-audio-payload", raw_mime)},
            headers={"X-Apartment-User": "Tamir"},
        )
        assert resp.status_code == 200
        assert captured_calls[-1]["audio_bytes"] == b"fake-audio-payload"
        assert captured_calls[-1]["audio_mime_type"] == expected_mime
        assert captured_calls[-1]["image_bytes"] is None

    data = resp.json()
    assert data["transcript"] == "קניתי חלב ב-12 שקל ונגמר עגבניות שרי"
    assert "חלב" in data["checked_off"]
    assert any(it["name"] == "עגבניות שרי" and it["default_split"] == "MIKUSH_100" for it in data["added_items"])
    assert len(data["logged_expenses"]) == 1 and data["logged_expenses"][0]["amount"] == 12.0

    # 5. Direct unit test: parse_brain_dump_with_gemini defaults to gemini-3.8-flash, LOW thinking, fallback gemini-3.5-flash-lite, and passes inline audio Part
    from google.genai import types, errors as genai_errors
    from services.gemini_service import (
        get_gemini_model,
        get_gemini_fallback_model,
        get_gemini_thinking_level,
        parse_receipt_with_gemini,
    )
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_FALLBACK_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_THINKING_LEVEL", raising=False)
    assert get_gemini_model() == "gemini-3.8-flash"
    assert get_gemini_fallback_model() == "gemini-3.5-flash-lite"
    assert get_gemini_thinking_level() == "LOW"

    sent_payloads = []

    class _FakeModels:
        def generate_content(self, model, contents, config):
            sent_payloads.append({"model": model, "contents": contents, "config": config})
            return type("Resp", (), {
                "parsed": None,
                "text": '{"transcript": "bring avocado and milk", "items_to_add": [{"name": "Avocado", "category": "Produce"}], "items_to_check_off": [], "expenses_to_log": [], "summary_message": "Added Avocado"}'
            })()

    monkeypatch.setattr("services.gemini_service._get_gemini_client", lambda: type("Client", (), {"models": _FakeModels()})())
    gem_res = parse_brain_dump_with_gemini(
        text_input=None,
        image_bytes=None,
        mime_type=None,
        active_profile="Tamir",
        active_grocery_items=[],
        audio_bytes=b"abc-mp4-bytes",
        audio_mime_type="audio/mp4",
    )
    assert gem_res["transcript"] == "bring avocado and milk"
    assert gem_res["model_used"] == "gemini-3.8-flash"
    assert gem_res["items_to_add"][0]["default_split"] == "MIKUSH_100"
    assert len(sent_payloads) == 1
    assert sent_payloads[0]["model"] == "gemini-3.8-flash"
    assert sent_payloads[0]["config"].thinking_config.thinking_level == types.ThinkingLevel.LOW
    parts = sent_payloads[0]["contents"]
    assert len(parts) == 2
    assert parts[0].inline_data.mime_type == "audio/mp4"
    assert parts[0].inline_data.data == b"abc-mp4-bytes"

    # 6. High-demand 503 fallback: gemini-3.8-flash 503 UNAVAILABLE -> automatically retries on gemini-3.5-flash-lite with LOW thinking
    fallback_calls = []

    class _OverloadedPrimaryModels:
        def generate_content(self, model, contents, config):
            fallback_calls.append({"model": model, "thinking_level": config.thinking_config.thinking_level})
            if model == "gemini-3.8-flash":
                raise genai_errors.ServerError(
                    503,
                    {"error": {"code": 503, "message": "This model is currently experiencing high demand. Please try again later.", "status": "UNAVAILABLE"}},
                )
            return type("Resp", (), {
                "parsed": None,
                "text": '{"merchant_name": "Shufersal", "receipt_type": "supermarket", "currency": "ILS", "items": [{"raw_name": "חלב 3%", "gross_price": 6.90, "net_price": 6.90}]}'
            })()

    monkeypatch.setattr("services.gemini_service._get_gemini_client", lambda: type("Client", (), {"models": _OverloadedPrimaryModels()})())
    fb_receipt = parse_receipt_with_gemini(b"jpg", "image/jpeg", {}, [])
    assert fb_receipt["model_used"] == "gemini-3.5-flash-lite"
    assert len(fb_receipt["items"]) == 1
    assert [c["model"] for c in fallback_calls] == ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
    assert all(c["thinking_level"] == types.ThinkingLevel.LOW for c in fallback_calls)

    # Also test 503 fallback on parse_brain_dump_with_gemini
    bd_fallback_calls = []

    class _OverloadedBrainDumpModels:
        def generate_content(self, model, contents, config):
            bd_fallback_calls.append({"model": model, "thinking_level": config.thinking_config.thinking_level})
            if model == "gemini-3.8-flash":
                raise genai_errors.ServerError(
                    503,
                    {"error": {"code": 503, "message": "This model is currently experiencing high demand. Please try again later.", "status": "UNAVAILABLE"}},
                )
            return type("Resp", (), {
                "parsed": None,
                "text": '{"transcript": "need milk", "items_to_add": [{"name": "Milk", "category": "Dairy/Eggs"}], "items_to_check_off": [], "expenses_to_log": [], "summary_message": "Added Milk"}'
            })()

    monkeypatch.setattr("services.gemini_service._get_gemini_client", lambda: type("Client", (), {"models": _OverloadedBrainDumpModels()})())
    fb_bd = parse_brain_dump_with_gemini(
        text_input=None,
        image_bytes=None,
        mime_type=None,
        active_profile="Tamir",
        active_grocery_items=[],
        audio_bytes=b"webm-bytes",
        audio_mime_type="audio/webm",
    )
    assert fb_bd["model_used"] == "gemini-3.5-flash-lite"
    assert [c["model"] for c in bd_fallback_calls] == ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
    assert all(c["thinking_level"] == types.ThinkingLevel.LOW for c in bd_fallback_calls)

    # Non-retryable 401/API_KEY_INVALID error fails fast without retrying fallback model
    auth_attempts = []

    class _InvalidKeyModels:
        def generate_content(self, model, contents, config):
            auth_attempts.append(model)
            raise genai_errors.ClientError(
                401,
                {"error": {"code": 401, "message": "API key not valid.", "status": "UNAUTHENTICATED"}},
            )

    monkeypatch.setattr("services.gemini_service._get_gemini_client", lambda: type("Client", (), {"models": _InvalidKeyModels()})())
    try:
        parse_receipt_with_gemini(b"jpg", "image/jpeg", {}, [])
        assert False, "Expected ClientError 401 to propagate immediately"
    except genai_errors.ClientError:
        pass
    assert auth_attempts == ["gemini-3.8-flash"]

    # Override GEMINI_MODEL & GEMINI_THINKING_LEVEL dynamically at runtime
    monkeypatch.setenv("GEMINI_MODEL", "gemini-custom-override")
    monkeypatch.setenv("GEMINI_THINKING_LEVEL", "minimal")
    assert get_gemini_model() == "gemini-custom-override"
    assert get_gemini_thinking_level() == "MINIMAL"

    class _FakeReceiptModels:
        def generate_content(self, model, contents, config):
            sent_payloads.append({"model": model, "contents": contents, "config": config})
            return type("Resp", (), {
                "parsed": None,
                "text": '{"merchant_name": "Shufersal", "receipt_type": "supermarket", "currency": "ILS", "items": []}'
            })()

    monkeypatch.setattr("services.gemini_service._get_gemini_client", lambda: type("Client", (), {"models": _FakeReceiptModels()})())
    parse_receipt_with_gemini(b"jpg", "image/jpeg", {}, [])
    assert sent_payloads[-1]["model"] == "gemini-custom-override"
    assert sent_payloads[-1]["config"].thinking_config.thinking_level == types.ThinkingLevel.MINIMAL

    # 7. iOS Safari camera / HEIC / data-URI base64 receipt upload fallback verification
    captured_receipt_calls = []

    def _fake_parse_receipt_img(image_bytes, mime_type, learned_rules_map, active_grocery_items):
        captured_receipt_calls.append({"image_bytes": image_bytes, "mime_type": mime_type})
        return {
            "merchant_name": "AM:PM",
            "receipt_type": "supermarket",
            "currency": "ILS",
            "items": [{"raw_name": "עגבניות שרי", "gross_price": 12.90, "net_price": 12.90, "is_produce": True, "split_rule": "MIKUSH_100"}],
            "parser_mode": "gemini",
        }

    monkeypatch.setattr("routers.receipts.parse_receipt_with_gemini", _fake_parse_receipt_img)

    # (a) Multipart upload with generic octet-stream and .heic extension normalizes to image/heic
    heic_resp = client.post(
        "/api/receipts/parse",
        files={"file": ("IMG_4021.HEIC", b"fake-heic-bytes", "application/octet-stream")},
        data={"paid_by": "Mikush"},
    )
    assert heic_resp.status_code == 200
    assert captured_receipt_calls[-1]["image_bytes"] == b"fake-heic-bytes"
    assert captured_receipt_calls[-1]["mime_type"] == "image/heic"
    assert heic_resp.json()["paid_by"] == "Mikush"

    # (b) JSON data-URI base64 fallback (used when iOS Safari multipart camera stream yields 0 bytes)
    import base64
    b64_data = "data:image/jpeg;base64," + base64.b64encode(b"ios-camera-jpeg").decode("ascii")
    b64_resp = client.post(
        "/api/receipts/parse",
        json={"image_base64": b64_data, "mime_type": "image/jpg", "paid_by": "Mikush"},
    )
    assert b64_resp.status_code == 200
    assert captured_receipt_calls[-1]["image_bytes"] == b"ios-camera-jpeg"
    assert captured_receipt_calls[-1]["mime_type"] == "image/jpeg"
