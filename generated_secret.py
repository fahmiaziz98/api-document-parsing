import argparse
import secrets
import string


def generate_secret_key(length: int = 64) -> str:
    """
    Generate a cryptographically secure secret key.
    
    Args:
        length (int): Length of the secret key to generate.
        
    Returns:
        str: Generated secure secret key string.
    """
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def validate_secret_key(key: str, expected: str) -> bool:
    """
    Securely validate a given key against an expected key 
    using constant-time comparison to mitigate timing attacks.
    
    Args:
        key (str): The key provided by the user/request.
        expected (str): The expected correct key.
        
    Returns:
        bool: True if they match, False otherwise.
    """
    if not key or not expected:
        return False
    return secrets.compare_digest(key, expected)


def main():
    parser = argparse.ArgumentParser(description="Generate and validate API secret keys.")
    parser.add_argument("--generate", action="store_true", help="Generate a new secret key")
    parser.add_argument("--length", type=int, default=64, help="Length of the generated key")
    parser.add_argument("--validate", type=str, help="Key to validate")
    parser.add_argument("--expected", type=str, help="Expected key to validate against")

    args = parser.parse_args()

    if args.generate or (not args.validate and not args.generate):
        new_key = generate_secret_key(args.length)
        print("Generated Secure API Key:")
        print("-" * 50)
        print(new_key)
        print("-" * 50)
        print("\nMake sure to add this to your .env file as API_KEY:")
        print(f"API_KEY={new_key}")
        
    elif args.validate and args.expected:
        is_valid = validate_secret_key(args.validate, args.expected)
        if is_valid:
            print("✅ Key is valid! (Matches expected key securely)")
        else:
            print("❌ Invalid key! (Does not match expected key)")
    elif args.validate and not args.expected:
        print("Error: Must provide --expected key when using --validate")

if __name__ == "__main__":
    main()
