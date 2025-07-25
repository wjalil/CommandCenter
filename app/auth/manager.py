from fastapi_users import BaseUserManager, UUIDIDMixin
from app.models.user import User
from app.db import async_session
from app.auth.config import auth_config
from typing import Optional

class UserManager(UUIDIDMixin, BaseUserManager[User, str]):
    reset_password_token_secret = auth_config.secret
    verification_token_secret = auth_config.secret

    async def on_after_register(self, user: User, request=None):
        print(f"User registered: {user.email}")
