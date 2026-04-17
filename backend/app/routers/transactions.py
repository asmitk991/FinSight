from datetime import date
from fastapi import APIRouter, Depends, HTTPException

from app.models.schemas import TransactionSource
from app.services.auth import get_current_user_id
from app.services.transaction_store import TransactionRepository
from app.services.vector_store import VectorStore


router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("")
async def list_transactions(
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
    source: TransactionSource | None = None,
    user_id: str = Depends(get_current_user_id),
):
    repository = TransactionRepository()
    return repository.list_transactions(
        user_id=user_id,
        start_date=None if not start_date else date.fromisoformat(start_date),
        end_date=None if not end_date else date.fromisoformat(end_date),
        category=category,
        source=source,
    )


@router.delete("/{transaction_id}")
async def delete_transaction(transaction_id: str, user_id: str = Depends(get_current_user_id)):
    repository = TransactionRepository()
    deleted = repository.delete(user_id, transaction_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Transaction not found")
    VectorStore().delete(user_id, transaction_id)
    return {"deleted": True}


@router.delete("")
async def clear_transactions(user_id: str = Depends(get_current_user_id)):
    # In a real app, you might not want to allow clearing everything
    # But for this implementation, we scope it to the current user
    repository = TransactionRepository()
    transactions = repository.list_transactions(user_id)
    for tx in transactions:
        repository.delete(user_id, tx.id)
        VectorStore().delete(user_id, tx.id)
    return {"deleted": "all_user_data"}
