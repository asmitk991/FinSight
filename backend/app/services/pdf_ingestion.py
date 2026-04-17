from __future__ import annotations

import re
from datetime import datetime
from uuid import uuid4

import fitz

from app.models.schemas import (
    CounterpartyType,
    ParsedTransaction,
    PdfPreviewResponse,
    TransactionDirection,
    TransactionRecord,
    TransactionSource,
    TransactionType,
    TransferKind,
)
from app.services.category import build_embedding_text, normalize_category_with_context
from app.services.llm import LlmService
from app.services.merchant_resolver import MerchantResolver
from app.services.transaction_store import PreviewRepository
from fastapi import HTTPException


class PdfIngestionService:
    def __init__(self) -> None:
        self.merchant_resolver = MerchantResolver()
        self.preview_repository = PreviewRepository()
        self.llm_service = LlmService()

    def extract_preview(self, user_id: str, file_path: str) -> PdfPreviewResponse:
        parsed = self._extract_transactions(file_path)
        transactions: list[TransactionRecord] = []
        for item in parsed:
            profile = self.merchant_resolver.resolve_profile(
                item.merchant,
                detail_text=item.detail_text,
                counterparty_type=item.counterparty_type.value if item.counterparty_type else None,
                transfer_kind=item.transfer_kind.value if item.transfer_kind else None,
            )
            resolved_merchant = profile.canonical_name
            category = normalize_category_with_context(
                resolved_merchant,
                item.raw_category,
                [],
                item.transfer_kind.value if item.transfer_kind else None,
                item.counterparty_type.value if item.counterparty_type else None,
                item.detail_text,
            )
            profile_locked = bool(profile.category and profile.confidence >= 0.7)
            if profile_locked:
                category = profile.category
            transactions.append(
                TransactionRecord(
                    user_id=user_id,
                    date=item.date,
                    merchant=resolved_merchant,
                    amount=item.amount,
                    currency="INR",
                    type=item.type,
                    category=category,
                    source=TransactionSource.pdf,
                    reference_id=item.reference_id,
                    time_text=item.time_text,
                    detail_text=item.detail_text,
                    direction=item.direction,
                    transfer_kind=item.transfer_kind,
                    counterparty_type=item.counterparty_type,
                    line_items=[],
                    raw_text=item.raw_text,
                    embedding_text=build_embedding_text(
                        item.date.strftime("%d %B %Y"),
                        resolved_merchant,
                        item.amount,
                        category,
                        item.type.value,
                        item.detail_text,
                        "INR",
                    ),
                )
            )

        preview_id = str(uuid4())
        self.preview_repository.create(user_id, preview_id, transactions)
        return PdfPreviewResponse(preview_id=preview_id, transactions=transactions)

    def _extract_transactions(self, file_path: str) -> list[ParsedTransaction]:
        parsed = self._extract_transactions_from_blocks(file_path)
        if parsed:
            return parsed
        rows = self._extract_rows(file_path)
        if not rows:
            raise HTTPException(
                status_code=400, 
                detail="Extraction failed. Ensure your PDF contains valid transaction history and try again."
            )
        return self.llm_service.parse_pdf_rows(rows)

    @staticmethod
    def _extract_rows(file_path: str) -> list[str]:
        rows: list[str] = []
        date_pattern = re.compile(
            r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}\b|\b\d{1,2}[A-Za-z]{3,9}\d,\d{3}\b"
        )
        amount_pattern = re.compile(r"(?:₹|Rs\.?\s*)\s*[\d,]+(?:\.\d{1,2})?")
        transaction_word_pattern = re.compile(
            r"\b(?:paid|received|debited|credited|paitdo|receifvreod)\b",
            flags=re.IGNORECASE,
        )
        with fitz.open(file_path) as document:
            for page in document:
                lines = PdfIngestionService._extract_lines_from_page(page)
                candidates = PdfIngestionService._build_candidate_rows(lines)
                for candidate in candidates:
                    normalized = " ".join(candidate.split())
                    if not normalized:
                        continue
                    if (
                        date_pattern.search(normalized)
                        and amount_pattern.search(normalized)
                        and transaction_word_pattern.search(normalized)
                        and not PdfIngestionService._looks_like_statement_summary(normalized)
                    ):
                        rows.append(normalized)
        deduped_rows: list[str] = []
        seen: set[str] = set()
        for row in rows:
            if row not in seen:
                seen.add(row)
                deduped_rows.append(row)
        return deduped_rows

    @staticmethod
    def _extract_transactions_from_blocks(file_path: str) -> list[ParsedTransaction]:
        parsed: list[ParsedTransaction] = []
        date_pattern = re.compile(r"^\d{1,2}\s+[A-Za-z]{3},\s+\d{4}$")
        amount_pattern = re.compile(r"₹\s*([\d,]+(?:\.\d{1,2})?)")
        time_pattern = re.compile(r"^\d{1,2}:\d{2}\s+[AP]M$", flags=re.IGNORECASE)
        detail_pattern = re.compile(r"^(Paid to|Received from|Self transfer to)\s+(.+)$", flags=re.IGNORECASE | re.DOTALL)
        reference_pattern = re.compile(r"UPI Transaction ID:\s*([A-Za-z0-9]+)", flags=re.IGNORECASE)

        with fitz.open(file_path) as document:
            for page in document:
                blocks = []
                for block in page.get_text("blocks", sort=True):
                    text = block[4] if len(block) > 4 else ""
                    text = " ".join(text.split())
                    if text:
                        blocks.append(text)

                index = 0
                while index < len(blocks):
                    text = blocks[index]
                    if not date_pattern.match(text):
                        index += 1
                        continue

                    window = blocks[index : index + 6]
                    detail_text = next((item for item in window if detail_pattern.match(item)), None)
                    amount_text = next((item for item in window if amount_pattern.search(item)), None)
                    time_text = next((item for item in window if time_pattern.match(item)), None)
                    reference_text = next((item for item in window if reference_pattern.search(item)), None)

                    if not detail_text or not amount_text:
                        index += 1
                        continue

                    detail_match = detail_pattern.match(detail_text)
                    if not detail_match:
                        index += 1
                        continue

                    tx_type = (
                        TransactionType.debit
                        if detail_match.group(1).lower().startswith(("paid", "self transfer"))
                        else TransactionType.credit
                    )
                    detail_prefix = detail_match.group(1).strip()
                    merchant = detail_match.group(2).strip()
                    amount_match = amount_pattern.search(amount_text)
                    if not amount_match:
                        index += 1
                        continue
                    reference_match = reference_pattern.search(reference_text or "")
                    direction, transfer_kind, counterparty_type = PdfIngestionService._infer_transaction_semantics(
                        detail_prefix,
                        merchant,
                    )

                    raw_text_parts = [text]
                    if time_text:
                        raw_text_parts.append(time_text)
                    raw_text_parts.extend(item for item in window if item not in raw_text_parts)

                    parsed.append(
                        ParsedTransaction(
                            date=PdfIngestionService._coerce_google_pay_datetime(text, time_text),
                            merchant=merchant,
                            amount=abs(float(amount_match.group(1).replace(",", ""))),
                            type=tx_type,
                            reference_id=reference_match.group(1) if reference_match else None,
                            time_text=time_text,
                            detail_text=f"{detail_prefix} {merchant}",
                            direction=direction,
                            transfer_kind=transfer_kind,
                            counterparty_type=counterparty_type,
                            raw_category=None,
                            raw_text=" | ".join(raw_text_parts),
                        )
                    )
                    index += 1

        deduped: list[ParsedTransaction] = []
        seen_keys: set[tuple[str, str, float, str, str | None]] = set()
        for item in parsed:
            key = (item.date.isoformat(), item.merchant.lower(), item.amount, item.type.value, item.reference_id)
            if key not in seen_keys:
                seen_keys.add(key)
                deduped.append(item)
        return deduped

    @staticmethod
    def _extract_lines_from_page(page: fitz.Page) -> list[str]:
        lines: list[str] = []

        blocks = page.get_text("blocks", sort=True)
        for block in blocks:
            text = block[4] if len(block) > 4 else ""
            if not text:
                continue
            lines.extend(segment.strip() for segment in text.splitlines() if segment.strip())

        if not lines:
            text = page.get_text("text", sort=True)
            lines.extend(segment.strip() for segment in text.splitlines() if segment.strip())

        deduped_lines: list[str] = []
        seen: set[str] = set()
        for line in lines:
            if line not in seen:
                seen.add(line)
                deduped_lines.append(line)
        return deduped_lines

    @staticmethod
    def _build_candidate_rows(lines: list[str]) -> list[str]:
        candidates: list[str] = []
        for index, line in enumerate(lines):
            candidates.append(line)
            if index + 1 < len(lines):
                candidates.append(f"{line} {lines[index + 1]}")
            if index + 2 < len(lines):
                candidates.append(f"{line} {lines[index + 1]} {lines[index + 2]}")
        return candidates

    @staticmethod
    def _looks_like_statement_summary(text: str) -> bool:
        lower = text.lower()
        if "statement period" in lower or "transaction period" in lower:
            return True
        if "sent received" in lower:
            return True
        if lower.count("march 2026") >= 2 or lower.count("mar2026") >= 2:
            return True
        date_occurrences = len(
            re.findall(
                r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}\b|\b\d{1,2}[A-Za-z]{3,9}\d,\d{3}\b",
                text,
            )
        )
        amount_occurrences = len(re.findall(r"(?:₹|Rs\.?\s*)\s*[\d,]+(?:\.\d{1,2})?", text))
        return date_occurrences > 1 and amount_occurrences > 1

    @staticmethod
    def _coerce_google_pay_datetime(date_text: str, time_text: str | None):
        # Handle unpadded days like '9 Apr, 2026' -> '09 Apr, 2026'
        clean_date = re.sub(r"\b(\d)\b", r"0\1", date_text)
        try:
            parsed_date = datetime.strptime(clean_date, "%d %b, %Y")
        except ValueError:
            # Fallback for different variations (e.g. without comma)
            try:
                parsed_date = datetime.strptime(clean_date.replace(",", ""), "%d %b %Y")
            except ValueError:
                # Last resort fallback to now
                parsed_date = datetime.utcnow()
                
        if time_text:
            try:
                parsed_time = datetime.strptime(time_text, "%I:%M %p")
                return parsed_date.replace(hour=parsed_time.hour, minute=parsed_time.minute)
            except ValueError:
                pass
        return parsed_date

    @staticmethod
    def _infer_transaction_semantics(detail_prefix: str, merchant: str):
        prefix = detail_prefix.lower()
        normalized_merchant = merchant.lower()
        if prefix.startswith("self transfer"):
            return (
                TransactionDirection.sent,
                TransferKind.self_transfer,
                CounterpartyType.bank_account,
            )
        if "google pay rewards" in normalized_merchant:
            return (
                TransactionDirection.received if prefix.startswith("received") else TransactionDirection.sent,
                TransferKind.reward,
                CounterpartyType.reward,
            )
        if prefix.startswith("received"):
            if PdfIngestionService._looks_like_person_name(merchant):
                return (
                    TransactionDirection.received,
                    TransferKind.person,
                    CounterpartyType.person,
                )
            return (
                TransactionDirection.received,
                TransferKind.merchant,
                CounterpartyType.business,
            )
        if prefix.startswith("paid"):
            if PdfIngestionService._looks_like_person_name(merchant):
                return (
                    TransactionDirection.sent,
                    TransferKind.person,
                    CounterpartyType.person,
                )
            return (
                TransactionDirection.sent,
                TransferKind.merchant,
                CounterpartyType.business,
            )
        return (None, TransferKind.unknown, CounterpartyType.unknown)

    @staticmethod
    def _looks_like_person_name(value: str) -> bool:
        lowered = value.lower()
        business_hints = [
            "limited",
            "private",
            "india",
            "bank",
            "systems",
            "global",
            "irctc",
            "netflix",
            "spotify",
            "uber",
            "google",
            "coffee day",
            "snapmint",
            "linkedin",
            "airtel",
            "go grab",
            "gograb",
            "chai adda",
            "solution",
            "solutions",
            "stuff",
            "rishihood",
        ]
        if any(hint in lowered for hint in business_hints):
            return False
        tokens = [token for token in re.split(r"\s+", value.strip()) if token]
        if not tokens or len(tokens) > 4:
            return False
        if len(tokens) == 1:
            token = tokens[0]
            return token[:1].isupper() and token[1:].islower()
        return all(token[:1].isupper() and token[1:].islower() for token in tokens)
