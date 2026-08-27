"""MongoDB access via motor (async), plus a minimal document client."""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)


class MongoDB:
    """Holds the async client + database handle, connected during app lifespan."""

    client: AsyncIOMotorClient | None = None
    db: AsyncIOMotorDatabase | None = None

    async def connect(self) -> None:
        logger.info("Connecting to MongoDB (db=%s)", settings.mongodb_db)
        self.client = AsyncIOMotorClient(settings.mongodb_uri)
        self.db = self.client[settings.mongodb_db]

    async def close(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None
            self.db = None
            logger.info("MongoDB connection closed")

    async def insert(self, collection: str, doc: dict[str, Any]) -> str:
        logger.deep_debug("Mongo insert into %s: %s", collection, doc)  # type: ignore[attr-defined]
        result = await self.db[collection].insert_one(doc)
        return str(result.inserted_id)

    async def find_one(self, collection: str, query: dict[str, Any]) -> dict[str, Any] | None:
        return await self.db[collection].find_one(query)

    async def delete_one(self, collection: str, query: dict[str, Any]) -> int:
        logger.deep_debug("Mongo delete from %s: %s", collection, query)  # type: ignore[attr-defined]
        result = await self.db[collection].delete_one(query)
        return result.deleted_count


mongodb = MongoDB()
