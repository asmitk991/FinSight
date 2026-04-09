from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

from app.config import get_settings
from app.models.schemas import LineItem, ReceiptExtraction
from app.services.category import infer_currency_from_text, normalize_category_with_context, normalize_merchant_name
from app.services.llm import LlmService
from app.services.merchant_resolver import MerchantResolver

try:
    from paddleocr import PaddleOCR
except ImportError:  # pragma: no cover
    PaddleOCR = None

try:
    from transformers import AutoModelForTokenClassification, AutoProcessor
except ImportError:  # pragma: no cover
    AutoModelForTokenClassification = None
    AutoProcessor = None


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
LINE_ITEM_BLOCKLIST = (
    "invoice",
    "receipt",
    "bill",
    "table",
    "token",
    "cashier",
    "server",
    "order",
    "date",
    "guest",
    "guests",
    "phone",
    "mobile",
    "fax",
    "table",
    "terminal",
    "cashier",
    "ref.no",
    "ref no",
    "ref",
    "gst",
    "upi",
    "visa",
    "mastercard",
    "thank",
    "welcome",
    "visit again",
    "item count",
)


@dataclass
class OCRWord:
    text: str
    box: list[int]
    score: float


@dataclass
class OCRLine:
    text: str
    words: list[OCRWord]
    y_center: float


class ReceiptPipeline:
    def __init__(self) -> None:
        settings = get_settings()
        self.ocr = PaddleOCR(use_angle_cls=True, lang="en") if PaddleOCR else None
        self.layoutlm_model_name = getattr(settings, "layoutlm_model_name", None)
        self.processor = None
        self.model = None
        if self.layoutlm_model_name and AutoProcessor and AutoModelForTokenClassification:
            try:
                self.processor = AutoProcessor.from_pretrained(self.layoutlm_model_name)
                self.model = AutoModelForTokenClassification.from_pretrained(self.layoutlm_model_name)
            except Exception:  # pragma: no cover
                self.processor = None
                self.model = None
        self.merchant_resolver = MerchantResolver()
        self.llm = LlmService()

    def parse_receipt(self, image_path: str) -> ReceiptExtraction:
        image = Path(image_path)
        words = self._extract_ocr_words(image)
        lines = self._group_words_into_lines(words)
        raw_text = "\n".join(line.text for line in lines)
        llm_receipt = self._extract_with_llm(image_path, words)
        if self._needs_ocr_setup(words, llm_receipt, image):
            raise RuntimeError(
                "Receipt OCR is not configured. Install PaddleOCR with PaddlePaddle, or set GEMINI_API_KEY so the image fallback can extract receipt fields."
            )

        layout_fields = self._layoutlm_extract(words)
        vendor = layout_fields.get("vendor") or llm_receipt.get("vendor") or self._extract_vendor(lines, image)
        total = layout_fields.get("total") or llm_receipt.get("total") or self._extract_total(lines)
        tx_date = layout_fields.get("date") or llm_receipt.get("date") or self._extract_date(lines)
        line_items = layout_fields.get("line_items") or llm_receipt.get("line_items") or self._extract_line_items(lines, total)
        if llm_receipt.get("raw_text"):
            raw_text = llm_receipt["raw_text"]
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
            raw_text=raw_text or image.stem.replace("_", " ").title(),
            category=category,
        )

    @classmethod
    def infer_line_items_from_raw_text(cls, raw_text: str, total: float) -> list[LineItem]:
        helper = cls()
        lines = [
            OCRLine(text=helper._clean_line_text(line), words=[], y_center=float(index))
            for index, line in enumerate(raw_text.splitlines())
            if helper._clean_line_text(line)
        ]
        return helper._extract_line_items(lines, total)

    @staticmethod
    def _needs_ocr_setup(words: list[OCRWord], llm_receipt: dict, image: Path) -> bool:
        if llm_receipt:
            return False
        if len(words) >= 8:
            return False
        fallback_text = image.stem.replace("_", " ").title()
        if len(words) == 1 and words[0].text.strip() == fallback_text:
            return True
        return not words

    def _extract_with_llm(self, image_path: str, words: list[OCRWord]) -> dict:
        if words and len(words) >= 8:
            return {}
        payload = self.llm.extract_receipt_image(image_path)
        if not payload:
            return {}
        raw_items = payload.get("line_items") or []
        line_items: list[LineItem] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            price = item.get("price")
            if not name:
                continue
            try:
                price_value = float(price) if price is not None else None
            except (TypeError, ValueError):
                price_value = None
            line_items.append(LineItem(name=name, price=price_value))

        parsed_date = None
        date_value = payload.get("date")
        if isinstance(date_value, str) and date_value.strip():
            parsed_date = self._find_date(date_value) or self._parse_iso_date(date_value)

        total_value = payload.get("total")
        try:
            total = float(total_value) if total_value is not None else 0.0
        except (TypeError, ValueError):
            total = 0.0

        raw_text = self._llm_raw_text(payload, line_items)
        return {
            "vendor": normalize_merchant_name(str(payload.get("vendor") or "").strip()) if payload.get("vendor") else None,
            "total": total,
            "date": parsed_date,
            "currency": infer_currency_from_text(payload.get("raw_text") or payload.get("vendor") or "", default="INR"),
            "line_items": line_items,
            "raw_text": raw_text,
        }

    def _extract_ocr_words(self, image_path: Path) -> list[OCRWord]:
        if not self.ocr:
            fallback = image_path.stem.replace("_", " ").title()
            return [OCRWord(text=fallback, box=[0, 0, 1000, 80], score=0.0)]

        result = self.ocr.ocr(str(image_path), cls=True)
        if not result:
            return []

        words: list[OCRWord] = []
        width, height = self._estimate_canvas_size(result)
        for block in result:
            for entry in block:
                polygon = entry[0]
                text = (entry[1][0] or "").strip()
                score = float(entry[1][1] or 0.0)
                if not text:
                    continue
                words.append(OCRWord(text=text, box=self._normalize_box(polygon, width, height), score=score))
        return words

    def _group_words_into_lines(self, words: list[OCRWord]) -> list[OCRLine]:
        if not words:
            return []

        sorted_words = sorted(words, key=lambda word: (self._box_center_y(word.box), word.box[0]))
        lines: list[OCRLine] = []
        current: list[OCRWord] = []

        for word in sorted_words:
            if not current:
                current = [word]
                continue
            current_center = sum(self._box_center_y(item.box) for item in current) / len(current)
            if abs(self._box_center_y(word.box) - current_center) <= 18:
                current.append(word)
                continue
            lines.append(self._build_line(current))
            current = [word]

        if current:
            lines.append(self._build_line(current))
        return lines

    def _extract_vendor(self, lines: list[OCRLine], image_path: Path) -> str:
        headline_candidates: list[str] = []
        for line in lines[:6]:
            text = self._clean_line_text(line.text)
            if not text:
                continue
            lower = text.lower()
            if any(token in lower for token in LINE_ITEM_BLOCKLIST):
                continue
            if self._find_amount(text) is not None:
                continue
            if self._find_date(text):
                continue
            if len(text) < 3:
                continue
            headline_candidates.append(text)
            if len(headline_candidates) >= 2:
                combined = " ".join(headline_candidates)
                if self._looks_like_vendor_name(combined):
                    return normalize_merchant_name(combined)
            if len(headline_candidates) == 1 and self._looks_like_vendor_name(text) and len(text.split()) >= 2:
                return normalize_merchant_name(text)
        if headline_candidates:
            return normalize_merchant_name(" ".join(headline_candidates[:2]))
        return image_path.stem.replace("_", " ").title()

    def _extract_total(self, lines: list[OCRLine]) -> float:
        keyword_candidates: list[float] = []
        fallback_candidates: list[float] = []

        for line in lines:
            lower = line.text.lower()
            amount = self._find_amount(line.text)
            if amount is None or amount <= 0:
                continue
            if amount <= 99999:
                fallback_candidates.append(amount)
            if any(keyword in lower for keyword in TOTAL_KEYWORDS) and not any(keyword in lower for keyword in SUBTOTAL_KEYWORDS):
                keyword_candidates.append(amount)

        if keyword_candidates:
            return max(keyword_candidates)
        if fallback_candidates:
            return max(fallback_candidates)
        return 0.0

    def _extract_date(self, lines: list[OCRLine]) -> datetime:
        for line in lines[:12]:
            parsed = self._find_date(line.text)
            if parsed:
                return parsed
        return datetime.utcnow()

    def _extract_line_items(self, lines: list[OCRLine], total: float) -> list[LineItem]:
        items: list[LineItem] = []
        seen: set[tuple[str, float]] = set()
        previous_item: LineItem | None = None

        for line in lines:
            text = self._clean_line_text(line.text)
            lower = text.lower()
            if not text:
                continue
            if any(keyword in lower for keyword in TOTAL_KEYWORDS + SUBTOTAL_KEYWORDS):
                continue
            if any(token in lower for token in LINE_ITEM_BLOCKLIST):
                continue
            if self._find_date(text):
                continue
            if self._looks_like_address_or_metadata(text):
                continue
            if self._is_quantity_detail_line(text):
                continue

            parsed_item = self._parse_line_item(text)
            if not parsed_item:
                continue
            name, amount = parsed_item
            if amount is None or amount <= 0:
                continue

            if len(name) < 2:
                continue
            if total and abs(amount - total) < 0.01:
                continue

            key = (name.lower(), round(amount, 2))
            if key in seen:
                continue
            seen.add(key)
            previous_item = LineItem(name=name, price=round(amount, 2))
            items.append(previous_item)

        return items[:20]

    @staticmethod
    def _parse_line_item(text: str) -> tuple[str, float] | None:
        normalized = " ".join(text.split())
        if ReceiptPipeline._is_quantity_detail_line(normalized):
            return None
        qty_first = re.match(r"^\s*(\d+(?:\.\d+)?)\s+(.+?)\s+(\d+(?:\.\d{1,2})?)\s*$", normalized)
        if qty_first:
            _, name, trailing_amount = qty_first.groups()
            cleaned_name = name.strip(" -:|")
            lowered = cleaned_name.lower()
            if cleaned_name and lowered not in {"cash", "change"}:
                return cleaned_name, round(float(trailing_amount), 2)

        amount = ReceiptPipeline._find_trailing_amount(normalized) or ReceiptPipeline._find_amount(normalized)
        if amount is None:
            return None
        name = ReceiptPipeline._strip_trailing_amount(normalized)
        if name == normalized:
            name = ReceiptPipeline._strip_amount_tokens(normalized)
        name = re.sub(r"\b[xX]\s*\d+\b", "", name).strip(" -:|")
        lowered = name.lower()
        if not name or lowered in {"cash", "change"}:
            return None
        return name, round(amount, 2)

    def _layoutlm_extract(self, words: list[OCRWord]) -> dict:
        if not self.processor or not self.model or not words:
            return {}

        # The project is structured to support a fine-tuned LayoutLMv3 checkpoint.
        # When no such checkpoint is configured, this step is intentionally skipped.
        try:  # pragma: no cover
            tokens = [word.text for word in words]
            boxes = [word.box for word in words]
            _ = self.processor(text=tokens, boxes=boxes, truncation=True, return_tensors="pt")
        except Exception:
            return {}
        return {}

    @staticmethod
    def _build_line(words: list[OCRWord]) -> OCRLine:
        ordered = sorted(words, key=lambda word: word.box[0])
        text = " ".join(word.text for word in ordered).strip()
        y_center = sum(ReceiptPipeline._box_center_y(word.box) for word in ordered) / len(ordered)
        return OCRLine(text=text, words=ordered, y_center=y_center)

    @staticmethod
    def _estimate_canvas_size(result: list) -> tuple[float, float]:
        max_x = 1.0
        max_y = 1.0
        for block in result:
            for entry in block:
                polygon = entry[0]
                for point in polygon:
                    max_x = max(max_x, float(point[0]))
                    max_y = max(max_y, float(point[1]))
        return max_x, max_y

    @staticmethod
    def _normalize_box(polygon: list, width: float, height: float) -> list[int]:
        xs = [max(0.0, min(width, float(point[0]))) for point in polygon]
        ys = [max(0.0, min(height, float(point[1]))) for point in polygon]
        left = int(xs and min(xs) / width * 1000 or 0)
        top = int(ys and min(ys) / height * 1000 or 0)
        right = int(xs and max(xs) / width * 1000 or 0)
        bottom = int(ys and max(ys) / height * 1000 or 0)
        return [left, top, right, bottom]

    @staticmethod
    def _box_center_y(box: list[int]) -> float:
        return (box[1] + box[3]) / 2

    @staticmethod
    def _find_amount(text: str) -> float | None:
        matches = re.findall(r"(?:rs\.?|inr|₹)?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})|\d+(?:\.\d{1,2})?)", text, flags=re.IGNORECASE)
        if not matches:
            return None
        values = [float(match.replace(",", "")) for match in matches if match]
        return max(values) if values else None

    @staticmethod
    def _find_trailing_amount(text: str) -> float | None:
        matches = re.findall(r"(?:\$|rs\.?|inr|₹)?\s*(\d+(?:\.\d{1,2})?)\s*(?:tfa)?\s*$", text, flags=re.IGNORECASE)
        if not matches:
            return None
        try:
            return float(matches[-1])
        except ValueError:
            return None

    @staticmethod
    def _find_date(text: str) -> datetime | None:
        cleaned = re.sub(r"[,|]", " ", text)
        candidates = re.findall(
            r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b|\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}\b|\b[A-Za-z]{3,9}\s+\d{1,2}\s+\d{2,4}\b",
            cleaned,
        )
        for candidate in candidates:
            normalized = " ".join(candidate.split())
            for pattern in DATE_PATTERNS:
                try:
                    return datetime.strptime(normalized, pattern)
                except ValueError:
                    continue
        return None

    @staticmethod
    def _parse_iso_date(text: str) -> datetime | None:
        try:
            return datetime.fromisoformat(text.strip())
        except ValueError:
            return None

    @staticmethod
    def _clean_line_text(text: str) -> str:
        cleaned = " ".join(text.split()).strip()
        cleaned = cleaned.strip(" |:-")
        return cleaned

    @staticmethod
    def _looks_like_vendor_name(text: str) -> bool:
        lower = text.lower()
        if any(char.isdigit() for char in text):
            return False
        if any(token in lower for token in LINE_ITEM_BLOCKLIST):
            return False
        return len(text.strip()) >= 3

    @staticmethod
    def _strip_amount_tokens(text: str) -> str:
        text = re.sub(r"(?:rs\.?|inr|₹)\s*\d[\d,]*(?:\.\d{1,2})?", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\b\d[\d,]*(?:\.\d{1,2})?\b", " ", text)
        return " ".join(text.split())

    @staticmethod
    def _strip_trailing_amount(text: str) -> str:
        stripped = re.sub(r"(?:\$|rs\.?|inr|₹)\s*\d+(?:\.\d{1,2})?\s*(?:tfa)?\s*$", "", text, flags=re.IGNORECASE).strip()
        return " ".join(stripped.split())

    @staticmethod
    def _is_quantity_detail_line(text: str) -> bool:
        normalized = " ".join(text.lower().split())
        return bool(
            re.match(r"^\d+\s*(ea|pk|pcs|pc)?\s*@\s*\d+(?:\.\d+)?\s*/?\s*(ea|pk|pcs|pc)?$", normalized)
            or re.match(r"^\d+\s*(ea|pk|pcs|pc)\b", normalized)
        )

    @staticmethod
    def _looks_like_address_or_metadata(text: str) -> bool:
        lower = text.lower()
        if "," in text and any(char.isdigit() for char in text):
            return True
        if re.match(r"^\d+\s+[A-Za-z]{1,4}(?:[-\s]\d+)?$", text):
            return True
        if (
            text.strip().startswith(tuple(str(n) for n in range(10)))
            and len(re.findall(r"[A-Za-z]+", text)) <= 2
            and not re.search(r"\d+\.\d{1,2}\s*$", text)
        ):
            return True
        if re.search(r"\b\d{5}(?:-\d{4})?\b", text):
            return True
        if any(token in lower for token in ["cashier", "lane", "clerk", "trans#", "date", "time", "thanks"]):
            return True
        return False

    @staticmethod
    def _llm_raw_text(payload: dict, line_items: list[LineItem]) -> str:
        pieces: list[str] = []
        vendor = payload.get("vendor")
        date = payload.get("date")
        total = payload.get("total")
        if vendor:
            pieces.append(f"Vendor: {vendor}")
        if date:
            pieces.append(f"Date: {date}")
        if total is not None:
            pieces.append(f"Total: {total}")
        if line_items:
            pieces.append("Items: " + ", ".join(f"{item.name} ({item.price})" for item in line_items))
        return "\n".join(pieces)
