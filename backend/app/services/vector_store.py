from __future__ import annotations

import requests
from typing import Any

from app.config import get_settings
from app.models.schemas import TransactionRecord
from app.services.supabase_store import SupabaseStore


class VectorStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.store = SupabaseStore()
        self.api_url = "https://api-inference.huggingface.co/models/sentence-transformers/all-MiniLM-L6-v2"
        self.headers = {"Authorization": f"Bearer {self.settings.hf_api_token}"}

    def _get_embedding(self, text: str) -> list[float] | None:
        if not self.settings.hf_api_token:
            return None
        try:
            response = requests.post(
                self.api_url, 
                headers=self.headers, 
                json={"inputs": text, "options": {"wait_for_model": True}}
            )
            return response.json()
        except Exception:
            return None

    def upsert_transactions(self, user_id: str, transactions: list[TransactionRecord]) -> None:
        if not self.store.client:
            return
            
        for tx in transactions:
            embedding = self._get_embedding(tx.embedding_text)
            if embedding:
                # Update the transaction in Supabase with the vector
                self.store.client.table("transactions").update({
                    "embedding_vector": embedding
                }).eq("id", tx.id).eq("user_id", user_id).execute()

    def delete(self, user_id: str, transaction_id: str) -> None:
        # Deleting the transaction in Supabase handles the vector too
        pass

    def query(
        self,
        user_id: str,
        query_text: str,
        top_k: int = 8,
    ) -> list[str]:
        if not self.store.client:
            return []
            
        embedding = self._get_embedding(query_text)
        if not embedding:
            return []
            
        # Call the Supabase RPC function we created
        response = self.store.client.rpc("match_transactions", {
            "query_embedding": embedding,
            "match_threshold": 0.5,
            "match_count": top_k,
            "p_user_id": user_id
        }).execute()
        
        return [item["id"] for item in response.data]
