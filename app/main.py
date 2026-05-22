# app/main.py
from fastapi import FastAPI
from app.core.error.exception import BusinessException
from app.core.error.handler import business_exception_handler
from app.domain.report.router import router as report_router
from app.domain.recommend.router import router as recommend_router
from app.domain.insight.router import router as insight_router
from app.core.config.nats import start_consumers  # 이게 빠진 거야

app = FastAPI(title="MoneyLog AI Service")

app.add_exception_handler(BusinessException, business_exception_handler)

app.include_router(report_router,    prefix="/api/ai",       tags=["AI Report"])
app.include_router(recommend_router, prefix="/api/recommend", tags=["Recommend"])
app.include_router(insight_router,   prefix="/api/ai",       tags=["Insight"])


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.on_event("startup")
async def startup():
    await start_consumers()