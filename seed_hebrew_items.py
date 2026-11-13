"""Israeli Supermarket & Household Grocery Dictionary (350+ items).

Standalone normalization, classification, aisle assignment, split rule, and
depletion-interval lookup helper for Israeli supermarket receipts (Hebrew & English).
"""

from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Any

AISLE_CATEGORIES: tuple[str, ...] = (
    "1_produce",
    "2_bakery",
    "3_dairy_eggs",
    "4_meat_fish",
    "5_pantry_dry",
    "6_spices_oils",
    "7_household_cleaning",
    "8_frozen",
)

SPLIT_VALUES: tuple[str, ...] = ("MIKUSH_100", "SHARED_50_50")

# Tuple layout:
# (hebrew_name, english_name, aisle, default_split, typical_depletion_days, aliases)
_CatalogEntry = tuple[str, str, str, str, int, tuple[str, ...]]

_RAW_CATALOG: tuple[_CatalogEntry, ...] = (
    # =========================================================================
    # 1_produce — Fresh Produce, Herbs & Cooking Aromatics (~90 items)
    # =========================================================================
    # Vegetables & Tomatoes / Peppers / Cucumbers (MIKUSH_100)
    ("עגבניה", "tomato", "1_produce", "MIKUSH_100", 5, ("עגבנייה", "עגבניות", "עגבניות חממה", "tomatoes")),
    ("עגבניות שרי", "cherry tomatoes", "1_produce", "MIKUSH_100", 5, ("שרי", "עגבניות שרי תמר", "עגבנית שרי", "cherry tomato")),
    ("עגבניות מגי", "maggie tomatoes", "1_produce", "MIKUSH_100", 6, ("עגבניה אשכולות", "עגבניות אשכול", "vine tomatoes")),
    ("מלפפון", "cucumber", "1_produce", "MIKUSH_100", 5, ("מלפפונים", "cucumbers")),
    ("מלפפון חממה", "greenhouse cucumber", "1_produce", "MIKUSH_100", 5, ("מלפפון בייבי", "baby cucumber", "persian cucumber")),
    ("פלפל אדום", "red bell pepper", "1_produce", "MIKUSH_100", 7, ("גמבה", "גמבה אדומה", "red pepper", "bell pepper")),
    ("פלפל צהוב", "yellow bell pepper", "1_produce", "MIKUSH_100", 7, ("yellow pepper",)),
    ("פלפל כתום", "orange bell pepper", "1_produce", "MIKUSH_100", 7, ("orange pepper",)),
    ("פלפל ירוק", "green bell pepper", "1_produce", "MIKUSH_100", 7, ("green pepper",)),
    ("פלפל חריף", "chili pepper", "1_produce", "MIKUSH_100", 10, ("פלפל ירוק חריף", "פלפל צ'ילי טרי", "jalapeno", "fresh chili")),
    ("אבוקדו", "avocado", "1_produce", "MIKUSH_100", 5, ("אבוקדו האס", "אבוקדו אטינגר", "avocados")),
    ("חציל", "eggplant", "1_produce", "MIKUSH_100", 7, ("חציל בלאדי", "חצילים", "aubergine")),
    ("קישוא", "zucchini", "1_produce", "MIKUSH_100", 7, ("קישואים", "זוקיני", "courgette")),
    ("גזר", "carrot", "1_produce", "MIKUSH_100", 10, ("גזרים", "גזר ארוז", "גזר גמדי", "carrots", "baby carrots")),
    ("בטטה", "sweet potato", "1_produce", "MIKUSH_100", 10, ("בטטות", "sweet potatoes")),
    ("תפוח אדמה", "potato", "1_produce", "MIKUSH_100", 12, ("תפוחי אדמה", "תפוח אדמה אדום", "תפוח אדמה לבן", "potatoes")),
    ("כרוב לבן", "white cabbage", "1_produce", "MIKUSH_100", 12, ("כרוב", "כרוב ירוק", "cabbage")),
    ("כרוב אדום", "red cabbage", "1_produce", "MIKUSH_100", 12, ("כרוב סגול", "purple cabbage")),
    ("כרובית", "cauliflower", "1_produce", "MIKUSH_100", 7, ("כרובית טרייה",)),
    ("ברוקולי", "broccoli", "1_produce", "MIKUSH_100", 7, ("ברוקולי טרי",)),
    ("סלק", "beetroot", "1_produce", "MIKUSH_100", 12, ("סלק אדום", "beets", "beet")),
    ("צנון", "radish", "1_produce", "MIKUSH_100", 10, ("צנונית", "צנוניות", "radishes")),
    ("קולורבי", "kohlrabi", "1_produce", "MIKUSH_100", 10, ("קולרבי",)),
    ("סלרי", "celery", "1_produce", "MIKUSH_100", 10, ("גבעולי סלרי", "שורש סלרי", "celery stalks")),
    ("שומר", "fennel", "1_produce", "MIKUSH_100", 10, ("שומר טרי", "fennel bulb")),
    ("דלעת", "pumpkin", "1_produce", "MIKUSH_100", 14, ("דלעת חתוכה",)),
    ("דלורית", "butternut squash", "1_produce", "MIKUSH_100", 14, ("דלוריות",)),
    ("כרישה", "leek", "1_produce", "MIKUSH_100", 10, ("פרסה", "leeks")),
    ("אספרגוס", "asparagus", "1_produce", "MIKUSH_100", 6, ("אספרגוס ירוק",)),
    ("שעועית ירוקה טרייה", "fresh green beans", "1_produce", "MIKUSH_100", 7, ("לוביה", "שעועית ירוקה", "green beans")),
    ("תירס טרי", "fresh corn", "1_produce", "MIKUSH_100", 6, ("קלחי תירס", "corn on the cob")),
    ("פטריות שמפיניון", "champignon mushrooms", "1_produce", "MIKUSH_100", 5, ("פטריות", "שמפיניון", "mushrooms")),
    ("פטריות פורטובלו", "portobello mushrooms", "1_produce", "MIKUSH_100", 5, ("פורטובלו",)),
    ("נבטים", "sprouts", "1_produce", "MIKUSH_100", 5, ("נבטים סיניים", "נבטי אלפלפא", "bean sprouts")),
    ("במיה", "okra", "1_produce", "MIKUSH_100", 7, ("במיה טרייה",)),
    ("ארטישוק", "artichoke", "1_produce", "MIKUSH_100", 10, ("ארטישוק ירושלמי",)),
    ("לפת", "turnip", "1_produce", "MIKUSH_100", 12, ("שורש פטרוזיליה", "parsnip")),

    # Leafy Greens & Fresh Culinary Herbs (MIKUSH_100)
    ("חסה", "lettuce", "1_produce", "MIKUSH_100", 5, ("חסה ערבית", "חסה אייסברג", "חסה לליק", "חסה סלנובה", "romaine lettuce")),
    ("עלי בייבי", "baby greens", "1_produce", "MIKUSH_100", 5, ("מיקס בייבי", "לקט סלט", "baby leaves", "spring mix")),
    ("תרד טרי", "fresh spinach", "1_produce", "MIKUSH_100", 5, ("תרד", "עלי תרד", "spinach")),
    ("רוקט", "arugula", "1_produce", "MIKUSH_100", 5, ("ארוגולה", "עלי רוקט", "rocket")),
    ("קייל", "kale", "1_produce", "MIKUSH_100", 6, ("עלי קייל",)),
    ("מנגולד", "swiss chard", "1_produce", "MIKUSH_100", 6, ("עלי סלק",)),
    ("בצל ירוק", "green onion", "1_produce", "MIKUSH_100", 7, ("scallions", "spring onion")),
    ("עירית", "chives", "1_produce", "MIKUSH_100", 7, ("עירית טרייה",)),
    ("פטרוזיליה", "parsley", "1_produce", "MIKUSH_100", 6, ("צרור פטרוזיליה", "עלי פטרוזיליה")),
    ("כוסברה", "cilantro", "1_produce", "MIKUSH_100", 6, ("צרור כוסברה", "coriander")),
    ("שמיר", "dill", "1_produce", "MIKUSH_100", 6, ("צרור שמיר",)),
    ("נענע", "mint", "1_produce", "MIKUSH_100", 6, ("נענע טרייה", "fresh mint")),
    ("בזיליקום טרי", "fresh basil", "1_produce", "MIKUSH_100", 6, ("בזיליקום", "basil")),
    ("רוזמרין טרי", "fresh rosemary", "1_produce", "MIKUSH_100", 10, ("ענפי רוזמרין",)),
    ("טימין טרי", "fresh thyme", "1_produce", "MIKUSH_100", 10, ("קורנית",)),

    # Cooking Aromatics (SHARED_50_50 per dietary cooking-sauce rule)
    ("בצל", "onion", "1_produce", "SHARED_50_50", 10, ("בצל יבש", "בצל לבן", "בצל זהוב", "onions", "yellow onion")),
    ("בצל סגול", "red onion", "1_produce", "SHARED_50_50", 10, ("בצל אדום", "שאלוט", "shallots")),
    ("שום", "garlic", "1_produce", "SHARED_50_50", 14, ("שום טרי", "ראש שום", "רשת שום", "שיני שום", "fresh garlic")),
    ("ג'ינג'ר טרי", "fresh ginger", "1_produce", "SHARED_50_50", 14, ("שורש ג'ינג'ר", "זנגביל טרי", "ginger root")),

    # Berries & Fresh Fruits (MIKUSH_100)
    ("תות שדה", "strawberry", "1_produce", "MIKUSH_100", 4, ("תות", "תותים", "strawberries")),
    ("אוכמניות", "blueberries", "1_produce", "MIKUSH_100", 5, ("אוכמניות טריות", "blueberry")),
    ("פטל", "raspberries", "1_produce", "MIKUSH_100", 4, ("פטל אדום", "פטל שחור", "raspberry", "blackberries")),
    ("בננה", "banana", "1_produce", "MIKUSH_100", 5, ("בננות", "bananas")),
    ("תפוח", "apple", "1_produce", "MIKUSH_100", 7, ("תפוח עץ", "תפוחים", "תפוח חרמון", "תפוח גרני סמית", "תפוח פינק ליידי", "תפוח גאלה", "apples")),
    ("אגס", "pear", "1_produce", "MIKUSH_100", 7, ("אגסים", "אגס ספדונה", "pears")),
    ("תפוז", "orange", "1_produce", "MIKUSH_100", 8, ("תפוזים", "oranges")),
    ("קלמנטינה", "clementine", "1_produce", "MIKUSH_100", 7, ("קלמנטינות", "מנדרינה", "מנדרינות", "mandarin", "tangerine")),
    ("לימון", "lemon", "1_produce", "MIKUSH_100", 10, ("לימונים", "lemons")),
    ("ליים", "lime", "1_produce", "MIKUSH_100", 10, ("ליים טרי", "limes")),
    ("אשכולית", "grapefruit", "1_produce", "MIKUSH_100", 10, ("אשכולית אדומה", "אשכוליות")),
    ("פומלה", "pomelo", "1_produce", "MIKUSH_100", 12, ("פומלית",)),
    ("ענבים", "grapes", "1_produce", "MIKUSH_100", 6, ("ענבים ירוקים", "ענבים שחורים", "ענבים ללא חרצנים", "green grapes")),
    ("אבטיח", "watermelon", "1_produce", "MIKUSH_100", 7, ("אבטיח ללא גרעינים",)),
    ("מלון", "melon", "1_produce", "MIKUSH_100", 7, ("מלון כתום", "cantaloupe", "honeydew")),
    ("מנגו", "mango", "1_produce", "MIKUSH_100", 6, ("מנגו מאיה", "mangoes")),
    ("אננס", "pineapple", "1_produce", "MIKUSH_100", 8, ("אננס טרי",)),
    ("קיווי", "kiwi", "1_produce", "MIKUSH_100", 7, ("קיווי ירוק",)),
    ("אפרסק", "peach", "1_produce", "MIKUSH_100", 6, ("אפרסקים", "אפרסק לבן", "peaches")),
    ("נקטרינה", "nectarine", "1_produce", "MIKUSH_100", 6, ("נקטרינות", "nectarines")),
    ("שזיף", "plum", "1_produce", "MIKUSH_100", 6, ("שזיפים", "plums")),
    ("משמש", "apricot", "1_produce", "MIKUSH_100", 5, ("משמשים", "apricots")),
    ("דובדבנים", "cherries", "1_produce", "MIKUSH_100", 4, ("דובדבן", "cherry")),
    ("רימון", "pomegranate", "1_produce", "MIKUSH_100", 10, ("רימונים", "גרגרי רימון")),
    ("אפרסמון", "persimmon", "1_produce", "MIKUSH_100", 7, ("אפרסמונים",)),
    ("תאנה", "figs", "1_produce", "MIKUSH_100", 4, ("תאנים", "תאנים טריות", "fig")),
    ("פסיפלורה", "passionfruit", "1_produce", "MIKUSH_100", 7, ("פרי התאווה",)),
    ("סברס", "prickly pear", "1_produce", "MIKUSH_100", 6, ("צבר",)),
    ("ליצ'י", "lychee", "1_produce", "MIKUSH_100", 5, ("ליצי",)),
    ("גויאבה", "guava", "1_produce", "MIKUSH_100", 6, ("פפאיה", "papaya")),
    ("חמוציות טריות", "fresh cranberries", "1_produce", "MIKUSH_100", 7, ("קוקוס טרי", "fresh coconut")),
    ("תמר לח טרי", "fresh yellow dates", "1_produce", "MIKUSH_100", 7, ("תמרים צהובים טריים",)),

    # =========================================================================
    # 2_bakery — Breads, Rolls, Pitas & Pastries (~32 items)
    # =========================================================================
    ("לחם", "bread", "2_bakery", "SHARED_50_50", 7, ("לחם אחיד", "לחם פרוס", "sliced bread")),
    ("לחם מלא", "whole wheat bread", "2_bakery", "SHARED_50_50", 7, ("לחם חיטה מלאה", "לחם דגנים")),
    ("לחם מחמצת", "sourdough bread", "2_bakery", "SHARED_50_50", 7, ("מחמצת", "לחם שאור", "sourdough")),
    ("לחם שיפון", "rye bread", "2_bakery", "SHARED_50_50", 7, ("לחם שיפון מלא",)),
    ("לחם כוסמין", "spelt bread", "2_bakery", "SHARED_50_50", 7, ("לחם כוסמין מלא",)),
    ("לחם קל", "light bread", "2_bakery", "SHARED_50_50", 7, ("לחם קלוי", "low calorie bread")),
    ("חלה", "challah", "2_bakery", "SHARED_50_50", 7, ("חלה מתוקה", "חלות", "חלה לשבת", "challah bread")),
    ("חלה קלועה", "braided challah", "2_bakery", "SHARED_50_50", 7, ("חלה עגולה", "חלת שבת")),
    ("פיתות", "pita bread", "2_bakery", "SHARED_50_50", 6, ("פיתה", "פיתות טריות", "pita")),
    ("פיתות כוסמין", "spelt pita", "2_bakery", "SHARED_50_50", 7, ("פיתות מלאות", "whole wheat pita")),
    ("מיני פיתות", "mini pita", "2_bakery", "SHARED_50_50", 6, ("פיתה ביס",)),
    ("לאפה", "laffa", "2_bakery", "SHARED_50_50", 7, ("לאפות", "פיתה עיראקית")),
    ("בגט", "baguette", "2_bakery", "SHARED_50_50", 4, ("באגט", "בגט צרפתי")),
    ("ג'בטה", "ciabatta", "2_bakery", "SHARED_50_50", 5, ("צ'אבטה", "ג'בטות")),
    ("פוקאצ'ה", "focaccia", "2_bakery", "SHARED_50_50", 5, ("פוקצה",)),
    ("לחמניות", "bread rolls", "2_bakery", "SHARED_50_50", 6, ("לחמנייה", "לחמניה", "לחמניות אצבע", "rolls")),
    ("לחמניות המבורגר", "burger buns", "2_bakery", "SHARED_50_50", 10, ("לחמניית המבורגר", "brioche buns")),
    ("לחמניות נקניקיות", "hot dog buns", "2_bakery", "SHARED_50_50", 10, ("לחמניה מתוקה",)),
    ("בייגל", "bagel", "2_bakery", "SHARED_50_50", 7, ("בייגל אמריקאי", "בייגל ירושלמי", "bagels")),
    ("טורטיות", "tortillas", "2_bakery", "SHARED_50_50", 14, ("טורטייה", "טורטיה", "wraps")),
    ("קרואסון", "croissant", "2_bakery", "SHARED_50_50", 5, ("קרואסון חמאה", "קרואסון שוקולד", "croissants")),
    ("רוגעלך", "rugelach", "2_bakery", "SHARED_50_50", 6, ("רוגלך",)),
    ("בורקס מאפייה", "bakery bourekas", "2_bakery", "SHARED_50_50", 5, ("בורקס גבינה", "בורקס תפוח אדמה", "בורקס פינוקים")),
    ("עוגת שמרים", "babka cake", "2_bakery", "SHARED_50_50", 7, ("עוגת שמרים שוקולד", "עוגת שמרים קינמון", "babka")),
    ("עוגת הבית", "loaf cake", "2_bakery", "SHARED_50_50", 10, ("עוגה בחושה", "עוגת תפוזים", "עוגת שיש", "pound cake")),
    ("עוגת שוקולד", "chocolate cake", "2_bakery", "SHARED_50_50", 7, ("עוגת יום הולדת",)),
    ("פנקייקים מוכנים", "ready pancakes", "2_bakery", "SHARED_50_50", 7, ("בלינצ'ס", "וופל בלגי", "waffles")),
    ("סופגניה", "doughnut", "2_bakery", "SHARED_50_50", 4, ("סופגניות", "דונאטס", "donuts")),
    ("גריסיני", "breadsticks", "2_bakery", "SHARED_50_50", 14, ("מקלות לחם", "מקלות מלוחים")),
    ("קריספיות", "toast crisps", "2_bakery", "SHARED_50_50", 14, ("צנימים", "טוסטים", "melba toast")),
    ("מאפינס", "muffins", "2_bakery", "SHARED_50_50", 7, ("מאפין אוכמניות", "מאפין שוקולד")),
    ("פרעצל", "soft pretzel", "2_bakery", "SHARED_50_50", 5, ("בייגלה רך",)),

    # =========================================================================
    # 3_dairy_eggs — Milk, Plant Milks, Cheeses, Yogurts, Eggs & Tofu (~54 items)
    # =========================================================================
    ("חלב", "milk", "3_dairy_eggs", "SHARED_50_50", 5, ("חלב 3%", "חלב טרי 3%", "תנובה חלב 3%", "חלב בקרטון", "חלב בשקית", "whole milk")),
    ("חלב 1%", "low fat milk 1%", "3_dairy_eggs", "SHARED_50_50", 5, ("חלב 1", "חלב דל שומן", "skim milk")),
    ("חלב דל לקטוז", "lactose free milk", "3_dairy_eggs", "SHARED_50_50", 6, ("חלב נטול לקטוז", "חלב ללא לקטוז")),
    ("חלב מועשר", "enriched milk", "3_dairy_eggs", "SHARED_50_50", 6, ("חלב סידן",)),
    ("חלב שיבולת שועל", "oat milk", "3_dairy_eggs", "SHARED_50_50", 7, ("משקה שיבולת שועל", "שיבולת שועל בריסטה", "oat drink", "oatly")),
    ("חלב סויה", "soy milk", "3_dairy_eggs", "SHARED_50_50", 7, ("משקה סויה", "משקה סויה וניל", "soy drink")),
    ("חלב שקדים", "almond milk", "3_dairy_eggs", "SHARED_50_50", 8, ("משקה שקדים", "almond drink")),
    ("חלב אורז", "rice milk", "3_dairy_eggs", "SHARED_50_50", 8, ("משקה אורז",)),
    ("שוקו", "chocolate milk", "3_dairy_eggs", "SHARED_50_50", 6, ("שוקו בשקית", "שוקו בקבוק", "שוקו יטבתה", "משקה שוקו")),
    ("קפה קר מוכן", "iced coffee bottle", "3_dairy_eggs", "SHARED_50_50", 7, ("אייס קפה", "קפה קר יטבתה", "iced coffee")),
    ("רוויון", "buttermilk", "3_dairy_eggs", "SHARED_50_50", 10, ("אשל", "גיל", "לבן", "kefir", "קפיר")),
    ("קוטג'", "cottage cheese", "3_dairy_eggs", "SHARED_50_50", 6, ("קוטג", "קוטג' 5%", "קוטג' 3%", "קוטג' 9%", "קוטג' תנובה")),
    ("גבינה לבנה", "white soft cheese", "3_dairy_eggs", "SHARED_50_50", 7, ("גבינה לבנה 5%", "גבינה לבנה 9%", "גבינה לבנה 3%", "quark")),
    ("גבינת שמנת", "cream cheese", "3_dairy_eggs", "SHARED_50_50", 12, ("נפוליאון", "סימפוניה", "פילדלפיה", "גבינת שמנת שום שמיר", "גבינת שמנת זיתים")),
    ("גבינה צהובה", "yellow cheese", "3_dairy_eggs", "SHARED_50_50", 10, ("עמק", "עמק 28%", "גבינת עמק", "נועם", "גבינה צהובה פרוסה", "sliced cheese")),
    ("גבינת גאודה", "gouda cheese", "3_dairy_eggs", "SHARED_50_50", 14, ("גאודה", "אדאם", "edam")),
    ("מוצרלה", "mozzarella", "3_dairy_eggs", "SHARED_50_50", 12, ("כדור מוצרלה", "מוצרלה בופאלו", "מוצרלה קשה")),
    ("פתיתי גבינה", "shredded cheese", "3_dairy_eggs", "SHARED_50_50", 14, ("פתיתי מוצרלה", "גבינה מגורדת", "פתיתי פרמזן", "פתיתי עמק")),
    ("פרמזן", "parmesan", "3_dairy_eggs", "SHARED_50_50", 30, ("פרמיג'אנו", "גרנה פדאנו", "parmesan cheese")),
    ("צ'דר", "cheddar cheese", "3_dairy_eggs", "SHARED_50_50", 18, ("גבינת צ'דר", "cheddar")),
    ("גבינה בולגרית", "bulgarian feta cheese", "3_dairy_eggs", "SHARED_50_50", 14, ("בולגרית", "בולגרית 5%", "בולגרית 16%", "בולגרית מעודנת")),
    ("פטה", "feta cheese", "3_dairy_eggs", "SHARED_50_50", 14, ("גבינת פטה", "קוביות פטה")),
    ("גבינה צפתית", "tzfatit cheese", "3_dairy_eggs", "SHARED_50_50", 12, ("צפתית", "צפתית קשה")),
    ("חלומי", "halloumi cheese", "3_dairy_eggs", "SHARED_50_50", 18, ("גבינת חלומי", "halloumi")),
    ("ריקוטה", "ricotta", "3_dairy_eggs", "SHARED_50_50", 12, ("ריקוטה פרסקה",)),
    ("מסקרפונה", "mascarpone", "3_dairy_eggs", "SHARED_50_50", 18, ("גבינת מסקרפונה",)),
    ("לבאנה", "labneh", "3_dairy_eggs", "SHARED_50_50", 10, ("לאבנה", "לבנה 5%", "לבאנה בשמן זית")),
    ("קממבר", "camembert", "3_dairy_eggs", "SHARED_50_50", 18, ("ברי", "גבינת ברי", "brie")),
    ("גבינת עיזים", "goat cheese", "3_dairy_eggs", "SHARED_50_50", 14, ("פרומעז", "גליל עיזים")),
    ("יוגורט טבעי", "plain yogurt", "3_dairy_eggs", "SHARED_50_50", 6, ("יוגורט", "יוגורט ביו", "yogurt")),
    ("יוגורט יווני", "greek yogurt", "3_dairy_eggs", "SHARED_50_50", 6, ("יוגורט יווני 10%", "יוגורט יווני 2%", "יוגורט גריק")),
    ("יוגורט חלבון", "protein yogurt", "3_dairy_eggs", "SHARED_50_50", 6, ("דנונה פרו", "יוגורט פרו", "pro יוגורט", "איירון פרו", "גו יוגורט")),
    ("יוגורט פירות", "fruit yogurt", "3_dairy_eggs", "SHARED_50_50", 6, ("יוגורט תות", "יופלה", "יופלה תות", "מולר", "אקטיביה", "דנונה תות")),
    ("מעדן מילקי", "milky dessert", "3_dairy_eggs", "SHARED_50_50", 7, ("מילקי", "מעדן שוקולד", "דני", "דניאלה", "גמדים", "יולו", "קרלו", "chocolate pudding")),
    ("שמנת חמוצה", "sour cream", "3_dairy_eggs", "SHARED_50_50", 10, ("שמנת חמוצה 15%", "שמנת של פעם", "שמנת חמוצה 27%", "שמנת קלה 9%")),
    ("שמנת מתוקה", "heavy whipping cream", "3_dairy_eggs", "SHARED_50_50", 14, ("שמנת להקצפה 38%", "שמנת להקצפה", "whipping cream")),
    ("שמנת לבישול", "cooking cream", "3_dairy_eggs", "SHARED_50_50", 14, ("שמנת לבישול 15%", "שמנת לבישול 10%")),
    ("חמאה", "butter", "3_dairy_eggs", "SHARED_50_50", 14, ("חמאה הולנדית", "חמאה לורפק", "חמאה מלוחה", "חמאה רכה", "לורפק")),
    ("מרגרינה", "margarine", "3_dairy_eggs", "SHARED_50_50", 30, ("מחמאה", "נטורינה")),
    ("ביצים", "eggs", "3_dairy_eggs", "SHARED_50_50", 10, ("ביצים L", "ביצים M", "ביצים XL", "תבנית ביצים", "ביצים גדולות", "ביצה")),
    ("ביצי חופש", "free range eggs", "3_dairy_eggs", "SHARED_50_50", 10, ("ביצים אורגניות", "ביצי חופש L")),
    ("חלבון ביצה בבקבוק", "liquid egg whites", "3_dairy_eggs", "SHARED_50_50", 10, ("נוזל ביצים", "egg whites")),
    ("טופו", "tofu", "3_dairy_eggs", "SHARED_50_50", 12, ("טופו טבעי", "טופו קשה", "טופו קדיתא", "טופו משי", "טופו מתובל")),
    ("סייטן", "seitan", "3_dairy_eggs", "SHARED_50_50", 14, ("טמפה", "tempeh")),

    # =========================================================================
    # 4_meat_fish — Fresh Poultry, Beef, Deli Meats & Fresh Fish (~36 items)
    # =========================================================================
    ("חזה עוף", "chicken breast", "4_meat_fish", "SHARED_50_50", 7, ("חזה עוף טרי", "פרפר חזה עוף")),
    ("שניצל עוף טרי", "chicken cutlets", "4_meat_fish", "SHARED_50_50", 7, ("שניצלוני עוף", "פילה חזה עוף")),
    ("כרעיים עוף", "chicken quarters", "4_meat_fish", "SHARED_50_50", 7, ("רבעי עוף", "ירכיים עוף", "chicken thighs")),
    ("שוקיים עוף", "chicken drumsticks", "4_meat_fish", "SHARED_50_50", 7, ("פולקע", "שוקי עוף", "drumsticks")),
    ("פרגיות", "boneless chicken thighs", "4_meat_fish", "SHARED_50_50", 7, ("סטייק פרגית", "פרגיות טריות")),
    ("כנפיים עוף", "chicken wings", "4_meat_fish", "SHARED_50_50", 10, ("כנפיים",)),
    ("עוף שלם", "whole chicken", "4_meat_fish", "SHARED_50_50", 10, ("עוף צעיר",)),
    ("עוף טחון", "ground chicken", "4_meat_fish", "SHARED_50_50", 7, ("חזה עוף טחון",)),
    ("הודו טחון", "ground turkey", "4_meat_fish", "SHARED_50_50", 8, ("חזה הודו", "שווארמה הודו")),
    ("בשר טחון", "ground beef", "4_meat_fish", "SHARED_50_50", 7, ("בקר טחון", "בשר בקר טחון טרי", "minced beef")),
    ("אנטריקוט", "ribeye steak", "4_meat_fish", "SHARED_50_50", 14, ("סטייק אנטריקוט", "עין האנטריקוט", "entrecote")),
    ("סינטה", "sirloin steak", "4_meat_fish", "SHARED_50_50", 14, ("סטייק סינטה", "sirloin")),
    ("פילה בקר", "beef tenderloin", "4_meat_fish", "SHARED_50_50", 14, ("פילה מדומה",)),
    ("צלי כתף", "beef chuck roast", "4_meat_fish", "SHARED_50_50", 14, ("כתף בקר", "בשר לצלי", "שייטל", "בשר לגולאש")),
    ("אסאדו", "beef short ribs", "4_meat_fish", "SHARED_50_50", 14, ("קשתית", "שפונדרה", "short ribs")),
    ("אוסובוקו", "beef shank", "4_meat_fish", "SHARED_50_50", 14, ("רגל בקר",)),
    ("קבב", "kebab", "4_meat_fish", "SHARED_50_50", 10, ("קבב רומני", "קבב מזרחי")),
    ("המבורגר טרי", "fresh burger patties", "4_meat_fish", "SHARED_50_50", 10, ("קציצות המבורגר", "קציצות בקר")),
    ("נקניקיות", "sausages", "4_meat_fish", "SHARED_50_50", 12, ("נקניקיות עוף", "נקניקיות בקר", "צ'וריסו", "מרגז", "hot dogs")),
    ("פסטרמה", "pastrami", "4_meat_fish", "SHARED_50_50", 10, ("פסטרמה דבש", "פסטרמה על גחלים", "פסטרמה הודו", "פסטרמה ברביקיו")),
    ("סלמי", "salami", "4_meat_fish", "SHARED_50_50", 14, ("נקניק סלמי", "סלמי איטלקי", "פפרוני")),
    ("קבנוס", "cabanossi", "4_meat_fish", "SHARED_50_50", 14, ("נקניק יבש",)),
    ("סלמון טרי", "fresh salmon", "4_meat_fish", "SHARED_50_50", 7, ("פילה סלמון", "סלמון נורווגי", "salmon fillet")),
    ("סלמון מעושן", "smoked salmon", "4_meat_fish", "SHARED_50_50", 14, ("לקס", "גרבלקס")),
    ("פילה אמנון", "tilapia fillet", "4_meat_fish", "SHARED_50_50", 10, ("אמנון", "דג מושט", "מושט", "tilapia")),
    ("דניס", "sea bream", "4_meat_fish", "SHARED_50_50", 10, ("דג דניס", "פילה דניס")),
    ("לברק", "sea bass", "4_meat_fish", "SHARED_50_50", 10, ("דג לברק", "פילה לברק")),
    ("בורי", "grey mullet", "4_meat_fish", "SHARED_50_50", 10, ("דג בורי",)),
    ("פילה בקלה", "cod fillet", "4_meat_fish", "SHARED_50_50", 12, ("דג קוד", "מרלוזה", "הליבוט")),
    ("טונה אדומה טרייה", "fresh tuna steak", "4_meat_fish", "SHARED_50_50", 10, ("סטייק טונה",)),
    ("נסיכת הנילוס", "nile perch", "4_meat_fish", "SHARED_50_50", 12, ("בורי טרי",)),
    ("קרפיון", "carp", "4_meat_fish", "SHARED_50_50", 14, ("טרוטה", "פורל", "trout")),

    # =========================================================================
    # 5_pantry_dry — Grains, Pasta, Legumes, Canned, Spreads, Coffee/Tea, Snacks, Drinks (~120 items)
    # =========================================================================
    # Rice, Grains & Pasta
    ("אורז בסמטי", "basmati rice", "5_pantry_dry", "SHARED_50_50", 25, ("אורז", "rice")),
    ("אורז יסמין", "jasmine rice", "5_pantry_dry", "SHARED_50_50", 25, ("אורז תאילנדי",)),
    ("אורז פרסי", "persian rice", "5_pantry_dry", "SHARED_50_50", 25, ("אורז לבן",)),
    ("אורז מלא", "brown rice", "5_pantry_dry", "SHARED_50_50", 28, ("אורז עגול", "אורז לריזוטו", "אורז סושי")),
    ("ספגטי", "spaghetti", "5_pantry_dry", "SHARED_50_50", 18, ("פסטה ספגטי", "פסטה")),
    ("פסטה פנה", "penne pasta", "5_pantry_dry", "SHARED_50_50", 18, ("פנה", "פסטה פוזילי", "פוזילי", "פסטה פרפרים", "מקרוני")),
    ("דפי לזניה", "lasagna sheets", "5_pantry_dry", "SHARED_50_50", 30, ("אטריות פטוצ'יני", "פטוצ'יני")),
    ("פתיתים", "israeli couscous", "5_pantry_dry", "SHARED_50_50", 21, ("פתיתים אפויים", "פתיתי קוסקוס", "פתיתים כוכבים")),
    ("קוסקוס", "couscous", "5_pantry_dry", "SHARED_50_50", 21, ("קוסקוס בינוני", "קוסקוס דק", "קוסקוס מלא")),
    ("בורגול", "bulgur", "5_pantry_dry", "SHARED_50_50", 30, ("בורגול דק", "בורגול גס")),
    ("קינואה", "quinoa", "5_pantry_dry", "SHARED_50_50", 28, ("קינואה לבנה", "קינואה אדומה", "קינואה טריקולור")),
    ("כוסמת", "buckwheat", "5_pantry_dry", "SHARED_50_50", 30, ("כוסמת ירוקה", "גריסים", "גריסי פנינה", "barley")),
    ("שיבולת שועל", "rolled oats", "5_pantry_dry", "SHARED_50_50", 21, ("קוואקר", "שיבולת שועל להכנה מהירה", "oats", "oatmeal")),
    ("אטריות ביצים", "egg noodles", "5_pantry_dry", "SHARED_50_50", 25, ("אטריות מרק", "איטריות דקות")),
    ("אטריות אורז", "rice noodles", "5_pantry_dry", "SHARED_50_50", 25, ("נודלס", "אטריות ראמן", "אטריות אודון")),
    ("דפי אורז", "rice paper", "5_pantry_dry", "SHARED_50_50", 30, ("אצות נורי", "nori sheets")),
    ("ניוקי", "gnocchi", "5_pantry_dry", "SHARED_50_50", 21, ("ניוקי תפוחי אדמה",)),
    ("שקדי מרק", "soup croutons", "5_pantry_dry", "SHARED_50_50", 21, ("קרוטונים", "croutons")),
    ("מנה חמה", "instant noodles", "5_pantry_dry", "SHARED_50_50", 14, ("נודלס אינסטנט",)),

    # Flours, Baking & Sugars
    ("קמח לבן", "white flour", "5_pantry_dry", "SHARED_50_50", 40, ("קמח", "קמח חיטה", "flour")),
    ("קמח תופח", "self rising flour", "5_pantry_dry", "SHARED_50_50", 45, ("קמח מלא", "קמח כוסמין")),
    ("קורנפלור", "cornstarch", "5_pantry_dry", "SHARED_50_50", 60, ("עמילן תירס", "קמח תפוחי אדמה", "קמח תירס", "פולנטה")),
    ("פירורי לחם", "breadcrumbs", "5_pantry_dry", "SHARED_50_50", 30, ("פנקו", "פירורי פנקו", "panko")),
    ("סוכר לבן", "white sugar", "5_pantry_dry", "SHARED_50_50", 45, ("סוכר", "sugar")),
    ("סוכר חום", "brown sugar", "5_pantry_dry", "SHARED_50_50", 45, ("סוכר דמררה", "אבקת סוכר", "סטיביה", "ממתיק")),
    ("סוכר וניל", "vanilla sugar", "5_pantry_dry", "SHARED_50_50", 60, ("תמצית וניל", "vanilla extract")),
    ("אבקת אפייה", "baking powder", "5_pantry_dry", "SHARED_50_50", 60, ("סודה לשתייה", "baking soda")),
    ("שמרים יבשים", "dry yeast", "5_pantry_dry", "SHARED_50_50", 60, ("שמרים אינסטנט",)),
    ("קקאו", "cocoa powder", "5_pantry_dry", "SHARED_50_50", 45, ("אבקת קקאו", "שוקולית", "שוקולד צ'יפס", "chocolate chips")),

    # Legumes & Canned / Jarred Goods
    ("גרגרי חומוס", "chickpeas", "5_pantry_dry", "SHARED_50_50", 25, ("חומוס גרגירים", "חומוס מבושל קופסה", "חומוס משומר")),
    ("שעועית לבנה", "white beans", "5_pantry_dry", "SHARED_50_50", 30, ("שעועית אדומה", "שעועית שחורה", "שעועית ברוטב")),
    ("עדשים כתומות", "red lentils", "5_pantry_dry", "SHARED_50_50", 30, ("עדשים", "עדשים ירוקות", "עדשים שחורות", "lentils")),
    ("רסק עגבניות", "tomato paste", "5_pantry_dry", "SHARED_50_50", 21, ("רסק עגבניות מרוכז", "מחית עגבניות")),
    ("עגבניות מרוסקות", "crushed tomatoes", "5_pantry_dry", "SHARED_50_50", 14, ("עגבניות חתוכות", "פאסאטה", "רוטב עגבניות", "רוטב פסטה", "רוטב פיצה")),
    ("תירס שימורים", "canned corn", "5_pantry_dry", "SHARED_50_50", 18, ("תירס מתוק שימורים", "גרעיני תירס מתוק", "תירס בקופסה")),
    ("אפונה וגזר שימורים", "canned peas and carrots", "5_pantry_dry", "SHARED_50_50", 25, ("אפונה שימורים", "אפונה יבשה")),
    ("מלפפון חמוץ", "pickles", "5_pantry_dry", "SHARED_50_50", 14, ("מלפפונים חמוצים", "מלפפונים במלח", "מלפפונים בחומץ", "חמוצים")),
    ("זיתים ירוקים", "green olives", "5_pantry_dry", "SHARED_50_50", 14, ("זיתים מגולענים", "זיתים סוריים", "olives")),
    ("זיתים שחורים", "black olives", "5_pantry_dry", "SHARED_50_50", 18, ("זיתי קלמטה", "טבעות זיתים", "kalamata olives")),
    ("פלפל קלוי בצנצנת", "roasted peppers jar", "5_pantry_dry", "SHARED_50_50", 25, ("עגבניות מיובשות", "sun dried tomatoes")),
    ("לבבות דקל", "hearts of palm", "5_pantry_dry", "SHARED_50_50", 30, ("פטריות חתוכות שימורים", "לבבות ארטישוק")),
    ("קרם קוקוס", "coconut cream", "5_pantry_dry", "SHARED_50_50", 21, ("חלב קוקוס", "מי קוקוס", "coconut milk")),
    ("טונה בשמן", "canned tuna in oil", "5_pantry_dry", "SHARED_50_50", 14, ("טונה", "טונה במים", "שישיית טונה", "רביעיית טונה", "canned tuna")),
    ("סרדינים", "sardines", "5_pantry_dry", "SHARED_50_50", 30, ("אנשובי", "anchovies")),

    # Spreads, Dips, Honey, Jams & Condiments (Pantry)
    ("טחינה גולמית", "raw tahini", "5_pantry_dry", "SHARED_50_50", 21, ("טחינה", "טחינה משומשום מלא", "tahini")),
    ("ממרח חומוס", "hummus spread", "5_pantry_dry", "SHARED_50_50", 7, ("חומוס אחלה", "חומוס צבר", "סלט חומוס", "טחינה מוכנה", "hummus")),
    ("מטבוחה", "matbucha", "5_pantry_dry", "SHARED_50_50", 10, ("סלט חצילים", "חצילים בטחינה", "חצילים במיונז", "סלט כרוב אדום")),
    ("חמאת בוטנים", "peanut butter", "5_pantry_dry", "SHARED_50_50", 30, ("חמאת בוטנים טבעית", "סקיפי")),
    ("ממרח שקדים", "almond butter", "5_pantry_dry", "SHARED_50_50", 35, ("שקדייה", "שקדיה")),
    ("דבש", "honey", "5_pantry_dry", "SHARED_50_50", 45, ("דבש פרחי בר", "דבש טהור")),
    ("סילאן", "date syrup", "5_pantry_dry", "SHARED_50_50", 40, ("סילאן טבעי", "מייפל", "סירופ מייפל", "maple syrup")),
    ("ממרח שוקולד", "chocolate spread", "5_pantry_dry", "SHARED_50_50", 30, ("נוטלה", "שוקולד השחר", "ממרח לוטוס", "nutella")),
    ("ריבת תות", "strawberry jam", "5_pantry_dry", "SHARED_50_50", 35, ("ריבה", "קונפיטורה", "ריבת משמש", "jam")),
    ("מרק מוכן שקית", "soup mix", "5_pantry_dry", "SHARED_50_50", 30, ("רוטב פסטו", "פסטו", "pesto")),

    # Breakfast Cereals, Coffee & Tea
    ("קורנפלקס", "cornflakes", "5_pantry_dry", "SHARED_50_50", 21, ("דגני בוקר", "כריות", "ברנפלקס", "צ'יריוס", "cereal")),
    ("גרנולה", "granola", "5_pantry_dry", "SHARED_50_50", 21, ("מוזלי",)),
    ("קפה שחור", "turkish coffee", "5_pantry_dry", "SHARED_50_50", 21, ("קפה טורקי", "קפה עלית", "black coffee")),
    ("נס קפה", "instant coffee", "5_pantry_dry", "SHARED_50_50", 30, ("קפה נמס", "טסטרס צ'ויס", "ג'ייקובס", "מגורען")),
    ("קפסולות קפה", "coffee capsules", "5_pantry_dry", "SHARED_50_50", 21, ("פולי קפה", "קפה טחון", "אספרסו", "coffee beans", "nespresso pods")),
    ("תה שחור", "black tea", "5_pantry_dry", "SHARED_50_50", 40, ("תיון", "ויסוצקי", "ארל גריי", "earl grey", "tea bags")),
    ("תה ירוק", "green tea", "5_pantry_dry", "SHARED_50_50", 40, ("תה נענע", "חליטת צמחים", "תה קמומיל", "chamomile tea")),

    # Snacks, Cookies, Chocolate, Nuts & Dried Fruit
    ("פתי בר", "petit beurre biscuits", "5_pantry_dry", "SHARED_50_50", 21, ("ביסקוויטים", "פטיבר")),
    ("עוגיות", "cookies", "5_pantry_dry", "SHARED_50_50", 14, ("עוגיות שוקולד צ'יפס", "אוריאו", "oreo", "לוטוס עוגיות")),
    ("בפלים", "wafers", "5_pantry_dry", "SHARED_50_50", 14, ("וופלים", "ופל", "וופל שוקולד")),
    ("שוקולד מריר", "dark chocolate", "5_pantry_dry", "SHARED_50_50", 14, ("שוקולד חלב", "שוקולד פרה", "שוקולד לבן", "חפיסת שוקולד")),
    ("חטיף אנרגיה", "granola bar", "5_pantry_dry", "SHARED_50_50", 14, ("חטיף חלבון", "חטיף בריאות", "protein bar")),
    ("במבה", "bamba", "5_pantry_dry", "SHARED_50_50", 10, ("במבה אדומה", "במבה נוגט")),
    ("ביסלי", "bissli", "5_pantry_dry", "SHARED_50_50", 14, ("אפרופו", "דובונים", "פופקורן")),
    ("דוריטוס", "doritos", "5_pantry_dry", "SHARED_50_50", 14, ("תפוצ'יפס", "צ'יטוס", "פרינגלס", "חטיף צ'יפס", "potato chips")),
    ("בייגלה", "pretzels", "5_pantry_dry", "SHARED_50_50", 14, ("בייגלה שטוחים", "שמיניות בייגלה")),
    ("קרקרים", "crackers", "5_pantry_dry", "SHARED_50_50", 18, ("פתית", "קרקר זהב")),
    ("פריכיות אורז", "rice cakes", "5_pantry_dry", "SHARED_50_50", 14, ("פריכיות", "פריכיות תירס")),
    ("חלבה", "halva", "5_pantry_dry", "SHARED_50_50", 30, ("חלווה",)),
    ("תמרים מג'הול", "medjool dates", "5_pantry_dry", "SHARED_50_50", 21, ("תמרים", "תמר מג'הול", "מג'הול", "dates")),
    ("צימוקים", "raisins", "5_pantry_dry", "SHARED_50_50", 35, ("חמוציות מיובשות", "חמוציות", "dried cranberries")),
    ("שקדים", "almonds", "5_pantry_dry", "SHARED_50_50", 28, ("שקדים טבעיים", "שקדים מולבנים")),
    ("אגוזי מלך", "walnuts", "5_pantry_dry", "SHARED_50_50", 28, ("אגוזי פקאן", "פקאן", "אגוזי לוז")),
    ("קשיו", "cashews", "5_pantry_dry", "SHARED_50_50", 25, ("אגוזי קשיו",)),
    ("פיסטוק", "pistachios", "5_pantry_dry", "SHARED_50_50", 25, ("פיסטוקים",)),
    ("בוטנים", "peanuts", "5_pantry_dry", "SHARED_50_50", 25, ("בוטנים קלויים", "קבוקים")),
    ("גרעיני חמנייה", "sunflower seeds", "5_pantry_dry", "SHARED_50_50", 30, ("גרעיני דלעת", "גרעינים שחורים", "זרעי צ'יה", "זרעי פשתן", "chia seeds")),
    ("שומשום", "sesame seeds", "5_pantry_dry", "SHARED_50_50", 45, ("שומשום מלא", "שומשום שחור", "קוקוס טחון")),

    # Beverages & Alcohol
    ("מים מינרליים", "mineral water", "5_pantry_dry", "SHARED_50_50", 7, ("שישיית מים", "נביעות", "מי עדן", "עין גדי", "water")),
    ("סודה", "sparkling water", "5_pantry_dry", "SHARED_50_50", 10, ("מי סודה", "שוופס סודה", "קינלי סודה")),
    ("קוקה קולה", "coca cola", "5_pantry_dry", "SHARED_50_50", 10, ("קולה", "קולה זירו", "דיאט קולה", "coke zero")),
    ("ספרייט", "sprite", "5_pantry_dry", "SHARED_50_50", 12, ("פאנטה", "ספרייט זירו", "fanta")),
    ("אייס טי", "iced tea", "5_pantry_dry", "SHARED_50_50", 10, ("פיוז טי", "תה קר", "fuze tea")),
    ("מיץ תפוזים", "orange juice", "5_pantry_dry", "SHARED_50_50", 7, ("מיץ תפוזים סחוט", "פריגת תפוזים")),
    ("מיץ תפוחים", "apple juice", "5_pantry_dry", "SHARED_50_50", 10, ("מיץ ענבים", "תירוש", "לימונדה", "נקטר")),
    ("בירה", "beer", "5_pantry_dry", "SHARED_50_50", 14, ("גולדסטאר", "מכבי", "הייניקן", "קרלסברג", "קורונה")),
    ("יין אדום", "red wine", "5_pantry_dry", "SHARED_50_50", 21, ("יין לבן", "יין רוזה", "קאווה", "wine")),

    # =========================================================================
    # 6_spices_oils — Oils, Vinegars, Cooking Sauces & Dry Spices (~48 items)
    # =========================================================================
    ("שמן קנולה", "canola oil", "6_spices_oils", "SHARED_50_50", 45, ("שמן",)),
    ("שמן זית", "olive oil", "6_spices_oils", "SHARED_50_50", 45, ("שמן זית כתית מעולה", "שמ\"ז")),
    ("שמן חמניות", "sunflower oil", "6_spices_oils", "SHARED_50_50", 45, ("שמן תירס", "שמן סויה")),
    ("שמן שומשום", "sesame oil", "6_spices_oils", "SHARED_50_50", 60, ("שמן שומשום קלוי",)),
    ("שמן קוקוס", "coconut oil", "6_spices_oils", "SHARED_50_50", 60, ("שמן קוקוס אורגני",)),
    ("תרסיס שמן", "cooking oil spray", "6_spices_oils", "SHARED_50_50", 45, ("ספריי שמן", "פאם", "תרסיס שמן זית")),
    ("חומץ", "vinegar", "6_spices_oils", "SHARED_50_50", 60, ("חומץ סינטטי", "חומץ לבן", "חומץ אורז")),
    ("חומץ תפוחים", "apple cider vinegar", "6_spices_oils", "SHARED_50_50", 60, ("חומץ תפוחים טבעי",)),
    ("חומץ בלסמי", "balsamic vinegar", "6_spices_oils", "SHARED_50_50", 60, ("רוטב בלסמי", "בלסמי מצומצם")),
    ("מיץ לימון משומר", "bottled lemon juice", "6_spices_oils", "SHARED_50_50", 40, ("לימון משומר", "תרכיז לימון")),
    ("רוטב סויה", "soy sauce", "6_spices_oils", "SHARED_50_50", 45, ("סויה", "קיקומן", "kikkoman")),
    ("רוטב טריאקי", "teriyaki sauce", "6_spices_oils", "SHARED_50_50", 45, ("טריאקי",)),
    ("רוטב צ'ילי מתוק", "sweet chili sauce", "6_spices_oils", "SHARED_50_50", 45, ("צ'ילי מתוק", "רוטב סרירצ'ה", "סרירצ'ה", "טבסקו", "sriracha")),
    ("קטשופ", "ketchup", "6_spices_oils", "SHARED_50_50", 30, ("קטשופ היינץ", "קטשופ אסם")),
    ("מיונז", "mayonnaise", "6_spices_oils", "SHARED_50_50", 30, ("מיונז הלמנס", "מיונז קל")),
    ("חרדל", "mustard", "6_spices_oils", "SHARED_50_50", 45, ("חרדל דיז'ון", "חרדל גרגירים", "dijon mustard")),
    ("רוטב ברביקיו", "bbq sauce", "6_spices_oils", "SHARED_50_50", 45, ("רוטב שום", "רוטב אלף האיים", "ויניגרט")),
    ("מלח", "salt", "6_spices_oils", "SHARED_50_50", 90, ("מלח דק", "מלח שולחן", "מלח אטלנטי")),
    ("מלח גס", "coarse salt", "6_spices_oils", "SHARED_50_50", 90, ("מלח ים", "מלח הימלאיה", "kosher salt")),
    ("פלפל שחור", "black pepper", "6_spices_oils", "SHARED_50_50", 60, ("פלפל שחור טחון", "פלפל שחור גרוס", "פלפל לבן", "גרגרי פלפל")),
    ("פלפל אנגלי", "allspice", "6_spices_oils", "SHARED_50_50", 90, ("בהרט",)),
    ("פפריקה מתוקה", "sweet paprika", "6_spices_oils", "SHARED_50_50", 60, ("פפריקה", "פפריקה מעושנת", "פפריקה חריפה", "paprika")),
    ("כמון", "cumin", "6_spices_oils", "SHARED_50_50", 60, ("כמון טחון",)),
    ("כורכום", "turmeric", "6_spices_oils", "SHARED_50_50", 60, ("כורכום טחון",)),
    ("אבקת שום", "garlic powder", "6_spices_oils", "SHARED_50_50", 60, ("שום גבישי", "שבבי שום")),
    ("אבקת בצל", "onion powder", "6_spices_oils", "SHARED_50_50", 60, ("שבבי בצל", "בצל מטוגן יבש")),
    ("אורגנו יבש", "dried oregano", "6_spices_oils", "SHARED_50_50", 75, ("בזיליקום יבש", "טימין יבש", "רוזמרין יבש", "פטרוזיליה יבשה")),
    ("זעתר", "zaatar", "6_spices_oils", "SHARED_50_50", 60, ("סומאק", "תבלין זעתר")),
    ("צ'ילי גרוס", "chili flakes", "6_spices_oils", "SHARED_50_50", 75, ("שאטה גרוס", "קאיין")),
    ("קינמון", "cinnamon", "6_spices_oils", "SHARED_50_50", 90, ("קינמון טחון", "מקלות קינמון")),
    ("אגוז מוסקט", "nutmeg", "6_spices_oils", "SHARED_50_50", 90, ("הל", "ציפורן")),
    ("קארי", "curry powder", "6_spices_oils", "SHARED_50_50", 60, ("גאראם מסאלה", "חוואייג'", "חוואייג' למרק", "תבלין גריל עוף", "תבלין שווארמה")),
    ("אבקת מרק", "bouillon powder", "6_spices_oils", "SHARED_50_50", 45, ("אבקת מרק עוף", "אבקת מרק ירקות", "ציר בקר")),
    ("עלי דפנה", "bay leaves", "6_spices_oils", "SHARED_50_50", 90, ("זנגביל טחון", "ג'ינג'ר טחון")),

    # =========================================================================
    # 7_household_cleaning — Paper Goods, Cleaning, Laundry & Toiletries (~62 items)
    # =========================================================================
    ("נייר טואלט", "toilet paper", "7_household_cleaning", "SHARED_50_50", 14, ("נייר טואלט לילי", "מולט", "טואלט")),
    ("מגבות נייר", "paper towels", "7_household_cleaning", "SHARED_50_50", 21, ("נייר סופג", "גליל סופג", "נייר מטבח")),
    ("טישו", "facial tissues", "7_household_cleaning", "SHARED_50_50", 25, ("ממחטות אף", "קלינקס", "tissues")),
    ("מגבונים לחים", "wet wipes", "7_household_cleaning", "SHARED_50_50", 25, ("מגבונים", "מגבוני תינוקות")),
    ("שקיות אשפה", "trash bags", "7_household_cleaning", "SHARED_50_50", 30, ("שקיות זבל", "שקיות לאשפה", "garbage bags")),
    ("שקיות הקפאה", "freezer bags", "7_household_cleaning", "SHARED_50_50", 45, ("שקיות סנדוויץ'", "שקיות אוכל", "שקיות זיפלוק", "ziploc")),
    ("נייר אפייה", "baking paper", "7_household_cleaning", "SHARED_50_50", 45, ("גליל נייר אפייה", "parchment paper")),
    ("נייר כסף", "aluminum foil", "7_household_cleaning", "SHARED_50_50", 45, ("רדיד אלומיניום", "אלומיניום")),
    ("ניילון נצמד", "plastic wrap", "7_household_cleaning", "SHARED_50_50", 45, ("גליל ניילון נצמד", "cling film")),
    ("נוזל כלים", "dish soap", "7_household_cleaning", "SHARED_50_50", 21, ("סבון כלים", "פיירי", "פיירי כלים", "dishwashing liquid")),
    ("טבליות למדיח", "dishwasher tablets", "7_household_cleaning", "SHARED_50_50", 35, ("קפסולות למדיח", "פיניש", "פיירי למדיח", "dishwasher pods")),
    ("מלח למדיח", "dishwasher salt", "7_household_cleaning", "SHARED_50_50", 60, ("נוזל הברקה למדיח", "מבריק למדיח")),
    ("ג'ל כביסה", "laundry detergent", "7_household_cleaning", "SHARED_50_50", 35, ("נוזל כביסה", "אבקת כביסה", "קפסולות כביסה", "טייד", "אריאל", "פרסיל", "מקסימה")),
    ("מרכך כביסה", "fabric softener", "7_household_cleaning", "SHARED_50_50", 35, ("בדין", "סנו מקסימה")),
    ("מסיר כתמים", "stain remover", "7_household_cleaning", "SHARED_50_50", 60, ("וניש קליה", "קליה")),
    ("אקונומיקה", "bleach", "7_household_cleaning", "SHARED_50_50", 45, ("סנו ז'אוול", "ז'אוול", "ג'ל אקונומיקה")),
    ("ספריי חלונות", "glass cleaner", "7_household_cleaning", "SHARED_50_50", 60, ("נוזל חלונות", "סנו קליר", "window cleaner")),
    ("נוזל רצפות", "floor cleaner", "7_household_cleaning", "SHARED_50_50", 35, ("חומר לשטיפת רצפות", "סנו פוליוויקס", "אג'קס")),
    ("מסיר שומנים", "degreaser", "7_household_cleaning", "SHARED_50_50", 60, ("סנט מוריץ", "מנקה תנורים")),
    ("מסיר אבנית", "descaler", "7_household_cleaning", "SHARED_50_50", 60, ("אנטי קאלק", "סנו אנטי קאלק", "דורגול")),
    ("מנקה אסלות", "toilet cleaner", "7_household_cleaning", "SHARED_50_50", 35, ("טבליות לאסלה", "סבון אסלה", "סנובון")),
    ("תרסיס חיטוי", "disinfectant spray", "7_household_cleaning", "SHARED_50_50", 45, ("ספריי ניקוי כללי", "סיף")),
    ("מטליות לחות לניקוי", "cleaning wipes", "7_household_cleaning", "SHARED_50_50", 25, ("מגבוני ניקוי", "מגבונים למשטחים")),
    ("מטליות מיקרופייבר", "microfiber cloths", "7_household_cleaning", "SHARED_50_50", 60, ("מטליות רב פעמיות", "סחבת רצפה")),
    ("סקוץ' לכלים", "dish sponges", "7_household_cleaning", "SHARED_50_50", 21, ("ספוג כלים", "כריות קרצוף", "צמר פלדה", "ספוג הפלא", "ננס")),
    ("כפפות חד פעמיות", "disposable gloves", "7_household_cleaning", "SHARED_50_50", 45, ("כפפות ניטריל", "כפפות ניקוי")),
    ("מטהר אוויר", "air freshener", "7_household_cleaning", "SHARED_50_50", 45, ("מבשם בדים", "מבשם אוויר")),
    ("סבון ידיים", "hand soap", "7_household_cleaning", "SHARED_50_50", 25, ("אל סבון ידיים", "מילוי סבון ידיים")),
    ("סבון רחצה", "body wash", "7_household_cleaning", "SHARED_50_50", 30, ("ג'ל רחצה", "תחליב רחצה", "סבון מוצק")),
    ("שמפו", "shampoo", "7_household_cleaning", "SHARED_50_50", 35, ("שמפו נגד קשקשים", "הד אנד שולדרס", "פנטן")),
    ("מרכך שיער", "hair conditioner", "7_household_cleaning", "SHARED_50_50", 40, ("קונדישנר", "מסיכה לשיער")),
    ("משחת שיניים", "toothpaste", "7_household_cleaning", "SHARED_50_50", 40, ("קולגייט", "אלמקס", "אורל בי")),
    ("מברשת שיניים", "toothbrush", "7_household_cleaning", "SHARED_50_50", 90, ("ראשי מברשת שיניים",)),
    ("מי פה", "mouthwash", "7_household_cleaning", "SHARED_50_50", 45, ("ליסטרין", "חוט דנטלי", "dental floss")),
    ("דאודורנט", "deodorant", "7_household_cleaning", "SHARED_50_50", 45, ("דאודורנט ספריי", "דאודורנט רול און")),
    ("קרם גוף", "body lotion", "7_household_cleaning", "SHARED_50_50", 60, ("קרם ידיים", "קרם פנים", "קרם הגנה", "sunscreen")),
    ("קצף גילוח", "shaving foam", "7_household_cleaning", "SHARED_50_50", 60, ("ג'ל גילוח", "סכיני גילוח", "razor blades")),
    ("מקלות אוזניים", "cotton swabs", "7_household_cleaning", "SHARED_50_50", 60, ("צמרונים", "פדים להסרת איפור", "צמר גפן")),
    ("צלחות חד פעמיות", "paper plates", "7_household_cleaning", "SHARED_50_50", 45, ("חד פעמי", "כוסות חד פעמיות", "כוסות לשתייה חמה", "סכו\"ם חד פעמי")),
    ("מפיות שולחן", "paper napkins", "7_household_cleaning", "SHARED_50_50", 30, ("מפיות נייר", "napkins")),
    ("נרות", "candles", "7_household_cleaning", "SHARED_50_50", 60, ("נרונים", "נרות שבת", "גפרורים", "מצית")),
    ("סוללות", "batteries", "7_household_cleaning", "SHARED_50_50", 90, ("סוללות AA", "סוללות AAA")),
    ("דוחה יתושים", "mosquito repellent", "7_household_cleaning", "SHARED_50_50", 60, ("טבליות נגד יתושים", "קוטל חרקים")),
    ("פלסטרים", "bandages", "7_household_cleaning", "SHARED_50_50", 90, ("אקמול", "אלכוהול לחיטוי")),

    # =========================================================================
    # 8_frozen — Frozen Produce, Dough, Meals, Meat Substitutes & Ice Cream (~34 items)
    # =========================================================================
    ("גלידה", "ice cream", "8_frozen", "SHARED_50_50", 14, ("גלידת שמנת", "בן אנד ג'ריס", "מגנום", "קופסת גלידה")),
    ("ארטיק", "popsicle", "8_frozen", "SHARED_50_50", 14, ("קרטיב", "מארז שלגונים", "שלגונים", "popsicles")),
    ("פיצה קפואה", "frozen pizza", "8_frozen", "SHARED_50_50", 14, ("פיצה מעדנות", "מעדנות פיצה")),
    ("צ'יפס קפוא", "frozen french fries", "8_frozen", "SHARED_50_50", 18, ("טוגנים קפואים", "תפוגן צ'יפס", "french fries")),
    ("שניצל תירס", "corn schnitzel", "8_frozen", "SHARED_50_50", 14, ("שניצל תירס טבעול", "טבעול תירס")),
    ("שניצל ברוקולי", "broccoli schnitzel", "8_frozen", "SHARED_50_50", 18, ("שניצל ירקות", "טבעול ברוקולי", "שניצל תרד")),
    ("שניצלונים קפואים", "frozen chicken nuggets", "8_frozen", "SHARED_50_50", 18, ("נאגטס", "מאמא עוף שניצל", "chicken nuggets")),
    ("בורקס קפוא", "frozen bourekas", "8_frozen", "SHARED_50_50", 21, ("בורקס גבינה קפוא", "בורקס תפוח אדמה קפוא", "בואיקוס קפוא")),
    ("מלאווח", "malawach", "8_frozen", "SHARED_50_50", 21, ("מלאוח",)),
    ("ג'חנון", "jachnun", "8_frozen", "SHARED_50_50", 25, ("גחנון",)),
    ("בצק עלים", "puff pastry", "8_frozen", "SHARED_50_50", 30, ("בצק עלים מרודד", "בצק פילו", "פילו קפוא")),
    ("בצק פיצה קפוא", "frozen pizza dough", "8_frozen", "SHARED_50_50", 25, ("כדורי בצק קפואים",)),
    ("אדממה קפוא", "frozen edamame", "8_frozen", "SHARED_50_50", 21, ("אדממה", "פולי סויה קפואים", "edamame")),
    ("אפונה קפואה", "frozen peas", "8_frozen", "SHARED_50_50", 21, ("אפונה עדינה קפואה", "אפונה וגזר קפוא")),
    ("שעועית ירוקה קפואה", "frozen green beans", "8_frozen", "SHARED_50_50", 21, ("שעועית שלמה קפואה",)),
    ("תירס קפוא", "frozen corn", "8_frozen", "SHARED_50_50", 21, ("תירס מתוק קפוא", "תירס גמדי קפוא")),
    ("ברוקולי קפוא", "frozen broccoli", "8_frozen", "SHARED_50_50", 21, ("כרובית קפואה",)),
    ("תרד קפוא", "frozen spinach", "8_frozen", "SHARED_50_50", 25, ("מדליוני תרד",)),
    ("לקט ירקות קפוא", "frozen mixed vegetables", "8_frozen", "SHARED_50_50", 21, ("לקט סיני", "לקט נורמנדי", "ירקות מוקפצים")),
    ("פירות יער קפואים", "frozen berries", "8_frozen", "SHARED_50_50", 21, ("תות קפוא", "אוכמניות קפואות", "מנגו קפוא", "אסאי קפוא")),
    ("שום כתוש קפוא", "frozen crushed garlic", "8_frozen", "SHARED_50_50", 35, ("קוביות שום", "קוביות שום דורות", "קוביות בצל קפוא", "קוביות בזיליקום")),
    ("סלמון קפוא", "frozen salmon", "8_frozen", "SHARED_50_50", 21, ("פילה דג קפוא", "אמנון קפוא")),
    ("המבורגר קפוא", "frozen burger patties", "8_frozen", "SHARED_50_50", 21, ("קציצות קפואות", "קבב קפוא")),
    ("גיוזה קפואה", "frozen dumplings", "8_frozen", "SHARED_50_50", 25, ("כיסונים קפואים", "רביולי קפוא", "קרפלך", "פלמני")),
    ("לחמניות קפואות", "frozen rolls", "8_frozen", "SHARED_50_50", 21, ("פיתות קפואות", "בייגל קפוא", "ג'חנון לאפייה")),
    ("פלאפל קפוא", "frozen falafel", "8_frozen", "SHARED_50_50", 21, ("קובה קפואה", "סיגרים קפואים", "פסטלים")),
    ("נקניקיות טבעול", "veggie sausages", "8_frozen", "SHARED_50_50", 21, ("המבורגר טבעוני", "תחליף בשר קפוא")),
    ("קוביות קרח", "ice cubes", "8_frozen", "SHARED_50_50", 30, ("שקית קרח",)),
)

# Multi-word Israeli brands/chains stripped cleanly before tokenizing
_RE_MULTI_BRANDS = re.compile(
    r"(?:^|\s)(?:רמי\s+לוי|אושר\s+עד|טירת\s+צבי|עוף\s+טוב|מאמא\s+עוף|"
    r"יד\s+מרדכי|ריו\s+מרה|עץ\s+הזית|בית\s+השיטה|בייגל\s+בייגל|"
    r"משק\s+צוריאל|סנו\s+סושי|טיב\s+טעם|מי\s+עדן|עין\s+גדי)(?=$|\s)",
    re.IGNORECASE,
)

# Single-word Israeli brands/chains that do not collide with food nouns
_BRAND_WORDS: frozenset[str] = frozenset({
    "תנובה", "שטראוס", "אסם", "אוסם", "שופרסל", "ויקטורי", "יוחננוף",
    "יטבתה", "יוטבתה", "טרה", "גד", "צוריאל", "אלפרו", "עלית", "תלמה",
    "יוניליוור", "סנו", "ניקול", "יעקבי", "פיניש", "טייד", "אריאל", "פרסיל",
    "בדין", "לילי", "מולט", "קולגייט", "אקטיביה", "דנונה", "מילקי", "יופלה",
    "בארכה", "אחוה", "הרדוף", "תבואות", "סוגת", "אנגל", "ברמן", "דוידוביץ",
    "זוגלובק", "יחיעם", "דלידג", "סטארקיסט", "ויליגר", "יכין", "מוטי",
    "ברילה", "סנפרוסט", "טבעול", "נביעות", "פריגת", "הלמנס", "היינץ",
    "ויסוצקי", "דורות", "תפוגן", "מעדנות", "מיה", "השחר", "קדיתא", "קיקומן",
    "tnuva", "strauss", "osem", "shufersal", "tara", "gad", "sano", "angel",
    "berman", "alpro", "sunfrost", "tivall", "heinz", "barilla", "fairy",
    "finish", "colgate", "elite", "telma", "yad", "mordechai", "achva",
})

_NOISE_WORDS: frozenset[str] = frozenset({
    "מבצע", "הנחה", "במשקל", "שקילה", "משק", "פרמיום", "פרימיום", "קלאסי",
    "מעולה", "איכותי", "אורגני", "אורגנית", "אורגניים", "מארז", "אריזה",
    "קרטון", "בקבוק", "צנצנת", "פחית", "גביע", "חבילה", "חבילת", "סלסלה",
    "צרור", "רשת", "זוג", "שלישיה", "רביעיה", "שישיה", "שמיניה", "גלילים",
    "יח", "יחידה", "יחידות", "ג", "גר", "גרם", "קג", "מל", "ל", "ליטר", "מג",
    "משווק", "סופר", "שוק", "טבעי", "מועשר", "כתית", "שטופה", "שטוף",
    "מרוכז", "מגורדת",
    "organic", "fresh", "pack", "pcs", "pc", "kg", "gr", "gm", "ml", "liter", "liters",
    "שח", "גדול", "גדולה", "קטן", "קטנה", "בינוני",
})

# Keep these single-letter / size markers only when paired directly with eggs
_SIZE_CODES: frozenset[str] = frozenset({"l", "m", "xl", "xxl", "s"})

# Words that represent strong product bases (should outrank trailing flavor nouns)
_BASE_PRODUCT_WORDS: frozenset[str] = frozenset({
    "יוגורט", "מעדן", "שוקו", "מיץ", "נקטר", "תה", "קפה", "ריבה", "קונפיטורה",
    "גלידה", "ארטיק", "קרטיב", "עוגה", "עוגת", "עוגיות", "חומץ", "רוטב",
    "סבון", "שמפו", "נוזל", "מרכך", "קרם", "ממרח", "שמן", "תרסיס",
    "מלח", "חטיף", "שוקולד", "חלב", "משקה", "קפסולות", "מים", "בירה",
})

# Regex patterns compiled once at import time
_RE_BARCODE = re.compile(r"^\s*\d{6,14}\s+")
_RE_PRICE_FRAG = re.compile(r"(?:₪\s*\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s*(?:₪|ש[\"׳']?ח)|[xX×]\s*\d+(?:[.,]\d+)?)")
_RE_WEIGHT_WITH_NUM = re.compile(
    r"(?:^|[\s,/(])(?:\d+(?:[.,]\d+)?)\s*(?:ק[\"׳']?ג|גרם|גר['׳]?|ג['׳]|מ[\"׳']?ל|ליטר|ל['׳]|יח[\"׳']?|kg|gr|gm|g|ml|l|oz|lb)(?=$|[\s,/):x×])",
    re.IGNORECASE,
)
_RE_PERCENT = re.compile(r"^\d+(?:[.,]\d+)?%$")
_RE_NUM_ONLY = re.compile(r"^\d+(?:[.,]\d+)?$")


def _unify_punctuation(text: str) -> str:
    """Normalize Hebrew gershayim/geresh variants and punctuation."""
    s = (text or "").strip()
    s = s.replace("״", '"').replace("”", '"').replace("“", '"')
    s = s.replace("׳", "'").replace("’", "'").replace("‘", "'").replace("`", "'")
    return s.lower()


def _expand_abbreviations(text: str) -> str:
    """Expand common Israeli receipt abbreviations before tokenization."""
    s = text
    # Exact acronym / quote abbreviations
    replacements = (
        (r'תפ"?א|תפו"?א|תפוא', "תפוח אדמה"),
        (r'תפו"?ע|תפוע', "תפוח עץ"),
        (r'גב"?צ|גבנ"?צ|גבינ"?צ', "גבינה צהובה"),
        (r'גבינ"?ל|גבנ"?ל', "גבינה לבנה"),
        (r'שמ"?ז(?:ית)?', "שמן זית"),
        (r"ח[\"']?\s*עוף", "חזה עוף"),
        (r"עגבנ['.]|עגב['.]", "עגבניות"),
        (r"מלפפ['.]|מלפ['.]", "מלפפון"),
        (r"פלפ['.]", "פלפל"),
        (r"שק['.]\s*אשפ['.]?", "שקיות אשפה"),
        (r"שקיות\s+אשפ['.]", "שקיות אשפה"),
        (r"נייר\s+טואל['.]", "נייר טואלט"),
        (r"טחינה\s+גול['.]", "טחינה גולמית"),
        (r"פלפל\s+אדו['.]", "פלפל אדום"),
        (r"מלפפון\s+חממ['.]", "מלפפון חממה"),
        (r"עגבניות\s+שר['.]", "עגבניות שרי"),
        (r"כוסבר['.]", "כוסברה"),
        (r"פטרוזיל['.]", "פטרוזיליה"),
        (r"אבק['.]\s*כביס['.]?", "אבקת כביסה"),
        (r"נוז['.]\s*כלים", "נוזל כלים"),
        (r"בצל\s+סגו['.]", "בצל סגול"),
    )
    for pattern, repl in replacements:
        s = re.sub(pattern, f" {repl} ", s)
    return s


def normalize_grocery_name(raw_name: str) -> str:
    """Normalize a dictionary key or item name for deterministic lookup."""
    s = _unify_punctuation(raw_name)
    s = _expand_abbreviations(s)
    # Remove trailing/leading asterisks & non-token separators
    s = re.sub(r"[\*\.\,\/\\\-\+\(\)\[\]\:\;]+", " ", s)
    # Keep % attached to digits, strip stray apostrophes/quotes except internal ones normalized away
    s = s.replace('"', " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _tokenize(text: str) -> list[str]:
    """Split text into clean tokens keeping percentages intact."""
    s = normalize_grocery_name(text)
    raw_tokens = s.split()
    tokens: list[str] = []
    for tok in raw_tokens:
        clean = tok.strip("'")
        if clean:
            tokens.append(clean)
    return tokens


def _token_variants(tok: str) -> set[str]:
    """Generate safe morphological variants for whole tokens (no arbitrary substrings)."""
    t = tok.replace("'", "").strip()
    if not t:
        return set()
    variants = {t}

    # Unify double yod / vav (ktiv male vs haser)
    compact = t.replace("יי", "י").replace("וו", "ו")
    variants.add(compact)

    # Handle ASCII / English simple plurals
    if t.isascii():
        if len(t) > 4 and t.endswith("ies"):
            variants.add(t[:-3] + "y")
        elif len(t) > 4 and t.endswith(("oes", "ses", "ches", "shes")):
            variants.add(t[:-2])
        elif len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            variants.add(t[:-1])
        return variants

    # Hebrew safe plural / feminine / construct variants
    base_forms = {t, compact}
    for w in list(base_forms):
        # Plural dual/endings
        if len(w) >= 5 and w.endswith("יות"):
            stem = w[:-3]
            variants.update({stem + "ה", stem + "יה", stem + "י", stem})
        elif len(w) >= 5 and w.endswith("אות"):
            stem = w[:-3]
            variants.update({stem + "ה", stem})
        elif len(w) >= 4 and w.endswith("ות"):
            stem = w[:-2]
            variants.update({stem + "ה", stem + "ת", stem})
        elif len(w) >= 5 and w.endswith("יים"):
            stem = w[:-3]
            variants.update({stem, stem + "ה"})
        elif len(w) >= 4 and w.endswith("ים"):
            stem = w[:-2]
            variants.update({stem, stem + "ה"})

        # Construct state ת -> ה
        if len(w) >= 4 and w.endswith("ת"):
            variants.add(w[:-1] + "ה")
        elif len(w) >= 4 and w.endswith("ה"):
            variants.add(w[:-1] + "ת")

        # Single leading Hebrew prefix (ה/ו/ב/ל/מ) for words >= 4 chars
        if len(w) >= 4 and w[0] in ("ה", "ו", "ב", "ל", "מ"):
            variants.add(w[1:])

    return {v for v in variants if v}


def _build_dictionary() -> tuple[
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
    dict[str, list[int]],
]:
    dictionary: dict[str, dict[str, Any]] = {}
    records: list[dict[str, Any]] = []
    token_index: dict[str, list[int]] = {}

    def _register_key(raw_key: str, meta: dict[str, Any]) -> None:
        key_norm = normalize_grocery_name(raw_key)
        if not key_norm:
            return
        # Keep existing specific entry if already registered by primary/earlier key
        if key_norm not in dictionary:
            dictionary[key_norm] = meta
        # Also register apostrophe-stripped variant when different (e.g. קוטג' -> קוטג)
        no_apos = key_norm.replace("'", "")
        if no_apos and no_apos not in dictionary:
            dictionary[no_apos] = meta

    for entry in _RAW_CATALOG:
        he_name, en_name, aisle, default_split, days, aliases = entry
        assert aisle in AISLE_CATEGORIES, f"Invalid aisle {aisle}"
        assert default_split in SPLIT_VALUES, f"Invalid split {default_split}"
        meta = {
            "aisle": aisle,
            "default_split": default_split,
            "typical_depletion_days": int(days),
        }
        all_names = (he_name, en_name) + aliases
        for nm in all_names:
            _register_key(nm, meta)

    for rec_idx, (key_norm, meta) in enumerate(dictionary.items()):
        tokens = _tokenize(key_norm)
        token_vars = [tuple(_token_variants(t)) for t in tokens]
        bare_tokens = [t.replace("'", "") for t in tokens]
        records.append({
            "idx": rec_idx,
            "key": key_norm,
            "meta": meta,
            "tokens": tokens,
            "bare_tokens": bare_tokens,
            "token_vars": token_vars,
            "char_len": len(key_norm.replace(" ", "")),
        })
        indexed_tokens: set[str] = set()
        for v_tuple in token_vars:
            indexed_tokens.update(v_tuple)
        for tok in indexed_tokens:
            token_index.setdefault(tok, []).append(rec_idx)

    return dictionary, records, token_index


HEBREW_GROCERY_DICTIONARY, _RECORDS, _TOKEN_INDEX = _build_dictionary()
CANONICAL_ITEM_COUNT: int = len(_RAW_CATALOG)


def _strip_receipt_clutter(raw_line: str) -> tuple[str, str, set[str], bool, bool]:
    """Clean receipt line into normalized forms and detect structural modifiers.

    Returns:
        (expanded_clean, bare_clean, flavor_tokens, is_frozen, is_canned)
    """
    s = _unify_punctuation(raw_line)
    s = _RE_BARCODE.sub("", s)
    s = _RE_PRICE_FRAG.sub(" ", s)
    s = _expand_abbreviations(s)
    # Strip number+unit weights and standalone unit tokens before splitting quotes
    s = _RE_WEIGHT_WITH_NUM.sub(" ", s)
    s = re.sub(r'(?:^|\s)(?:ק"ג|מ"ל|ש"ח|יח\'|גר\'|ג\'|ל\')(?=$|\s)', " ", s)
    s = re.sub(r"[\*\.\,\/\\\-\+\(\)\[\]\:\;]+", " ", s)
    s = s.replace('"', " ")
    s = _RE_MULTI_BRANDS.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()

    raw_tokens = [t.strip("'") for t in s.split() if t.strip("'")]
    is_frozen = any(t in {"קפוא", "קפואה", "קפואים", "קפואות", "סנפרוסט", "frozen"} for t in raw_tokens)
    is_canned = any(t in {"שימורים", "קופסה", "קופסא", "במלח", "בחומץ", "canned", "pickled"} for t in raw_tokens)

    # Track flavor tokens introduced after 'בטעם' / 'במילוי' / 'ללא'
    flavor_tokens: set[str] = set()
    negated_tokens: set[str] = set()
    for i, tok in enumerate(raw_tokens):
        if tok in {"בטעם", "במילוי", "בתוספת", "בסגנון"} and i + 1 < len(raw_tokens):
            flavor_tokens.add(raw_tokens[i + 1].replace("'", ""))
        if tok == "ללא" and i + 1 < len(raw_tokens):
            negated_tokens.add(raw_tokens[i + 1].replace("'", ""))

    # Build filtered token lists
    kept_pct_tokens: list[str] = []
    bare_tokens: list[str] = []
    has_eggs = any(t in {"ביצים", "ביצה", "ביצי", "eggs", "egg"} for t in raw_tokens)

    for tok in raw_tokens:
        clean_t = tok.replace("'", "")
        if clean_t in negated_tokens or tok == "ללא":
            continue
        if clean_t in _BRAND_WORDS:
            continue
        if clean_t in _NOISE_WORDS:
            continue
        if _RE_NUM_ONLY.match(clean_t):
            continue
        if clean_t in _SIZE_CODES and not has_eggs:
            continue

        kept_pct_tokens.append(tok)
        if not _RE_PERCENT.match(clean_t):
            bare_tokens.append(tok)

    return " ".join(kept_pct_tokens), " ".join(bare_tokens), flavor_tokens, is_frozen, is_canned


def _result_dict(meta: dict[str, Any]) -> dict[str, Any]:
    """Return a clean copy of the classification triple."""
    return {
        "aisle": meta["aisle"],
        "default_split": meta["default_split"],
        "typical_depletion_days": meta["typical_depletion_days"],
    }


def _heuristic_fallback(tokens: list[str], is_frozen: bool) -> dict[str, Any]:
    """Fallback categorization when no dictionary entry reaches threshold."""
    if is_frozen:
        return {"aisle": "8_frozen", "default_split": "SHARED_50_50", "typical_depletion_days": 21}

    joined = " ".join(tokens)
    if any(w in joined for w in ("שמפו", "סבון", "ניקוי", "כביסה", "אקונומיקה", "טואלט", "אשפה", "מדיח")):
        return {"aisle": "7_household_cleaning", "default_split": "SHARED_50_50", "typical_depletion_days": 30}
    if any(w in joined for w in ("גבינ", "יוגורט", "חלב", "שמנת", "ביצ")):
        return {"aisle": "3_dairy_eggs", "default_split": "SHARED_50_50", "typical_depletion_days": 7}
    if any(w in joined for w in ("עוף", "בקר", "הודו", "סטייק", "דג", "סלמון", "פסטרמה")):
        return {"aisle": "4_meat_fish", "default_split": "SHARED_50_50", "typical_depletion_days": 7}
    if any(w in joined for w in ("לחם", "פיתה", "לחמני", "חלה", "עוגה", "בגט")):
        return {"aisle": "2_bakery", "default_split": "SHARED_50_50", "typical_depletion_days": 7}
    if any(w in joined for w in ("תבלין", "רוטב", "שמן", "חומץ", "פפריקה")):
        return {"aisle": "6_spices_oils", "default_split": "SHARED_50_50", "typical_depletion_days": 60}
    return {"aisle": "5_pantry_dry", "default_split": "SHARED_50_50", "typical_depletion_days": 14}


def classify_grocery_item(raw_receipt_line: str) -> dict[str, Any]:
    """Classify a raw Hebrew or English receipt line into aisle, split, and depletion days.

    Strips Israeli supermarket weights (ק"ג, גר', מ"ל, ל'), brand prefixes
    (תנובה, שטראוס, אסם, שופרסל, ...), barcodes, prices, and standalone numbers,
    then runs exact lookup followed by token-aware fuzzy scoring.

    Returns:
        Dict with keys: `aisle`, `default_split`, `typical_depletion_days`.
    """
    if not raw_receipt_line or not raw_receipt_line.strip():
        return {"aisle": "5_pantry_dry", "default_split": "SHARED_50_50", "typical_depletion_days": 14}

    kept_pct_str, bare_str, flavor_tokens, is_frozen, is_canned = _strip_receipt_clutter(raw_receipt_line)

    # 1. Exact dictionary hit checks (raw -> kept_pct -> bare)
    raw_norm = normalize_grocery_name(raw_receipt_line)
    for probe in (raw_norm, raw_norm.replace("'", ""), kept_pct_str, kept_pct_str.replace("'", ""), bare_str, bare_str.replace("'", "")):
        if probe and probe in HEBREW_GROCERY_DICTIONARY:
            # Skip bare exact hit if 'קפוא' / 'קפואה' changed frozen nature unless dictionary entry is frozen
            hit = HEBREW_GROCERY_DICTIONARY[probe]
            if is_frozen and hit["aisle"] != "8_frozen":
                break
            return _result_dict(hit)

    # 2. Token-aware candidate generation via inverted index
    q_tokens = _tokenize(kept_pct_str) or _tokenize(raw_norm)
    q_bare_tokens = [t.replace("'", "") for t in q_tokens]
    q_variants: list[set[str]] = [_token_variants(t) for t in q_tokens]

    candidate_ids: set[int] = set()
    for v_set in q_variants:
        for v in v_set:
            if v in _TOKEN_INDEX:
                candidate_ids.update(_TOKEN_INDEX[v])

    # Identify if any base product word appears early (used to penalize trailing flavor tokens)
    has_base_product = any(t in _BASE_PRODUCT_WORDS for t in q_bare_tokens)

    best_score = -1.0
    best_meta: dict[str, Any] | None = None

    for idx in candidate_ids:
        rec = _RECORDS[idx]
        rec_tokens = rec["bare_tokens"]
        rec_vars = rec["token_vars"]
        m = len(rec_tokens)
        if m == 0:
            continue

        # Match every token in candidate key against a query token
        matched_positions: list[int] = []
        exact_matches = 0
        used_q: set[int] = set()

        for k_i in range(m):
            k_tok = rec_tokens[k_i]
            k_var_set = set(rec_vars[k_i])
            best_pos = -1
            is_exact = False
            for q_i, q_tok in enumerate(q_bare_tokens):
                if q_i in used_q:
                    continue
                if q_tok == k_tok:
                    best_pos = q_i
                    is_exact = True
                    break
                if q_variants[q_i] & k_var_set:
                    if best_pos == -1:
                        best_pos = q_i
            if best_pos != -1:
                used_q.add(best_pos)
                matched_positions.append(best_pos)
                if is_exact:
                    exact_matches += 1

        if len(matched_positions) == m:
            # Full token match of dictionary phrase
            score = m * 100.0 + exact_matches * 20.0 + rec["char_len"] * 0.5

            # Contiguous / ordered token bonus
            if matched_positions == sorted(matched_positions):
                score += 15.0
                if m > 1 and matched_positions[-1] - matched_positions[0] == m - 1:
                    score += 20.0

            # Early head-noun bonus
            if matched_positions[0] == 0:
                score += 6.0

            # Flavor disambiguation: do not pick 1-token fruit/spice flavor over a base product
            if m == 1 and rec_tokens[0] in flavor_tokens:
                score -= 60.0
            elif (
                m == 1
                and has_base_product
                and rec_tokens[0] not in _BASE_PRODUCT_WORDS
                and matched_positions[0] > 0
                and q_bare_tokens[0] in _BASE_PRODUCT_WORDS
            ):
                score -= 25.0

            # Frozen / canned contextual bonus
            if is_frozen:
                score += 55.0 if rec["meta"]["aisle"] == "8_frozen" else -25.0
            elif is_canned:
                score += 30.0 if rec["meta"]["aisle"] == "5_pantry_dry" else 0.0

            if score > best_score:
                best_score = score
                best_meta = rec["meta"]

    if best_meta is not None and best_score > 0:
        return _result_dict(best_meta)

    # 3. Fuzzy / typo fallback across tokens (SequenceMatcher >= 0.80)
    if q_bare_tokens:
        fuzzy_best_score = 0.0
        fuzzy_best_meta: dict[str, Any] | None = None
        for rec in _RECORDS:
            r_tokens = rec["bare_tokens"]
            if abs(len(r_tokens) - len(q_bare_tokens)) > 2:
                continue
            matched = 0
            sim_sum = 0.0
            for rt in r_tokens:
                best_tok_sim = 0.0
                for qt in q_bare_tokens:
                    if len(qt) < 2 or len(rt) < 2:
                        continue
                    sim = SequenceMatcher(None, qt, rt).ratio()
                    if sim > best_tok_sim:
                        best_tok_sim = sim
                if best_tok_sim >= 0.80:
                    matched += 1
                    sim_sum += best_tok_sim
            coverage = matched / len(r_tokens)
            if coverage >= 0.65 and sim_sum > 0:
                f_score = coverage * 100.0 + sim_sum * 20.0 + matched * 10.0
                if is_frozen and rec["meta"]["aisle"] == "8_frozen":
                    f_score += 40.0
                if f_score > fuzzy_best_score:
                    fuzzy_best_score = f_score
                    fuzzy_best_meta = rec["meta"]

        if fuzzy_best_meta is not None:
            return _result_dict(fuzzy_best_meta)

    return _heuristic_fallback(q_bare_tokens, is_frozen)
