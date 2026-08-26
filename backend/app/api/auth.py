from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import api_key_service, settings_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)


class ApiKeyVerify(BaseModel):
    key: str = Field(..., min_length=1)


@router.get("/keys")
async def list_keys():
    return {"keys": await api_key_service.list_keys()}


@router.post("/verify")
async def verify_key(body: ApiKeyVerify):
    return {"valid": await api_key_service.is_valid(body.key)}


@router.post("/keys")
async def create_key(body: ApiKeyCreate):
    return await api_key_service.create_key(body.name)


@router.get("/keys/{key_id}")
async def reveal_key(key_id: int):
    plain = await api_key_service.get_plain_key(key_id)
    if not plain:
        raise HTTPException(status_code=404, detail="API key not found")
    return {"key": plain}


@router.delete("/keys/{key_id}")
async def delete_key(key_id: int):
    if bool(settings_service.get("auth_enabled")) and await api_key_service.count() <= 1:
        await settings_service.update({"auth_enabled": False})
    if not await api_key_service.delete_key(key_id):
        raise HTTPException(status_code=404, detail="API key not found")
    return {"ok": True}
