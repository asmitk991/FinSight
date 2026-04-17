from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.models.schemas import TransactionRecord, TransactionSource
from app.services.category import build_embedding_text, infer_currency_from_text, normalize_category_with_context
from app.services.merchant_resolver import MerchantResolver
from app.services.ocr_layout import ReceiptPipeline
from app.services.supabase_store import SupabaseStore


class TransactionRepository:
    def __init__(self) -> None:
        self.store = SupabaseStore()
        self.merchant_resolver = MerchantResolver()

    def list_transactions(
        self,
        user_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
        category: str | None = None,
        source: str | None = None,
    ) -> list[TransactionRecord]:
        filters = {
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "category": category,
            "source": source,
        }
        rows = self.store.list_transactions(user_id, filters)
        return [TransactionRecord.model_validate(row) for row in rows]

    def get(self, user_id: str, transaction_id: str) -> TransactionRecord | None:
        # For simplicity, we filter the list, but in a real DB we'd use a direct query
        transactions = self.list_transactions(user_id)
        for tx in transactions:
            if tx.id == transaction_id:
                return tx
        return None

    def save_many(self, user_id: str, transactions: list[TransactionRecord]) -> list[TransactionRecord]:
        prepared = [self._prepare_transaction(user_id, tx) for tx in transactions]
        rows = self.store.save_many(prepared)
        return [TransactionRecord.model_validate(row) for row in rows]

    def delete(self, user_id: str, transaction_id: str) -> bool:
        return self.store.delete(user_id, transaction_id)

    def _prepare_transaction(self, user_id: str, tx: TransactionRecord) -> TransactionRecord:
        tx.user_id = user_id
        line_items = tx.line_items
        if tx.source == TransactionSource.image and not line_items and tx.raw_text:
            line_items = ReceiptPipeline.infer_line_items_from_raw_text(tx.raw_text, tx.amount)
        
        currency = tx.currency
        if tx.source == TransactionSource.image and tx.raw_text:
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

        embedding_text = build_embedding_text(
            tx.date.strftime("%d %B %Y"),
            merchant,
            tx.amount,
            category,
            tx.type.value,
            tx.detail_text,
            currency,
        )

        return tx.model_copy(
            update={
                "merchant": merchant,
                "category": category,
                "currency": currency,
                "line_items": line_items,
                "embedding_text": embedding_text,
                "user_id": user_id,
            }
        )


class PreviewRepository:
    def __init__(self) -> None:
        self.store = SupabaseStore()

    def create(self, user_id: str, preview_id: str, transactions: list[TransactionRecord]) -> None:
        if not self.store.client:
            return
        payload = {
            "preview_id": preview_id,
            "user_id": user_id,
            "transactions": [tx.model_dump(mode="json") for tx in transactions],
        }
        self.store.client.table("previews").upsert(payload).execute()

    def get(self, user_id: str, preview_id: str) -> list[TransactionRecord]:
        if not self.store.client:
            return []
        response = (
            self.store.client.table("previews")
            .select("transactions")
            .eq("preview_id", preview_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not response.data:
            return []
        return [TransactionRecord.model_validate(tx) for tx in response.data[0]["transactions"]]

    def delete(self, user_id: str, preview_id: str) -> None:
        if not self.store.client:
            return
        self.store.client.table("previews").delete().eq("preview_id", preview_id).eq("user_id", user_id).execute()


class ImageJobRepository:
    def __init__(self) -> None:
        self.store = SupabaseStore()

    def save(self, user_id: str, job_id: str, status: str, results: list[TransactionRecord] | None = None, error: str | None = None) -> None:
        if not self.store.client:
            return
        payload = {
            "id": job_id,
            "user_id": user_id,
            "status": status,
            "results": [tx.model_dump(mode="json") for tx in results] if results else None,
            "error": error,
            "updated_at": datetime.utcnow().isoformat(),
        }
        self.store.client.table("image_jobs").upsert(payload).execute()

    def get(self, user_id: str, job_id: str) -> dict | None:
        if not self.store.client:
            return None
        response = (
            self.store.client.table("image_jobs")
            .select("*")
            .eq("id", job_id)
            .eq("user_id", user_id)
            .execute()
        )
        return response.data[0] if response.data else None
