import os
from typing import Optional
import aioboto3

DO_SPACES_KEY = os.getenv("DO_SPACES_KEY")
DO_SPACES_SECRET = os.getenv("DO_SPACES_SECRET")
DO_SPACES_REGION = os.getenv("DO_SPACES_REGION", "nyc3")
DO_SPACES_BUCKET = os.getenv("DO_SPACES_BUCKET")
DO_SPACES_ENDPOINT = os.getenv("DO_SPACES_ENDPOINT")  # e.g. https://nyc3.digitaloceanspaces.com
DO_SPACES_CDN_BASE = os.getenv("DO_SPACES_CDN_BASE")  # e.g. https://<bucket>.nyc3.cdn.digitaloceanspaces.com
DO_SPACES_PREFIX = os.getenv("DO_SPACES_PREFIX", "prod").strip("/")

_session = aioboto3.Session()

def public_url(key: str) -> str:
    key = key.lstrip("/")
    return f"{DO_SPACES_CDN_BASE}/{key}"

def _s3_client():
    return _session.client(
        "s3",
        region_name=DO_SPACES_REGION,
        endpoint_url=DO_SPACES_ENDPOINT,
        aws_access_key_id=DO_SPACES_KEY,
        aws_secret_access_key=DO_SPACES_SECRET,
    )

async def put_public_object(*, key: str, body: bytes, content_type: str) -> str:
    """Uploads a public-read object to Spaces and returns the object key."""
    if not all([DO_SPACES_KEY, DO_SPACES_SECRET, DO_SPACES_BUCKET, DO_SPACES_ENDPOINT, DO_SPACES_CDN_BASE]):
        raise RuntimeError("Spaces env vars not fully configured")

    key = key.lstrip("/")
    async with _s3_client() as s3:
        await s3.put_object(
            Bucket=DO_SPACES_BUCKET,
            Key=key,
            Body=body,
            ContentType=content_type or "application/octet-stream",
            ACL="public-read",
        )
    return key

async def delete_object(key: str) -> None:
    """Deletes an object from Spaces. Silently ignores missing objects."""
    if not all([DO_SPACES_KEY, DO_SPACES_SECRET, DO_SPACES_BUCKET, DO_SPACES_ENDPOINT]):
        return
    key = key.lstrip("/")
    async with _s3_client() as s3:
        await s3.delete_object(Bucket=DO_SPACES_BUCKET, Key=key)

def key_from_url(url: str) -> Optional[str]:
    """Extracts the Spaces object key from a CDN URL, or returns None if not a CDN URL."""
    if not url or not DO_SPACES_CDN_BASE:
        return None
    cdn = DO_SPACES_CDN_BASE.rstrip("/")
    if url.startswith(cdn + "/"):
        return url[len(cdn) + 1:]
    return None
