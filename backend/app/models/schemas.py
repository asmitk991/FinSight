from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class TransactionType(str, Enum):
    debit = "debit"
    credit = "credit"


class TransactionSource(str, Enum):
    pdf = "pdf"
    image = "image"


class TransactionDirection(str, Enum):
    sent = "sent"
    received = "received"


class TransferKind(str, Enum):
    self_transfer = "self_transfer"
    person = "person"
    merchant = "merchant"
    reward = "reward"
    bank = "bank"
    unknown = "unknown"


class CounterpartyType(str, Enum):
    person = "person"
    business = "business"
    bank_account = "bank_account"
    reward = "reward"
    unknown = "unknown"


class LineItem(BaseModel):
    name: str
    price: float | None = None


class TransactionBase(BaseModel):
    date: datetime
    merchant: str
    amount: float
    currency: str = "INR"
    type: TransactionType
    category: str
    source: TransactionSource
    reference_id: str | None = None
    time_text: str | None = None
    detail_text: str | None = None
    direction: TransactionDirection | None = None
    transfer_kind: TransferKind | None = None
    counterparty_type: CounterpartyType | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    raw_text: str
    embedding_text: str
    user_id: str | None = None


class TransactionRecord(TransactionBase):
    id: str = Field(default_factory=lambda: str(uuid4()))


class ParsedTransaction(BaseModel):
    date: datetime
    merchant: str
    amount: float
    type: TransactionType
    reference_id: str | None = None
    time_text: str | None = None
    detail_text: str | None = None
    direction: TransactionDirection | None = None
    transfer_kind: TransferKind | None = None
    counterparty_type: CounterpartyType | None = None
    raw_category: str | None = None
    raw_text: str
    user_id: str | None = None


class PdfPreviewResponse(BaseModel):
    preview_id: str
    transactions: list[TransactionRecord]


class ConfirmPreviewRequest(BaseModel):
    preview_id: str
    transaction_ids: list[str] | None = None


class ReceiptExtraction(BaseModel):
    vendor: str
    date: datetime
    total: float
    currency: str = "INR"
    line_items: list[LineItem] = Field(default_factory=list)
    raw_text: str
    category: str


class ImageJobStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class ImageJob(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    status: ImageJobStatus = ImageJobStatus.queued
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    results: list[TransactionRecord] = Field(default_factory=list)
    error: str | None = None


class TransactionFilters(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    category: str | None = None
    source: TransactionSource | None = None


class AgentQueryRequest(BaseModel):
    question: str
    top_k: int = 8
    start_date: date | None = None
    end_date: date | None = None
    category: str | None = None


class AgentQueryResponse(BaseModel):
    answer: str
    supporting_transactions: list[TransactionRecord]
    metrics: dict[str, Any] = Field(default_factory=dict)


class ReportRequest(BaseModel):
    start_date: date
    end_date: date


class CategoryBreakdown(BaseModel):
    category: str
    total: float
    percentage: float


class MerchantBreakdown(BaseModel):
    merchant: str
    total: float
    count: int


class ReportResponse(BaseModel):
    start_date: date
    end_date: date
    total_spend: float
    category_breakdown: list[CategoryBreakdown]
    top_merchants: list[MerchantBreakdown]
    largest_transactions: list[TransactionRecord]
    anomalies: list[TransactionRecord]
    narrative: str
    supporting_transactions: list[TransactionRecord]


class ExecutiveReportRequest(BaseModel):
    start_date: date | None = None
    end_date: date | None = None


class ExecutiveReportResponse(BaseModel):
    headline: str
    overview: str
    behavioral_insights: list[str]
    recommendations: list[str]
    health_score: int
    health_label: str
    period_label: str = ""
    total_spend: float = 0.0
    top_category: str = ""
    top_merchant: str = ""
