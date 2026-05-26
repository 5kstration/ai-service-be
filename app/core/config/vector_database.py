# app/core/config/vector_database.py
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.core.config.settings import settings

logger = logging.getLogger(__name__)

VECTOR_DB_URL = (
    f"postgresql+psycopg2://"
    f"{settings.VECTOR_DB_USER}:{settings.VECTOR_DB_PASSWORD}"
    f"@{settings.VECTOR_DB_HOST}:{settings.VECTOR_DB_PORT}"
    f"/{settings.VECTOR_DB_NAME}"
    f"?sslmode=require"
)

vector_engine       = create_engine(VECTOR_DB_URL, echo=False)
VectorSessionLocal  = sessionmaker(autocommit=False, autoflush=False, bind=vector_engine)


class VectorBase(DeclarativeBase):
    pass


def get_vector_db():
    db = VectorSessionLocal()
    try:
        yield db
    finally:
        db.close()