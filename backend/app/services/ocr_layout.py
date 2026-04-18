from __future__ import annotations

import base64
import requests
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

from app.config import get_settings
from app.models.schemas import LineItem, ReceiptExtraction
from app.services.category import infer_currency_from_text, normalize_category_with_context, normalize_merchant_name
from app.services.llm import LlmService
from app.services.merchant_resolver import MerchantResolver


DATE_PATTERNS = (
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y-%m-%d",
    "%d/%m/%y",
    "%d-%m-%y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d %Y",
    "%B %d %Y",
)

TOTAL_KEYWORDS = ("grand total", "amount paid", "net amount", "balance due", "total", "payable", "bill amount", "sale")
SUBTOTAL_KEYWORDS = ("subtotal", "sub total", "tax", "gst", "cgst", "sgst", "service charge", "discount", "round off")


class ReceiptPipeline:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.merchant_resolver = MerchantResolver()
        self.llm = LlmService()
        self.hf_token = self.settings.hf_api_token

    def parse_receipt(self, image_path: str) -> ReceiptExtraction:
        # 1. Primary Extraction: Specialized Document-AI via Hugging Face
        # (Showcases OCR & Document Understanding skills)
        llm_receipt = self._extract_with_huggingface(image_path)
        
        # 2. Secondary Extraction: LLM Fallback (Gemini)
        # Used if specialized OCR fails to identify basic merchant data
        if not llm_receipt or not llm_receipt.get("vendor"):
            llm_receipt = self._extract_with_gemini(image_path)

        if not llm_receipt or not llm_receipt.get("vendor"):
            raise RuntimeError("Could not extract any meaningful data from receipt. Ensure your API keys are valid.")

        vendor = llm_receipt.get("vendor")
        total = llm_receipt.get("total") or 0.0
        tx_date = llm_receipt.get("date") or datetime.utcnow()
        line_items = llm_receipt.get("line_items") or []
        raw_text = llm_receipt.get("raw_text") or f"Receipt from {vendor}"
        currency = llm_receipt.get("currency") or infer_currency_from_text(raw_text, default="INR")

        profile = self.merchant_resolver.resolve_profile(vendor, detail_text=raw_text, counterparty_type="business", transfer_kind="merchant")
        vendor = profile.canonical_name or normalize_merchant_name(vendor)
        category = normalize_category_with_context(
            vendor,
            None,
            [item.name for item in line_items],
            "merchant",
            "business",
            raw_text,
        )
        if profile.category and profile.confidence >= 0.7:
            category = profile.category

        return ReceiptExtraction(
            vendor=vendor,
            date=tx_date,
            total=total,
            currency=currency,
            line_items=line_items,
            raw_text=raw_text,
            category=category,
        )

    def _extract_with_gemini(self, image_path: str) -> dict:
        payload = self.llm.extract_receipt_image(image_path)
        if not payload:
            return {}
        return self._format_extraction_payload(payload)

    def _extract_with_huggingface(self, image_path: str) -> dict:
        if not self.hf_token:
            print("HF skipped: HF_API_TOKEN is not set.")
            return {}

        # donut-base-finetuned-cord-v2 is receipt-specific, still on HF Inference API
        model_id = "naver-clova-ix/donut-base-finetuned-cord-v2"
        url = f"https://api-inference.huggingface.co/models/{model_id}"
        headers = {
            "Authorization": f"Bearer {self.hf_token}",
            "Content-Type": "application/octet-stream"  # raw bytes, not JSON
        }

        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()

            response = requests.post(url, headers=headers, data=image_bytes, timeout=30)

            if response.status_code != 200:
                print(f"HF Donut returned {response.status_code}: {response.text}")
                return {}

            data = response.json()

            # Donut returns: [{"generated_text": "<s_menu>...</s_menu><s_total>...</s_total>..."}]
            # or a nested dict depending on version — handle both
            raw_output = ""
            if isinstance(data, list) and len(data) > 0:
                raw_output = data[0].get("generated_text", "")
            elif isinstance(data, dict):
                raw_output = data.get("generated_text", "")

            if not raw_output:
                print("HF Donut: empty response")
                return {}

            return self._parse_donut_output(raw_output)

        except Exception as e:
            print(f"HF Donut exception: {e}")
            return {}

    def _parse_donut_output(self, raw_output: str) -> dict:
        import re

        def extract_tag(tag: str) -> str:
            match = re.search(rf"<{tag}>(.*?)</{tag}>", raw_output)
            return match.group(1).strip() if match else ""

        vendor = extract_tag("s_store_name") or extract_tag("s_nm")
        total_str = extract_tag("s_total_price") or extract_tag("s_price")
        date_str = extract_tag("s_date")

        # Parse line items
        line_items = []
        items = re.findall(r"<s_menu>(.*?)</s_menu>", raw_output, re.DOTALL)
        for item in items:
            name = re.search(r"<s_nm>(.*?)</s_nm>", item)
            price = re.search(r"<s_price>(.*?)</s_price>", item)
            if name:
                try:
                    price_val = float(price.group(1).replace(",", "")) if price else 0.0
                    line_items.append({"name": name.group(1).strip(), "price": price_val})
                except ValueError:
                    continue

        try:
            total = float(total_str.replace(",", "")) if total_str else None
        except ValueError:
            total = None

        return {
            "vendor": vendor or None,
            "total": total,
            "date": date_str or None,
            "line_items": line_items,
            "raw_text": raw_output,
        }

    def _format_extraction_payload(self, payload: dict) -> dict:
        raw_items = payload.get("line_items") or []
        line_items: list[LineItem] = []
        for item in raw_items:
            name = str(item.get("name") or "").strip()
            price = item.get("price")
            if name:
                try:
                    price_value = float(price) if price else 0.0
                    line_items.append(LineItem(name=name, price=price_value))
                except (ValueError, TypeError):
                    continue

        parsed_date = None
        date_str = payload.get("date")
        if date_str:
            for fmt in DATE_PATTERNS:
                try:
                    parsed_date = datetime.strptime(date_str, fmt)
                    break
                except Exception:
                    continue

        return {
            "vendor": payload.get("vendor"),
            "total": payload.get("total"),
            "date": parsed_date,
            "line_items": line_items,
            "raw_text": f"Vendor: {payload.get('vendor')}\nTotal: {payload.get('total')}",
        }

    @classmethod
    def infer_line_items_from_raw_text(cls, raw_text: str, total: float) -> list[LineItem]:
        # Simple regex-based fallback if we only have text
        items = []
        for line in raw_text.splitlines():
            match = re.search(r"(.+?)\s+([\d,]+\.?\d*)", line)
            if match:
                name, price = match.groups()
                items.append(LineItem(name=name.strip(), price=float(price.replace(",", ""))))
        return items
