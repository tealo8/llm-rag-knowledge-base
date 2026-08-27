from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest


TEST_ROOT = Path(tempfile.mkdtemp(prefix="zhiyu-tests-"))
os.environ["DATABASE_PATH"] = str(TEST_ROOT / "knowledge-test.db")
os.environ["UPLOAD_DIR"] = str(TEST_ROOT / "uploads")
os.environ["JWT_SECRET"] = "test-secret-not-for-production"
os.environ["APP_ENV"] = "test"
os.environ["DEMO_MODE"] = "true"
os.environ["LLM_PROVIDER"] = "disabled"
os.environ["EMBEDDING_PROVIDER"] = "local"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client
    shutil.rmtree(TEST_ROOT, ignore_errors=True)


@pytest.fixture(scope="session")
def tokens(client):
    accounts = {
        "admin": "admin123",
        "engineer": "engineer123",
        "finance": "finance123",
        "otheradmin": "other123",
    }
    result = {}
    for username, password in accounts.items():
        response = client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )
        assert response.status_code == 200
        result[username] = response.json()["access_token"]
    return result


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
