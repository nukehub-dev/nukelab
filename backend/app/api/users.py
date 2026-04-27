from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.api.auth import get_current_user
from app.models.user import User

router = APIRouter()


@router.get("/")
async def list_users(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return {"message": "List users - TODO"}


@router.post("/")
async def create_user(db: AsyncSession = Depends(get_db)):
    return {"message": "Create user - TODO"}
