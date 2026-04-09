from __future__ import annotations

from datetime import datetime

from app.celery_app import celery_app
from app.models.schemas import ImageJob, ImageJobStatus, TransactionRecord, TransactionSource, TransactionType
from app.services.category import build_embedding_text
from app.services.ocr_layout import ReceiptPipeline
from app.services.transaction_store import ImageJobRepository, TransactionRepository
from app.services.vector_store import VectorStore


def process_receipts_job(job_id: str, image_paths: list[str]) -> dict:
    jobs = ImageJobRepository()
    repository = TransactionRepository()
    vectors = VectorStore()
    pipeline = ReceiptPipeline()

    job = jobs.get(job_id) or ImageJob(id=job_id)
    job.status = ImageJobStatus.processing
    job.updated_at = datetime.utcnow()
    jobs.save(job)

    try:
        results: list[TransactionRecord] = []
        for image_path in image_paths:
            receipt = pipeline.parse_receipt(image_path)
            results.append(
                TransactionRecord(
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
        repository.save_many(results)
        vectors.upsert_transactions(results)
        job.status = ImageJobStatus.completed
        job.results = results
        job.updated_at = datetime.utcnow()
        jobs.save(job)
        return job.model_dump(mode="json")
    except Exception as exc:  # pragma: no cover
        job.status = ImageJobStatus.failed
        job.error = str(exc)
        job.updated_at = datetime.utcnow()
        jobs.save(job)
        raise


@celery_app.task(name="app.tasks.process_receipts")
def process_receipts(job_id: str, image_paths: list[str]) -> dict:
    return process_receipts_job(job_id, image_paths)
