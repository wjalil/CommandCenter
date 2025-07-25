from fastapi import Depends
from fastapi_users import FastAPIUsers
from fastapi_users.authentication import AuthenticationBackend, JWTStrategy, BearerTransport
from app.models.user import User
from app.auth.manager import UserManager
from app.auth.config import auth_config
from app.db import get_db
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")

def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(
        secret=auth_config.secret,
        lifetime_seconds=auth_config.jwt_lifetime_seconds,
        token_audience=auth_config.jwt_audience  # ✅ MUST match JWT aud
    )

auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

# Dependency to get User DB
async def get_user_db(session: AsyncSession = Depends(get_db)):
    from app.models.user import User  # avoid circular import
    return SQLAlchemyUserDatabase(session, User)

# Dependency to get UserManager
async def get_user_manager(user_db=Depends(get_user_db)):
    yield UserManager(user_db)

fastapi_users = FastAPIUsers[User, str](
    get_user_manager,
    [auth_backend],
)

# Export user dependencies
get_current_user = fastapi_users.current_user(active=True)
get_current_admin_user = fastapi_users.current_user(active=True, verified=True)
