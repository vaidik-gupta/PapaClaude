"""Application configuration.

Loaded from two env files, later ones overriding earlier ones:
  1. .env        — deployment defaults
  2. .env.local  — local development overrides (docker-compose containers)
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: str = "local"
    log_level: str = "INFO"

    # Anthropic / Claude Agent SDK
    anthropic_api_key: str = ""

    # AWS (DynamoDB + S3). AWS_ENDPOINT_URL points at LocalStack in local dev,
    # and is empty in deployment so boto3 hits real AWS.
    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_endpoint_url: str = ""
    s3_bucket: str = "mymaid-local"
    dynamodb_table: str = "mymaid-local"

    # MongoDB
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "mymaid"

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000


settings = Settings()
