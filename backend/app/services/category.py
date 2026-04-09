from __future__ import annotations

from collections.abc import Iterable
import re


CATEGORY_MAP = {
    "swiggy": "food",
    "zomato": "food",
    "chai adda": "food",
    "coffee day": "food",
    "blinkit": "groceries",
    "zepto": "groceries",
    "bigbasket": "groceries",
    "ola": "transport",
    "rapido": "transport",
    "uber": "transport",
    "metro": "transport",
    "bescom": "utilities",
    "airtel": "utilities",
    "jio": "utilities",
    "netflix": "entertainment",
    "spotify": "entertainment",
    "apollo": "health",
    "pharmeasy": "health",
    "amazon": "shopping",
    "flipkart": "shopping",
    "linkedin": "shopping",
    "supermarket": "groceries",
    "mart": "groceries",
    "grocery": "groceries",
    "google pay": "transfer",
    "upi": "transfer",
    "gograb": "food",
}

GROCERY_ITEM_HINTS = {
    "apple",
    "banana",
    "orange",
    "pear",
    "grapes",
    "strawberry",
    "blueberry",
    "kiwi",
    "watermelon",
    "lemon",
    "raspberry",
    "milk",
    "cheese",
    "yogurt",
    "bread",
    "egg",
    "rice",
    "dal",
    "flour",
    "atta",
    "vegetable",
    "fruit",
}

ITEM_GROUPS = {
    "fruits": {
        "apple",
        "banana",
        "orange",
        "pear",
        "grapes",
        "strawberry",
        "blueberry",
        "kiwi",
        "watermelon",
        "lemon",
        "raspberry",
        "fruit",
    },
    "vegetables": {
        "vegetable",
        "tomato",
        "potato",
        "onion",
        "carrot",
        "spinach",
        "capsicum",
        "pepper",
        "cucumber",
        "broccoli",
    },
    "dairy": {
        "milk",
        "cheese",
        "yogurt",
        "curd",
        "butter",
        "paneer",
    },
    "beverages": {
        "tea",
        "coffee",
        "redbull",
        "juice",
        "cola",
        "water",
        "drink",
        "beverage",
    },
    "snacks": {
        "chips",
        "cookies",
        "biscuit",
        "snack",
        "fries",
    },
    "meals": {
        "chicken",
        "naan",
        "burger",
        "pizza",
        "rice",
        "meal",
        "sandwich",
        "pasta",
    },
}

MEAL_CONTEXT_HINTS = {
    "chicken",
    "naan",
    "burger",
    "pizza",
    "rice",
    "meal",
    "sandwich",
    "pasta",
    "tea",
    "coffee",
}

BUSINESS_HINTS = {
    "limited",
    "ltd",
    "private",
    "pvt",
    "systems",
    "global",
    "india",
    "solution",
    "solutions",
    "advisory",
    "prepaid",
    "rewards",
    "cafe",
    "coffee",
    "chai",
    "netflix",
    "spotify",
    "linkedin",
    "irctc",
    "uber",
    "gograb",
}

MERCHANT_ALIASES = {
    "amiktumar": "Amit Kumar",
    "amikumar": "Amit Kumar",
    "ishkaumari": "Isha Kumari",
    "imshkaumari": "Isha Kumari",
    "ubeirndisaystepmrsivaltiemited": "Uber India Systems Private Limited",
    "coffedeaygloballimited": "Coffee Day Global Limited",
    "netflcioxm": "Netflix",
    "spotiinfdyia": "Spotify India",
    "airptreelpaid": "Airtel Prepaid",
    "chaaidda": "Chai Adda",
    "mmanojkumar": "Manoj Kumar",
    "amthaurpvadhyay": "Amtha Urpvadhyay",
    "smhreysaingh": "Shreya Singh",
    "gmoogplaeyrewards": "Google Pay Rewards",
    "irctc": "IRCTC",
    "gograb": "GoGrab",
    "bchrishihood": "BCH Rishihood",
    "snapmcirnetdaidtvisporriyvlaitmeited": "Snapmint Advisory Private Limited",
    "snapmcirnetdaidtvisporriylaitmeited": "Snapmint Advisory Private Limited",
    "linkedin": "LinkedIn",
    "mrsonukumanrayak": "Mr Sonu Kumanrayak",
    "yashdeekpaur": "Yashdeep Kaur",
    "ravinadterri": "Ravin Adterri",
    "abuzahraideri": "Abuzahraideri",
    "nimiesttyufsfolution": "Nimiesttyuf Solution",
}


def merchant_key(value: str) -> str:
    cleaned = normalize_merchant_name(value)
    return re.sub(r"[^a-z0-9]+", "", cleaned.lower())


def normalize_merchant_name(value: str) -> str:
    merchant = value.strip(" -,:")
    merchant = re.sub(r"^(?:Paitdo|Receifvreod)\s*", "", merchant, flags=re.IGNORECASE)
    merchant = re.sub(r"(?:Paitdo|Receifvreod)$", "", merchant, flags=re.IGNORECASE)
    merchant = re.sub(r"\s{2,}", " ", merchant).strip(" -,:")
    merchant = re.sub(r"([a-z])([A-Z])", r"\1 \2", merchant)
    alias = MERCHANT_ALIASES.get(re.sub(r"[^a-z0-9]+", "", merchant.lower()))
    if alias:
        return alias
    if merchant.isupper() and len(merchant) <= 12:
        return merchant
    if merchant.isupper():
        return merchant.title()
    if merchant and merchant.lower() == merchant:
        return merchant.title()
    return merchant


def normalize_category(merchant: str, raw_category: str | None = None, line_items: Iterable[str] | None = None) -> str:
    clean_merchant = normalize_merchant_name(merchant)
    haystacks = [merchant.lower(), clean_merchant.lower()]
    if raw_category:
        haystacks.append(raw_category.lower())
    if line_items:
        haystacks.extend(item.lower() for item in line_items)

    for needle, category in CATEGORY_MAP.items():
        if any(needle in text for text in haystacks):
            return category

    if raw_category:
        raw = raw_category.lower()
        if "bill" in raw or "recharge" in raw:
            return "utilities"
        if "food" in raw or "restaurant" in raw:
            return "food"
        if "travel" in raw or "ride" in raw:
            return "transport"

    if line_items:
        normalized_items = {re.sub(r"[^a-z]+", " ", item.lower()).strip() for item in line_items}
        grocery_hits = 0
        food_hits = 0
        for item in normalized_items:
            words = set(item.split())
            if words & GROCERY_ITEM_HINTS:
                grocery_hits += 1
            if {"chicken", "naan", "tea", "coffee", "burger", "pizza", "fries"} & words:
                food_hits += 1
        if grocery_hits >= 3:
            return "groceries"
        if food_hits >= 2:
            return "food"

    if looks_like_personal_counterparty(clean_merchant):
        return "transfer"

    return "other"


def normalize_category_with_context(
    merchant: str,
    raw_category: str | None = None,
    line_items: Iterable[str] | None = None,
    transfer_kind: str | None = None,
    counterparty_type: str | None = None,
    detail_text: str | None = None,
) -> str:
    base = normalize_category(merchant, raw_category, line_items)
    if transfer_kind == "self_transfer":
        return "self_transfer"
    if transfer_kind in {"person", "bank"} or counterparty_type == "bank_account":
        return "transfer"
    if transfer_kind == "reward":
        return "other"
    if detail_text and "self transfer" in detail_text.lower():
        return "self_transfer"
    return base


def infer_question_category(question: str) -> str | None:
    lower = question.lower()
    for category in ["food", "transport", "groceries", "utilities", "entertainment", "health", "shopping", "self_transfer", "transfer", "other"]:
        if category in lower:
            return category
    if "self transfer" in lower or "other account" in lower:
        return "self_transfer"
    if "travel" in lower or "ride" in lower or "cab" in lower:
        return "transport"
    if "restaurant" in lower or "snacks" in lower:
        return "food"
    if "person" in lower or "sent money" in lower or "received money" in lower:
        return "transfer"
    return None


def find_item_group(question: str) -> str | None:
    lower = question.lower()
    for group, keywords in ITEM_GROUPS.items():
        if group in lower:
            return group
        singular = group[:-1] if group.endswith("s") else group
        if singular in lower:
            return group
        if any(keyword in lower for keyword in keywords if len(keyword) > 3):
            return group
    return None


def item_belongs_to_group(item_name: str, group: str) -> bool:
    keywords = ITEM_GROUPS.get(group, set())
    normalized = re.sub(r"[^a-z]+", " ", item_name.lower()).strip()
    words = set(normalized.split())
    if group == "dairy" and words & {"butter"} and words & MEAL_CONTEXT_HINTS:
        return False
    if group == "dairy" and words & {"cheese"} and words & {"string", "pack", "pk", "16pk"}:
        return True
    if group in {"dairy", "beverages"} and words & MEAL_CONTEXT_HINTS and not words <= keywords:
        return False
    return bool(words & keywords)


def looks_like_personal_counterparty(merchant: str) -> bool:
    normalized = merchant.strip()
    if not normalized:
        return False
    if any(hint in normalized.lower() for hint in BUSINESS_HINTS):
        return False
    tokens = [token for token in re.split(r"\s+", normalized) if token]
    if len(tokens) == 1:
        token = tokens[0]
        return token[:1].isupper() and token[1:].islower() and len(token) >= 5
    if len(tokens) <= 3 and all(token[:1].isupper() for token in tokens):
        return True
    return False


def build_embedding_text(
    date_text: str,
    merchant: str,
    amount: float,
    category: str,
    tx_type: str,
    detail_text: str | None = None,
    currency: str = "INR",
) -> str:
    clean_merchant = normalize_merchant_name(merchant)
    detail_suffix = f" Detail: {detail_text}." if detail_text else ""
    return f"{clean_merchant} transaction on {date_text} for {format_amount(amount, currency)}, {category} category, {tx_type}.{detail_suffix}"


def infer_currency_from_text(text: str | None, default: str = "INR") -> str:
    if not text:
        return default
    lower = text.lower()
    if "$" in text or " usd" in lower or "dollar" in lower:
        return "USD"
    if "aed" in lower or "dirham" in lower:
        return "AED"
    if "€" in text or " eur" in lower:
        return "EUR"
    if "£" in text or " gbp" in lower:
        return "GBP"
    if "₹" in text or " inr" in lower or "rs." in lower or "rs " in lower:
        return "INR"
    return default


def currency_symbol(currency: str | None) -> str:
    symbols = {
        "INR": "INR",
        "USD": "$",
        "AED": "AED",
        "EUR": "EUR",
        "GBP": "GBP",
    }
    return symbols.get((currency or "INR").upper(), (currency or "INR").upper())


def format_amount(amount: float, currency: str | None) -> str:
    symbol = currency_symbol(currency)
    if symbol == "$":
        return f"$ {amount:.2f}"
    return f"{symbol} {amount:.2f}"
