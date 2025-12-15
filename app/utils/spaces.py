import os
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

async def put_public_object(*, key: str, body: bytes, content_type: str) -> str:
    """
    Uploads a public-read object to Spaces and returns the object key.
    """
    if not all([DO_SPACES_KEY, DO_SPACES_SECRET, DO_SPACES_BUCKET, DO_SPACES_ENDPOINT, DO_SPACES_CDN_BASE]):
        raise RuntimeError("Spaces env vars not fully configured")

    key = key.lstrip("/")
    async with _session.client(
        "s3",
        region_name=DO_SPACES_REGION,
        endpoint_url=DO_SPACES_ENDPOINT,
        aws_access_key_id=DO_SPACES_KEY,
        aws_secret_access_key=DO_SPACES_SECRET,
    ) as s3:
        await s3.put_object(
            Bucket=DO_SPACES_BUCKET,
            Key=key,
            Body=body,
            ContentType=content_type or "application/octet-stream",
            ACL="public-read",
        )
    return key
