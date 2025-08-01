# app/utils/security.py

import uuid
from fastapi import UploadFile, HTTPException

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png"]

async def validate_and_read_image(file: UploadFile) -> bytes:
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid file type.")
    
    contents = await file.read()

    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (5MB max).")
    
    return contents

def generate_safe_filename(original_filename: str) -> str:
    ext = original_filename.split(".")[-1].lower()
    return f"{uuid.uuid4()}.{ext}"
