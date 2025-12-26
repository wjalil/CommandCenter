# app/utils/security.py

import os
import uuid
import base64
from fastapi import UploadFile, HTTPException
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png"]

# Encryption for sensitive API keys (RESEND, etc.)
# Master key should be set in environment variable: ENCRYPTION_MASTER_KEY
def _get_encryption_key() -> bytes:
    """Derive encryption key from master key in environment"""
    master_key = os.getenv("ENCRYPTION_MASTER_KEY", "default-insecure-key-change-in-production")

    # Derive a 32-byte key using PBKDF2HMAC
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'cookieops-salt-v1',  # Static salt (acceptable for app-level encryption)
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(master_key.encode()))
    return key

def encrypt_api_key(plain_key: str) -> str:
    """Encrypt an API key for storage in database"""
    if not plain_key:
        return ""

    fernet = Fernet(_get_encryption_key())
    encrypted = fernet.encrypt(plain_key.encode())
    return encrypted.decode()

def decrypt_api_key(encrypted_key: str) -> str:
    """Decrypt an API key from database storage"""
    if not encrypted_key:
        return ""

    try:
        fernet = Fernet(_get_encryption_key())
        decrypted = fernet.decrypt(encrypted_key.encode())
        return decrypted.decode()
    except Exception:
        # If decryption fails, return empty string (invalid/corrupted key)
        return ""

async def validate_and_read_image(file: UploadFile) -> bytes:
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid file type.")
    
    contents = await file.read()

    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (10MB max).")
    
    return contents

def generate_safe_filename(original_filename: str) -> str:
    ext = original_filename.split(".")[-1].lower()
    return f"{uuid.uuid4()}.{ext}"
