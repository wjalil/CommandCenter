from pydantic import BaseSettings

class AuthConfig(BaseSettings):
    secret: str = "cookieops-super-secret-key"  # 🔐 Replace with something strong and secure
    jwt_lifetime_seconds: int = 3600
    jwt_algorithm: str = "HS256"
    jwt_audience: str = "fastapi-users:auth"

auth_config = AuthConfig()
