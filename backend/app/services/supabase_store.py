from __future__ import annotations

from typing import Any

from supabase import Client, create_client

from app.config import get_settings
from app.models.schemas import TransactionRecord


class SupabaseStore:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.supabase_url or not settings.supabase_service_role_key:
            self.client = None
            return
        self.client: Client = create_client(
            settings.supabase_url, settings.supabase_service_role_key
        )

    def list_transactions(self, user_id: str, filters: dict[str, Any] | None = None) -> list[dict]:
        if not self.client:
            return []
        
        query = self.client.table("transactions").select("*").eq("user_id", user_id)
        
        if filters:
            if filters.get("start_date"):
                query = query.gte("date", filters["start_date"])
            if filters.get("end_date"):
                query = query.lte("date", filters["end_date"])
            if filters.get("category"):
                query = query.eq("category", filters["category"])
            if filters.get("source"):
                query = query.eq("source", filters["source"])
        
        response = query.order("date", desc=True).execute()
        return response.data

    def match_transactions(self, user_id: str, query_embedding: list[float], match_threshold: float = 0.70, match_count: int = 15) -> list[dict]:
        if not self.client:
            return []
        
        response = self.client.rpc(
            'match_transactions',
            {
                'query_embedding': query_embedding,
                'match_threshold': match_threshold,
                'match_count': match_count,
                'p_user_id': user_id
            }
        ).execute()
        return response.data

    def save_many(self, transactions: list[TransactionRecord]) -> list[dict]:
        if not self.client or not transactions:
            return []
        
        payload = [tx.model_dump(mode="json") for tx in transactions]
        # We use upsert to avoid duplicates if reference_id is present
        # In Supabase, we need a unique constraint for upsert to work effectively
        # For now, we'll just insert
        response = self.client.table("transactions").insert(payload).execute()
        return response.data

    def delete(self, user_id: str, transaction_id: str) -> bool:
        if not self.client:
            return False
        
        response = (
            self.client.table("transactions")
            .delete()
            .eq("id", transaction_id)
            .eq("user_id", user_id)
            .execute()
        )
        return len(response.data) > 0

    def delete_all(self, user_id: str) -> None:
        """Delete all transactions for a user in a single query — O(1) regardless of count."""
        if not self.client:
            return
        self.client.table("transactions").delete().eq("user_id", user_id).execute()

    def get_merchants(self, user_id: str) -> list[str]:
        if not self.client:
            return []
        
        response = (
            self.client.table("transactions")
            .select("merchant")
            .eq("user_id", user_id)
            .execute()
        )
        return list(set(item["merchant"] for item in response.data))
