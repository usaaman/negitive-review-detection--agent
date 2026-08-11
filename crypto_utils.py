from cryptography.fernet import Fernet
import os
from dotenv import load_dotenv

def ensure_keys_in_env():
    """
    Checks the local .env file. If ENCRYPTION_KEY or SECRET_KEY is missing,
    generates secure random values and appends them to .env, then overrides current env variables.
    """
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        env_path = os.path.join(os.path.abspath(os.getcwd()), ".env")

    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    
    keys = {}
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            parts = line.strip().split("=", 1)
            keys[parts[0].strip()] = parts[1].strip()
            
    modified = False
    if "ENCRYPTION_KEY" not in keys:
        new_key = Fernet.generate_key().decode()
        lines.append(f"\nENCRYPTION_KEY={new_key}\n")
        modified = True
        
    if "SECRET_KEY" not in keys:
        import secrets
        sec_key = secrets.token_hex(24)
        lines.append(f"\nSECRET_KEY={sec_key}\n")
        modified = True
        
    if modified:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        # Reload environment
        load_dotenv(dotenv_path=env_path, override=True)

# Run verification/generation of keys
ensure_keys_in_env()

def get_fernet():
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        raise ValueError("ENCRYPTION_KEY is missing from environment. Make sure ensure_keys_in_env() has run.")
    return Fernet(key.encode())

def encrypt_value(plain_text: str) -> str:
    if not plain_text:
        return ""
    return get_fernet().encrypt(plain_text.encode()).decode()

def decrypt_value(encrypted_text: str) -> str:
    if not encrypted_text:
        return ""
    return get_fernet().decrypt(encrypted_text.encode()).decode()
