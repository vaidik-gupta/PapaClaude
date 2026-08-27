# MyMaid

A [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) service
built on FastAPI, with DynamoDB, MongoDB, and S3, plus LangChain document loaders.

## Stack

| Concern           | Choice                                            |
| ----------------- | ------------------------------------------------- |
| Package manager   | `uv`                                              |
| Web server        | FastAPI + uvicorn                                 |
| Agent             | `claude-agent-sdk`                                |
| DynamoDB & S3     | `boto3` (LocalStack in local dev)                 |
| MongoDB           | `motor` (async)                                   |
| Document loaders  | `langchain-community`                             |

## Layout

```
app/
├── main.py              FastAPI app + uvicorn entrypoint
├── config.py            pydantic-settings (loads .env then .env.local)
├── logging_config.py    INFO / DEBUG / DEEP_DEBUG logger
├── agent/client.py      Claude Agent SDK wrapper
├── db/                  dynamodb.py, s3.py, mongodb.py
├── loaders/             LangChain document loaders
└── api/routes.py        HTTP routes
```

## Configuration

Two layered env files (later overrides earlier):

1. `.env` — deployment config (real AWS / MongoDB).
2. `.env.local` — local dev config pointing at the docker-compose containers.

Both are gitignored. Templates are committed as `.env.example` and `.env.local.example`.
Set your `ANTHROPIC_API_KEY` in `.env.local`.

## Logging

Three levels, most-verbose first: `DEEP_DEBUG` (5) < `DEBUG` (10) < `INFO` (20).
Set `LOG_LEVEL` in the env file. `DEEP_DEBUG` is a custom level:

```python
from app.logging_config import get_logger
logger = get_logger(__name__)
logger.deep_debug("very verbose trace")
```

## Getting started

Prerequisites: `uv`, Docker, and the Claude Code CLI (`npm install -g @anthropic-ai/claude-code`).

```bash
# 1. Install dependencies
uv sync

# 2. Copy env templates and set your ANTHROPIC_API_KEY
cp .env.example .env
cp .env.local.example .env.local

# 3. Start local containers (LocalStack S3+DynamoDB, MongoDB)
docker compose up -d

# 4. Run the API
uv run uvicorn app.main:app --reload
```

Then:

```bash
curl localhost:8000/health
curl -X POST localhost:8000/agent -H 'content-type: application/json' \
  -d '{"prompt": "Hello!"}'
```
