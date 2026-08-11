from fastapi import APIRouter
from app.services.qoder_client import QODER_MODEL_DISPLAY

router = APIRouter(tags=["models"])


@router.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": key,
                "object": "model",
                "created": 1700000000,
                "owned_by": "qoder",
                "display_name": name,
            }
            for name, key in QODER_MODEL_DISPLAY
        ],
    }