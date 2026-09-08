"""Unit tests for scrypt key hashing."""

from app.auth.hashing import hash_key, verify_key


def test_hash_verifies_and_is_salted():
    h1 = hash_key("hunter2")
    h2 = hash_key("hunter2")
    assert h1 != h2  # random salt -> distinct hashes for the same key
    assert verify_key("hunter2", h1)
    assert verify_key("hunter2", h2)


def test_wrong_key_does_not_verify():
    assert not verify_key("nope", hash_key("hunter2"))


def test_malformed_stored_hash_fails_closed():
    assert not verify_key("hunter2", "")
    assert not verify_key("hunter2", "not-a-hash")
    assert not verify_key("hunter2", "md5$deadbeef")  # unknown algo
