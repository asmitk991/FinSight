from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from app.config import get_settings
from app.models.schemas import ParsedTransaction, TransactionType
from app.services.category import normalize_merchant_name

try:
    import google.generativeai as genai
except ImportError:  # pragma: no cover
    genai = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


PDF_PROMPT = """
You are extracting structured transactions from a Google Pay or UPI statement.
Return only a valid JSON array. Each element must have:
date, merchant, amount, type, raw_category.

Categorization Rules for LLM stage:
- 'utilities': Telecom recharges (Jio, Airtel), Electricity, Water, Broadband.
- 'food': Swiggy, Zomato, GoGrab, Coffee, Restaurants.
- 'groceries': Blinkit, Zepto, Milk, Supermarkets.
- 'transport': Uber, Ola, Metro, IRCTC, Petrol.
- 'transfer': UPI transfers to people, bank transfers.
Do not include markdown fences or any explanation.
"""

CATEGORY_PROMPT = """
You are classifying a personal finance transaction into exactly one category.
Valid categories: food, transport, groceries, utilities, entertainment, health, shopping, transfer, other.
Return only the category label and nothing else.
Prefer transfer for person-to-person payments and reimbursements.
Prefer other only if the merchant is too ambiguous.
"""

MERCHANT_PROFILE_PROMPT = """
You are resolving a merchant or counterparty from a payments ledger.
Return only valid JSON with these keys:
canonical_name, merchant_type, category, confidence.

Rules:
- canonical_name should be the cleaned business/person/bank name.
- merchant_type must be one of: person, business, bank_account, reward, unknown.
- category must be one of: food, transport, groceries, utilities, entertainment, health, shopping, transfer, self_transfer, other.
- confidence must be a number from 0 to 1.
- Use the provided detail text and search context if available.
- If the merchant is a person or bank transfer, category should usually be transfer or self_transfer.
"""

QUERY_PLAN_PROMPT = """
You are planning a finance query over a user's transaction ledger.
Return only valid JSON with these keys:
action, direction, category, transfer_kind, counterparty, month, year, comparison_month, comparison_year, limit.

Rules:
- action must be one of: sum, list, top_counterparty, max_transaction, category_breakdown, overview, compare, trend.
- Use 'compare' when the user wants to see changes between months or merchants.
- Use 'trend' when the user asks about progress over time.
- direction must be one of: sent, received, any.
- category must be one of: food, transport, groceries, utilities, entertainment, health, shopping, transfer, self_transfer, professional, other, or null.
- counterparty should be one of the provided merchant names when the user is asking about a specific merchant/person, otherwise null.
- For comparisons (e.g., "Jan vs Feb"):
  - set month and year for the first period.
  - set comparison_month and comparison_year for the second period.
- Infer the user's intent from the question naturally. For example:
  - "Compare my food spend between January and February" => action=compare, category=food, month=1, year=2026, comparison_month=2, comparison_year=2026
  - "How did my GoGrab spend change between March and April?" => action=compare, counterparty=GoGrab, month=3, year=2026, comparison_month=4, comparison_year=2026
  - "What's the trend for my savings?" => action=trend, direction=received
- Do not invent merchants not present in the provided merchant list.
"""

EDITOR_AGENT_PROMPT = """
You are a behavioral finance analyst writing a personal spending intelligence report.
You are given pre-computed behavioral and temporal metrics about a person's transaction history.
Your job is to extract genuinely surprising, specific, and actionable insights a person cannot see just by looking at a chart.

Output ONLY valid JSON with these exact keys:
- "headline": One punchy sentence capturing the most interesting behavioral finding (not just "total spend was X").
- "overview": 2 sentences. Summarize the period and one surprising behavioural pattern.
- "behavioral_insights": An array of exactly 4 strings. Each must be a specific, data-backed behavioral observation using real numbers and merchant names from the data. Examples of the kind of insight to produce:
    * Time-of-day: "83% of your GoGrab transactions happened after 12 PM, suggesting afternoon snack runs are a consistent habit."
    * Temporal: "You spent 2.3x more in the first half of the month (days 1-15) than the second half."
    * Day pattern: "Saturday is your highest-spend day, averaging 40% more than weekdays."
    * Merchant habit: "You visited Chai Adda 12 times — nearly every working day — making it your most frequent merchant by visit count."
    * Impulse signal: "You made 7 impulse purchases totaling ₹2,400 at merchants like Amazon and Snapmint outside of your routine spending."
    * Concentration: "3 merchants account for 71% of your total spend."
- "recommendations": An array of exactly 2 actionable, specific recommendations based on the behavioral data. Name specific merchants or habits. Do not give generic advice.
- "health_score": An integer from 1-100 rating financial discipline. Penalise high impulse frequency, single-merchant concentration, and late-night spending. Reward diverse categories and planned large transactions.
- "health_label": "Excellent" (80-100), "Good" (60-79), "Fair" (40-59), "Needs Attention" (0-39).

Rules:
- NEVER output a generic insight like "your top category was food". Use the specific numbers, merchant names, and time data provided.
- DO NOT call routine small transactions (like coffee, tea, or transport) "impulse buys". Use the impulse metrics ONLY for non-routine shopping or unexpected spikes at specific merchants.
- Do not include markdown, code fences, or any text outside the JSON object.
- Do not invent data not present in the metrics provided.
"""

RECEIPT_IMAGE_PROMPT = """
You are extracting structured data from a receipt image.
Return only valid JSON with these keys:
vendor, date, total, line_items.

Rules:
- vendor must be the merchant/store name.
- date should be in YYYY-MM-DD format when visible, otherwise null.
- total must be the final paid amount as a number.
- line_items must be an array of objects with keys: name and price.
- If a field is not visible, use null for scalars and [] for line_items.
- Do not include markdown fences or any explanation.
"""


class LlmService:
    def __init__(self) -> None:
        settings = get_settings()
        self.model_name = settings.google_gemini_model
        self.available = bool(settings.gemini_api_key and genai)
        if self.available:
            genai.configure(api_key=settings.gemini_api_key)
            self.model = genai.GenerativeModel(self.model_name)
        else:
            self.model = None

    def parse_pdf_rows(self, raw_rows: list[str]) -> list[ParsedTransaction]:
        if self.available and self.model:
            response = self.model.generate_content([PDF_PROMPT, "\n".join(raw_rows)])
            text = response.text.strip()
            # Clean possible markdown fences
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
            text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
            data = json.loads(text)
            return [self._to_parsed_transaction(item, " | ".join(raw_rows)) for item in data]
        return self._fallback_parse(raw_rows)

    def classify_category(self, merchant: str, raw_category: str | None = None, line_items: list[str] | None = None) -> str | None:
        if not self.available or not self.model:
            return None
        payload = {
            "merchant": merchant,
            "raw_category": raw_category,
            "line_items": line_items or [],
        }
        response = self.model.generate_content([CATEGORY_PROMPT, json.dumps(payload)])
        label = response.text.strip().lower()
        valid = {"food", "transport", "groceries", "utilities", "entertainment", "health", "shopping", "transfer", "other"}
        return label if label in valid else None

    def classify_merchant_profile(
        self,
        merchant: str,
        detail_text: str | None = None,
        counterparty_type: str | None = None,
        transfer_kind: str | None = None,
        search_summary: str | None = None,
    ) -> dict | None:
        if not self.available or not self.model:
            return None
        payload = {
            "merchant": merchant,
            "detail_text": detail_text,
            "counterparty_type": counterparty_type,
            "transfer_kind": transfer_kind,
            "search_summary": search_summary,
        }
        try:
            response = self.model.generate_content([MERCHANT_PROFILE_PROMPT, json.dumps(payload)])
            text = response.text.strip()
            return json.loads(text)
        except Exception:
            return None

    def plan_agent_query(self, question: str, merchants: list[str]) -> dict | None:
        if not self.available or not self.model:
            return None
        payload = {
            "question": question,
            "merchants": merchants[:200],
        }
        try:
            response = self.model.generate_content([QUERY_PLAN_PROMPT, json.dumps(payload)])
            text = response.text.strip()
            # Clean possible markdown fences
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
            text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
            return json.loads(text)
        except Exception:
            return None

    def extract_receipt_image(self, image_path: str) -> dict | None:
        if not self.available or not self.model or Image is None:
            print("Gemini image extraction skipped: model unavailable or Pillow missing.")
            return None
        try:
            image = Image.open(Path(image_path))
            response = self.model.generate_content([RECEIPT_IMAGE_PROMPT, image])
            text = response.text.strip()
            # Clean possible markdown fences
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
            text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
            return json.loads(text)
        except Exception as e:
            print(f"Gemini image extraction failed: {e}")
            return None

    def generate_executive_report(self, metrics: dict) -> dict | None:
        if not self.available or not self.model:
            return None
        try:
            payload = json.dumps(metrics, default=str, indent=2)
            response = self.model.generate_content([EDITOR_AGENT_PROMPT, f"Here are the financial metrics:\n\n{payload}"])
            text = response.text.strip()
            # Strip markdown fences if the model wraps output anyway
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            return json.loads(text)
        except Exception:
            return None
    def generate_agent_response(self, question: str, metrics: dict) -> str:
        if not self.available or not self.model:
            return "I have the data but my natural language engine is currently offline."
        try:
            payload = json.dumps(metrics, default=str, indent=2)
            prompt = f"""
            You are a financial intelligence agent.
            The user asked: "{question}"
            
            Here are the calculated metrics:
            {payload}
            
            Answer the user's question accurately based on THESE METRICS ONLY. 
            Keep it professional, conversational, and direct. 
            If it's a comparison or trend, highlight the percentage change or key differences.
            Do not repeat the raw JSON.
            """
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"Error generating answer: {str(e)}"

    def _fallback_parse(self, raw_rows: list[str]) -> list[ParsedTransaction]:
        parsed: list[ParsedTransaction] = []
        for row in raw_rows:
            pipe_parts = [part.strip() for part in row.split("|") if part.strip()]
            if len(pipe_parts) >= 4:
                tx_date, merchant, amount_text, tx_type = pipe_parts[:4]
                amount = float(amount_text.replace("₹", "").replace(",", "").strip())
                parsed.append(
                    ParsedTransaction(
                        date=self._coerce_date(tx_date),
                        merchant=merchant,
                        amount=abs(amount),
                        type=TransactionType.credit if "credit" in tx_type.lower() else TransactionType.debit,
                        reference_id=None,
                        time_text=None,
                        detail_text=None,
                        direction=None,
                        transfer_kind=None,
                        counterparty_type=None,
                        raw_category=pipe_parts[4] if len(pipe_parts) > 4 else None,
                        raw_text=row,
                    )
                )
                continue

            tx = self._parse_text_row(row)
            if tx:
                parsed.append(tx)
        return parsed

    def _to_parsed_transaction(self, item: dict, raw_text: str) -> ParsedTransaction:
        return ParsedTransaction(
            date=self._coerce_date(item["date"]),
            merchant=item["merchant"],
            amount=abs(float(item["amount"])),
            type=TransactionType(item["type"].lower()),
            reference_id=item.get("reference_id"),
            time_text=item.get("time_text"),
            detail_text=item.get("detail_text"),
            direction=item.get("direction"),
            transfer_kind=item.get("transfer_kind"),
            counterparty_type=item.get("counterparty_type"),
            raw_category=item.get("raw_category"),
            raw_text=raw_text,
        )

    @staticmethod
    def _coerce_date(value: str) -> datetime:
        normalized = value.strip()
        normalized = re.sub(r"(\d{1,2})([A-Za-z]{3,9})(\d),(\d{3})", r"\1 \2 \3\4", normalized)
        for fmt in ("%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(normalized, fmt)
            except ValueError:
                continue
        return datetime.fromisoformat(normalized)

    def _parse_text_row(self, row: str) -> ParsedTransaction | None:
        date_match = re.search(
            r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}\b|\b\d{1,2}[A-Za-z]{3,9}\d,\d{3}\b",
            row,
        )
        amount_matches = re.findall(r"(?:₹|Rs\.?\s*)\s*([\d,]+(?:\.\d{1,2})?)|(?<!\d)([\d,]+\.\d{1,2})(?!\d)", row, flags=re.IGNORECASE)
        if not date_match or not amount_matches:
            return None

        amount_text = next((left or right for left, right in amount_matches if left or right), None)
        if not amount_text:
            return None

        amount = float(amount_text.replace(",", ""))
        tx_type = (
            TransactionType.credit
            if any(word in row.lower() for word in ["credit", "credited", "received", "receifvreod"])
            else TransactionType.debit
        )

        date_text = date_match.group(0)
        remainder = row.replace(date_text, " ", 1)
        remainder = re.sub(r"(?:₹|Rs\.?\s*)\s*[\d,]+(?:\.\d{1,2})?", " ", remainder, flags=re.IGNORECASE)
        remainder = re.sub(
            r"\b(?:debited|credited|credit|debit|paid|received|paitdo|receifvreod|completed|transaction|ref|upi)\b",
            " ",
            remainder,
            flags=re.IGNORECASE,
        )
        remainder = re.sub(r"\b(?:from|to|by|via)\b", " ", remainder, flags=re.IGNORECASE)
        remainder = re.sub(r"\b(?:statebankofindia|sbi|bankofindia|googlepayapp|googlepay)\b", " ", remainder, flags=re.IGNORECASE)
        remainder = re.sub(r"\b[A-Z]{2,}ID\b[:\s]*[A-Za-z0-9]+\b", " ", remainder, flags=re.IGNORECASE)
        remainder = re.sub(r"\b\d{1,2}:\d{2}\s*[AP]M\b", " ", remainder, flags=re.IGNORECASE)
        remainder = re.sub(r"\b\d{6,}\b", " ", remainder)
        merchant = " ".join(remainder.split()).strip(" -,:")
        merchant = normalize_merchant_name(merchant)

        if not merchant:
            merchant = "Unknown merchant"
        if re.fullmatch(r"\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}", merchant):
            return None

        return ParsedTransaction(
            date=self._coerce_date(date_text),
            merchant=merchant,
            amount=abs(amount),
            type=tx_type,
            reference_id=None,
            time_text=None,
            detail_text=None,
            direction=None,
            transfer_kind=None,
            counterparty_type=None,
            raw_category=None,
            raw_text=row,
        )
