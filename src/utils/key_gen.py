import hashlib
import secrets
import string


def generate_api_key(environment: str = "prod") -> tuple[str, str]:
    """
    Generate a per-client API key with prefix and return raw key + hash.

    Format: dp_{environment}_{random64}
    Example: dp_prod_xK9mN2pQ7rS1tU3vW5xY7zA9bC1dE3fG5...

    Args:
        environment: Environment prefix ("prod", "dev", "staging")

    Returns:
        tuple: (raw_key, sha256_hash)
            - raw_key: The key to give to the client (only shown once)
            - sha256_hash: The hash to store in env/secrets
    """
    if not environment:
        raise ValueError("environment must not be empty")

    # Generate 64 random characters (base62-like: alphanumeric)
    random_part = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(64))

    # Construct key: dp_{environment}_{random64}
    raw_key = f"dp_{environment}_{random_part}"

    # Hash it for storage
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    return raw_key, key_hash


def hash_api_key(key: str) -> str:
    """
    Hash an API key for comparison during verification.

    Args:
        key: Raw API key

    Returns:
        SHA256 hash of the key
    """
    return hashlib.sha256(key.encode()).hexdigest()
