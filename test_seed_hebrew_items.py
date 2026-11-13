"""Standalone verification suite for seed_hebrew_items.py."""

import pytest

from seed_hebrew_items import (
    AISLE_CATEGORIES,
    CANONICAL_ITEM_COUNT,
    HEBREW_GROCERY_DICTIONARY,
    SPLIT_VALUES,
    classify_grocery_item,
    normalize_grocery_name,
)


def test_dictionary_coverage_and_schema():
    """Verify 350+ canonical items, 8 aisles, valid split rules, and depletion bounds."""
    assert CANONICAL_ITEM_COUNT >= 350
    assert len(HEBREW_GROCERY_DICTIONARY) >= 350

    seen_aisles = set()
    for key, meta in HEBREW_GROCERY_DICTIONARY.items():
        assert isinstance(key, str) and key
        assert set(meta.keys()) == {"aisle", "default_split", "typical_depletion_days"}
        assert meta["aisle"] in AISLE_CATEGORIES
        assert meta["default_split"] in SPLIT_VALUES
        assert isinstance(meta["typical_depletion_days"], int)
        assert 1 <= meta["typical_depletion_days"] <= 180
        seen_aisles.add(meta["aisle"])

    assert seen_aisles == set(AISLE_CATEGORIES)


def test_required_prompt_depletion_benchmarks():
    """Verify baseline depletion days & dietary split rules called out in spec."""
    milk = classify_grocery_item("תנובה חלב 3%")
    assert milk == {"aisle": "3_dairy_eggs", "default_split": "SHARED_50_50", "typical_depletion_days": 5}

    eggs = classify_grocery_item("ביצים L")
    assert eggs == {"aisle": "3_dairy_eggs", "default_split": "SHARED_50_50", "typical_depletion_days": 10}

    challah = classify_grocery_item("חלה")
    assert challah == {"aisle": "2_bakery", "default_split": "SHARED_50_50", "typical_depletion_days": 7}

    bread = classify_grocery_item("לחם")
    assert bread == {"aisle": "2_bakery", "default_split": "SHARED_50_50", "typical_depletion_days": 7}

    tahini = classify_grocery_item("טחינה גולמית")
    assert tahini == {"aisle": "5_pantry_dry", "default_split": "SHARED_50_50", "typical_depletion_days": 21}

    canola = classify_grocery_item("שמן קנולה")
    assert canola == {"aisle": "6_spices_oils", "default_split": "SHARED_50_50", "typical_depletion_days": 45}

    trash_bags = classify_grocery_item("שקיות אשפה")
    assert trash_bags == {"aisle": "7_household_cleaning", "default_split": "SHARED_50_50", "typical_depletion_days": 30}


# Over 60 realistic Israeli supermarket receipt lines (Hebrew, abbreviations, brands, weights, English)
REALISTIC_RECEIPT_CASES = [
    # Produce (fresh fruits/veggies/berries/greens -> MIKUSH_100; cooking onions/garlic -> SHARED_50_50)
    ("עגבניות שרי 0.645 ק\"ג X 12.90", "1_produce", "MIKUSH_100"),
    ("עגב' שרי תמר 0.420 קג", "1_produce", "MIKUSH_100"),
    ("מלפפון חממה במשקל 0.850 ק\"ג", "1_produce", "MIKUSH_100"),
    ("מלפ' חממה 0.7 קג", "1_produce", "MIKUSH_100"),
    ("פלפל אדום שופרסל 0.65 ק\"ג", "1_produce", "MIKUSH_100"),
    ("גמבה אדומה במשקל 0.550 ק\"ג", "1_produce", "MIKUSH_100"),
    ("אבוקדו האס 2 יח'", "1_produce", "MIKUSH_100"),
    ("תות שדה סלסלה 400 גר'", "1_produce", "MIKUSH_100"),
    ("חסה ערבית שטופה מארז", "1_produce", "MIKUSH_100"),
    ("אוכמניות טריות 125 ג'", "1_produce", "MIKUSH_100"),
    ("תרד טרי שקית 200 גרם", "1_produce", "MIKUSH_100"),
    ("כוסבר' צרור", "1_produce", "MIKUSH_100"),
    ("פטרוזיליה טרייה צרור", "1_produce", "MIKUSH_100"),
    ("תפ\"א אדום 1.5 ק\"ג", "1_produce", "MIKUSH_100"),
    ("בננה 1.120 ק\"ג X 6.90", "1_produce", "MIKUSH_100"),
    ("ענבים ירוקים ללא חרצנים 0.9 ק\"ג", "1_produce", "MIKUSH_100"),
    ("לימון במשקל 0.320 ק\"ג", "1_produce", "MIKUSH_100"),
    ("בצל ירוק צרור", "1_produce", "MIKUSH_100"),
    ("בצל יבש שקית 1 ק\"ג", "1_produce", "SHARED_50_50"),
    ("בצל סגול 0.45 ק\"ג", "1_produce", "SHARED_50_50"),
    ("שום טרי רשת 4 יח'", "1_produce", "SHARED_50_50"),
    ("ג'ינג'ר טרי 0.150 ק\"ג", "1_produce", "SHARED_50_50"),

    # Bakery
    ("חלה מתוקה מאפייה 500 ג'", "2_bakery", "SHARED_50_50"),
    ("אנג'ל לחם פרוס אחיד 750 ג'", "2_bakery", "SHARED_50_50"),
    ("פיתות 10 יח' מאפיית ברמן", "2_bakery", "SHARED_50_50"),
    ("בגט צרפתי חם", "2_bakery", "SHARED_50_50"),
    ("טורטיות 8 יח' 320 ג'", "2_bakery", "SHARED_50_50"),
    ("לחמניות המבורגר 6 יח'", "2_bakery", "SHARED_50_50"),
    ("עוגת שמרים שוקולד 550 ג'", "2_bakery", "SHARED_50_50"),

    # Dairy & Eggs
    ("תנובה חלב 3% קרטון 1 ל'", "3_dairy_eggs", "SHARED_50_50"),
    ("חלב טרה 1% 1 ליטר", "3_dairy_eggs", "SHARED_50_50"),
    ("קוטג' 5% שטראוס 250 ג'", "3_dairy_eggs", "SHARED_50_50"),
    ("גבינה לבנה תנובה 5% 500 ג'", "3_dairy_eggs", "SHARED_50_50"),
    ("גבינ\"צ עמק 28% 200 ג'", "3_dairy_eggs", "SHARED_50_50"),
    ("ביצים L 12 יח' משק", "3_dairy_eggs", "SHARED_50_50"),
    ("שמנת להקצפה 38% 250 מ\"ל", "3_dairy_eggs", "SHARED_50_50"),
    ("חמאה לורפק 200 ג'", "3_dairy_eggs", "SHARED_50_50"),
    ("יוגורט פרו 200 ג' דנונה", "3_dairy_eggs", "SHARED_50_50"),
    ("אלפרו משקה שיבולת שועל ללא סוכר 1 ליטר", "3_dairy_eggs", "SHARED_50_50"),
    ("שוקו יטבתה בקבוק 1 ל'", "3_dairy_eggs", "SHARED_50_50"),
    ("גבינה בולגרית 5% גד 250 ג'", "3_dairy_eggs", "SHARED_50_50"),
    ("טופו קדיתא 300 ג'", "3_dairy_eggs", "SHARED_50_50"),
    ("יוגורט בטעם תות שטראוס 150 ג'", "3_dairy_eggs", "SHARED_50_50"),

    # Meat & Fish
    ("חזה עוף טרי עוף טוב 1.150 ק\"ג", "4_meat_fish", "SHARED_50_50"),
    ("פרגיות טריות 0.900 ק\"ג", "4_meat_fish", "SHARED_50_50"),
    ("בשר בקר טחון 0.650 ק\"ג", "4_meat_fish", "SHARED_50_50"),
    ("פילה סלמון נורווגי 0.780 ק\"ג", "4_meat_fish", "SHARED_50_50"),
    ("פסטרמה הודו יחיעם 300 ג'", "4_meat_fish", "SHARED_50_50"),
    ("פילה אמנון 0.850 ק\"ג", "4_meat_fish", "SHARED_50_50"),

    # Pantry & Dry
    ("טחינה גולמית בארכה 500 ג'", "5_pantry_dry", "SHARED_50_50"),
    ("אסם במבה 80 גרם מבצע", "5_pantry_dry", "SHARED_50_50"),
    ("אורז בסמטי סוגת 1 ק\"ג", "5_pantry_dry", "SHARED_50_50"),
    ("פסטה ברילה ספגטי 500 ג'", "5_pantry_dry", "SHARED_50_50"),
    ("רסק עגבניות מרוכז יכין 100 ג'", "5_pantry_dry", "SHARED_50_50"),
    ("עגבניות מרוסקות מוטי 400 ג'", "5_pantry_dry", "SHARED_50_50"),
    ("חלב קוקוס 400 מ\"ל", "5_pantry_dry", "SHARED_50_50"),
    ("מלפפון חמוץ במלח בית השיטה 560 ג'", "5_pantry_dry", "SHARED_50_50"),
    ("טונה בשמן ריו מרה 160 ג'", "5_pantry_dry", "SHARED_50_50"),
    ("דגני בוקר כריות תלמה 750 ג'", "5_pantry_dry", "SHARED_50_50"),
    ("שוקולד חלב עלית 100 ג'", "5_pantry_dry", "SHARED_50_50"),
    ("שומשום מלא 200 ג'", "5_pantry_dry", "SHARED_50_50"),
    ("תמרים מג'הול 500 ג'", "5_pantry_dry", "SHARED_50_50"),
    ("קפה שחור עלית 200 ג'", "5_pantry_dry", "SHARED_50_50"),

    # Spices & Oils
    ("שמן קנולה עץ הזית 1 ל'", "6_spices_oils", "SHARED_50_50"),
    ("שמן זית כתית מעולה יד מרדכי 750 מ\"ל", "6_spices_oils", "SHARED_50_50"),
    ("רוטב סויה קיקומן 250 מ\"ל", "6_spices_oils", "SHARED_50_50"),
    ("פפריקה מתוקה 80 ג'", "6_spices_oils", "SHARED_50_50"),
    ("מלח גס 1 ק\"ג", "6_spices_oils", "SHARED_50_50"),
    ("פלפל שחור גרוס 100 ג'", "6_spices_oils", "SHARED_50_50"),
    ("קטשופ היינץ 700 ג'", "6_spices_oils", "SHARED_50_50"),

    # Household & Cleaning
    ("נייר טואלט לילי 32 גלילים", "7_household_cleaning", "SHARED_50_50"),
    ("שקיות אשפה 75X90 סנו סושי 30 יח'", "7_household_cleaning", "SHARED_50_50"),
    ("פיירי נוזל כלים לימון 650 מ\"ל", "7_household_cleaning", "SHARED_50_50"),
    ("טבליות למדיח פיניש 40 יח'", "7_household_cleaning", "SHARED_50_50"),
    ("ג'ל כביסה אריאל 2.5 ל'", "7_household_cleaning", "SHARED_50_50"),
    ("סנו ז'אוול אקונומיקה 2 ל'", "7_household_cleaning", "SHARED_50_50"),
    ("שמפו נגד קשקשים 400 מ\"ל", "7_household_cleaning", "SHARED_50_50"),

    # Frozen
    ("טבעול שניצל תירס קפוא 600 ג'", "8_frozen", "SHARED_50_50"),
    ("תפוגן צ'יפס קפוא 1 ק\"ג", "8_frozen", "SHARED_50_50"),
    ("מעדנות פיצה קפואה 500 ג'", "8_frozen", "SHARED_50_50"),
    ("אפונה קפואה סנפרוסט 800 ג'", "8_frozen", "SHARED_50_50"),
    ("מלאווח 6 יח' 700 ג'", "8_frozen", "SHARED_50_50"),
    ("אדממה קפוא 500 ג'", "8_frozen", "SHARED_50_50"),
    ("קוביות שום דורות 160 ג'", "8_frozen", "SHARED_50_50"),
    ("גלידה שמנת 500 מ\"ל", "8_frozen", "SHARED_50_50"),

    # English inputs
    ("Cherry Tomatoes 500g", "1_produce", "MIKUSH_100"),
    ("Organic Avocado", "1_produce", "MIKUSH_100"),
    ("Fresh Garlic", "1_produce", "SHARED_50_50"),
    ("Red Onion 1kg", "1_produce", "SHARED_50_50"),
    ("Tnuva Milk 3% 1L", "3_dairy_eggs", "SHARED_50_50"),
    ("Shufersal Canola Oil 1L", "6_spices_oils", "SHARED_50_50"),
    ("Trash Bags 30 pack", "7_household_cleaning", "SHARED_50_50"),
    ("Frozen Edamame 500g", "8_frozen", "SHARED_50_50"),
]


@pytest.mark.parametrize("receipt_line,expected_aisle,expected_split", REALISTIC_RECEIPT_CASES)
def test_realistic_israeli_receipt_lines(receipt_line: str, expected_aisle: str, expected_split: str):
    """Verify accurate classification across 85+ realistic receipt lines."""
    res = classify_grocery_item(receipt_line)
    assert res["aisle"] == expected_aisle, f"Line {receipt_line!r} mapped to {res}"
    assert res["default_split"] == expected_split, f"Line {receipt_line!r} split mismatch: {res}"
    assert isinstance(res["typical_depletion_days"], int) and res["typical_depletion_days"] >= 1


def test_disambiguation_and_edge_cases():
    """Verify token-boundary safety, barcode stripping, and empty/unknown resilience."""
    # Barcode prefix & price fragment stripped cleanly
    barcoded = classify_grocery_item("7290004123456 תנובה קוטג' 5% 250 ג' ₪6.90")
    assert barcoded["aisle"] == "3_dairy_eggs"
    assert barcoded["default_split"] == "SHARED_50_50"

    # Normalization utility check
    assert normalize_grocery_name('תפ"א  500  גר\'') == "תפוח אדמה 500 גר'"

    # Typo / near-match tolerance
    typo_avocado = classify_grocery_item("אבקדו")
    assert typo_avocado["aisle"] == "1_produce"
    assert typo_avocado["default_split"] == "MIKUSH_100"

    # Unknown & empty inputs return well-formed defaults without crashing
    for fallback_input in ("", "   ", "פריט כללי לא מזוהה 999"):
        fb = classify_grocery_item(fallback_input)
        assert fb["aisle"] in AISLE_CATEGORIES
        assert fb["default_split"] in SPLIT_VALUES
        assert isinstance(fb["typical_depletion_days"], int) and fb["typical_depletion_days"] > 0
