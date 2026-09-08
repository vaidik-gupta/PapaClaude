"""Key hashing for durable credential storage.

Uses scrypt (stdlib, an approved password-hashing algorithm) so no extra
dependency is needed. Hashes are stored as a self-describing string
``scrypt$<n>$<r>$<p>$<salt_hex>$<hash_hex>`` so the cost parameters can be
raised later without breaking hashes already on disk. Verification is
constant-time and fails closed on any malformed input.
"""

import hashlib
import secrets
from hmac import compare_digest

# scrypt cost parameters. Memory use is ~128 * N * r bytes (~16 MB here),
# within scrypt's default maxmem limit.
_N = 2**14
_R = 8
_P = 1
_SALT_BYTES = 16


def hash_key(key: str) -> str:
    """Return a self-describing scrypt hash of ``key`` with a random salt."""
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.scrypt(key.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def verify_key(key: str, stored: str) -> bool:
    """Constant-time check of ``key`` against a stored hash; False if malformed."""
    try:
        algo, n, r, p, salt_hex, hash_hex = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(
            key.encode(), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p)
        )
    except ValueError:
        return False
    return compare_digest(dk.hex(), hash_hex)
