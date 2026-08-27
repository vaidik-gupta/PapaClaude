"""S3 access via boto3, plus a minimal object client."""

from functools import lru_cache

import boto3

from app.config import settings
from app.db._aws import boto3_kwargs
from app.logging_config import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def s3_client():
    logger.debug("Creating S3 client (endpoint=%s)", settings.aws_endpoint_url or "aws")
    return boto3.client("s3", **boto3_kwargs())


class S3Client:
    """Minimal wrapper around the configured bucket."""

    def put(self, key: str, body: bytes) -> None:
        logger.deep_debug("S3 put: %s (%d bytes)", key, len(body))  # type: ignore[attr-defined]
        s3_client().put_object(Bucket=settings.s3_bucket, Key=key, Body=body)

    def get(self, key: str) -> bytes:
        resp = s3_client().get_object(Bucket=settings.s3_bucket, Key=key)
        return resp["Body"].read()

    def delete(self, key: str) -> None:
        logger.deep_debug("S3 delete: %s", key)  # type: ignore[attr-defined]
        s3_client().delete_object(Bucket=settings.s3_bucket, Key=key)


s3 = S3Client()
