#!/usr/bin/env python3
"""
CLI tool to generate per-client API keys for the Document Parsing API.

Usage:
    python generated_secret.py --environment prod
    python generated_secret.py --environment dev
    python generated_secret.py --environment staging

The tool outputs:
    - Raw key: Give this to the client (only shown once)
    - Hash: Store this in X_API_KEY_HASH environment variable
"""

import argparse
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from src.utils.key_gen import generate_api_key


def main():
    """Generate and display a new API key with its hash."""
    parser = argparse.ArgumentParser(
        description="Generate per-client API key for Document Parsing API"
    )
    parser.add_argument(
        "--environment",
        "-e",
        default="prod",
        choices=["prod", "dev", "staging"],
        help="Environment prefix (default: prod)",
    )

    args = parser.parse_args()

    # Generate key and hash
    raw_key, key_hash = generate_api_key(environment=args.environment)

    # Display results
    print("\n" + "=" * 80)
    print("API KEY GENERATED")
    print("=" * 80)
    print(f"\nEnvironment: {args.environment}")
    print("\nRaw Key (give to client, shown only once):")
    print(f"  {raw_key}")
    print("\nHash (store in X_API_KEY_HASH env var):")
    print(f"  {key_hash}")
    print("\n" + "=" * 80)
    print("\nSetup instructions:")
    print("  1. Give the raw key to your client")
    print("  2. Store the hash in your .env file:")
    print(f"     X_API_KEY_HASH={key_hash}")
    print("  3. If you have multiple keys, separate them with commas:")
    print("     X_API_KEY_HASH=hash1,hash2,hash3")
    print("\n")


if __name__ == "__main__":
    main()
