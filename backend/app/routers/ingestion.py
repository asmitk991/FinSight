from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile

from app.models.schemas import ConfirmPreviewRequest, ImageJob, ImageJobStatus, PdfPreviewResponse
from app.config import get_settings
from app.services.pdf_ingestion import PdfIngestionService
from app.services.transaction_store import ImageJobRepository, PreviewRepository, TransactionRepository
from app.services.vector_store import VectorStore
from app.tasks import process_receipts, process_receipts_job


router = APIRouter(prefix="/ingest", tags=["ingestion"])


@router.post("/pdf", response_model=PdfPreviewResponse)
async def ingest_pdf(file: UploadFile = File(...)) -> PdfPreviewResponse:
    suffix = Path(file.filename or "statement.pdf").suffix or ".pdf"
    with NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_file.write(await file.read())
        temp_path = temp_file.name
    return PdfIngestionService().extract_preview(temp_path)


@router.post("/pdf/confirm")
async def confirm_pdf_preview(payload: ConfirmPreviewRequest):
    previews = PreviewRepository()
    repository = TransactionRepository()
    vectors = VectorStore()
    preview_transactions = previews.get(payload.preview_id)
    if not preview_transactions:
        raise HTTPException(status_code=404, detail="Preview not found")
    selected = preview_transactions
    if payload.transaction_ids:
        allowed = set(payload.transaction_ids)
        selected = [tx for tx in preview_transactions if tx.id in allowed]
    saved = repository.save_many(selected)
    vectors.upsert_transactions(saved)
    previews.delete(payload.preview_id)
    return {"saved": len(saved), "transactions": [tx.model_dump(mode="json") for tx in saved]}


@router.post("/image")
async def ingest_images(background_tasks: BackgroundTasks, files: list[UploadFile] = File(...)):
    settings = get_settings()
    image_paths: list[str] = []
    for file in files:
        suffix = Path(file.filename or "receipt.jpg").suffix or ".jpg"
        with NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(await file.read())
            image_paths.append(temp_file.name)

    job = ImageJob(id=str(uuid4()), status=ImageJobStatus.queued)
    ImageJobRepository().save(job)
    if settings.use_celery_for_images:
        try:
            process_receipts.delay(job.id, image_paths)
        except Exception:
            background_tasks.add_task(process_receipts_job, job.id, image_paths)
    else:
        background_tasks.add_task(process_receipts_job, job.id, image_paths)
    return {"job_id": job.id, "status": job.status}


@router.get("/image/jobs/{job_id}")
async def get_image_job(job_id: str):
    job = ImageJobRepository().get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
