from uuid import UUID
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from jose import JWTError

from app.database import get_db
from app.core.i18n import t
from app.core.security import verify_token
from app.models.chat import Chat
from app.models.user import User

# auto_error=False so a missing header raises our localized 401 below instead
# of FastAPI's hard-coded English "Not authenticated".
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)

def to_uuid(val: str | UUID) -> UUID:
    return UUID(str(val)) if not isinstance(val, UUID) else val


async def get_owned_chat(chat_id: str, user: User, db: AsyncSession) -> Chat:
    """Fetch a chat by ID and verify it belongs to ``user`` (404/403 otherwise)."""
    cid = to_uuid(chat_id)
    result = await db.execute(select(Chat).where(Chat.id == cid))
    chat = result.scalar_one_or_none()
    if not chat or chat.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=t("chat.not_found"))
    if str(chat.user_id) != str(user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=t("chat.access_denied"))
    return chat

async def get_current_user(token: str | None = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=t("auth.could_not_validate"),
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception

    payload = verify_token(token)
    user_id_raw = payload.get("sub")
    token_type: str = payload.get("type")
    
    if user_id_raw is None or token_type != "access":
        raise credentials_exception
        
    try:
        user_uuid = to_uuid(user_id_raw)
    except ValueError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalars().first()
    
    if user is None:
        raise credentials_exception
    return user

async def get_current_user_optional(token: str | None = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> User | None:
    if not token:
        return None
    try:
        return await get_current_user(token, db)
    except HTTPException:
        return None
