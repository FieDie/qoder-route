from fastapi import APIRouter
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
