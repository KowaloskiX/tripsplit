"""Auth cryptography: passwords (argon2id) and session tokens. No HTTP, no database.

The public API is async because argon2 costs ~40 ms of CPU per call and would block the event
loop; the blocking variants are private and the public ones run in threads. A limiter caps
concurrency at `cores / parallelism`: argon2id uses 64 MiB per call (anyio's 40-slot pool
could reach ~2.5 GiB) and 4 threads per hash (more would starve the loop thread). Measured on
8 cores, a limit of 2 gave near-best throughput with ~4 ms max loop lag.
"""

import hashlib
import os
import secrets

from anyio import CapacityLimiter, to_thread
from pwdlib import PasswordHash

_SESSION_TOKEN_BYTES = 32

# argon2id with pwdlib's recommended defaults (64 MiB, time_cost 3).
# `verify_and_update` lets us migrate old hashes during login.
_hasher = PasswordHash.recommended()

# Hash compared against when the user does not exist — equalizes response time
# and blocks account enumeration by timing.
_DUMMY_HASH = _hasher.hash("dummy-password-for-constant-time-compare")

# The `parallelism` parameter from pwdlib's recommended settings. Kept as a constant because
# it feeds the limit formula; if pwdlib ever changes it,
# `test_argon2_parallelism_matches_assumption` will complain.
_ARGON2_PARALLELISM = 4

_HASHING_LIMITER = CapacityLimiter(max(1, (os.cpu_count() or 1) // _ARGON2_PARALLELISM))


def _hash_password_blocking(password: str) -> str:
    return _hasher.hash(password)


def _verify_password_blocking(password: str, password_hash: str) -> tuple[bool, str | None]:
    return _hasher.verify_and_update(password, password_hash)


def _waste_time_blocking(password: str) -> None:
    _hasher.verify(password, _DUMMY_HASH)


async def hash_password(password: str) -> str:
    return await to_thread.run_sync(_hash_password_blocking, password, limiter=_HASHING_LIMITER)


async def verify_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    """Returns (is_valid, new_hash_if_rehash_needed)."""
    return await to_thread.run_sync(
        _verify_password_blocking, password, password_hash, limiter=_HASHING_LIMITER
    )


async def waste_time_like_verify(password: str) -> None:
    """Call this when the account does not exist — otherwise a missing account gives itself
    away through a shorter response.

    It goes through the same semaphore as a real verification: if the "no such account" path
    queued separately, response times would start telling the two cases apart again.
    """
    await to_thread.run_sync(_waste_time_blocking, password, limiter=_HASHING_LIMITER)


def generate_session_token() -> str:
    return secrets.token_urlsafe(_SESSION_TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    """SHA-256 is enough: the token carries 256 bits of entropy, so brute force is off the
    table (argon2 would only add cost to every request). Cheap, so it stays synchronous."""
    return hashlib.sha256(token.encode()).hexdigest()
