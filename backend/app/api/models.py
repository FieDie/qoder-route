from fastapi import APIRouter, HTTPException
from app.services import model_sync
from app.services.model_catalog import public_model_catalog

router = APIRouter(tags=["models"])


@router.get("/v1/models")
async def list_models():
    models = public_model_catalog()
    data = [
        {
                "id": model["key"],
                "object": "model",
                # Anthropic clients read `type` + `display_name`; OpenAI
                # clients ignore the extra fields, so one list serves both.
                "type": "model",
                "created": 1700000000,
                "created_at": "2023-11-14T00:00:00Z",
                "owned_by": "qoder",
                "display_name": model["name"],
                "credit_factor": model["credit_factor"],
            }
            for model in models
    ]
    return {
        "object": "list",
        "data": data,
        "has_more": False,
        "first_id": data[0]["id"] if data else None,
        "last_id": data[-1]["id"] if data else None,
    }


@router.get("/api/models/catalog")
async def model_catalog():
    return public_model_catalog()


@router.get("/api/models/sync")
async def model_sync_status():
    """Last sync time + synced model count for the panel."""
    return model_sync.sync_status()


@router.post("/api/models/sync")
async def sync_model_catalog():
    """Pull Qoder's live model list through the signer and activate it."""
    result = await model_sync.sync_model_catalog()
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error", "Sync failed"))
    return result
