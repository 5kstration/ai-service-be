# app/main.py
import logging
from fastapi import FastAPI
from app.core.error.exception import BusinessException
from app.core.error.handler import business_exception_handler
from app.domain.report.router import router as report_router
from app.domain.recommend.router import router as recommend_router
from app.domain.insight.router import router as insight_router
from app.domain.recommend_ai.router import router as recommend_ai_router
from app.core.config.nats import start_consumers
from app.core.config.scheduler import setup_scheduler
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="MoneyLog AI Service")

app.add_exception_handler(BusinessException, business_exception_handler)

app.include_router(report_router,       prefix="/api/ai",          tags=["AI Report"])
app.include_router(recommend_router,    prefix="/api/recommend",   tags=["Recommend"])
app.include_router(insight_router,      prefix="/api/ai",          tags=["Insight"])
app.include_router(recommend_ai_router,                             tags=["Recommend AI"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.on_event("startup")
async def startup():
    # Vector DB 테이블 생성
    from app.core.config.vector_database import VectorBase, vector_engine
    from app.domain.recommend_ai.entity import ProductEmbedding  # noqa
    VectorBase.metadata.create_all(bind=vector_engine)

    await start_consumers()
    setup_scheduler()


@app.on_event("shutdown")
async def shutdown():
    # 외부 클라이언트 종료
    try:
        from app.core.client.neo4j_client import neo4j_client
        neo4j_client.close()
    except Exception as e:
        logging.error(f"Neo4j client close failed: {e}")

    from app.core.config.scheduler import scheduler
    if scheduler.running:
        scheduler.shutdown(wait=False)
