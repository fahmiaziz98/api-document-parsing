import os
import secrets

from fastapi import HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader
from loguru import logger

from src.utils.key_gen import hash_api_key

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=True)


async def verify_api_key(api_key: str = Security(API_KEY_HEADER)) -> str:
    """
    Verify API key from header securely, supporting both:
    - Legacy: single global key in X_API_KEY env var
    - Current: per-client hashed keys in X_API_KEY_HASH env var (comma-separated)

    Uses timing-safe comparison with secrets.compare_digest.

    Args:
        api_key: API key from X-API-Key header

    Returns:
        API key if valid

    Raises:
        HTTPException: If API key is invalid or not configured on the server
    """
    # Try per-client hashed keys first
    hashed_keys_env = os.environ.get("X_API_KEY_HASH", "").strip()
    if hashed_keys_env:
        # Split by comma or newline, strip whitespace
        allowed_hashes = {
            h.strip() for h in hashed_keys_env.replace("\n", ",").split(",") if h.strip()
        }

        api_key_hash = hash_api_key(api_key)
        for allowed_hash in allowed_hashes:
            if secrets.compare_digest(api_key_hash, allowed_hash):
                logger.debug(
                    "API key authenticated",
                    extra={"api_key_prefix": _extract_prefix(api_key), "auth_mode": "hashed"},
                )
                return api_key

        logger.warning(
            "Invalid API key attempt",
            extra={"hash_prefix": api_key_hash[:10], "auth_mode": "hashed"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "API key"},
        )

    # Fallback: legacy single global key (backward compatible)
    expected = os.environ.get("X_API_KEY", "")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server API key not configured",
        )
    if not secrets.compare_digest(api_key, expected):
        logger.warning("Invalid API key attempt", extra={"auth_mode": "legacy"})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "API key"},
        )

    logger.debug("API key authenticated", extra={"auth_mode": "legacy"})
    return api_key


def _extract_prefix(api_key: str) -> str:
    """
    Extract prefix from API key for logging (e.g., 'dp_prod' from 'dp_prod_xxx...').

    Args:
        api_key: Raw API key

    Returns:
        Prefix string (first 10 chars + ... if longer)
    """
    if len(api_key) > 10:
        return f"{api_key[:10]}..."
    return api_key
