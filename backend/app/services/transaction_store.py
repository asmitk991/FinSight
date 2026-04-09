from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from app.config import get_settings
from app.models.schemas import ImageJob, TransactionRecord
from app.services.category import build_embedding_text, infer_currency_from_text, merchant_key, normalize_category_with_context, normalize_merchant_name
from app.services.merchant_resolver import MerchantResolver
from app.services.ocr_layout import ReceiptPipeline


class JsonStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")

    def read_all(self) -> list[dict]:
        content = self.path.read_text(encoding="utf-8").strip()
        if not content:
            return []
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return []

    def write_all(self, rows: list[dict]) -> None:
        self.path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")


class TransactionRepository:
    def __init__(self) -> None:
        settings = get_settings()
        self.store = JsonStore(settings.data_file)
        self.merchant_resolver = MerchantResolver()

    def list_transactions(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        category: str | None = None,
        source: str | None = None,
    ) -> list[TransactionRecord]:
        items = self._load_clean_transactions()
        results: list[TransactionRecord] = []
        for item in items:
            tx_date = item.date.date()
            if start_date and tx_date < start_date:
                continue
            if end_date and tx_date > end_date:
                continue
            if category and item.category != category:
                continue
            if source and item.source != source:
                continue
            results.append(item)
        return sorted(results, key=lambda tx: tx.date, reverse=True)

    def get(self, transaction_id: str) -> TransactionRecord | None:
        for item in self._load_clean_transactions():
            if item.id == transaction_id:
                return item
        return None

    def save_many(self, transactions: list[TransactionRecord]) -> list[TransactionRecord]:
        input_ids = {tx.id for tx in transactions}
        payload = self.store.read_all()
        payload.extend(self._prepare_transaction(tx).model_dump(mode="json") for tx in transactions)
        cleaned = self._dedupe_transactions([TransactionRecord.model_validate(item) for item in payload])
        self.store.write_all([tx.model_dump(mode="json") for tx in cleaned])
        return [tx for tx in cleaned if tx.id in input_ids]

    def delete(self, transaction_id: str) -> bool:
        payload = self.store.read_all()
        next_payload = [item for item in payload if item["id"] != transaction_id]
        deleted = len(next_payload) != len(payload)
        if deleted:
            self.store.write_all(next_payload)
        return deleted

    def clear(self) -> None:
        self.store.write_all([])

    def _load_clean_transactions(self) -> list[TransactionRecord]:
        raw_items = [TransactionRecord.model_validate(item) for item in self.store.read_all()]
        cleaned = self._dedupe_transactions(raw_items)
        serialized = [tx.model_dump(mode="json") for tx in cleaned]
        if serialized != self.store.read_all():
            self.store.write_all(serialized)
        return cleaned

    def _dedupe_transactions(self, items: list[TransactionRecord]) -> list[TransactionRecord]:
        deduped: dict[tuple[str, str, float, str, str, str | None, str | None], TransactionRecord] = {}
        for item in items:
            prepared = self._prepare_transaction(item)
            fingerprint = self._fingerprint(prepared)
            current = deduped.get(fingerprint)
            if current is None or self._quality_score(prepared) > self._quality_score(current):
                deduped[fingerprint] = prepared
        return sorted(deduped.values(), key=lambda tx: tx.date, reverse=True)

    def _prepare_transaction(self, tx: TransactionRecord) -> TransactionRecord:
        line_items = tx.line_items
        if tx.source.value == "image" and not line_items and tx.raw_text:
            line_items = ReceiptPipeline.infer_line_items_from_raw_text(tx.raw_text, tx.amount)
        currency = tx.currency
        if tx.source.value == "image" and tx.raw_text:
            currency = infer_currency_from_text(tx.raw_text, default=tx.currency)

        profile = self.merchant_resolver.resolve_profile(
            tx.merchant,
            detail_text=tx.detail_text,
            counterparty_type=tx.counterparty_type.value if tx.counterparty_type else None,
            transfer_kind=tx.transfer_kind.value if tx.transfer_kind else None,
        )
        merchant = profile.canonical_name
        category = normalize_category_with_context(
            merchant or tx.merchant,
            tx.category if tx.category not in {"other", "transfer", "self_transfer"} else None,
            [item.name for item in line_items],
            tx.transfer_kind.value if tx.transfer_kind else None,
            tx.counterparty_type.value if tx.counterparty_type else None,
            tx.detail_text,
        )
        if profile.category and profile.confidence >= 0.7:
            category = profile.category
        return tx.model_copy(
            update={
                "merchant": merchant,
                "category": category,
                "currency": currency,
                "line_items": line_items,
                "embedding_text": build_embedding_text(
                    tx.date.strftime("%d %B %Y"),
                    merchant,
                    tx.amount,
                    category,
                    tx.type.value,
                    tx.detail_text,
                    currency,
                ),
            }
        )

    @staticmethod
    def _quality_score(tx: TransactionRecord) -> int:
        merchant = tx.merchant
        score = 0
        if "Paitdo" not in merchant and "Receifvreod" not in merchant:
            score += 100
        if " " in merchant:
            score += 15
        if merchant != merchant.upper():
            score += 10
        if merchant != "Unknown merchant":
            score += 5
        return score

    @staticmethod
    def _fingerprint(tx: TransactionRecord) -> tuple[str, str, float, str, str, str | None, str | None]:
        reference_id = tx.reference_id.strip() if tx.reference_id else None
        if reference_id:
            return (
                tx.source.value,
                reference_id,
                round(tx.amount, 2),
                tx.type.value,
                tx.date.date().isoformat(),
                None,
                None,
            )
        return (
            tx.date.date().isoformat(),
            merchant_key(tx.merchant),
            round(tx.amount, 2),
            tx.type.value,
            tx.source.value,
            tx.time_text,
            None,
        )


class PreviewRepository:
    def __init__(self) -> None:
        settings = get_settings()
        self.store = JsonStore(settings.ingest_preview_file)

    def create(self, preview_id: str, transactions: list[TransactionRecord]) -> None:
        payload = self.store.read_all()
        payload = [item for item in payload if item["preview_id"] != preview_id]
        payload.append(
            {
                "preview_id": preview_id,
                "transactions": [tx.model_dump(mode="json") for tx in transactions],
                "created_at": datetime.utcnow().isoformat(),
            }
        )
        self.store.write_all(payload)

    def get(self, preview_id: str) -> list[TransactionRecord]:
        for item in self.store.read_all():
            if item["preview_id"] == preview_id:
                return [TransactionRecord.model_validate(tx) for tx in item["transactions"]]
        return []

    def delete(self, preview_id: str) -> None:
        payload = [item for item in self.store.read_all() if item["preview_id"] != preview_id]
        self.store.write_all(payload)


class ImageJobRepository:
    def __init__(self) -> None:
        settings = get_settings()
        self.store = JsonStore(settings.image_jobs_file)

    def save(self, job: ImageJob) -> ImageJob:
        payload = [item for item in self.store.read_all() if item["id"] != job.id]
        payload.append(job.model_dump(mode="json"))
        self.store.write_all(payload)
        return job

    def get(self, job_id: str) -> ImageJob | None:
        for item in self.store.read_all():
            if item["id"] == job_id:
                return ImageJob.model_validate(item)
        return None
