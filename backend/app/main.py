from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers.agent import router as agent_router
from app.routers.ingestion import router as ingestion_router
from app.routers.transactions import router as transactions_router


settings = get_settings()
app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingestion_router, prefix=settings.api_prefix)
app.include_router(transactions_router, prefix=settings.api_prefix)
app.include_router(agent_router, prefix=settings.api_prefix)


@app.get("/health")
async def healthcheck():
    return {"status": "ok"}
