"""End-to-end: a ContentTree written through MongoTreePersistence survives a
fresh store/cache (simulating a process restart). Needs the Mongo container.
"""

import pytest
from pymongo import MongoClient

from app.config import settings
from app.content.store import ContentTreeStore, MongoTreePersistence
from app.content.tree import NodeKind

pytestmark = pytest.mark.e2e


def test_tree_survives_a_fresh_store(dbs_available):
    user = "e2e_tree_user"
    coll = MongoClient(settings.mongodb_uri)[settings.mongodb_db][
        MongoTreePersistence.COLLECTION
    ]
    coll.delete_one({"_id": user})
    try:
        # First store instance: mutate + write-through to Mongo.
        store1 = ContentTreeStore(persistence=MongoTreePersistence())
        tree = store1.get_or_create(user)
        tree.add(["mongodb", "default"], kind=NodeKind.GROUP, owner=user)
        tree.add(["mongodb", "default", "app"], kind=NodeKind.DATABASE, owner=user)
        store1.on_mutated(user)

        # A brand-new store instance (cold cache) must load it back from Mongo.
        store2 = ContentTreeStore(persistence=MongoTreePersistence())
        loaded = store2.get_or_create(user)
        assert loaded.has(["mongodb", "default", "app"])
        assert loaded.get(["mongodb", "default", "app"]).owner == user
    finally:
        coll.delete_one({"_id": user})
