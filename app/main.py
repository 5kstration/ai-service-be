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

# OpenTelemetry 설정
try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    import os

    # 리소스 설정 (서비스 이름 등)
    service_name = os.getenv("OTEL_SERVICE_NAME", "ai-service")
    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)
    
    # OTLP Exporter 설정 (환경변수 OTEL_EXPORTER_OTLP_ENDPOINT 사용)
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    
    trace.set_tracer_provider(provider)
    
    # FastAPI 앱 계측
    FastAPIInstrumentor.instrument_app(app)
    logging.info("OpenTelemetry instrumentation applied successfully.")
except ImportError as e:
    logging.warning(f"OpenTelemetry packages not found, skipping instrumentation. Error: {e}")



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
