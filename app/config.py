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

    # GitHub Copilot SDK. Local dev (environment="local") uses the logged-in
    # Copilot user via device login (sign in once with the Copilot/gh CLI) and
    # ignores github_token. github_token is for non-local envs — see the TODO in
    # app/agent/client.py. copilot_model is the model id to run (options come from
    # client.list_models()).
    github_token: str = ""
    copilot_model: str = "claude-sonnet-5"

    # Service auth. USER_NAME is the admin account (the only one allowed to
    # register new users); USER_KEY is its credential. Local defaults to
    # admin/admin; in deployment USER_KEY comes from the auth-management service.
    user_name: str = "admin"
    user_key: str = "admin"

    # AWS (DynamoDB + S3). AWS_ENDPOINT_URL points at LocalStack in local dev,
    # and is empty in deployment so boto3 hits real AWS.
    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_endpoint_url: str = ""
    s3_bucket: str = "papaclaude-local"
    dynamodb_table: str = "papaclaude-local"

    # MongoDB
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "papaclaude"

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000


settings = Settings()
