"""Shared boto3 configuration for DynamoDB and S3.

Builds the common client kwargs from settings. AWS_ENDPOINT_URL is set to
LocalStack in local dev and empty in deployment (so boto3 uses real AWS).
"""

from app.config import settings


def boto3_kwargs() -> dict:
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_endpoint_url:
        kwargs["endpoint_url"] = settings.aws_endpoint_url
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
    if settings.aws_secret_access_key:
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return kwargs
