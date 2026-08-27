"""DynamoDB access via boto3, plus a minimal item client."""

from functools import lru_cache
from typing import Any

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


class DynamoDBClient:
    """Minimal wrapper around the configured table (keyed by `pk`)."""

    def put(self, item: dict[str, Any]) -> None:
        logger.deep_debug("DynamoDB put: %s", item)  # type: ignore[attr-defined]
        table().put_item(Item=item)

    def get(self, pk: str) -> dict[str, Any] | None:
        resp = table().get_item(Key={"pk": pk})
        return resp.get("Item")

    def delete(self, pk: str) -> None:
        logger.deep_debug("DynamoDB delete: pk=%s", pk)  # type: ignore[attr-defined]
        table().delete_item(Key={"pk": pk})


dynamodb = DynamoDBClient()
