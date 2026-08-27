"""S3 access via boto3."""

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
