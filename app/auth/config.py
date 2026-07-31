import logging
from pydantic import BaseSettings, validator

logger = logging.getLogger(__name__)

_INSECURE_JWT_DEFAULT = "cookieops-super-secret-key"


class AuthConfig(BaseSettings):
    secret: str = _INSECURE_JWT_DEFAULT
    jwt_lifetime_seconds: int = 60 * 60 * 24 * 365  # 1 year — tokens persist until explicit logout
    jwt_algorithm: str = "HS256"
    jwt_audience: str = "fastapi-users:auth"

    class Config:
        # reads from JWT_SECRET environment variable
        fields = {"secret": {"env": "JWT_SECRET"}}

    @validator("secret")
    def warn_if_insecure(cls, v):
        if v == _INSECURE_JWT_DEFAULT:
            logger.warning(
                "⚠️  JWT_SECRET is using the insecure hardcoded default. "
                "Set the JWT_SECRET environment variable before running in production!"
            )
        return v


auth_config = AuthConfig()
