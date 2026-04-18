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
            print("HF Document QA skipped: HF_API_TOKEN is not set.")
            return {}
        
        # Using a Document-QA model which is better at structured extraction than raw OCR
        model_id = "impira/layoutlm-document-qa"
        url = f"https://api-inference.huggingface.co/models/{model_id}"
        headers = {"Authorization": f"Bearer {self.hf_token}"}
        
        with open(image_path, "rb") as f:
            img_base64 = base64.b64encode(f.read()).decode("utf-8")

        queries = {
            "vendor": "What is the name of the store or merchant?",
            "total": "What is the total amount or grand total?",
            "date": "What is the date of the transaction?",
        }
        
        results = {}
        try:
            for key, question in queries.items():
                payload = {
                    "inputs": {
                        "image": img_base64,
                        "question": question
                    }
                }
                response = requests.post(url, headers=headers, json=payload, timeout=20)
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list) and len(data) > 0:
                        results[key] = data[0].get("answer")
                else:
                    print(f"HF API returned {response.status_code} for query '{key}': {response.text}")
            
            return results
        except Exception as e:
            print(f"HF Document QA exception: {e}")
            return {}

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
