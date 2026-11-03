from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from uuid import UUID

class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class RefreshRequest(BaseModel):
    refresh_token: str

class UserResponse(BaseModel):
    id: UUID
    name: str
    email: EmailStr
    created_at: datetime
    
    class Config:
        from_attributes = True
