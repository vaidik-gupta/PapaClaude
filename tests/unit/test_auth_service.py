import pytest

from app.auth.service import AuthService
from app.auth.store import InMemoryUserStore


def svc() -> AuthService:
    return AuthService("admin", "secret", InMemoryUserStore())


def test_admin_authenticates_and_is_admin():
    u = svc().authenticate("admin", "secret")
    assert u is not None
    assert u.is_admin


def test_wrong_key_unknown_user_and_empty_key():
    s = svc()
    assert s.authenticate("admin", "nope") is None
    assert s.authenticate("ghost", "secret") is None
    assert s.authenticate("admin", "") is None


def test_add_user_then_authenticate_non_admin():
    s = svc()
    created = s.add_user("bob", "pw")
    assert not created.is_admin
    authed = s.authenticate("bob", "pw")
    assert authed is not None
    assert not authed.is_admin
    assert s.authenticate("bob", "wrong") is None


def test_add_duplicate_user_raises():
    s = svc()
    s.add_user("bob", "pw")
    with pytest.raises(ValueError):
        s.add_user("bob", "pw2")


def test_cannot_register_the_admin_name():
    with pytest.raises(ValueError):
        svc().add_user("admin", "pw")


def test_registered_key_is_stored_hashed_not_plaintext():
    store = InMemoryUserStore()
    AuthService("admin", "secret", store).add_user("bob", "pw")
    stored = store.get_hash("bob")
    assert stored is not None
    assert "pw" not in stored  # persisted as a hash, never the raw key
    assert stored.startswith("scrypt$")
