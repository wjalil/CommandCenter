from fastapi_users import schemas
from pydantic import EmailStr

class UserRead(schemas.BaseUser[str]):
    tenant_id: str

class UserCreate(schemas.BaseUserCreate):
    email: EmailStr
    password: str
    tenant_id: str 
