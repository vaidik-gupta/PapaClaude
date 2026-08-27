"""DynamoDB access via boto3."""

from functools import lru_cache

import boto3

from app.config import settings
from app.db._aws import boto3_kwargs
from app.logging_config import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def dynamodb_resource():
    logger.debug("Creating DynamoDB resource (endpoint=%s)", settings.aws_endpoint_url or "aws")
    return boto3.resource("dynamodb", **boto3_kwargs())


def table():
    """Return the configured DynamoDB table resource."""
    return dynamodb_resource().Table(settings.dynamodb_table)
