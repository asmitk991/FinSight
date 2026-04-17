from fastapi import APIRouter, Depends

from app.models.schemas import AgentQueryRequest, ExecutiveReportRequest, ReportRequest
from app.services.agent import FinanceAgentService
from app.services.auth import get_current_user_id


router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/query")
async def query_agent(payload: AgentQueryRequest, user_id: str = Depends(get_current_user_id)):
    return FinanceAgentService().query(
        user_id=user_id,
        question=payload.question,
        top_k=payload.top_k,
        start_date=payload.start_date,
        end_date=payload.end_date,
        category=payload.category,
    )


@router.post("/report")
async def generate_report(payload: ReportRequest, user_id: str = Depends(get_current_user_id)):
    return FinanceAgentService().report(user_id, payload.start_date, payload.end_date)


@router.post("/executive-report")
async def generate_executive_report(payload: ExecutiveReportRequest, user_id: str = Depends(get_current_user_id)):
    return FinanceAgentService().executive_report(
        user_id=user_id,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
