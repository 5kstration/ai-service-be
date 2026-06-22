import os
os.environ["DB_USER"] = "test"
os.environ["DB_PASSWORD"] = "test"
os.environ["DB_HOST"] = "localhost"
os.environ["DB_NAME"] = "test"
os.environ["NEO4J_URI"] = "bolt://localhost:7687"
os.environ["NEO4J_PASSWORD"] = "test"
os.environ["REDIS_SENTINEL_HOSTS"] = "localhost:26379"
os.environ["REDIS_SENTINEL_MASTER"] = "mymaster"
os.environ["ANTHROPIC_API_KEY"] = "test_key"

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from app.main import app
from app.core.config.database import get_db
from app.core.middleware.auth import get_current_user
from contextlib import asynccontextmanager

app.router.on_startup.clear()
app.router.on_shutdown.clear()

@asynccontextmanager
async def mock_lifespan(app_):
    yield

app.router.lifespan_context = mock_lifespan

@pytest.fixture(scope="module")
def client():
    def mock_get_current_user():
        return "test_user_id"
    
    def mock_get_db():
        yield MagicMock()

    app.dependency_overrides[get_current_user] = mock_get_current_user
    app.dependency_overrides[get_db] = mock_get_db
    
    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()

# 공통 TestClient Fixture
@pytest.fixture(scope="module")
def client():
    # Dependency Override
    def mock_get_current_user():
        return "test_user_id"
    
    def mock_get_db():
        yield MagicMock()

    app.dependency_overrides[get_current_user] = mock_get_current_user
    app.dependency_overrides[get_db] = mock_get_db
    
    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
