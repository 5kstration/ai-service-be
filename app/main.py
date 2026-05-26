# app/main.py
import logging
from fastapi import FastAPI
from app.core.error.exception import BusinessException
from app.core.error.handler import business_exception_handler
from app.domain.report.router import router as report_router
from app.domain.recommend.router import router as recommend_router
from app.domain.insight.router import router as insight_router
from app.core.config.sqs import start_consumers
from app.domain.sync.router import router as sync_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="MoneyLog AI Service")

app.add_exception_handler(BusinessException, business_exception_handler)

app.include_router(report_router,    prefix="/api/ai",       tags=["AI Report"])
app.include_router(recommend_router, prefix="/api/recommend", tags=["Recommend"])
app.include_router(insight_router,   prefix="/api/ai",       tags=["Insight"])
app.include_router(sync_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.on_event("startup")
async def startup():
    # SQS consumer 백그라운드 폴링 시작
    # 연결 실패 시 경고 로그만 남기고 앱 시작 계속
    await start_consumers()