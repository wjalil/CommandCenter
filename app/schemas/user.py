from fastapi_users import schemas
from pydantic import EmailStr

class UserRead(schemas.BaseUser[str]):
    pass

class UserCreate(schemas.BaseUserCreate):
    email: EmailStr
    password: str
