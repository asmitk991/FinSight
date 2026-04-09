from __future__ import annotations

from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import get_settings
from app.models.schemas import TransactionRecord

try:
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
except ImportError:
    GoogleGenerativeAIEmbeddings = None


class VectorStore:
    def __init__(self) -> None:
        settings = get_settings()
        self.client = chromadb.PersistentClient(
            path=str(settings.chroma_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(name=settings.chroma_collection)
        
        self.embedding_function = None
        if GoogleGenerativeAIEmbeddings and settings.gemini_api_key:
            try:
                self.embedding_function = GoogleGenerativeAIEmbeddings(
                    model="models/embedding-001",
                    google_api_key=settings.gemini_api_key
                )
            except Exception:
                self.embedding_function = None

    def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        if not self.embedding_function:
            return None
        try:
            return self.embedding_function.embed_documents(texts)
        except Exception:
            return None

    def upsert_transactions(self, transactions: list[TransactionRecord]) -> None:
        embeddings = self.embed_texts([tx.embedding_text for tx in transactions])
        self.collection.upsert(
            ids=[tx.id for tx in transactions],
            documents=[tx.embedding_text for tx in transactions],
            embeddings=embeddings,
            metadatas=[
                {
                    "date": tx.date.date().isoformat(),
                    "merchant": tx.merchant,
                    "amount": tx.amount,
                    "currency": tx.currency,
                    "category": tx.category,
                    "type": tx.type.value,
                    "source": tx.source.value,
                    "direction": tx.direction.value if tx.direction else "",
                    "transfer_kind": tx.transfer_kind.value if tx.transfer_kind else "",
                    "counterparty_type": tx.counterparty_type.value if tx.counterparty_type else "",
                }
                for tx in transactions
            ],
        )

    def delete(self, transaction_id: str) -> None:
        self.collection.delete(ids=[transaction_id])

    def reset(self) -> None:
        settings = get_settings()
        try:
            self.client.delete_collection(settings.chroma_collection)
        except Exception:
            pass
        self.collection = self.client.get_or_create_collection(name=settings.chroma_collection)

    def query(
        self,
        query_text: str,
        top_k: int = 8,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[str]:
        # If we have a custom embedding function, we must use it to embed the query manually
        # as Chroma's default internal function might not match.
        query_embeddings = self.embed_texts([query_text])
        
        result = self.collection.query(
            query_embeddings=query_embeddings,
            query_texts=[query_text] if not query_embeddings else None,
            n_results=top_k,
            where=metadata_filter or None,
        )
        return result.get("ids", [[]])[0]
