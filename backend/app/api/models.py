from fastapi import APIRouter
from app.services.model_catalog import public_model_catalog

router = APIRouter(tags=["models"])


@router.get("/v1/models")
async def list_models():
    models = public_model_catalog()
    return {
        "object": "list",
        "data": [
            {
                "id": model["key"],
                "object": "model",
                "created": 1700000000,
                "owned_by": "qoder",
                "display_name": model["name"],
                "credit_factor": model["credit_factor"],
            }
            for model in models
        ],
    }


@router.get("/api/models/catalog")
async def model_catalog():
    return public_model_catalog()
