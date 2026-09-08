"""End-to-end: a user registered through MongoUserStore survives a fresh
service instance (simulating a process restart). Needs the Mongo container.
"""

import pytest
from pymongo import MongoClient

from app.auth.service import AuthService
from app.auth.store import MongoUserStore
from app.config import settings

pytestmark = pytest.mark.e2e


def test_registered_user_survives_a_fresh_service(dbs_available):
    user = "e2e_auth_user"
    coll = MongoClient(settings.mongodb_uri)[settings.mongodb_db][MongoUserStore.COLLECTION]
    coll.delete_one({"_id": user})
    try:
        AuthService("admin", "secret", MongoUserStore()).add_user(user, "pw")

        # A brand-new service (cold) must authenticate against the persisted hash.
        fresh = AuthService("admin", "secret", MongoUserStore())
        authed = fresh.authenticate(user, "pw")
        assert authed is not None
        assert not authed.is_admin
        assert fresh.authenticate(user, "wrong") is None
    finally:
        coll.delete_one({"_id": user})
