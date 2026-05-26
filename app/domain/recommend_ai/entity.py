# app/domain/recommend_ai/entity.py
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from app.core.config.vector_database import VectorBase


class ProductEmbedding(VectorBase):
    """상품 임베딩 벡터 저장."""
    __tablename__ = "product_embedding"

    id           = Column(String(26),  primary_key=True, nullable=False)
    product_id   = Column(String(26),  nullable=False)
    product_type = Column(String(20),  nullable=False)  # card, insurance, policy
    embedding    = Column(Vector(1536), nullable=True)
    content      = Column(Text,         nullable=True)  # 임베딩한 원본 텍스트
    created_at   = Column(DateTime,     nullable=False, server_default=func.now())