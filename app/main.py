"""FastAPI application entrypoint.

Run with uv:
    uv run uvicorn app.main:app --reload
or:
    uv run python -m app.main
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.config import settings
from app.db.mongodb import mongodb
from app.logging_config import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting MyMaid (environment=%s)", settings.environment)
    await mongodb.connect()
    yield
    await mongodb.close()
    logger.info("MyMaid shutdown complete")


app = FastAPI(title="MyMaid", version="0.1.0", lifespan=lifespan)
app.include_router(router)


def main() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.environment == "local",
    )


if __name__ == "__main__":
    main()
