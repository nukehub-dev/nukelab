from fastapi import APIRouter, Depends
from app.api.auth import get_current_user
from app.models.user import User

router = APIRouter()


@router.get("/")
async def list_servers(current_user: User = Depends(get_current_user)):
    return {"message": "List servers - TODO"}


@router.post("/")
async def create_server(current_user: User = Depends(get_current_user)):
    return {"message": "Create server - TODO"}
