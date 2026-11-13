import os
import re
import json
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field

from models.groceries import GROCERY_CATEGORIES
from seed_hebrew_items import (
    classify_grocery_item,
    HEBREW_GROCERY_DICTIONARY,
    normalize_grocery_name,
    _RAW_CATALOG,
    _strip_receipt_clutter,
)

AISLE_TO_GROCERY_CATEGORY: Dict[str, str] = {
    "1_produce": "Produce",
    "2_bakery": "Bakery",
    "3_dairy_eggs": "Dairy/Eggs",
    "4_meat_fish": "Meat/Fish",
    "5_pantry_dry": "Pantry/Dry",
    "6_spices_oils": "Spices/Oils",
    "7_household_cleaning": "Household",
    "8_frozen": "Frozen",
}

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


class GeminiAPIKeyMissingError(Exception):
    """Raised when GEMINI_API_KEY is missing or unconfigured in .env."""


# ===================== PYDANTIC STRUCTURED OUTPUT SCHEMAS =====================
class ParsedReceiptLineItemSchema(BaseModel):
    raw_name: str
    normalized_name: str
    quantity: float = 1.0
    unit: Optional[str] = "pcs"
    unit_price: float = 0.0
    gross_price: float = 0.0
    discount_amount: float = 0.0
    discount_label: Optional[str] = None
    net_price: float = 0.0
    category: str = "Pantry/Dry"
    is_produce: bool = False
    is_deposit: bool = False
    is_discount_row: bool = False
    split_rule: Literal["SHARED_50_50", "MIKUSH_100", "TAMIR_100"] = "SHARED_50_50"
    matched_grocery_id: Optional[int] = None


class ParsedReceiptResponseSchema(BaseModel):
    merchant_name: str = "Supermarket Receipt"
    receipt_type: Literal["supermarket", "wolt", "utility", "other"] = "supermarket"
    receipt_date: Optional[str] = None
    currency: str = "ILS"
    items: List[ParsedReceiptLineItemSchema] = Field(default_factory=list)
    printed_total: Optional[float] = None


class BrainDumpItemToAddSchema(BaseModel):
    name: str
    amount: Optional[float] = None
    unit: Optional[str] = None
    category: str = "Produce"
    for_member: Optional[str] = None


class BrainDumpItemToCheckSchema(BaseModel):
    name: str
    matched_grocery_id: Optional[int] = None


class BrainDumpExpenseSchema(BaseModel):
    description: str
    amount: float
    category: str = "Groceries"
    paid_by: Optional[str] = None
    split_rule: Literal["SHARED_50_50", "MIKUSH_100", "TAMIR_100"] = "SHARED_50_50"


class BrainDumpResponseSchema(BaseModel):
    items_to_add: List[BrainDumpItemToAddSchema] = Field(default_factory=list)
    items_to_check_off: List[BrainDumpItemToCheckSchema] = Field(default_factory=list)
    expenses_to_log: List[BrainDumpExpenseSchema] = Field(default_factory=list)
    summary_message: str = ""


# ===================== BILINGUAL NORMALIZATION & AISLE CLASSIFIER =====================
DISCOUNT_PREFIXES = (
    "מבצע", "הנחה", "הנחת", "זיכוי", "קופון", "הוזלה", "מועדון",
    "discount", "promo", "promotion", "coupon", "sale"
)

DEPOSIT_KEYWORDS = (
    "פיקדון", "פקדון", "דמי פיקדון", "דמי פקדון", "בקבוק פיקדון",
    "bottle deposit", "deposit"
)

# Processed tomato/fruit products or spices that must NOT be flagged as fresh produce
NON_PRODUCE_EXCLUSIONS = (
    "שמן", "oil", "רסק", "paste", "קטשופ", "ketchup", "רוטב", "sauce",
    "מיץ", "juice", "ריבה", "jam", "תבלין", "spice", "כמון", "פפריקה",
    "פלפל שחור", "black pepper", "מלח", "salt", "אבקת", "powder", "מיובש", "dried",
    "קפוא", "frozen", "פסטה", "pasta", "שימור", "canned", "טחינה", "tahini",
    "קפה", "coffee", "תה", "tea", "תה ירוק", "שוקולד", "chocolate", "ממרח", "spread"
)

PRODUCE_KEYWORDS = (
    # Hebrew fresh fruits, vegetables, herbs & berries
    "עגבני", "מלפפון", "גמבה", "פלפל אדום", "פלפל צהוב", "פלפל ירוק", "פלפל חריף",
    "חסה", "אבוקדו", "בצל", "שום", "גזר", "קישוא", "זוקיני", "חציל", "ברוקולי",
    "כרובית", "בטטה", "תפוח אדמה", "תפוא", "תפו\"א", "תפוח", "בננה", "בננות",
    "תות", "תותים", "אוכמניות", "פטל", "לימון", "לימונים", "תפוז", "קלמנטינה",
    "אשכולית", "ענבים", "אבטיח", "מלון", "מנגו", "אפרסק", "נקטרינה", "שזיף",
    "אגס", "קיווי", "רימון", "אננס", "דובדבן", "תאנה", "פומלה", "סלרי",
    "צנון", "צנונית", "סלק", "כרוב", "תרד", "רוקט", "ארוגולה", "קייל",
    "פטרוזיליה", "כוסברה", "שמיר", "נענע", "בזיליקום", "טימין", "רוזמרין",
    "בצל ירוק", "עירית", "כרישה", "פטריות", "שמפיניון", "פורטובלו", "נבטים",
    "ירק", "פירות", "ירקות", "דלעת", "דלורית", "תירס טרי", "קולורבי", "שומר",
    # English fresh fruits, vegetables, herbs & berries
    "tomato", "cherry tomato", "cucumber", "bell pepper", "lettuce", "romaine",
    "avocado", "onion", "garlic", "carrot", "zucchini", "eggplant", "broccoli",
    "cauliflower", "sweet potato", "potato", "apple", "banana", "strawberry",
    "strawberries", "blueberries", "blueberry", "raspberry", "berries", "lemon",
    "lime", "orange", "clementine", "grapefruit", "grapes", "watermelon", "melon",
    "mango", "peach", "nectarine", "plum", "pear", "kiwi", "pomegranate", "pineapple",
    "cherry", "cherries", "celery", "radish", "beet", "cabbage", "spinach",
    "arugula", "rocket", "kale", "parsley", "cilantro", "coriander", "dill",
    "mint", "basil", "thyme", "rosemary", "scallion", "green onion", "leek",
    "mushroom", "mushrooms", "sprouts", "pumpkin", "squash", "fresh herbs"
)

AISLE_KEYWORDS: Dict[str, tuple] = {
    "Produce": PRODUCE_KEYWORDS,
    "Bakery": (
        "bread", "sourdough", "challah", "pita", "baguette", "bun", "buns", "roll",
        "bagel", "croissant", "tortilla", "lavash", "brioche", "bakery",
        "לחם", "חלה", "פיתה", "פיתות", "באגט", "לחמניה", "לחמניות", "בייגל", "קרואסון", "טורטיה"
    ),
    "Dairy/Eggs": (
        "milk", "egg", "eggs", "butter", "cheese", "parmesan", "mozzarella", "cheddar",
        "feta", "yogurt", "cottage", "cream", "sour cream", "ricotta", "labneh",
        "oat milk", "soy milk", "almond milk",
        "חלב", "ביצים", "ביצה", "חמאה", "גבינה", "גבינת", "קוטג", "קוטג'", "יוגורט",
        "שמנת", "פרמזן", "מוצרלה", "בולגרית", "צפתית", "לאבנה", "מעדן", "שוקו"
    ),
    "Meat/Fish": (
        "chicken", "beef", "steak", "salmon", "fish", "tuna", "turkey", "minced",
        "ground beef", "meatballs", "sausage", "shrimp", "fillet", "breast", "shawarma",
        "עוף", "חזה עוף", "פרגית", "בשר", "בקר", "טחון", "סטייק", "סלמון", "דג",
        "טונה", "הודו", "נקניק", "קציצות", "שניצל טרי", "פילה"
    ),
    "Spices/Oils": (
        "olive oil", "canola oil", "sesame oil", "sunflower oil", "coconut oil", "oil",
        "salt", "pepper", "black pepper", "cumin", "paprika", "turmeric", "oregano",
        "cinnamon", "zaatar", "sumac", "chili flakes", "nutmeg", "curry", "spice", "vinegar",
        "שמן זית", "שמן קנולה", "שמן שומשום", "שמן", "מלח", "פלפל שחור", "כמון",
        "פפריקה", "כורכום", "אורגנו", "קינמון", "זעתר", "תבלין", "תבלינים", "חומץ"
    ),
    "Household": (
        "trash bag", "trash bags", "garbage bag", "paper towel", "paper towels",
        "toilet paper", "dish soap", "soap", "detergent", "laundry", "bleach",
        "sponge", "sponges", "foil", "baking paper", "plastic wrap", "napkin",
        "napkins", "cleaner", "wipes", "shampoo", "toothpaste", "deodorant", "tissue",
        "שקיות אשפה", "שקית אשפה", "נייר סופג", "מגבות נייר", "נייר טואלט", "סבון כלים",
        "סבון", "אבקת כביסה", "נוזל כביסה", "מרכך", "אקונומיקה", "ספוג", "סקוץ",
        "נייר אפיה", "ניילון נצמד", "מפיות", "מגבונים", "שמפו", "משחת שיניים"
    ),
    "Frozen": (
        "frozen", "ice cream", "gelato", "sorbet", "frozen peas", "frozen corn",
        "edamame", "frozen pizza", "fries", "waffle", "popsicles", "dumplings",
        "קפוא", "קפואה", "קפואים", "גלידה", "סורבה", "אדממה", "פיצה קפואה",
        "צ'יפס", "ציפס", "לקט קפוא", "אפונה קפואה", "בורקס קפוא", "מלאווח", "ג'חנון"
    ),
    "Pantry/Dry": (
        "pasta", "spaghetti", "penne", "rice", "coffee", "espresso", "tea", "flour",
        "sugar", "oats", "cereal", "granola", "crushed tomatoes", "tomato paste",
        "tahini", "peanut butter", "honey", "jam", "chocolate", "snack", "chips",
        "crackers", "nuts", "beans", "lentils", "chickpeas", "couscous", "quinoa",
        "water", "soda", "cola", "beer", "wine", "juice",
        "פסטה", "ספגטי", "אורז", "קפה", "תה", "קמח", "סוכר", "שיבולת שועל", "דגנים",
        "עגבניות מרוסקות", "רסק עגבניות", "טחינה", "חמאת בוטנים", "דבש", "ריבה",
        "שוקולד", "במבה", "ביסלי", "חטיף", "קרקרים", "אגוזים", "שעועית", "עדשים",
        "חומוס", "קוסקוס", "קינואה", "מים", "סודה", "קולה", "בירה", "יין", "מיץ"
    ),
}

BILINGUAL_ALIASES: List[tuple] = [
    ({"milk", "חלב", "חלב תנובה", "חלב 3%", "חלב טרה", "חלב יוטבתה"}, "milk"),
    ({"egg", "eggs", "ביצים", "ביצה", "ביצי חופש"}, "eggs"),
    ({"bread", "sourdough", "sourdough bread", "challah", "לחם", "לחם מחמצת", "חלה", "לחם אחיד"}, "bread"),
    ({"butter", "חמאה", "חמאה תנובה"}, "butter"),
    ({"coffee", "coffee beans", "קפה", "קפה שחור", "פולי קפה", "קפסולות קפה"}, "coffee"),
    ({"onion", "onions", "בצל", "בצל יבש", "בצל סגול"}, "onions"),
    ({"garlic", "שום", "ראשי שום"}, "garlic"),
    ({"olive oil", "שמן זית"}, "olive oil"),
    ({"tomato", "tomatoes", "cherry tomatoes", "עגבניה", "עגבניות", "עגבניות שרי"}, "tomatoes"),
    ({"cucumber", "cucumbers", "מלפפון", "מלפפונים"}, "cucumber"),
    ({"avocado", "אבוקדו"}, "avocado"),
    ({"banana", "bananas", "בננה", "בננות"}, "bananas"),
    ({"paper towel", "paper towels", "נייר סופג", "מגבות נייר"}, "paper towels"),
    ({"dish soap", "סבון כלים", "נוזל כלים"}, "dish soap"),
    ({"trash bag", "trash bags", "שקיות אשפה", "שקיות זבל"}, "trash bags"),
    ({"toilet paper", "נייר טואלט"}, "toilet paper"),
    ({"cottage", "cottage cheese", "קוטג", "קוטג'"}, "cottage cheese"),
    ({"yogurt", "יוגורט"}, "yogurt"),
    ({"pasta", "spaghetti", "penne", "פסטה", "ספגטי"}, "pasta"),
    ({"salmon", "salmon fillets", "סלמון", "פילה סלמון"}, "salmon"),
]


def _build_seed_catalog_index() -> tuple[Dict[str, dict], List[set]]:
    """Pre-indexes all 350+ bilingual items from seed_hebrew_items for O(1) lookup & alias matching."""
    term_map: Dict[str, dict] = {}
    groups: List[set] = []
    for he_name, en_name, aisle, default_split, days, aliases in _RAW_CATALOG:
        cat_name = AISLE_TO_GROCERY_CATEGORY.get(aisle, "Pantry/Dry")
        terms = {
            normalize_item_key(he_name),
            normalize_item_key(en_name),
            normalize_grocery_name(he_name),
            normalize_grocery_name(en_name),
        }
        for al in aliases:
            terms.add(normalize_item_key(al))
            terms.add(normalize_grocery_name(al))
        terms.discard("")
        entry = {
            "he": he_name,
            "en": en_name,
            "category": cat_name,
            "default_split": default_split,
            "typical_depletion_days": int(days),
            "terms": terms,
        }
        groups.append(terms)
        for t in terms:
            term_map.setdefault(t, entry)
    return term_map, groups


def normalize_item_key(name: str) -> str:
    """Normalizes Hebrew/English item names for LearnedItemRule & Depletion Radar matching."""
    if not name:
        return ""
    cleaned = re.sub(r"\s+", " ", name.strip().lower())
    # Strip trailing quantity/weight tokens e.g. "milk 1l", "חלב 3% 1 ליטר"
    cleaned = re.sub(r"[\"'`´״׳]", "", cleaned)
    return cleaned.strip()


_SEED_TERM_MAP, _SEED_ALIAS_GROUPS = _build_seed_catalog_index()


def _clean_receipt_str(name: str) -> str:
    """Extracts the primary normalized clutter-free string from seed_hebrew_items._strip_receipt_clutter."""
    if not name:
        return ""
    expanded_clean, bare_clean, *_ = _strip_receipt_clutter(name)
    return expanded_clean or bare_clean or ""


def _lookup_seed_entry(name: str) -> Optional[dict]:
    """Returns exact seed catalog entry (ignoring receipt noise/weights/brands) if matched."""
    if not name:
        return None
    expanded_clean, bare_clean, *_ = _strip_receipt_clutter(name)
    candidates = (
        normalize_item_key(name),
        normalize_grocery_name(name),
        normalize_item_key(expanded_clean),
        normalize_grocery_name(expanded_clean),
        normalize_item_key(bare_clean),
        normalize_grocery_name(bare_clean),
    )
    for cand in candidates:
        if cand and cand in _SEED_TERM_MAP:
            return _SEED_TERM_MAP[cand]
    return None


def _canonical_alias_groups(name: str) -> set:
    norm = normalize_item_key(name)
    stripped_str = _clean_receipt_str(name)
    stripped = normalize_item_key(stripped_str)
    groups = {t for t in (norm, stripped, normalize_grocery_name(name), normalize_grocery_name(stripped_str)) if t}

    seed_entry = _lookup_seed_entry(name)
    if seed_entry:
        groups.update(seed_entry["terms"])

    for alias_set, canonical in BILINGUAL_ALIASES:
        for al in alias_set:
            if norm == al or stripped == al or (len(al) >= 3 and (al in norm or (norm and norm in al))):
                groups.add(canonical)
                groups.update(alias_set)
                break
    return groups


def _is_non_produce_excluded(norm: str) -> bool:
    return any(excl in norm for excl in NON_PRODUCE_EXCLUSIONS)


def _lookup_keyword_aisle(norm: str) -> Optional[str]:
    """Matches AISLE_KEYWORDS in priority order so Spices/Oils & Frozen beat Produce."""
    priority_order = (
        "Spices/Oils",
        "Frozen",
        "Household",
        "Dairy/Eggs",
        "Bakery",
        "Meat/Fish",
        "Pantry/Dry",
        "Produce",
    )
    for aisle in priority_order:
        if any(kw in norm for kw in AISLE_KEYWORDS[aisle]):
            return aisle
    return None


def is_produce_item(name: str, category: Optional[str] = None, gemini_flag: bool = False) -> bool:
    """Returns True if item is fresh fruit, vegetable, or herb eligible for MIKUSH_100."""
    norm = normalize_item_key(name)
    if not norm:
        return False

    # Exclude processed sauces, spices, oils, frozen goods
    if _is_non_produce_excluded(norm):
        return False

    # Defer first to seed_hebrew_items (e.g. Garlic/Onion are 1_produce but SHARED_50_50)
    seed_entry = _lookup_seed_entry(name)
    if seed_entry:
        return seed_entry["default_split"] == "MIKUSH_100"

    seed = classify_grocery_item(name)
    if seed["aisle"] != "5_pantry_dry" or normalize_grocery_name(_clean_receipt_str(name)) in HEBREW_GROCERY_DICTIONARY:
        return seed["default_split"] == "MIKUSH_100"

    if any(kw in norm for kw in PRODUCE_KEYWORDS):
        return True

    if gemini_flag and (not category or category == "Produce"):
        return True

    if category == "Produce":
        return True

    return False


def classify_grocery_metadata(
    name: str,
    explicit_category: Optional[str] = None,
    explicit_split: Optional[str] = None,
    prefer_dictionary: bool = False,
) -> dict:
    """
    Deterministically classifies an item using seed_hebrew_items.py first, then bilingual
    keyword heuristics, returning {category, default_split, typical_depletion_days, dict_matched}.
    """
    norm = normalize_item_key(name)
    stripped_norm = normalize_grocery_name(_clean_receipt_str(name))
    seed_entry = _lookup_seed_entry(name)
    seed = classify_grocery_item(name)
    seed_category = AISLE_TO_GROCERY_CATEGORY.get(seed["aisle"], "Pantry/Dry")

    dict_matched = bool(
        seed_entry
        or stripped_norm in HEBREW_GROCERY_DICTIONARY
        or normalize_grocery_name(name) in HEBREW_GROCERY_DICTIONARY
        or seed["aisle"] != "5_pantry_dry"
        or seed["typical_depletion_days"] != 14
    )
    kw_aisle = _lookup_keyword_aisle(norm) if not dict_matched else None

    # Resolve category
    has_non_default_explicit = bool(
        explicit_category and explicit_category in GROCERY_CATEGORIES and explicit_category != "Produce"
    )
    if dict_matched:
        if _is_non_produce_excluded(norm) and seed_category == "Produce":
            auto_category = _lookup_keyword_aisle(norm) or "Pantry/Dry"
        else:
            auto_category = seed_category
        resolved_category = auto_category if (prefer_dictionary or not has_non_default_explicit) else explicit_category
    elif kw_aisle:
        resolved_category = explicit_category if (not prefer_dictionary and has_non_default_explicit) else kw_aisle
    elif explicit_category and explicit_category in GROCERY_CATEGORIES:
        resolved_category = explicit_category
    else:
        resolved_category = "Pantry/Dry"

    # Resolve split rule (never treat non-produce exclusions as MIKUSH_100 automatically)
    if explicit_split in ("SHARED_50_50", "MIKUSH_100", "TAMIR_100"):
        resolved_split = explicit_split
    elif _is_non_produce_excluded(norm):
        resolved_split = "SHARED_50_50"
    elif dict_matched:
        resolved_split = seed["default_split"]
    elif resolved_category == "Produce":
        resolved_split = "MIKUSH_100"
    else:
        resolved_split = "SHARED_50_50"

    typical_days = int(seed["typical_depletion_days"])
    if not dict_matched and resolved_category == "Produce" and typical_days == 14:
        typical_days = 7

    return {
        "category": resolved_category,
        "default_split": resolved_split,
        "typical_depletion_days": typical_days,
        "dict_matched": dict_matched,
    }


def infer_grocery_category(name: str, explicit_category: Optional[str] = None) -> str:
    """Classifies an item into one of the 8 Supermarket Walking-Order categories."""
    return classify_grocery_metadata(name, explicit_category=explicit_category)["category"]


def _is_discount_line(item_dict: dict) -> bool:
    if item_dict.get("is_discount_row"):
        return True
    gross = float(item_dict.get("gross_price") or 0.0)
    net = float(item_dict.get("net_price") or 0.0)
    if gross < 0 or net < 0:
        return True
    name_norm = normalize_item_key(item_dict.get("raw_name") or item_dict.get("name") or "")
    return any(name_norm.startswith(pref) for pref in DISCOUNT_PREFIXES)


def _is_deposit_line(item_dict: dict) -> bool:
    if item_dict.get("is_deposit"):
        return True
    name_norm = normalize_item_key(item_dict.get("raw_name") or item_dict.get("name") or "")
    return any(kw in name_norm for kw in DEPOSIT_KEYWORDS)


def _match_active_grocery_item(item_name: str, norm_name: str, active_grocery_items: List[dict]) -> Optional[dict]:
    if not active_grocery_items:
        return None
    item_groups = _canonical_alias_groups(item_name)
    item_groups.add(norm_name)

    for g in active_grocery_items:
        g_groups = _canonical_alias_groups(g.get("name", ""))
        if item_groups & g_groups:
            return g
        g_norm = normalize_item_key(g.get("name", ""))
        if g_norm and norm_name and (g_norm in norm_name or norm_name in g_norm):
            return g
    return None


def process_and_enrich_receipt_items(
    raw_items: List[dict],
    learned_rules_map: Optional[Dict[str, dict]] = None,
    active_grocery_items: Optional[List[dict]] = None,
) -> List[dict]:
    """
    Applies Israeli supermarket edge cases deterministically:
    1) Attaches next-line store promotions (מבצע / הנחה / negative rows) to the parent item above BEFORE splitting.
    2) Handles weighted produce (שקילה: float quantity * unit_price = gross_price).
    3) Applies LearnedItemRule overrides (highest priority), then Dietary Produce Rule (MIKUSH_100).
    4) Bottle deposits (פיקדון) inherit the split_rule of the beverage line directly above them.
    5) Matches active Grocery List items for auto-crossing off on commit.
    """
    learned_rules_map = learned_rules_map or {}
    active_grocery_items = active_grocery_items or []

    # Pass 1: Collapse orphan next-line discount rows onto parent item above
    collapsed_items: List[dict] = []
    for raw in raw_items:
        item = dict(raw)
        if _is_discount_line(item):
            discount_val = abs(
                float(item.get("discount_amount") or 0.0)
                or float(item.get("net_price") or 0.0)
                or float(item.get("gross_price") or 0.0)
            )
            label = (item.get("discount_label") or item.get("raw_name") or "מבצע").strip()
            if collapsed_items and discount_val > 0:
                parent = collapsed_items[-1]
                parent["discount_amount"] = round(float(parent.get("discount_amount") or 0.0) + discount_val, 2)
                existing_label = parent.get("discount_label")
                parent["discount_label"] = f"{existing_label}, {label}" if existing_label else label
            continue
        collapsed_items.append(item)

    # Pass 2: Normalize pricing (weighted produce & discounts), cross-check LearnedItemRules -> seed_hebrew_items.py
    processed: List[dict] = []
    for idx, item in enumerate(collapsed_items):
        raw_name = (item.get("raw_name") or item.get("name") or "Item").strip()
        norm_name = normalize_item_key(item.get("normalized_name") or raw_name)
        raw_norm = normalize_item_key(raw_name)
        stripped_norm = normalize_item_key(_clean_receipt_str(raw_name))

        qty = float(item.get("quantity") if item.get("quantity") is not None else 1.0)
        unit = item.get("unit") or ("kg" if (qty % 1 != 0) else "pcs")
        unit_price = float(item.get("unit_price") or 0.0)
        gross_price = float(item.get("gross_price") or 0.0)
        discount_amount = abs(float(item.get("discount_amount") or 0.0))
        net_price = float(item.get("net_price") or 0.0)

        # Weighted produce (שקילה) or standard qty * unit_price fallback
        if gross_price <= 0 and unit_price > 0 and qty > 0:
            gross_price = round(qty * unit_price, 2)
        elif gross_price <= 0 and net_price > 0:
            gross_price = round(net_price + discount_amount, 2)
        if unit_price <= 0 and gross_price > 0 and qty > 0:
            unit_price = round(gross_price / qty, 2)

        # Always enforce net_price = max(0, gross_price - discount_amount) BEFORE splitting
        if discount_amount > 0:
            computed_net = round(max(0.0, gross_price - discount_amount), 2)
            # If caller passed gross==net (discount not yet subtracted), subtract it now
            if net_price <= 0 or abs(net_price - gross_price) < 0.01 or abs(net_price - computed_net) > 0.05:
                net_price = computed_net
        else:
            if net_price <= 0:
                net_price = round(gross_price, 2)

        is_deposit = _is_deposit_line(item)
        raw_cat = item.get("category")
        learned_rule = (
            learned_rules_map.get(norm_name)
            or learned_rules_map.get(raw_norm)
            or (learned_rules_map.get(stripped_norm) if stripped_norm else None)
        )

        # Deterministic pre/post check against seed_hebrew_items.py
        seed_meta = classify_grocery_metadata(raw_name, explicit_category=raw_cat, prefer_dictionary=True)
        if not seed_meta["dict_matched"] and item.get("normalized_name"):
            alt_meta = classify_grocery_metadata(
                item["normalized_name"], explicit_category=raw_cat, prefer_dictionary=True
            )
            if alt_meta["dict_matched"]:
                seed_meta = alt_meta

        if is_deposit:
            inferred_cat = "Pantry/Dry"
            is_prod = False
        elif seed_meta["dict_matched"]:
            inferred_cat = seed_meta["category"]
            is_prod = (inferred_cat == "Produce" and seed_meta["default_split"] == "MIKUSH_100")
        else:
            is_prod = is_produce_item(raw_name, raw_cat, bool(item.get("is_produce")))
            if not is_prod and item.get("normalized_name"):
                is_prod = is_produce_item(item["normalized_name"], raw_cat, bool(item.get("is_produce")))
            inferred_cat = "Produce" if is_prod else infer_grocery_category(raw_name, raw_cat)

        if learned_rule and learned_rule.get("category") in GROCERY_CATEGORIES and not seed_meta["dict_matched"]:
            inferred_cat = learned_rule["category"]

        # Split rule priority:
        # 1) Explicit manual user flip (user_flipped=True)
        # 2) LearnedItemRule (exact/stripped match)
        # 3) Bottle deposit (resolved in Pass 3 below)
        # 4) Deterministic seed_hebrew_items.py match (MIKUSH_100 produce vs SHARED_50_50 staples/aromatics)
        # 5) Automatic Dietary Produce Rule -> MIKUSH_100
        # 6) Gemini / default -> SHARED_50_50
        if item.get("user_flipped") and item.get("split_rule") in ("SHARED_50_50", "MIKUSH_100", "TAMIR_100"):
            split_rule = item["split_rule"]
            rule_source = item.get("rule_source") or "manual"
        elif learned_rule:
            split_rule = learned_rule["split_rule"]
            rule_source = "learned"
        elif is_deposit:
            split_rule = item.get("split_rule") or "SHARED_50_50"
            rule_source = "deposit_pending"
        elif seed_meta["dict_matched"]:
            split_rule = seed_meta["default_split"]
            rule_source = "dietary_produce_rule" if split_rule == "MIKUSH_100" else "seed_dictionary"
        elif is_prod:
            split_rule = "MIKUSH_100"
            rule_source = "dietary_produce_rule"
        else:
            candidate_split = item.get("split_rule") or "SHARED_50_50"
            split_rule = candidate_split if candidate_split in ("SHARED_50_50", "MIKUSH_100", "TAMIR_100") else "SHARED_50_50"
            rule_source = item.get("rule_source") or "default"

        matched_grocery = None
        if not is_deposit:
            if item.get("matched_grocery_id"):
                matched_grocery = next(
                    (g for g in active_grocery_items if g["id"] == item["matched_grocery_id"]),
                    None
                )
            if not matched_grocery:
                matched_grocery = _match_active_grocery_item(raw_name, norm_name, active_grocery_items)

        processed.append({
            "index": idx,
            "raw_name": raw_name,
            "normalized_name": norm_name or raw_norm,
            "quantity": round(qty, 3),
            "unit": unit,
            "unit_price": round(unit_price, 2),
            "gross_price": round(gross_price, 2),
            "discount_amount": round(discount_amount, 2),
            "discount_label": item.get("discount_label"),
            "net_price": round(net_price, 2),
            "category": inferred_cat,
            "is_produce": is_prod,
            "is_deposit": is_deposit,
            "split_rule": split_rule,
            "rule_source": rule_source,
            "typical_depletion_days": seed_meta["typical_depletion_days"],
            "user_flipped": bool(item.get("user_flipped", False)),
            "matched_grocery_id": matched_grocery["id"] if matched_grocery else None,
            "matched_grocery_name": matched_grocery["name"] if matched_grocery else None,
        })

    # Pass 3: Bottle deposit (פיקדון) inherits split_rule of the beverage line directly above it
    for idx, item in enumerate(processed):
        if item["is_deposit"] and item["rule_source"] != "learned" and not item["user_flipped"] and idx > 0:
            parent_bev = processed[idx - 1]
            item["split_rule"] = parent_bev["split_rule"]
            item["rule_source"] = "deposit_inherited"

    return processed


def calculate_receipt_totals(items: List[dict], paid_by: str = "Tamir") -> dict:
    """Computes exact asymmetric split shares across SHARED_50_50, MIKUSH_100, and TAMIR_100."""
    shared_total = round(sum(float(i.get("net_price") or 0.0) for i in items if i.get("split_rule") == "SHARED_50_50"), 2)
    mikush_only = round(sum(float(i.get("net_price") or 0.0) for i in items if i.get("split_rule") == "MIKUSH_100"), 2)
    tamir_only = round(sum(float(i.get("net_price") or 0.0) for i in items if i.get("split_rule") == "TAMIR_100"), 2)

    total_amount = round(shared_total + mikush_only + tamir_only, 2)
    half_tamir = round(shared_total / 2.0, 2)
    half_mikush = round(shared_total - half_tamir, 2)

    tamir_final_share = round(half_tamir + tamir_only, 2)
    mikush_final_share = round(half_mikush + mikush_only, 2)

    if paid_by == "Mikush":
        net_impact_label = f"Tamir owes Mikush ₪{tamir_final_share:.2f} for this receipt"
    else:
        net_impact_label = f"Mikush owes Tamir ₪{mikush_final_share:.2f} for this receipt"

    return {
        "total_amount": total_amount,
        "shared_50_50_total": shared_total,
        "mikush_100_total": mikush_only,
        "tamir_100_total": tamir_only,
        "tamir_final_share": tamir_final_share,
        "mikush_final_share": mikush_final_share,
        "paid_by": paid_by,
        "net_impact_label": net_impact_label,
    }


def _get_gemini_client():
    """Lazily initializes the official google-genai client so missing keys never crash boot."""
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key or api_key == "your-gemini-api-key-here":
        raise GeminiAPIKeyMissingError(
            "GEMINI_API_KEY is not configured in .env. Add GEMINI_API_KEY=<your-key> to .env to enable AI scanning and Brain Dump."
        )
    from google import genai
    return genai.Client(api_key=api_key)


def parse_receipt_with_gemini(
    image_bytes: bytes,
    mime_type: str,
    learned_rules_map: Dict[str, dict],
    active_grocery_items: List[dict],
) -> dict:
    """Parses an Israeli supermarket receipt, Wolt order, or utility bill using gemini-2.5-flash."""
    client = _get_gemini_client()
    from google.genai import types

    active_list_hint = json.dumps(
        [{"id": g["id"], "name": g["name"], "category": g["category"]} for g in active_grocery_items],
        ensure_ascii=False
    )
    learned_hint = json.dumps(
        [{"normalized_name": k, "split_rule": v["split_rule"]} for k, v in learned_rules_map.items()],
        ensure_ascii=False
    )

    prompt = f"""
You are an expert Israeli supermarket receipt, Wolt order, and utility bill parser.
Extract every item from the image into the required JSON schema carefully obeying ALL rules below:

1. **Weighted Produce (שקילה):**
   For weighted fruits/vegetables (e.g. "0.645 ק\"ג X 12.90 = 8.32"), set quantity=0.645 (float weight), unit="kg", unit_price=12.90, gross_price=8.32.
2. **Next-Line Store Promotions (מבצע / הנחה / הנחת מועדון):**
   Israeli receipts print discounts on the line immediately BELOW the item (e.g., "מבצע זוגות -4.90" or "הנחה -3.00").
   DO NOT output a separate line item for the discount. Attach the positive discount value (e.g. 4.90) to `discount_amount` on the parent item ABOVE it, write the promo text into `discount_label`, and set `net_price = round(gross_price - discount_amount, 2)`.
3. **Bottle Deposits (פיקדון / דמי פיקדון):**
   If a bottle deposit line appears beneath a beverage, set `is_deposit=true` and inherit the beverage's `split_rule`.
4. **Automatic Dietary Split Rule:**
   Tamir does NOT eat fruits or vegetables.
   - Fresh produce (all fruits, vegetables, fresh herbs, berries, salad greens) MUST have `is_produce=true`, `category="Produce"`, and `split_rule="MIKUSH_100"`.
   - Shared household/food staples (dairy, bread, meat, pantry, spices/oils, cleaning, frozen) default to `split_rule="SHARED_50_50"`.
   - Explicitly personal items default to `TAMIR_100` or `MIKUSH_100`.
5. **Learned Item Rules Override (HIGHEST PRIORITY):**
   {learned_hint}
6. **Israeli Supermarket Abbreviations Pre-Pass Reference:**
   Expand truncated Hebrew store names into clean bilingual names where recognizable (e.g. עגבניות/עגב' = Tomatoes, מלפפון/מלפ' = Cucumber, קוטג' = Cottage Cheese, חלב = Milk, טחינה = Tahini, בצל = Onion, שום = Garlic).
7. **Active Grocery List Matching:**
   If a parsed item matches an item on the active grocery list below (even across Hebrew <-> English), set `matched_grocery_id` to its `id`:
   {active_list_hint}
8. **Allowed Categories:**
   Use ONLY one of: {", ".join(GROCERY_CATEGORIES)}.
"""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type or "image/jpeg"),
            prompt,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ParsedReceiptResponseSchema,
            temperature=0.1,
        ),
    )

    if getattr(response, "parsed", None):
        parsed_obj = response.parsed
        data = parsed_obj.model_dump() if hasattr(parsed_obj, "model_dump") else dict(parsed_obj)
    else:
        data = json.loads(response.text)

    enriched_items = process_and_enrich_receipt_items(
        data.get("items", []),
        learned_rules_map=learned_rules_map,
        active_grocery_items=active_grocery_items,
    )

    return {
        "merchant_name": data.get("merchant_name") or "Supermarket Receipt",
        "receipt_type": data.get("receipt_type") or "supermarket",
        "receipt_date": data.get("receipt_date"),
        "currency": data.get("currency") or "ILS",
        "printed_total": data.get("printed_total"),
        "items": enriched_items,
        "parser_mode": "gemini",
    }


# ===================== OFFLINE DETERMINISTIC RECEIPT & BRAIN DUMP FALLBACKS =====================
_RECEIPT_SUMMARY_TOKENS = (
    "סה\"כ", "סך הכל", "סהכ", "לתשלום", "יתרה לתשלום", "אשראי", "ויזה",
    "ישראכרט", "מסטרקארד", "מזומן", "עודף", "מע\"מ", "לפני מעמ",
    "subtotal", "total", "balance due", "credit card", "visa", "mastercard", "change", "vat",
)

_EXPENSE_CATEGORY_MAP: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Rent", ("rent", "שכירות", "שכר דירה")),
    ("Arnona", ("arnona", "ארנונה", "עירייה")),
    ("Electricity", ("electricity", "electric", "חשמל", "חברת חשמל")),
    ("Water", ("water bill", "water", "מי אביבים", "חשבון מים", "מים")),
    ("Internet", ("internet", "fiber", "wifi", "אינטרנט", "סיבים", "בזק", "פרטנר", "סלקום")),
    ("Gas / Vaad Bayit", ("gas", "vaad", "vaad bayit", "גז", "ועד בית", "ועד")),
    ("Date Night / Takeout", ("wolt", "takeout", "restaurant", "dinner", "date", "מסעדה", "אוכל בחוץ", "וולט", "טייק אווי")),
    ("Groceries", ("groceries", "grocery", "supermarket", "shufersal", "rami levy", "am:pm", "סופר", "שופרסל", "רמי לוי", "קניות")),
)


def parse_receipt_text_locally(
    receipt_text: str,
    learned_rules_map: Optional[Dict[str, dict]] = None,
    active_grocery_items: Optional[List[dict]] = None,
    merchant_name: Optional[str] = None,
    receipt_type: Optional[str] = None,
) -> dict:
    """Offline deterministic receipt text parser powered by LearnedItemRules + seed_hebrew_items."""
    lines = [ln.strip() for ln in (receipt_text or "").splitlines() if ln.strip()]
    raw_items: List[dict] = []
    detected_merchant = (merchant_name or "").strip() or "Supermarket Receipt"
    printed_total: Optional[float] = None

    weight_re = re.compile(
        r"(\d+(?:\.\d+)?)\s*(?:ק\"ג|קג|ק׳ג|kg)?\s*[xX*×@]\s*(\d+(?:\.\d+)?)\s*(?:=\s*(\d+(?:\.\d+)?))?"
    )
    qty_prefix_re = re.compile(r"^(\d+(?:\.\d+)?)\s*[xX*×]\s+(.+)$")
    trailing_price_re = re.compile(r"(-?\s*(?:₪|ש\"ח|שח|ils|nis)?\s*\d+(?:\.\d+)?-?)\s*(?:₪|ש\"ח|שח|ils|nis)?$", re.IGNORECASE)

    for idx, line in enumerate(lines):
        if re.fullmatch(r"[-=*_.#\s]{3,}", line):
            continue

        norm_line = normalize_item_key(line)
        is_discount = any(norm_line.startswith(pref) for pref in DISCOUNT_PREFIXES) or ("הנחת" in norm_line)
        if not is_discount and any(tok in norm_line for tok in _RECEIPT_SUMMARY_TOKENS):
            m_tot = trailing_price_re.search(line)
            if m_tot and ("סה\"כ" in norm_line or "סך הכל" in norm_line or "total" in norm_line):
                num_str = re.sub(r"[^\d.-]", "", m_tot.group(1))
                try:
                    printed_total = abs(float(num_str))
                except ValueError:
                    pass
            continue

        # Treat leading text-only line before items as merchant name
        if idx == 0 and not re.search(r"\d+(?:\.\d+)?", line) and detected_merchant == "Supermarket Receipt":
            detected_merchant = line
            continue

        qty = 1.0
        unit = "pcs"
        unit_price = 0.0
        gross_price = 0.0
        clean_name = line

        m_weight = weight_re.search(clean_name)
        if m_weight:
            qty = float(m_weight.group(1))
            unit = "kg"
            unit_price = float(m_weight.group(2))
            gross_price = float(m_weight.group(3)) if m_weight.group(3) else round(qty * unit_price, 2)
            clean_name = (clean_name[:m_weight.start()] + " " + clean_name[m_weight.end():]).strip()
        else:
            m_price = trailing_price_re.search(clean_name)
            if m_price:
                token = m_price.group(1).strip()
                trailing_minus = token.endswith("-")
                num_clean = re.sub(r"[^\d.-]", "", token.rstrip("-"))
                try:
                    parsed_val = float(num_clean)
                    if trailing_minus:
                        parsed_val = -abs(parsed_val)
                    gross_price = parsed_val
                    clean_name = clean_name[:m_price.start()].strip()
                except ValueError:
                    pass

        m_qty = qty_prefix_re.match(clean_name)
        if m_qty and unit != "kg":
            qty = float(m_qty.group(1))
            clean_name = m_qty.group(2).strip()

        clean_name = re.sub(r"^[\-\*\•\d]+\)\s*", "", clean_name).strip(" -:\t")
        if not clean_name and gross_price == 0:
            continue

        if is_discount or gross_price < 0:
            disc_val = abs(gross_price)
            raw_items.append({
                "raw_name": clean_name or "מבצע",
                "is_discount_row": True,
                "discount_amount": disc_val,
                "discount_label": clean_name or "מבצע",
                "gross_price": -disc_val,
                "net_price": -disc_val,
            })
        else:
            if unit_price <= 0 and qty > 0 and gross_price > 0:
                unit_price = round(gross_price / qty, 2)
            raw_items.append({
                "raw_name": clean_name or line,
                "normalized_name": normalize_item_key(_clean_receipt_str(clean_name or line)),
                "quantity": qty,
                "unit": unit,
                "unit_price": unit_price,
                "gross_price": gross_price,
                "net_price": gross_price,
            })

    enriched_items = process_and_enrich_receipt_items(
        raw_items,
        learned_rules_map=learned_rules_map or {},
        active_grocery_items=active_grocery_items or [],
    )
    return {
        "merchant_name": detected_merchant,
        "receipt_type": receipt_type or "supermarket",
        "receipt_date": None,
        "currency": "ILS",
        "printed_total": printed_total,
        "items": enriched_items,
        "parser_mode": "local_fallback",
    }


def _infer_expense_category(desc: str) -> str:
    norm = normalize_item_key(desc)
    for cat, keywords in _EXPENSE_CATEGORY_MAP:
        if any(kw in norm for kw in keywords):
            return cat
    return "Other"


def _extract_quantity_and_unit(token: str) -> tuple[str, Optional[float], Optional[str]]:
    m = re.match(
        r"^(?:a\s+|an\s+|some\s+)?(\d+(?:\.\d+)?)\s*(kg|g|gr|l|ml|pcs|pack|packs|ק\"ג|קג|גרם|ליטר|יח|חבילות|אריזות)?\s+(.+)$",
        token.strip(),
        flags=re.IGNORECASE,
    )
    if not m:
        return token.strip(), None, None
    amt = float(m.group(1))
    raw_u = (m.group(2) or "").lower()
    unit_map = {
        "kg": "kg", "ק\"ג": "kg", "קג": "kg",
        "g": "g", "gr": "g", "גרם": "g",
        "l": "L", "ליטר": "L", "ml": "ml",
        "pack": "pack", "packs": "pack", "חבילות": "pack", "אריזות": "pack",
        "pcs": "pcs", "יח": "pcs",
    }
    unit = unit_map.get(raw_u, "pcs" if raw_u or amt else None)
    return m.group(3).strip(), amt, unit


def _split_item_tokens(phrase: str) -> List[str]:
    """Splits a phrase like 'milk and eggs' or 'חלב, קוטג' ועגבניות שרי' into individual item names."""
    if not phrase:
        return []
    parts = re.split(r"\s*(?:,|/|&|\band\b|\bוגם\b)\s*", phrase.strip(), flags=re.IGNORECASE)
    tokens: List[str] = []
    for part in parts:
        # Handle Hebrew attached conjunction 'ו' before whitespace-separated words when recognizable
        words = part.strip().split()
        rebuilt: List[str] = []
        for idx, w in enumerate(words):
            clean_w = w.strip(".,!?:;\"'")
            if idx > 0 and clean_w.startswith("ו") and len(clean_w) >= 3:
                without_vav = clean_w[1:]
                # Split if remainder (or remainder + remaining phrase) matches seed dictionary or starts a Hebrew food term
                rest_phrase = " ".join([without_vav] + words[idx + 1:])
                if _lookup_seed_entry(clean_w) is None and (
                    _lookup_seed_entry(rest_phrase) is not None
                    or _lookup_seed_entry(without_vav) is not None
                    or _lookup_keyword_aisle(normalize_item_key(rest_phrase)) is not None
                ):
                    if rebuilt:
                        tokens.append(" ".join(rebuilt))
                        rebuilt = []
                    rebuilt.append(without_vav)
                    continue
            rebuilt.append(w)
        if rebuilt:
            tokens.append(" ".join(rebuilt))
    return [t.strip(" .,-") for t in tokens if t.strip(" .,-")]


def _format_clean_item_name(raw_token: str) -> str:
    seed_entry = _lookup_seed_entry(raw_token)
    if re.search(r"[\u0590-\u05ff]", raw_token):
        return raw_token.strip()
    if seed_entry and seed_entry["en"].lower() == raw_token.strip().lower():
        return seed_entry["en"]
    return raw_token.strip().title()


def parse_brain_dump_locally(
    text_input: str,
    active_profile: str,
    active_grocery_items: List[dict],
) -> dict:
    """Offline regex + seed_hebrew_items parser for Hebrew/English additions, check-offs, and expenses."""
    raw_text = (text_input or "").strip()
    items_to_add: List[dict] = []
    items_to_check_off: List[dict] = []
    expenses_to_log: List[dict] = []

    if not raw_text:
        return {
            "items_to_add": [],
            "items_to_check_off": [],
            "expenses_to_log": [],
            "summary_message": "Nothing to parse.",
            "parser_mode": "local_fallback",
        }

    # Normalize line breaks and split into intent clauses while preserving "milk and eggs for 45"
    clauses = re.split(
        r"(?:[\n;]+|(?<!\d)\.(?!\d)\s+|,\s+(?:(?:and|וגם)\s+)?|\s+(?:and|וגם)\s+(?=(?:log|paid|spent|bought|got|we'?re\s+out|out\s+of|need|add|check|purchased|קניתי|קנינו|צריך|נגמר|שילמתי|הוסף)\b|\d+\s+(?:for|on|על|עבור|ל)\b))",
        raw_text,
        flags=re.IGNORECASE,
    )

    add_prefix_re = re.compile(
        r"^(?:and\s+)?(?:we'?re\s+out\s+of|i'?m\s+out\s+of|out\s+of|need\s+to\s+buy|need|add|get|buy|missing|חסר|נגמר|נגמרו|צריך|צריכים|תוסיף|להוסיף|הוסף)\s+",
        flags=re.IGNORECASE,
    )
    check_prefix_re = re.compile(
        r"^(?:and\s+)?(?:i\s+|we\s+)?(?:bought|got|purchased|picked\s+up|checked\s+off|check\s+off|mark\s+off|קניתי|קנינו|לקחתי|הבאתי|סומן)\s+",
        flags=re.IGNORECASE,
    )
    paid_by_re = re.compile(r"\b(?:paid\s+by|שולם\s+ע\"י|שילם|שילמה)\s+(tamir|mikush|תמיר|מיקוש)\b", flags=re.IGNORECASE)
    for_amount_re = re.compile(r"(?:^|\s)(?:for|ב-?|עבור|בעלות)\s*(?:₪|nis|ils)?\s*(\d+(?:\.\d+)?)\s*(?:₪|ש\"ח|שח|nis|ils)?$", flags=re.IGNORECASE)
    standalone_expense_re = re.compile(
        r"^(?:and\s+)?(?:log|paid|spent|added|add|record|שילמתי|הוצאתי|רשום|להוסיף)?\s*(?:₪|nis|ils)?\s*(\d+(?:\.\d+)?)\s*(?:₪|ש\"ח|שח|nis|ils)?\s+(?:for|on|to|על|עבור|ל)?\s*(.+)$",
        flags=re.IGNORECASE,
    )
    trailing_expense_re = re.compile(
        r"^(?:and\s+)?(?:log|paid|spent|שילמתי)\s+(.+?)\s+(?:for|ב-?|ב)?\s*(?:₪|nis|ils)?\s*(\d+(?:\.\d+)?)\s*(?:₪|ש\"ח|שח|nis|ils)?$",
        flags=re.IGNORECASE,
    )

    for raw_clause in clauses:
        clause = raw_clause.strip(" ,.")
        if not clause:
            continue

        # Detect explicit payer
        paid_by = active_profile
        m_payer = paid_by_re.search(clause)
        if m_payer:
            p_tok = m_payer.group(1).lower()
            paid_by = "Mikush" if p_tok in ("mikush", "מיקוש") else "Tamir"
            clause = (clause[:m_payer.start()] + " " + clause[m_payer.end():]).strip(" ,.")

        # Case 1: Check-off clause ("Bought milk and eggs for 45" / "קניתי חלב ב-12")
        if check_prefix_re.match(clause):
            remainder = check_prefix_re.sub("", clause, count=1).strip()
            exp_amount: Optional[float] = None
            m_amt = for_amount_re.search(remainder)
            if m_amt:
                exp_amount = float(m_amt.group(1))
                remainder = remainder[:m_amt.start()].strip()

            bought_tokens = _split_item_tokens(remainder)
            for tok in bought_tokens:
                clean_tok, _, _ = _extract_quantity_and_unit(tok)
                if not clean_tok:
                    continue
                matched = _match_active_grocery_item(clean_tok, normalize_item_key(clean_tok), active_grocery_items)
                items_to_check_off.append({
                    "name": _format_clean_item_name(clean_tok),
                    "matched_grocery_id": matched["id"] if matched else None,
                })

            if exp_amount and exp_amount > 0:
                desc = ", ".join(_format_clean_item_name(t) for t in bought_tokens) or "Groceries"
                expenses_to_log.append({
                    "description": desc,
                    "amount": exp_amount,
                    "category": "Groceries",
                    "paid_by": paid_by,
                    "split_rule": "SHARED_50_50",
                })
            continue

        # Case 2: Standalone expense ("85 for groceries", "log 320 for electricity", "420 חשמל")
        m_exp = standalone_expense_re.match(clause)
        if m_exp:
            amt = float(m_exp.group(1))
            desc_raw = m_exp.group(2).strip(" ,.")
            # Guard: do NOT misclassify grocery quantity prefixes like "2 kg tomatoes" or "3 avocados"
            # as expenses unless currency symbol/expense verb/for/on/expense keyword is explicitly present!
            has_expense_cue = bool(
                re.search(r"\b(?:for|on|to|על|עבור|log|paid|spent|שילמתי|הוצאתי|₪|ש\"ח|שח|nis|ils)\b", clause, re.IGNORECASE)
                or _infer_expense_category(desc_raw) != "Other"
            )
            if has_expense_cue and amt > 0 and desc_raw:
                cat = _infer_expense_category(desc_raw)
                clean_desc = desc_raw if re.search(r"[\u0590-\u05ff]", desc_raw) else desc_raw.title()
                expenses_to_log.append({
                    "description": clean_desc,
                    "amount": amt,
                    "category": cat,
                    "paid_by": paid_by,
                    "split_rule": "SHARED_50_50",
                })
                continue

        m_texp = trailing_expense_re.match(clause)
        if m_texp:
            desc_raw = m_texp.group(1).strip(" ,.")
            amt = float(m_texp.group(2))
            if amt > 0 and desc_raw:
                cat = _infer_expense_category(desc_raw)
                clean_desc = desc_raw if re.search(r"[\u0590-\u05ff]", desc_raw) else desc_raw.title()
                expenses_to_log.append({
                    "description": clean_desc,
                    "amount": amt,
                    "category": cat,
                    "paid_by": paid_by,
                    "split_rule": "SHARED_50_50",
                })
                continue

        # Case 3: Grocery additions ("we're out of trash bags and garlic", "milk, eggs", "נגמר חלב ועגבניות")
        add_body = add_prefix_re.sub("", clause, count=1).strip()
        for tok in _split_item_tokens(add_body):
            item_name_raw, qty, unit = _extract_quantity_and_unit(tok)
            if not item_name_raw or re.fullmatch(r"\d+(?:\.\d+)?", item_name_raw):
                continue
            meta = classify_grocery_metadata(item_name_raw)
            items_to_add.append({
                "name": _format_clean_item_name(item_name_raw),
                "amount": qty,
                "unit": unit,
                "category": meta["category"],
                "default_split": meta["default_split"],
                "typical_depletion_days": meta["typical_depletion_days"],
                "for_member": None,
            })

    summary_parts = []
    if items_to_add:
        summary_parts.append(f"Added {len(items_to_add)} item(s)")
    if items_to_check_off:
        summary_parts.append(f"Checked off {len(items_to_check_off)} item(s)")
    if expenses_to_log:
        summary_parts.append(f"Logged {len(expenses_to_log)} expense(s)")

    return {
        "items_to_add": items_to_add,
        "items_to_check_off": items_to_check_off,
        "expenses_to_log": expenses_to_log,
        "summary_message": " • ".join(summary_parts) if summary_parts else "Parsed offline.",
        "parser_mode": "local_fallback",
    }


def parse_brain_dump_with_gemini(
    text_input: Optional[str],
    image_bytes: Optional[bytes],
    mime_type: Optional[str],
    active_profile: str,
    active_grocery_items: List[dict],
) -> dict:
    """Parses messy text, voice transcripts, or handwritten shopping list photos into multi-intent actions."""
    client = _get_gemini_client()
    from google.genai import types

    active_list_hint = json.dumps(
        [{"id": g["id"], "name": g["name"], "category": g["category"]} for g in active_grocery_items],
        ensure_ascii=False
    )

    prompt = f"""
You are the AI assistant for Tamir & Mikush's Shared Apartment Hub.
Active user speaking/typing: {active_profile}.
Active unchecked grocery list: {active_list_hint}

Analyze the user's messy text / voice transcript / handwritten shopping list photo and extract all simultaneous intents into JSON:
1. `items_to_add`: Items we are out of or need to buy (e.g. "we're out of trash bags and garlic" -> add Trash Bags [Household], Garlic [Produce]).
   - Assign each item to one of the 8 Supermarket Walking-Order categories: {", ".join(GROCERY_CATEGORIES)}.
2. `items_to_check_off`: Items already bought or mentioned in past tense (e.g. "Bought milk and eggs for 45" -> check off Milk and Eggs).
   - If the item matches one in the active grocery list (even Hebrew <-> English), include its `matched_grocery_id`.
3. `expenses_to_log`: Any spending/bills mentioned (e.g. "Bought milk and eggs for 45" -> amount=45, category="Groceries", description="Milk and eggs", paid_by="{active_profile}", split_rule="SHARED_50_50"; "log 320 for electricity paid by Tamir" -> amount=320, category="Electricity", description="Electricity bill", paid_by="Tamir", split_rule="SHARED_50_50").
   - Default `paid_by` to "{active_profile}" unless the user specifies Tamir or Mikush.
4. `summary_message`: A concise 1-line summary of the actions taken.

User input text: {text_input or "(See attached handwritten list image)"}
"""

    contents: List[Any] = []
    if image_bytes:
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type or "image/jpeg"))
    contents.append(prompt)

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=BrainDumpResponseSchema,
            temperature=0.1,
        ),
    )

    if getattr(response, "parsed", None):
        parsed_obj = response.parsed
        data = parsed_obj.model_dump() if hasattr(parsed_obj, "model_dump") else dict(parsed_obj)
    else:
        data = json.loads(response.text)

    # Normalize categories, default_split, and typical_depletion_days via deterministic classifier
    for it in data.get("items_to_add", []):
        meta = classify_grocery_metadata(it.get("name", ""), explicit_category=it.get("category"))
        it["category"] = meta["category"]
        it["default_split"] = meta["default_split"]
        it["typical_depletion_days"] = meta["typical_depletion_days"]

    data["parser_mode"] = "gemini"
    return data
