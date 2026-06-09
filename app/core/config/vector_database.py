# app/core/config/vector_database.py
import logging
from sqlalchemy import create_engine, URL
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.core.config.settings import settings

logger = logging.getLogger(__name__)

VECTOR_DB_URL = URL.create(
    drivername = "postgresql+psycopg2",
    username   = settings.VECTOR_DB_USER,
    password   = settings.VECTOR_DB_PASSWORD, 
    host       = settings.VECTOR_DB_HOST,
    port       = settings.VECTOR_DB_PORT,
    database   = settings.VECTOR_DB_NAME,
    query      = {"sslmode": "require"},
)

vector_engine = create_engine(
    VECTOR_DB_URL,
    echo=False,
    pool_pre_ping=True,        # 커넥션 사용 전 유효성 체크
    pool_recycle=1800,         # 30분마다 커넥션 재사용
)
VectorSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=vector_engine)


class VectorBase(DeclarativeBase):
    pass


def get_vector_db():
    db = VectorSessionLocal()
    try:
        yield db
    finally:
        db.close()