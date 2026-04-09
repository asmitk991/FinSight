from fastapi import APIRouter

from app.models.schemas import AgentQueryRequest, ExecutiveReportRequest, ReportRequest
from app.services.agent import FinanceAgentService


router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/query")
async def query_agent(payload: AgentQueryRequest):
    return FinanceAgentService().query(
        question=payload.question,
        top_k=payload.top_k,
        start_date=payload.start_date,
        end_date=payload.end_date,
        category=payload.category,
    )


@router.post("/report")
async def generate_report(payload: ReportRequest):
    return FinanceAgentService().report(payload.start_date, payload.end_date)


@router.post("/executive-report")
async def generate_executive_report(payload: ExecutiveReportRequest):
    return FinanceAgentService().executive_report(
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
