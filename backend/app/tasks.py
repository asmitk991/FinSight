from __future__ import annotations

from datetime import datetime

from app.celery_app import celery_app
from app.models.schemas import ImageJob, ImageJobStatus, TransactionRecord, TransactionSource, TransactionType
from app.services.category import build_embedding_text
from app.services.ocr_layout import ReceiptPipeline
from app.services.transaction_store import ImageJobRepository, TransactionRepository
from app.services.vector_store import VectorStore


def process_receipts_job(user_id: str, job_id: str, image_paths: list[str]) -> dict:
    jobs = ImageJobRepository()
    repository = TransactionRepository()
    vectors = VectorStore()
    pipeline = ReceiptPipeline()

    jobs.save(user_id, job_id, ImageJobStatus.processing)

    try:
        results: list[TransactionRecord] = []
        for image_path in image_paths:
            receipt = pipeline.parse_receipt(image_path)
            results.append(
                TransactionRecord(
                    user_id=user_id,
                    date=receipt.date,
                    merchant=receipt.vendor,
                    amount=receipt.total,
                    currency=receipt.currency,
                    type=TransactionType.debit,
                    category=receipt.category,
                    source=TransactionSource.image,
                    line_items=receipt.line_items,
                    raw_text=receipt.raw_text,
                    embedding_text=build_embedding_text(
                        receipt.date.strftime("%d %B %Y"),
                        receipt.vendor,
                        receipt.total,
                        receipt.category,
                        "debit",
                        None,
                        receipt.currency,
                    ),
                )
            )
        saved = repository.save_many(user_id, results)
        vectors.upsert_transactions(user_id, saved)
        jobs.save(user_id, job_id, ImageJobStatus.completed, results=saved)
        return {"id": job_id, "status": ImageJobStatus.completed, "results": [tx.model_dump(mode="json") for tx in saved]}
    except Exception as exc:  # pragma: no cover
        jobs.save(user_id, job_id, ImageJobStatus.failed, error=str(exc))
        raise


@celery_app.task(name="app.tasks.process_receipts")
def process_receipts(user_id: str, job_id: str, image_paths: list[str]) -> dict:
    return process_receipts_job(user_id, job_id, image_paths)
