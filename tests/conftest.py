"""Shared test fixtures."""

import logging
import urllib.request
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def _quiet_noisy_loggers():
    # .env.local sets LOG_LEVEL=DEEP_DEBUG, which enables very chatty driver logs
    # (and a teardown race in pymongo's monitor thread). Silence them for tests.
    for name in ("pymongo", "botocore", "boto3", "urllib3", "s3transfer"):
        logging.getLogger(name).setLevel(logging.WARNING)


@pytest.fixture(scope="session")
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_headers() -> dict:
    return {"X-User-Name": "admin", "X-User-Key": "admin"}


@pytest.fixture
def unique() -> str:
    """A short lowercase token unique per test (safe for S3 bucket names)."""
    return "it" + uuid.uuid4().hex[:10]


def _localstack_up() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:4566/_localstack/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _mongo_up() -> bool:
    try:
        from pymongo import MongoClient

        from app.config import settings

        MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=2000).admin.command("ping")
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def dbs_available() -> bool:
    """Skip a test unless both local containers are reachable."""
    if not (_localstack_up() and _mongo_up()):
        pytest.skip("local containers (LocalStack + MongoDB) not available")
    return True
